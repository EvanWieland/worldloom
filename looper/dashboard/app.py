"""looper terminal dashboard (spec: docs/superpowers/specs/2026-09-24-dashboard-design.md).
Renders Observer snapshots only; never writes files, never controls jobs."""
from __future__ import annotations

import time
from pathlib import Path

from rich.markup import escape
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, RichLog, Static

from looper.dashboard.widgets import (BLUE_AMBER_RED, GREEN_AMBER_RED, TEAL_VIOLET_MAGENTA, BrailleGraph,
                                      gradient_bar)
from looper.events import REPO_ROOT
from looper.observe import Observer, Snapshot

try:
    from textual_image.widget import Image as ImageWidget
except Exception:  # no textual-image -> text placeholder
    ImageWidget = None


def fmt_dur(s: float | None) -> str:
    if s is None:
        return "—"
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


class NowPanel(Static):
    def show(self, snap: Snapshot) -> None:
        n = snap.now
        if n is None:
            nxt = f"\nnext ▸ {escape(' · '.join(q.title for q in snap.queue[:3]))}" if snap.queue else ""
            self.update(f"[dim]idle, no stage running[/]{nxt}")
            return
        t = Text()
        t.append(f"{n.title}\n", style="bold #e5e7eb")
        win = f"  (window {n.window}/{n.total_windows})" if n.window else ""
        t.append(f"stage   {n.stage}{win}  {n.phase}\n", style="#cbd5e1")
        if n.step is not None and n.total_steps:
            t.append("step    ")
            t.append(gradient_bar(n.step / n.total_steps, 20, TEAL_VIOLET_MAGENTA))
            t.append(f"  {n.step}/{n.total_steps}  {n.sec_per_step or '—'} s/step\n")
        if n.stage_pct is not None:
            t.append("stage   ")
            t.append(gradient_bar(n.stage_pct / 100, 20, TEAL_VIOLET_MAGENTA))
            t.append(f"  {n.stage_pct:.0f}%\n")
        eta = time.strftime("%H:%M", time.localtime(snap.generated_at + n.eta_s)) if n.eta_s else "—"
        t.append(f"elapsed {fmt_dur(n.elapsed_s)}   ETA {eta}")
        if n.stalled:
            t.append("   ⚠ stalled?", style="bold #fbbf24")
        if snap.queue:
            t.append(f"\nnext ▸ {' · '.join(q.title for q in snap.queue[:3])}", style="#94a3b8")
        self.update(t)


class ModelsPanel(Static):
    def show(self, snap: Snapshot) -> None:
        m = snap.models
        lines = []
        if m.llm_live:
            lv = m.llm_live
            lines.append(f"[b #f472b6]LLM[/] {escape(str(lv.get('model', '')))} [#fbbf24]● generating[/]")
            lines.append(f"  out {lv.get('output_tokens_so_far') or 0:,} tok · {lv.get('tokens_per_s') or '—'} tok/s")
            lines.append(f"  {lv.get('elapsed_s') or 0:.0f} s elapsed")
        elif m.llm_last:
            la = m.llm_last
            lines.append(f"[b #f472b6]LLM[/] {escape(str(la.get('model', '')))}")
            lines.append(f"  in {la.get('input_tokens') or 0:,} · out {la.get('output_tokens') or 0:,} tok")
            lines.append(f"  {la.get('tokens_per_s') or '—'} tok/s · {la.get('latency_s') or '—'} s")
        else:
            lines.append("[b #f472b6]LLM[/] [dim]no calls yet[/]")
        lines.append("")
        if m.video_stage:
            lines.append(f"[b #38bdf8]VIDEO[/] {escape(str(m.video_stage))}")
            fpm = f" · {m.frames_per_min:.1f} fr/min" if m.frames_per_min else ""
            lines.append(f"  {m.sec_per_step or '—'} s/step{fpm}")
        else:
            lines.append("[b #38bdf8]VIDEO[/] [dim]idle[/]")
        self.update("\n".join(lines))


class PreviewPanel(Vertical):
    MODES = ("preview", "keyframe")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.mode = 0
        self._shown: str | None = None

    def compose(self) -> ComposeResult:
        if ImageWidget:
            yield ImageWidget(id="img")
        else:
            yield Static("[dim]textual-image not installed[/]", id="img")
        yield Static("", id="img_caption")

    def show(self, snap: Snapshot) -> None:
        src = snap.now or (snap.history[0] if snap.history else None)
        want = None
        if src is not None:
            if self.MODES[self.mode] == "preview":
                want = getattr(src, "preview_path", None)
            want = want or getattr(src, "keyframe_path", None)
        self.query_one("#img_caption", Static).update(f"[dim]{self.MODES[self.mode]} · p to switch[/]")
        if ImageWidget and want and want != self._shown and Path(want).exists():
            try:
                from PIL import Image as PILImage
                with PILImage.open(want) as im:
                    im.load()  # full decode here, not at render time: a truncated file must fail inside this try
                    img = im.copy()
                self.query_one("#img").image = img
                self._shown = want
            except Exception:
                pass  # half-written or corrupt file: keep the last good image


