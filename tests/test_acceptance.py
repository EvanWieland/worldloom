"""Content gates (handoff 2026-09-27 §7): cached computation is not cached approval; a decision binds to the exact
artifact and contract; a rejection stops everything downstream."""
import json
import tempfile
import unittest
from pathlib import Path

try:
    import cv2  # noqa: F401  (loop_pipeline imports the CPU stages)
    HAVE = True
except ImportError:  # only cv2 is optional; a missing looper module must fail, not skip
    HAVE = False
from looper import acceptance, front
from looper.engine import Engine


@unittest.skipUnless(HAVE, "needs cv2 (WanGP venv)")
class TestGate(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.engine = Engine(self.dir, "r")
        self.ref = {"stage": "take", "fingerprint": "f1", "output": "take.mp4", "output_sha": "s1", "contract_sha": "c1"}

    def gate(self, ref):
        from looper.loop_pipeline import _gate
        return _gate(self.engine, self.dir, "take", ref, {"review": "audition.md"})

    def test_pending_then_accepted(self):
        with self.assertRaises(front.AwaitingApproval):
            self.gate(self.ref)
        self.assertTrue((self.dir / "review" / "pending_take.json").exists())
        acceptance.record(self.dir, "take", "accepted", "waves fine")
        self.assertEqual(self.gate(self.ref)["status"], "accepted")

    def test_changed_output_or_contract_invalidates(self):
        with self.assertRaises(front.AwaitingApproval):
            self.gate(self.ref)
        acceptance.record(self.dir, "take", "accepted")
        for change in ({"output_sha": "s2"}, {"contract_sha": "c2"}, {"fingerprint": "f2"}):
            with self.assertRaises(front.AwaitingApproval):
                self.gate({**self.ref, **change})

    def test_rejected_stops(self):
        with self.assertRaises(front.AwaitingApproval):
            self.gate(self.ref)
        acceptance.record(self.dir, "take", "rejected", "lantern off")
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            self.gate(self.ref)

    def test_history_is_kept_and_newest_wins(self):
        with self.assertRaises(front.AwaitingApproval):
            self.gate(self.ref)
        acceptance.record(self.dir, "take", "rejected")
        acceptance.record(self.dir, "take", "accepted", "second look")
        self.assertEqual(self.gate(self.ref)["note"], "second look")
        log = (self.dir / "acceptance.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(x)["status"] for x in log], ["rejected", "accepted"])

    def test_giving_up_is_unresolved_with_the_unmet_requirement(self):  # realism amendment §11
        from looper.loop_pipeline import unresolved
        r = unresolved(self.engine, "no usable take in 3 seeds (region drift [9.1, 8.4, 12.0] grey; limit 7.5)")
        self.assertEqual((r["outcome"], r["failed_at"]), ("unresolved", "take_qc"))
        self.assertIn("loopable take", r["unmet"])
        self.engine.run_stage("close", 1, {}, {}, lambda i, c, o: {}, key="close[306]")
        with self.assertRaises(RuntimeError):
            self.engine.run_stage("splice", 1, {}, {}, lambda i, c, o: (_ for _ in ()).throw(RuntimeError("x")))
        self.assertEqual(unresolved(self.engine, "something new")["failed_at"], "splice")

    def test_nothing_pending_refuses(self):
        with self.assertRaises(FileNotFoundError):
            acceptance.record(self.dir, "loop", "accepted")


if __name__ == "__main__":
    unittest.main()
