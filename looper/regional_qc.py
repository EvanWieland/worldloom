"""Regional, source-relative loop QC (ported from experiments/loop_eval/rqc.py; calibration and human verdicts in
research/particle-loop-closure.md section 1 and 9). Built after Review E: whole-frame checks passed a loop whose glass
drips had stalled for over a second.

Everything is measured per REGION (masks derived once from the REFERENCE take, never from the loop under test, so a
frozen region cannot drop out of its own evaluation) and relative to the reference's own distribution:
  E[r,b,k,t] = sqrt(mean_r((B_b(I[t]) - B_b(I[t-k]))**2)), bands raw / fine (DoG .7/2) / coarse (DoG 2/6),
  lags 1, 2, 4, 8 frames at 24 fps;  R = E / median over the reference.
Gates (each region on its own; the loop is evaluated cyclically):
  low          0.25 s rolling mean of raw R at lags >= 1/6 s < 0.5          (motion present)
  low_texture  same at lag 1 (raw + fine) < 0.35                             (per-frame change / visibility)
               relative_low (declared moving light only): limit = min(fixed, 0.85 x the reference's own minimum)
  spike        one-frame lag-1 R > max(3, the reference's own max)
  beads        0.5 s windows of bead moving fraction / speed / count / contrast / births / deaths outside
               [0.85 x min, 1.15 x max] of ordinary reference windows (only for configured bead regions)
  static       static-tile edge deviation > 1.5 x the reference's own max; tile luma similarly (+1)
Regions: a scene dict {"regions": {name: [[x0,y0,x1,y1], ...]}, "bead_regions": [...]} or AUTO (no dict): a 4x3 grid,
cells whose reference activity is above the cells' median become regions c<row><col>; no bead tracking.
Thresholds rest on two human verdicts plus synthetic controls: provisional.
"""
import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial import cKDTree

BANDS = {"raw": None, "fine": (0.7, 2.0), "coarse": (2.0, 6.0)}
LAGS_S = [1 / 24, 2 / 24, 4 / 24, 8 / 24]
ROLL_S, BEAD_WIN_S = 0.25, 0.5
LOW_MARGIN = 0.85  # low / low_texture limit = min(fixed limit, this x the reference's own minimum rolling R)
MOVE_PX_S = 18.0  # bead step counts as moving above 0.75 px per 24 fps frame (centroid jitter on still beads ~0.3)


def gray(f):
    return cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)


def band(g, b):
    if BANDS[b] is None:
        return g
    s1, s2 = BANDS[b]
    return cv2.GaussianBlur(g, (0, 0), s1) - cv2.GaussianBlur(g, (0, 0), s2)


def build_masks(scene, src_gray):
    act = np.abs(np.diff(np.stack(src_gray), axis=0)).mean(0)
    h, w = act.shape
    masks, anyb = {}, np.zeros((h, w), bool)
    for r, boxes in scene["regions"].items():
        m = np.zeros((h, w), bool)
        for x0, y0, x1, y1 in boxes:
            m[y0:y1, x0:x1] = True
        anyb |= m
        masks[r] = m & (act >= np.percentile(act[m], 25))
    grown = cv2.dilate(anyb.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)
    masks["static"] = (act < np.percentile(act, 40)) & ~grown
    return masks, act


def cyc(i, n, wrap):
    return i % n if wrap else i


def roll_mean(x, w, wrap):
    """Mean over the w frames ending at t (NaN-aware: needs >= half the window valid). Cyclic when wrap."""
    x = np.asarray(x, float)
    xx = np.concatenate([x[-(w - 1):], x]) if wrap and w > 1 else np.concatenate([np.full(w - 1, np.nan), x])
    ok = ~np.isnan(xx)
    c = np.convolve(np.where(ok, xx, 0), np.ones(w), "valid")
    cnt = np.convolve(ok.astype(float), np.ones(w), "valid")
    return np.where(cnt >= max(1, w / 2), c / np.maximum(cnt, 1), np.nan)