class HardwarePanel(Vertical):
    GRAPHS = [("vram_mib", "VRAM", TEAL_VIOLET_MAGENTA, "MiB", 6144),
              ("gpu_util", "GPU", TEAL_VIOLET_MAGENTA, "%", 100),
              ("temp_c", "TEMP", BLUE_AMBER_RED, "°C", 90),
              ("ram_gib", "RAM", GREEN_AMBER_RED, "GiB", 64)]

    def compose(self) -> ComposeResult:
        for key, label, grad, unit, vmax in self.GRAPHS:
            yield BrailleGraph(label, grad, unit, vmax, id=f"g_{key}")

    def show(self, snap: Snapshot) -> None:
        lt = snap.hw.latest
        for key, _label, _grad, unit, _vmax in self.GRAPHS:
            vals = [v for _, v in snap.hw.series.get(key, [])]
            cur = lt.get(key)
            extra = f" · {lt.get('power_w') or '—'} W" if key == "temp_c" else ""
            if key == "ram_gib" and cur is not None and lt.get("ram_total_gib"):
                extra = f" / {lt['ram_total_gib']:.0f}" + (" ⚠ tight" if cur > 0.9 * lt["ram_total_gib"] else "")
            if cur is not None:
                txt = f"{cur:.0f} {unit}{extra}"
            else:
                txt = "[sampler down]" if not snap.hw.sampler_alive else "—"
            self.query_one(f"#g_{key}", BrailleGraph).set_series(vals, txt)


TOKEN_STYLES = {"▶": "#38bdf8", "◀": "#f472b6", "✓": "#2dd4bf", "▦": "#a78bfa", "⚡": "#fbbf24"}


def token_text(lines: list[str], live: str | None, width: int = 400) -> Text:
    """Token-log lines coloured by kind (▶ prompt in, ◀ text out, ✓ call done, ▦ video tokens, ⚡ live rate)."""
    t = Text()
    for ln in lines:
        t.append(ln[:width] + "\n", style=TOKEN_STYLES.get(ln[:1], "#e5e7eb"))
    if live:
        t.append(live, style="bold " + TOKEN_STYLES["⚡"])
    return t


class TokensPanel(Static):
    def show(self, snap: Snapshot) -> None:
        if not snap.tokens and not snap.tokens_live:
            self.update(Text("no model calls yet (▶ prompts in · ◀ text out · ▦ video tokens · ⚡ live rate) — t: full view",
                             style="dim"))
            return
        self.update(token_text(snap.tokens[-6:], snap.tokens_live, width=160))


class TokensScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "back")]

    def __init__(self, snap: Snapshot | None, **kw):
        super().__init__(name="tokens", **kw)
        self._snap = snap

    def compose(self) -> ComposeResult:
        yield RichLog(wrap=True, markup=False)
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one(RichLog)
        s = self._snap
        if not s or (not s.tokens and not s.tokens_live):
            log.write("(no model calls yet)")
            return
        log.write(token_text(s.tokens, s.tokens_live))


class LogScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "back")]

    def __init__(self, events: list[dict], **kw):
        super().__init__(name="log", **kw)
        self._events = events

    def compose(self) -> ComposeResult:
        yield RichLog(highlight=True, markup=False, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one(RichLog)
        if not self._events:
            log.write("(no events for this run yet)")
        for e in self._events:
            ts = time.strftime("%H:%M:%S", time.localtime(e.get("ts", 0)))
            log.write(f"{ts} {e.get('stage') or '-':10} {e.get('type', ''):18} {e.get('payload')}")


class HardwareScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "back")]

    def __init__(self, **kw):
        super().__init__(name="hardware", **kw)

    def compose(self) -> ComposeResult:
        yield HardwarePanel(id="hw_big")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_graphs()
        self.set_interval(1.0, self.refresh_graphs)

    def refresh_graphs(self) -> None:
        if self.app.snap:
            self.query_one(HardwarePanel).show(self.app.snap)


class DetailScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "back")]

    def __init__(self, item, events: list[dict], **kw):
        super().__init__(name="detail", **kw)
        self.item, self._events = item, events

    def compose(self) -> ComposeResult:
        i = self.item
        with Horizontal(id="detail_top"):
            if ImageWidget and i is not None and i.keyframe_path:
                yield ImageWidget(i.keyframe_path, id="detail_img")
            if i is None:
                body = "[dim]no run selected[/]"
            else:
                stages = "\n".join(f"  {s or '?':12} {fmt_dur(d)}" for s, d in i.stages) or "  —"
                body = (f"[b]{escape(i.title)}[/]  ({escape(i.run_id)})\nstatus {escape(i.status)} · {fmt_dur(i.duration_s)}\n"
                        f"verdict: {escape(i.verdict or '—')}\nerror: {escape(i.error or '—')}\n"
                        f"results: {escape(str(i.results or '—'))}\nstages:\n{escape(stages)}")
            yield Static(body)
        yield RichLog(wrap=True, markup=False)
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one(RichLog)
        for e in self._events[-40:]:
            log.write(f"{e.get('type')} {e.get('payload')}")


class LooperDash(App):
    CSS_PATH = "theme.tcss"
    TITLE = "LOOPER"
    BINDINGS = [("q", "quit", "quit"), ("p", "toggle_preview", "preview"), ("l", "log", "log"),
                ("h", "hardware", "hardware"), ("t", "tokens", "tokens"), ("enter", "open_run", "open run")]

    def __init__(self, root: Path = REPO_ROOT, observer: Observer | None = None, **kw):
        super().__init__(**kw)
        self.observer = observer or Observer(root)
        self.snap: Snapshot | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="status")
        with Horizontal():
            with Vertical():
                yield NowPanel(id="now", classes="panel")
                yield HardwarePanel(id="hardware", classes="panel")
                yield TokensPanel(id="tokens", classes="panel")
                yield DataTable(id="history", classes="panel", cursor_type="row")
            with Vertical(id="side"):
                yield PreviewPanel(id="preview", classes="panel")
                yield ModelsPanel(id="models", classes="panel")
                yield Static("", id="warnings")
        yield Footer()

    def on_mount(self) -> None:
        for wid, title in (("#now", "NOW"), ("#preview", "PREVIEW"), ("#models", "MODELS"),
                           ("#hardware", "HARDWARE"), ("#tokens", "TOKENS"), ("#history", "HISTORY")):
            self.query_one(wid).border_title = title
        self.query_one("#history", DataTable).add_columns("", "run", "time", "result", "verdict")
        self.refresh_all()
        self.set_interval(1.0, self.refresh_all)

    def refresh_all(self) -> None:
        self.snap = s = self.observer.poll()
        if self.screen is not self.screen_stack[0]:
            return  # sub-screens refresh themselves; the main widgets aren't on screen
        state = "[#2dd4bf]● rendering[/]" if s.now else "[dim]○ idle[/]"
        self.query_one("#status", Static).update(
            f"[b #a78bfa]LOOPER[/]   {state} · {len(s.queue)} queued · {time.strftime('%H:%M')}")
        self.query_one("#now", NowPanel).show(s)
        self.query_one("#models", ModelsPanel).show(s)
        self.query_one("#preview", PreviewPanel).show(s)
        self.query_one("#hardware", HardwarePanel).show(s)
        self.query_one("#tokens", TokensPanel).show(s)
        self.query_one("#warnings", Static).update(Text("\n".join(f"⚠ {w}" for w in s.warnings), style="#fbbf24"))
        t = self.query_one("#history", DataTable)
        row = t.cursor_row
        t.clear()
        for h in s.history:
            mark = (Text("✔", style="green") if h.status == "ok" else
                    Text("⏸", style="#fbbf24") if h.status == "awaiting approval" else Text("✖", style="red"))
            res = h.error or ("awaiting approval" if h.status == "awaiting approval" else
                              str(h.results.get("joins")) if h.results.get("joins") else "")
            t.add_row(mark, Text(h.title), fmt_dur(h.duration_s), Text(res[:28]), Text(h.verdict or ""))
        if s.history:
            t.move_cursor(row=min(max(row, 0), len(s.history) - 1))

    def _selected(self):
        if not self.snap or not self.snap.history:
            return None
        row = self.query_one("#history", DataTable).cursor_row
        return self.snap.history[min(max(row, 0), len(self.snap.history) - 1)]

    def action_toggle_preview(self) -> None:
        p = self.query_one("#preview", PreviewPanel)
        p.mode = (p.mode + 1) % len(p.MODES)
        p._shown = None

    def action_log(self) -> None:
        sel = self._selected()
        rid = self.snap.now.run_id if self.snap and self.snap.now else (sel.run_id if sel else "")
        self.push_screen(LogScreen(self.observer.recent_events(rid)))

    def action_tokens(self) -> None:
        self.push_screen(TokensScreen(self.snap))

    def action_hardware(self) -> None:
        self.push_screen(HardwareScreen())

    def action_open_run(self) -> None:
        item = self._selected()
        self.push_screen(DetailScreen(item, self.observer.recent_events(item.run_id) if item else []))

    def on_data_table_row_selected(self, _event) -> None:
        self.action_open_run()
