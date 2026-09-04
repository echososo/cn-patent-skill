#!/usr/bin/env python3
"""发布前扫描：检查一个目录里有没有个人信息或密钥残留。

用法：
  python3 strip_personal.py <目录>
  python3 strip_personal.py <目录> --json
  python3 strip_personal.py <目录> --rules 我的规则.json

命中任何一条即退出码 1（发布流程据此失败）。只读，不改任何文件。
自身和自己的测试文件不在扫描范围内（它们必须写出这些模式才能工作）。

内置的只有通用模式：邮箱地址、个人绝对路径、常见密钥前缀。
**你自己的名字、账号、域名、在审案件关键词不写在代码里**——写进一个规则文件：

    {"我的名字": "作者名", "mydomain\\.com": "个人域名"}

键是正则，值是这条规则的说明。放在被扫目录下叫 `strip_personal.rules.json`
会被自动读到（本仓库的 .gitignore 已经忽略这个文件名，不会被提交上去），
也可以用 `--rules 路径` 显式指定。样例见 `scripts/strip_personal.rules.example.json`。

机读约定（全包统一）：干净时 stdout 最后一行 `OK: hits=0 files=N`（--json 时打到 stderr）；
有残留或目录不存在时 stderr 一行 `FAIL: ...`，退出码 1。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 内置模式 -> 说明。只放通用的；个人化的模式写进规则文件，见模块开头。
BUILTIN_PATTERNS: dict[str, str] = {
    r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}": "邮箱地址",
    r"/Users/[A-Za-z]": "macOS 个人绝对路径",
    r"[A-Z]:\\Users\\": "Windows 个人绝对路径",
    r"/sessions/[a-z0-9-]{8,}": "沙盒会话路径",
    r"(?:ghp_|github_pat_|gho_|sk-[A-Za-z0-9]|AKIA[A-Z0-9]{6}|xox[baprs]-)": "疑似密钥或令牌",
}

RULES_FILENAME = "strip_personal.rules.json"


def load_rules(root: Path, rules_path: str | None) -> dict[str, str]:
    """内置模式 + 规则文件里的模式。规则文件不存在就只用内置的。"""
    patterns = dict(BUILTIN_PATTERNS)
    candidate = Path(rules_path) if rules_path else root / RULES_FILENAME
    if rules_path and not candidate.is_file():
        raise FileNotFoundError(str(candidate))
    if candidate.is_file():
        extra = json.loads(candidate.read_text(encoding="utf-8"))
        if not isinstance(extra, dict):
            raise ValueError(f"{candidate} 里应该是 {{正则: 说明}} 的对象")
        for pattern, why in extra.items():
            re.compile(pattern)          # 坏正则早点炸，别扫到一半才发现
            patterns[str(pattern)] = str(why)
    return patterns


SKIP_NAMES = {"strip_personal.py", "test_strip_personal.py", RULES_FILENAME}
SKIP_DIRS = {".git", "__pycache__", "node_modules"}
TEXT_SUFFIXES = {".md", ".py", ".sh", ".ps1", ".txt", ".json", ".canvas", ".yaml", ".yml", ".toml", ".css", ".base"}


def scan_file(path: Path, patterns: dict[str, str] | None = None) -> list[dict]:
    patterns = BUILTIN_PATTERNS if patterns is None else patterns
    hits = []
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, OSError):
        return hits  # 非文本文件不扫
    for lineno, line in enumerate(text.splitlines(), 1):
        for pattern, why in patterns.items():
            if re.search(pattern, line):
                hits.append({
                    "file": str(path), "line": lineno, "why": why,
                    "pattern": pattern,
                    "snippet": line.strip()[:100],
                })
    return hits


def iter_files(root: Path):
    """该扫的文件：跳过自身、隐藏目录、非文本后缀。"""
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in SKIP_NAMES:
            continue
        if any(part in SKIP_DIRS or part.startswith(".") for part in path.relative_to(root).parts[:-1]):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.suffix != "":
            continue
        yield path


def scan(root: Path, patterns: dict[str, str] | None = None) -> list[dict]:
    patterns = load_rules(root, None) if patterns is None else patterns
    hits = []
    for path in iter_files(root):
        hits.extend(scan_file(path, patterns))
    return hits


def _ok(stats: dict, to_stderr: bool = False) -> None:
    """成功收尾行。--json 时打到 stderr，stdout 只留 JSON。"""
    line = "OK: " + " ".join(f"{k}={v}" for k, v in stats.items())
    print(line, file=sys.stderr if to_stderr else sys.stdout, flush=True)


def _fail(reason: str) -> None:
    """失败收尾行，永远在 stderr。先把 stdout 冲掉，免得 2>&1 时顺序乱。"""
    try:
        sys.stdout.flush()
    except (OSError, ValueError):
        pass
    print(f"FAIL: {reason}", file=sys.stderr, flush=True)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="扫描目录里的个人信息或密钥残留，命中即失败")
    ap.add_argument("root", help="要扫描的目录")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--rules", default=None,
                    help=f"额外规则文件（JSON：{{正则: 说明}}）。默认读被扫目录下的 {RULES_FILENAME}")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"错误：{root} 不是目录", file=sys.stderr)
        _fail(f"not_a_directory {root}")
        return 1      # 输入错误是 1；2 留给"依赖/入口不可用"
    try:
        patterns = load_rules(root, args.rules)
    except FileNotFoundError as exc:
        print(f"错误：规则文件不存在：{exc}", file=sys.stderr)
        _fail(f"rules_not_found {exc}")
        return 1
    except (ValueError, re.error, json.JSONDecodeError) as exc:
        print(f"错误：规则文件有问题：{exc}", file=sys.stderr)
        _fail(f"bad_rules {exc}")
        return 1
    files = list(iter_files(root))
    hits = [h for path in files for h in scan_file(path, patterns)]
    if args.json:
        print(json.dumps({"root": str(root), "files": len(files), "hits": hits, "clean": not hits},
                         ensure_ascii=False, indent=2))
    else:
        if hits:
            print(f"发现 {len(hits)} 处个人信息残留：")
            for h in hits:
                print(f"  [{h['why']}] {h['file']}:{h['line']}  {h['snippet']}")
            print("\n发布中止。清干净再发。")
        else:
            print(f"干净：{root} 未发现个人信息残留。")
    if hits:
        _fail(f"hits={len(hits)} files={len(files)}")
        return 1
    _ok({"hits": 0, "files": len(files)}, to_stderr=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