# ---------------- beads ----------------
KER = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))


def detect(g, mask, thr):
    th = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, KER)
    bw = ((th > thr) & mask).astype(np.uint8)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(bw, connectivity=8)
    if n <= 1:
        return np.zeros((0, 2)), np.zeros(0), np.zeros(0)
    area = stats[1:, cv2.CC_STAT_AREA].astype(float)
    peak = np.zeros(n)
    np.maximum.at(peak, lab.ravel(), th.ravel())
    keep = (area <= 60)
    return cent[1:][keep], peak[1:][keep], area[keep]


def bead_series(G, mask, thr, fps, wrap):
    """Per-frame: detections (count/px, contrast, area), linked steps (moving fraction, speed px/s, direction),
    births/deaths inside the pane (away from the mask border)."""
    n = len(G)
    inner = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 3) > 5
    dets = [detect(g, mask, thr) for g in G]
    rad = max(4.0, 60.0 / fps)  # search radius: beads move < ~2.5 px per 24 fps frame
    links = [None] * n  # links[t] = (i_prev, j_cur) index pairs from frame t-1 to t
    for t in range(n):
        tp = t - 1
        if tp < 0 and not wrap:
            continue
        a, b = dets[tp % n][0], dets[t][0]
        if len(a) == 0 or len(b) == 0:
            links[t] = (np.zeros(0, int), np.zeros(0, int))
            continue
        ta, tb = cKDTree(a), cKDTree(b)
        da, ja = tb.query(a, distance_upper_bound=rad)
        db, ib = ta.query(b, distance_upper_bound=rad)
        ii = np.nonzero((ja < len(b)))[0]
        ii = ii[ib[ja[ii]] == ii]  # mutual nearest
        links[t] = (ii, ja[ii])
    out = {k: np.full(n, np.nan) for k in ("count", "contrast", "area", "moving", "speed", "vx", "vy", "births", "deaths",
                                           "n_moving")}
    area_px = mask.sum()
    for t in range(n):
        c, pk, ar = dets[t]
        out["count"][t] = len(c) / area_px * 1e4
        if len(c):
            out["contrast"][t], out["area"][t] = np.median(pk), np.median(ar)
        if links[t] is None:
            continue
        i, j = links[t]
        prev = dets[(t - 1) % n][0]
        # keep only links that are part of a >= 3-frame track (continued on either side)
        nxt = links[(t + 1) % n] if (t + 1 < n or wrap) else None
        prv = links[t - 1] if (t - 1 >= 0 or wrap) else None
        cont = np.zeros(len(i), bool)
        if nxt is not None:
            cont |= np.isin(j, nxt[0])
        if prv is not None and prv is not None:
            cont |= np.isin(i, prv[1])
        i, j = i[cont], j[cont]
        if len(i) >= 3:
            d = (c[j] - prev[i]) * fps
            sp = np.hypot(d[:, 0], d[:, 1])
            mv = sp > MOVE_PX_S
            out["moving"][t], out["n_moving"][t] = mv.mean(), mv.sum()
            if mv.sum() >= 2:
                out["speed"][t] = np.median(sp[mv])
                out["vx"][t], out["vy"][t] = np.median(d[mv, 0]), np.median(d[mv, 1])
        # births: detections in the interior with no incoming link; deaths: previous detections with no outgoing link
        ok_new = np.ones(len(c), bool); ok_new[j] = False
        ok_old = np.ones(len(prev), bool); ok_old[i] = False
        cy, cx = c[:, 1].astype(int).clip(0, mask.shape[0] - 1), c[:, 0].astype(int).clip(0, mask.shape[1] - 1)
        py, px = prev[:, 1].astype(int).clip(0, mask.shape[0] - 1), prev[:, 0].astype(int).clip(0, mask.shape[1] - 1)
        out["births"][t] = (ok_new & inner[cy, cx]).sum() / area_px * 1e4
        out["deaths"][t] = (ok_old & inner[py, px]).sum() / area_px * 1e4
    return out


