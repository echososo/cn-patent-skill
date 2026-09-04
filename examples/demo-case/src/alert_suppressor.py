"""告警抑制器（演练用虚构代码，不对应任何真实系统）。

场景：同一条告警在几分钟内反复触发，值班群被刷屏，真正要紧的那条反而被淹没。

做法四步：
1. 归一化指纹：把告警标题里易变的部分（时间戳、UUID、数字）抹成通配符再取哈希，
   同一类告警落到同一个指纹上；
2. 抑制窗口：同一指纹在窗口内只发一条，其余只计数；
3. 自适应窗口：窗口长度＝该等级的基础窗口 × 退避倍数^连续吵闹次数，并设上限；
   安静一个窗口就回落一级；
4. 升级逃逸与摘要：窗口内等级升高立即放行并重开窗口；窗口关闭时若压过条数大于零，
   补发一条摘要，说明这一窗口合并了多少条。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

LEVEL_ORDER = {"P2": 0, "P1": 1, "P0": 2}
BASE_WINDOW = {"P0": 30.0, "P1": 120.0, "P2": 600.0}  # 秒
MAX_WINDOW = 3600.0
BACKOFF_FACTOR = 2.0

_VARIABLE_PATTERNS = (
    re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I),
    re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"),
    re.compile(r"\d+(?:\.\d+)?"),
)


def fingerprint(source: str, title: str) -> str:
    """抹掉易变部分后取指纹，同一类告警得到同一个值。"""
    normalized = title
    for pattern in _VARIABLE_PATTERNS:
        normalized = pattern.sub("*", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return hashlib.sha256(f"{source}|{normalized}".encode("utf-8")).hexdigest()[:16]


@dataclass
class Alert:
    source: str
    title: str
    level: str
    ts: float


@dataclass
class Decision:
    action: str  # emit / suppress / escalate / summary
    alert: Alert
    window: float
    suppressed: int = 0
    reason: str = ""


@dataclass
class _Window:
    opened_at: float
    length: float
    level: str
    sample: Alert
    count: int = 0
    streak: int = 0
    closed: bool = False


class AlertSuppressor:
    """窗口按指纹独立维护，互不影响。"""

    def __init__(self, base_window=None, max_window=MAX_WINDOW,
                 backoff=BACKOFF_FACTOR, forget_after=None):
        self._base = dict(base_window or BASE_WINDOW)
        self._max = float(max_window)
        self._backoff = float(backoff)
        self._forget_after = float(forget_after if forget_after is not None else max_window)
        self._windows: dict[str, _Window] = {}

    def _length_for(self, level: str, streak: int) -> float:
        return min(self._base[level] * (self._backoff ** streak), self._max)

    def _close(self, win: _Window, escalated: bool = False) -> list[Decision]:
        win.closed = True
        win.streak = win.streak + 1 if win.count > 0 else max(0, win.streak - 1)
        if win.count == 0:
            return []
        reason = "等级升高，提前结算" if escalated else "窗口关闭，合并计数"
        return [Decision("summary", win.sample, win.length, win.count, reason)]

    def _open(self, key: str, alert: Alert, streak: int) -> float:
        length = self._length_for(alert.level, streak)
        self._windows[key] = _Window(alert.ts, length, alert.level, alert, streak=streak)
        return length

    def submit(self, alert: Alert) -> list[Decision]:
        """收一条告警，返回本次产生的判定（可能同时带一条摘要）。"""
        key = fingerprint(alert.source, alert.title)
        out: list[Decision] = []
        win = self._windows.get(key)

        if win and not win.closed and alert.ts >= win.opened_at + win.length:
            out += self._close(win)

        win = self._windows.get(key)
        if win is None or win.closed:
            streak = win.streak if win else 0
            length = self._open(key, alert, streak)
            out.append(Decision("emit", alert, length, 0, "窗口外首条"))
            return out

        if LEVEL_ORDER[alert.level] > LEVEL_ORDER[win.level]:
            out += self._close(win, escalated=True)
            length = self._open(key, alert, 0)
            out.append(Decision("escalate", alert, length, 0, "等级升高"))
            return out

        win.count += 1
        out.append(Decision("suppress", alert, win.length, win.count, "窗口内重复"))
        return out

    def tick(self, now: float) -> list[Decision]:
        """推进时间：关闭到期窗口、补发摘要、遗忘久未复发的退避记忆。"""
        out: list[Decision] = []
        for key, win in list(self._windows.items()):
            if not win.closed and now >= win.opened_at + win.length:
                out += self._close(win)
            if win.closed and now - win.opened_at >= win.length + self._forget_after:
                del self._windows[key]
        return out

    def pending_windows(self) -> int:
        return sum(1 for win in self._windows.values() if not win.closed)
