#!/usr/bin/env python3
"""修订记录：每轮改稿/评审/答复/检索后，往案件目录的 修订记录.md 追加一条，谁改的、为什么、交付了什么，日后可追溯。

用法：
  python3 revision_log.py --case-dir 案件目录 --kind 改稿 \\
      --user "用户这轮说了什么（摘要）" --files "新文件1,新文件2" --summary "改了什么、为什么"

--kind 只认：改稿 | 评审 | 答复 | 检索 | 其他。--files 逗号分隔，可不给。
文件不存在就创建（带表头说明）；已有就在末尾追加，序号顺延。只用标准库。

成功时 stdout 最后一行：OK: entry=N kind=.. files=N out=案件目录/修订记录.md
失败时 stderr 一行 FAIL: 原因；退出码 1。
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


class _Parser(argparse.ArgumentParser):
    """参数错误也走 FAIL: 行，退出码 1（argparse 默认 2，会和"缺依赖"混淆）。"""

    def error(self, message):
        print(f"FAIL: 参数错误：{message}", file=sys.stderr)
        raise SystemExit(1)


LOG_NAME = "修订记录.md"
KINDS = ("改稿", "评审", "答复", "检索", "其他")

HEADER = """# 修订记录

本文件由 scripts/revision_log.py 自动追加：每轮改稿、评审、答复、检索各记一条，说明用户当时的要求、交付了哪些文件、改了什么、为什么。
时间先写本机本地时间，括号内是 UTC。已有条目请勿手改；要补充说明，在条目下另起一行。

"""

_ENTRY_RE = re.compile(r"^## (\d+) · ", re.M)


def next_entry_no(existing: str) -> int:
    nums = [int(m.group(1)) for m in _ENTRY_RE.finditer(existing)]
    return (max(nums) + 1) if nums else 1


def _one_line(text: str) -> str:
    """换行、连续空白压成一个空格，免得把列表项撑破。"""
    return re.sub(r"\s+", " ", text or "").strip()


def format_entry(no: int, kind: str, user: str, files: list[str], summary: str, now: datetime) -> str:
    local = now if now.tzinfo is not None else now.astimezone()   # 传进来的带时区时间就按它的时区写
    utc = local.astimezone(timezone.utc)
    files_text = "、".join(f"`{f}`" for f in files) if files else "（无新文件）"
    return (
        f"## {no} · {local.strftime('%Y-%m-%d %H:%M')} · {kind}\n\n"
        f"- 时间：{local.strftime('%Y-%m-%d %H:%M:%S %z')}（UTC {utc.strftime('%Y-%m-%d %H:%M:%S')}）\n"
        f"- 类型：{kind}\n"
        f"- 用户这轮说的：{_one_line(user)}\n"
        f"- 交付文件：{files_text}\n"
        f"- 改了什么、为什么：{_one_line(summary)}\n\n"
    )


def append_entry(case_dir: Path, kind: str, user: str, files: list[str], summary: str,
                 now: datetime | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"--kind 只认 {' | '.join(KINDS)}，收到：{kind}")
    if not case_dir.is_dir():
        raise FileNotFoundError(f"案件目录不存在：{case_dir}")
    log = case_dir / LOG_NAME
    existing = log.read_text(encoding="utf-8") if log.is_file() else ""
    no = next_entry_no(existing)
    entry = format_entry(no, kind, user, files, summary, now or datetime.now().astimezone())
    if existing:
        body = existing.rstrip("\n") + "\n\n" + entry
    else:
        body = HEADER + entry
    log.write_text(body, encoding="utf-8")
    return {"entry": no, "kind": kind, "files": len(files), "output": str(log), "created": not existing}


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = _Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case-dir", required=True)
    ap.add_argument("--kind", required=True, choices=KINDS)
    ap.add_argument("--user", required=True, help="用户这轮说了什么（摘要）")
    ap.add_argument("--files", default="", help="交付的新文件，逗号分隔")
    ap.add_argument("--summary", required=True, help="改了什么、为什么")
    args = ap.parse_args(argv)
    files = [f.strip() for f in args.files.split(",") if f.strip()]
    try:
        r = append_entry(Path(args.case_dir), args.kind, args.user, files, args.summary)
    except (ValueError, FileNotFoundError, OSError) as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print(f"{'新建' if r['created'] else '追加'} 第 {r['entry']} 条（{r['kind']}）→ {r['output']}")
    print(f"OK: entry={r['entry']} kind={r['kind']} files={r['files']} out={r['output']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