# ---------------- main analysis ----------------
def analyze(frames, scene, masks, fps, wrap, thr=None, ref_med=None):
    n = len(frames)
    G = [gray(f) for f in frames]
    lags = sorted({max(1, round(s * fps)) for s in LAGS_S})
    res = {"n": n, "fps": fps, "wrap": wrap, "lags": lags, "E": {}, "beads": {}, "static": {}}
    for b in BANDS:
        F = np.stack([band(g, b) for g in G]).astype(np.float32)
        for r, m in masks.items():
            P = F[:, m]
            for k in lags:
                e = np.full(n, np.nan)
                for t in range(n):
                    if t - k >= 0 or wrap:
                        e[t] = np.sqrt(np.mean((P[t] - P[(t - k) % n]) ** 2))
                res["E"][f"{r}|{b}|{k}"] = e
        del F
    thr = thr or {}
    for r in scene.get("bead_regions", []):
        if r not in thr:  # threshold fixed from the SOURCE: p99 of top-hat inside the region
            th = np.concatenate([cv2.morphologyEx(g, cv2.MORPH_TOPHAT, KER)[masks[r]] for g in G[::8]])
            thr[r] = float(max(8.0, np.percentile(th, 99)))
        res["beads"][r] = bead_series(G, masks[r], thr[r], fps, wrap)
    # static structure: per-frame max over 32 px tiles of |edges - reference edges| (tile mean), luma too
    sm = masks["static"]
    ed = [cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)) for g in G]
    if ref_med is None:
        ref_med = {"edge": np.median(np.stack(ed[:: max(1, n // 40)]), 0), "luma": np.median(np.stack(G[:: max(1, n // 40)]), 0)}
    h, w = sm.shape
    tiles = [(y, x) for y in range(0, h - 31, 32) for x in range(0, w - 31, 32) if sm[y:y + 32, x:x + 32].mean() > 0.6]
    edev, ldev = np.zeros(n), np.zeros(n)
    for t in range(n):
        ee = np.abs(ed[t] - ref_med["edge"]); ll = G[t] - ref_med["luma"]
        edev[t] = max(float(ee[y:y + 32, x:x + 32].mean()) for y, x in tiles)
        ldev[t] = max(abs(float(ll[y:y + 32, x:x + 32].mean())) for y, x in tiles)
    res["static"] = {"edge_dev": edev, "luma_dev": ldev, "tiles": len(tiles)}
    return res, thr, ref_med


def summarize_reference(ref):
    fps = ref["fps"]
    w = max(1, round(ROLL_S * fps))
    s = {"med": {}, "roll_min": {}, "max1": {}, "beads": {}, "static": {}}
    for key, e in ref["E"].items():
        med = float(np.nanmedian(e))
        s["med"][key] = med
        R = e / (med + 1e-6)
        s["roll_min"][key] = float(np.nanmin(roll_mean(R, w, False)))
        s["max1"][key] = float(np.nanmax(R))
    bw = max(2, round(BEAD_WIN_S * fps))
    for r, bs in ref["beads"].items():
        s["beads"][r] = {}
        for k in ("count", "contrast", "area", "moving", "speed", "births", "deaths"):
            rm = roll_mean(np.nan_to_num(bs[k], nan=0.0) if k == "moving" else bs[k], bw, False)
            s["beads"][r][k] = {"p5": float(np.nanpercentile(rm, 5)), "p50": float(np.nanpercentile(rm, 50)),
                                "p95": float(np.nanpercentile(rm, 95)), "min": float(np.nanmin(rm)),
                                "max": float(np.nanmax(rm)), "valid": int(np.sum(~np.isnan(bs[k])))}
        # moving bead steps per 0.5 s window: below 8 the moving-fraction statistic is noise -> insufficient evidence
        s["beads"][r]["moving_steps_per_window_med"] = float(np.nanmedian(roll_mean(np.nan_to_num(bs["n_moving"]), bw, False)) * bw)
    s["static"] = {k: float(np.max(v)) for k, v in ref["static"].items() if k != "tiles"}
    return s


def gate(res, S, masks, scene, low=0.5, low_tex=0.35, spike=3.0, lo_f=0.85, hi_f=1.15, relative_low=False):
    fps, wrap = res["fps"], res["wrap"]
    w = max(1, round(ROLL_S * fps))
    k1, k4 = res["lags"][0], min(res["lags"], key=lambda k: abs(k / fps - 4 / 24))
    out = {}
    for r in masks:
        if r == "static":
            continue
        g = {}
        worst = {"low": (9.0, None, 9.0, low), "low_texture": (9.0, None, 9.0, low_tex)}  # (value / limit, at, value, limit)
        worst_sp, where_sp = 0.0, None
        k_long = [k for k in res["lags"] if k / fps >= 4 / 24 - 1e-6]
        for b in ("raw", "fine"):
            for k in [k1] + k_long:
                key = f"{r}|{b}|{k}"
                sk = key if key in S["med"] else f"{r}|{b}|{round(k / fps * 24)}"  # other fps: matched time lag
                R = res["E"][key] / (S["med"][sk] + 1e-6)
                rm = roll_mean(R, w, wrap)
                which = "low_texture" if k == k1 else "low"
                if b == "raw" or which == "low_texture":
                    # relative_low (declared moving light only): a region whose own take lulls (pulsing light between
                    # pulses) may lull as low in the loop; 0.85 = margin. NOT for other scenes: replayed on the
                    # harvester, it passed old-route closures whose drum-cell stall a reviewer saw.
                    lim = low if which == "low" else low_tex
                    if relative_low:
                        lim = min(lim, LOW_MARGIN * S["roll_min"][sk])
                    v = float(np.nanmin(rm))
                    if v / lim < worst[which][0]:
                        worst[which] = (v / lim, (key, int(np.nanargmin(rm))), v, lim)
                if k == k1:
                    lim = max(spike, S["max1"][sk])
                    if np.nanmax(R) / lim > worst_sp:
                        worst_sp, where_sp = float(np.nanmax(R) / lim), (key, int(np.nanargmax(R)), float(np.nanmax(R)))
        for which in ("low", "low_texture"):
            ratio, at, v, lim = worst[which]
            g[which] = {"pass": ratio >= 1.0, "min_roll_R": round(v, 3), "limit": round(lim, 3), "at": at}
        g["spike"] = {"pass": worst_sp <= 1.0, "max_R_over_limit": round(worst_sp, 3), "at": where_sp}
        if r in res["beads"]:
            bw = max(2, round(BEAD_WIN_S * fps))
            bg = {}
            for k in ("moving", "speed", "count", "contrast", "births", "deaths"):
                ref = S["beads"][r][k]
                if ref["valid"] < 30 or (k in ("moving", "speed") and S["beads"][r]["moving_steps_per_window_med"] < 8):
                    bg[k] = {"pass": None, "why": "insufficient source tracks",
                             "moving_steps_per_window": S["beads"][r]["moving_steps_per_window_med"]}
                    continue
                rm = roll_mean(np.nan_to_num(res["beads"][r][k], nan=0.0) if k == "moving" else res["beads"][r][k], bw, wrap)
                if k == "speed":  # windows with no moving beads have no speed: the moving gate covers them
                    rm = np.where(np.isnan(rm), ref["p50"], rm)
                lo, hi = lo_f * ref["min"], hi_f * ref["max"]  # outside every ordinary source window, with margin
                mn, mx = float(np.nanmin(rm)), float(np.nanmax(rm))
                bg[k] = {"pass": bool(mn >= lo and mx <= hi), "min": round(mn, 3), "max": round(mx, 3),
                         "ref_p5": round(ref["p5"], 3), "ref_p95": round(ref["p95"], 3),
                         "at_min": int(np.nanargmin(rm)), "at_max": int(np.nanargmax(rm))}
            g["beads"] = bg
        out[r] = g
    st = {}
    for k in ("edge_dev", "luma_dev"):
        v = float(np.max(res["static"][k]))
        st[k] = {"pass": v <= 1.5 * S["static"][k] + (1.0 if k == "luma_dev" else 0), "max": round(v, 2),
                 "src_max": round(S["static"][k], 2), "at": int(np.argmax(res["static"][k]))}
    out["static"] = st
    return out


def gap_motion(res, S, gap_start, margin=12) -> dict:
    """Per region: mean lag-1 raw R over the closure gap [gap_start, n) divided by its mean over the rest of the loop.
    A closure that catches a rotating wheel up to its target runs that region 1.12-1.16x faster through the WHOLE gap
    (dir_furnace_bright, all seeds; the user saw a shudder) while whole-frame steps stay <= 1.4x: sustained, not a
    spike, so neither the closing score nor the spike gate sees it."""
    k1 = res["lags"][0]
    out = {}
    for key, e in res["E"].items():
        r, b, k = key.split("|")
        if b != "raw" or int(k) != k1:
            continue
        R = e / (S["med"][key] + 1e-6)
        rest = R[margin:gap_start - margin]
        out[r] = round(float(np.nanmean(R[gap_start:]) / (np.nanmean(rest) + 1e-6)), 3) if len(rest) else float("nan")
    return out


def verdict(g):
    fails = []
    for r, gg in g.items():
        for name, v in gg.items():
            if name == "beads":
                fails += [f"{r}.beads.{k}" for k, vv in v.items() if vv["pass"] is False]
            elif v["pass"] is False:
                fails.append(f"{r}.{name}")
    return fails


AUTO_GRID = (3, 4)  # rows, cols


def auto_scene(ref_gray) -> dict:
    """No hand-drawn boxes: grid cells with above-median reference activity become regions."""
    act = np.abs(np.diff(np.stack(ref_gray), axis=0)).mean(0)
    h, w = act.shape
    R, C = AUTO_GRID
    cells = {f"c{r}{c}": [c * w // C, r * h // R, (c + 1) * w // C, (r + 1) * h // R] for r in range(R) for c in range(C)}
    score = {k: float(act[y0:y1, x0:x1].mean()) for k, (x0, y0, x1, y1) in cells.items()}
    med = float(np.median(list(score.values())))
    return {"regions": {k: [v] for k, v in cells.items() if score[k] > med}, "bead_regions": [], "auto": True}


@dataclass
class Reference:
    scene: dict
    masks: dict
    thr: dict
    ref_med: dict
    S: dict
    fps: float


def reference(frames, scene: dict | None = None, fps: float = 24) -> Reference:
    """Build the QC reference from ordinary footage (the take), not from anything under test."""
    G = [gray(f) for f in frames]
    scene = scene or auto_scene(G)
    masks, _ = build_masks(scene, G)
    ref, thr, ref_med = analyze(frames, scene, masks, fps, wrap=False)
    return Reference(scene, masks, thr, ref_med, summarize_reference(ref), fps)


def evaluate(frames, ref: Reference, wrap: bool = True, fps: float | None = None, **gate_kw) -> tuple[dict, dict]:
    """-> (report {gates, fails, verdict}, raw analysis for plots)."""
    fps = fps or ref.fps
    res, _, _ = analyze(frames, ref.scene, ref.masks, fps, wrap, thr=dict(ref.thr), ref_med=ref.ref_med)
    g = gate(res, ref.S, ref.masks, ref.scene, **gate_kw)
    fails = verdict(g)
    return {"gates": _jsonable(g), "fails": fails, "verdict": "FAIL" if fails else "PASS"}, res


def _jsonable(o):
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.generic):
        return o.item()
    return o


def plots(res, S, masks, marks, path, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    regs = [r for r in masks if r != "static"]
    fps, n = res["fps"], res["n"]
    w = max(1, round(ROLL_S * fps))
    t = np.arange(n) / fps
    nb = len(res["beads"])
    fig, ax = plt.subplots(len(regs) + nb + 1, 1, figsize=(12, 2.2 * (len(regs) + nb + 1)), sharex=True)
    for i, r in enumerate(regs):
        for b, k, col in (("raw", res["lags"][0], "C0"), ("fine", res["lags"][0], "C1"), ("raw", res["lags"][-1], "C2")):
            key = f"{r}|{b}|{k}"
            sk = key if key in S["med"] else f"{r}|{b}|{round(k / fps * 24)}"
            R = res["E"][key] / (S["med"][sk] + 1e-6)
            ax[i].plot(t, R, col, lw=0.5, alpha=0.5)
            ax[i].plot(t, roll_mean(R, w, res["wrap"]), col, lw=1.4, label=f"{b} lag {k}")
        ax[i].axhline(0.5, color="r", ls="--", lw=0.8); ax[i].axhline(1, color="k", lw=0.5)
        ax[i].set_ylim(0, 4); ax[i].set_ylabel(f"{r}\nE/src med"); ax[i].legend(fontsize=7, loc="upper right", ncol=3)
    for j, (r, bs) in enumerate(res["beads"].items()):
        a = ax[len(regs) + j]
        bw = max(2, round(BEAD_WIN_S * fps))
        for k, col in (("moving", "C0"), ("speed", "C1"), ("count", "C2"), ("contrast", "C3")):
            ref = S["beads"][r][k]["p50"] or 1
            v = np.nan_to_num(bs[k], nan=0.0) if k == "moving" else bs[k]
            a.plot(t, roll_mean(v, bw, res["wrap"]) / ref, col, lw=1.2, label=k)
        a.axhline(1, color="k", lw=0.5); a.set_ylim(0, 2.5); a.set_ylabel(f"{r} beads\n/src median")
        a.legend(fontsize=7, loc="upper right", ncol=4)
    a = ax[-1]
    a.plot(t, res["static"]["edge_dev"] / S["static"]["edge_dev"], label="static edge dev / src max")
    a.plot(t, res["static"]["luma_dev"] / max(S["static"]["luma_dev"], 0.5), label="static luma dev / src max")
    a.axhline(1.5, color="r", ls="--", lw=0.8); a.legend(fontsize=7); a.set_xlabel("s")
    for aa in ax:
        for m in marks:
            aa.axvline(m / fps, color="m", lw=0.8)
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=80)
    plt.close(fig)


def slices(frames, masks, scene, path, marks, act, fps):
    """Vertical space-time slices (y down, time right, 2 px per frame) through the 4 glass columns with the most
    source activity: sliding beads draw diagonal streaks; a stall draws horizontal lines."""
    regs = scene.get("bead_regions") or list(scene["regions"])
    m = np.zeros_like(masks["static"])
    for r in regs:
        m |= masks[r]
    colscore = np.where(m, act, 0).sum(0)
    cols = []
    for x in np.argsort(colscore)[::-1]:
        if all(abs(x - c) > 40 for c in cols):
            cols.append(int(x))
        if len(cols) == 4:
            break
    rows = []
    for x in cols:
        ys = np.nonzero(m[:, x])[0]
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        sl = np.stack([f[y0:y1, x] for f in frames], axis=1)  # (h, n, 3)
        sl = np.clip(sl.astype(np.float32) * 2.0, 0, 255).astype(np.uint8)
        sl = cv2.resize(sl, (sl.shape[1] * 2, (y1 - y0) * 2), interpolation=cv2.INTER_NEAREST)
        for mk in marks:
            sl[:6, 2 * mk:2 * mk + 2] = (255, 0, 255)
        cv2.putText(sl, f"x={x} y{y0}-{y1}", (4, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        rows.append(sl)
    wmax = max(r.shape[1] for r in rows)
    rows = [np.pad(r, ((0, 4), (0, wmax - r.shape[1]), (0, 0))) for r in rows]
    cv2.imwrite(str(path), np.vstack(rows))


