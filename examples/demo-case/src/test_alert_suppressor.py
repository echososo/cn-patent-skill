"""演练案例的单元测试：python3 -m unittest 或 pytest 都能跑。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from alert_suppressor import Alert, AlertSuppressor, fingerprint  # noqa: E402

BASE = {"P0": 10.0, "P1": 20.0, "P2": 40.0}


def make(level="P1", ts=0.0, title="磁盘使用率 91.2% 超过阈值", source="node-a"):
    return Alert(source=source, title=title, level=level, ts=ts)


def actions(decisions):
    return [d.action for d in decisions]


class FingerprintTest(unittest.TestCase):
    def test_变量部分不影响指纹(self):
        a = fingerprint("node-a", "磁盘使用率 91.2% 超过阈值 at 2026-08-27T10:00:00")
        b = fingerprint("node-a", "磁盘使用率 93.8% 超过阈值 at 2026-08-27T10:05:00")
        c = fingerprint("node-a", "磁盘使用率 91.2% 超过阈值 id=1f0c9a2b-1111-2222-3333-444455556666")
        d = fingerprint("node-a", "磁盘使用率 88.0% 超过阈值 id=7b3e0000-9999-8888-7777-666655554444")
        self.assertEqual(a, b)
        self.assertEqual(c, d)
        self.assertNotEqual(a, c)

    def test_不同告警不同指纹(self):
        self.assertNotEqual(fingerprint("node-a", "磁盘满"), fingerprint("node-a", "内存满"))

    def test_不同来源不同指纹(self):
        self.assertNotEqual(fingerprint("node-a", "磁盘满"), fingerprint("node-b", "磁盘满"))


class SuppressTest(unittest.TestCase):
    def setUp(self):
        self.s = AlertSuppressor(base_window=BASE, max_window=80.0, backoff=2.0, forget_after=1000.0)

    def test_首条立即放行(self):
        out = self.s.submit(make(ts=0))
        self.assertEqual(actions(out), ["emit"])
        self.assertEqual(out[0].window, 20.0)

    def test_窗口内重复被压掉(self):
        self.s.submit(make(ts=0))
        out = self.s.submit(make(ts=5))
        self.assertEqual(actions(out), ["suppress"])
        self.assertEqual(out[0].suppressed, 1)

    def test_窗口到期后先出摘要再放行(self):
        self.s.submit(make(ts=0))
        self.s.submit(make(ts=5))
        self.s.submit(make(ts=6))
        out = self.s.submit(make(ts=20))
        self.assertEqual(actions(out), ["summary", "emit"])
        self.assertEqual(out[0].suppressed, 2)

    def test_不同指纹互不影响(self):
        self.s.submit(make(ts=0, title="磁盘满"))
        out = self.s.submit(make(ts=1, title="内存满"))
        self.assertEqual(actions(out), ["emit"])
        self.assertEqual(self.s.pending_windows(), 2)

    def test_连续吵闹窗口翻倍(self):
        self.s.submit(make(ts=0))
        self.s.submit(make(ts=5))
        out = self.s.submit(make(ts=20))  # 第二个窗口
        self.assertEqual(out[-1].window, 40.0)

    def test_退避有上限(self):
        ts = 0.0
        for _ in range(5):
            self.s.submit(make(ts=ts))
            self.s.submit(make(ts=ts + 1))
            ts += 200.0
        out = self.s.submit(make(ts=ts))
        self.assertLessEqual(out[-1].window, 80.0)

    def test_安静一个窗口后回落(self):
        self.s.submit(make(ts=0))
        self.s.submit(make(ts=5))          # 吵 -> streak 1
        out = self.s.submit(make(ts=20))   # 窗口 40
        self.assertEqual(out[-1].window, 40.0)
        self.s.tick(now=100)               # 这一窗没重复 -> streak 回落
        out = self.s.submit(make(ts=120))
        self.assertEqual(out[-1].window, 20.0)

    def test_等级升高立即放行并重开窗口(self):
        self.s.submit(make(level="P2", ts=0))
        self.s.submit(make(level="P2", ts=1))
        out = self.s.submit(make(level="P0", ts=2))
        self.assertEqual(actions(out), ["summary", "escalate"])
        self.assertEqual(out[0].suppressed, 1)
        self.assertEqual(out[1].window, 10.0)

    def test_等级降低不放行(self):
        self.s.submit(make(level="P0", ts=0))
        out = self.s.submit(make(level="P2", ts=1))
        self.assertEqual(actions(out), ["suppress"])

    def test_tick补发摘要且只发一次(self):
        self.s.submit(make(ts=0))
        self.s.submit(make(ts=5))
        first = self.s.tick(now=20)
        second = self.s.tick(now=21)
        self.assertEqual(actions(first), ["summary"])
        self.assertEqual(first[0].suppressed, 1)
        self.assertEqual(second, [])
        self.assertEqual(self.s.pending_windows(), 0)


if __name__ == "__main__":
    unittest.main()
