#!/usr/bin/env python3
"""把本地工具服务（local_tools.py）注册进各宿主的 MCP 配置。可选，主流程不需要它。

只有宿主没有终端、agent 自己跑不了 Python 脚本时才用得上：注册之后 agent 能直接调
form_check / docx_to_md / md_to_docx / pdf_to_text / make_figure / build_case_graph 六个工具。
Claude Code / Codex / Cursor 这类有终端的宿主不用装，直接跑 scripts/ 下的脚本更省事。

用法：
  python3 register.py                 # 写进探测到的宿主
  python3 register.py --dry-run       # 只看会改什么，不落盘

动刀的文件（每个都先备份成 .bak-日期）：
  Claude Code   ~/.claude.json                mcpServers.patent-local-tools（stdio）
  Cursor        ~/.cursor/mcp.json            mcpServers.patent-local-tools（stdio）
  Codex CLI     ~/.codex/config.toml          [mcp_servers.patent-local-tools]（stdio）
  WorkBuddy     ~/.workbuddy/.mcp.json        mcpServers.patent-local-tools（stdio）
nanobot 的配置格式官方没写清，打印手动配置片段。

纯标准库。重复跑安全：同名条目原地替换，不会越积越多。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

LOCAL_NAME = "patent-local-tools"


def backup(path: Path) -> str:
    if path.exists():
        b = path.with_name(path.name + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        b.write_bytes(path.read_bytes())
        return b.name
    return ""


def upsert_json(path: Path, entries: dict, dry: bool) -> str:
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return f"跳过：{path} 不是合法 JSON，没敢动，请手动检查"
    servers = data.setdefault("mcpServers", {})
    servers.update(entries)
    if dry:
        return f"会写入 {path}（{', '.join(entries)}）"
    b = backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"已写入 {path}" + (f"（原文件备份为 {b}）" if b else "")


def upsert_toml(path: Path, blocks: dict[str, str], dry: bool) -> str:
    """按节名整节替换/追加。不引入 TOML 库，只做保守的文本操作。"""
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    for section, block in blocks.items():
        pattern = re.compile(
            rf"(?ms)^\[{re.escape(section)}\]\s*$.*?(?=^\[|\Z)")
        if pattern.search(text):
            text = pattern.sub(block.rstrip() + "\n\n", text)
        else:
            if text and not text.endswith("\n\n"):
                text = text.rstrip("\n") + "\n\n"
            text += block.rstrip() + "\n\n"
    if dry:
        return f"会写入 {path}（{', '.join(blocks)}）"
    b = backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return f"已写入 {path}" + (f"（原文件备份为 {b}）" if b else "")


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--home", default=None, help=argparse.SUPPRESS)  # 测试用
    args = ap.parse_args(argv)

    here = Path(__file__).resolve().parent
    local = here / "local_tools.py"
    home = Path(args.home) if args.home else Path.home()
    py = sys.executable or "python3"
    dry = args.dry_run
    done, skipped = [], []

    json_hosts = [
        ("Claude Code", home / ".claude", home / ".claude.json", True),
        ("Cursor", home / ".cursor", home / ".cursor" / "mcp.json", False),
        ("WorkBuddy", home / ".workbuddy", home / ".workbuddy" / ".mcp.json", True),
    ]
    for label, marker, cfg, typed in json_hosts:
        if not marker.is_dir():
            skipped.append(label)
            continue
        entry = {"command": py, "args": [str(local)]}
        if typed:
            entry = {"type": "stdio", **entry}
        done.append((label, upsert_json(cfg, {LOCAL_NAME: entry}, dry)))

    if (home / ".codex").is_dir():
        blocks = {f"mcp_servers.{LOCAL_NAME}":
                  f'[mcp_servers.{LOCAL_NAME}]\n'
                  f'command = "{py}"\n'
                  f'args = ["{local}"]\n'}
        done.append(("Codex CLI", upsert_toml(home / ".codex" / "config.toml", blocks, dry)))
    else:
        skipped.append("Codex CLI")

    for label, note in done:
        print(f"  {label}：{note}")
    if skipped:
        print(f"  没装所以跳过：{'、'.join(skipped)}")
    if not done:
        print("  一个宿主都没探测到（~/.claude、~/.cursor、~/.codex、~/.workbuddy 都不存在），什么都没写。")
        sys.stdout.flush()
        print("FAIL: no_host_detected hosts=0", file=sys.stderr, flush=True)   # 全包统一的机读收尾行
        return 2

    if (home / ".nanobot").is_dir():
        print(f"\n  nanobot 检测到，但它的 MCP 配置格式官方没写清（没实测过）。"
              f"通用做法：在它的 MCP/插件设置里加一个本地命令服务：\n"
              f"    命令：{py}\n    参数：{local}")

    print("\n注册完重启对应的 agent 生效。验证：问它「用 form_check 检查 examples/demo-case/bad-draft.md」。")
    print(f"OK: hosts={len(done)} skipped={len(skipped)} dry_run={int(dry)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
