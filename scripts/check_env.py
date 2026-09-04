#!/usr/bin/env python3
"""环境体检：看看这台机器能用本包的哪些功能，缺什么、怎么补。

用法：python3 check_env.py [--json]

技能规则本身是纯 Markdown，不需要 Python——本脚本只检查 scripts/ 和 mcp/ 下工具的可用性。

成功时 stdout 最后一行：OK: python=.. python_ok=0/1 modules_ok=N modules_missing=N missing=a,b hosts=..
（--json 时 OK 行打到 stderr，stdout 只有 JSON）。缺可选模块不算失败——本脚本只报告，不下结论。
"""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sys
from pathlib import Path


class _Parser(argparse.ArgumentParser):
    """参数错误也走 FAIL: 行，退出码 1（argparse 默认 2，会和"缺依赖"混淆）。"""

    def error(self, message):
        print(f"FAIL: 参数错误：{message}", file=sys.stderr)
        raise SystemExit(1)


REQUIRED_PY = (3, 9)

# 模块名 -> (pip 包名, 谁需要它)
OPTIONAL_MODULES = {
    "docx": ("python-docx", "docx_to_md.py / md_to_docx.py（Word 转换）"),
    "pypdf": ("pypdf", "pdf_to_text.py（PDF 抽文本）"),
    "matplotlib": ("matplotlib", "make_figure.py（画附图）"),
    "yaml": ("pyyaml", "make_figure.py 的 YAML 输入（可选，JSON 不需要）"),
    "latex2mathml": ("latex2mathml", "md_to_docx.py 把 LaTeX 公式转成 Word 可编辑公式（没装则公式按原文保留）"),
    "pptx": ("python-pptx", "pptx_to_md.py（PPT 转 Markdown）"),
    "playwright": ("playwright", "mermaid_render.py 出图、cnipa_search.py 查国知局（另需本机 Chrome/Edge，或 playwright install chromium）"),
}
# 这些没装也不影响主流程，补齐命令里单独说明
SOFT_OPTIONAL = {"yaml", "playwright"}

HOSTS = {
    "Claude Code": ".claude",
    "Codex CLI": ".codex",
    "Cursor": ".cursor",
    "WorkBuddy": ".workbuddy",
    "nanobot": ".nanobot",
}


def check(home: Path | None = None) -> dict:
    home = home or Path.home()
    py_ok = sys.version_info[:2] >= REQUIRED_PY
    modules = {}
    for mod, (pip_name, used_by) in OPTIONAL_MODULES.items():
        try:
            importlib.import_module(mod)
            modules[mod] = {"ok": True, "pip": pip_name, "used_by": used_by}
        except ImportError:
            modules[mod] = {"ok": False, "pip": pip_name, "used_by": used_by}
    hosts = {}
    skill_name = "patent-writing-pro"
    for label, dot in HOSTS.items():
        root = home / dot
        sub = "workspace/skills" if dot == ".nanobot" else "skills"
        installed = (root / sub / skill_name / "SKILL.md").exists()
        hosts[label] = {"present": root.is_dir(), "skill_installed": installed}
    return {
        "python": {"version": sys.version.split()[0], "ok": py_ok,
                   "need": f"{REQUIRED_PY[0]}.{REQUIRED_PY[1]}+"},
        "modules": modules,
        "hosts": hosts,
        "obsidian_hint": bool(shutil.which("obsidian"))
        or (home / "Library/Application Support/obsidian").exists()
        or (home / ".config/obsidian").exists()
        or (home / "AppData/Roaming/obsidian").exists(),
    }


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = _Parser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    r = check()
    missing_all = [m for m, info in r["modules"].items() if not info["ok"]]
    ok_line = (f"OK: python={r['python']['version']} python_ok={int(r['python']['ok'])} "
               f"modules_ok={len(r['modules']) - len(missing_all)} modules_missing={len(missing_all)} "
               f"missing={','.join(missing_all) or '-'} "
               f"hosts={','.join(h for h, i in r['hosts'].items() if i['present']) or '-'}")
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        print(ok_line, file=sys.stderr)
        return 0
    p = r["python"]
    print(f"Python {p['version']}  {'OK' if p['ok'] else '低于 ' + p['need'] + '，转换和附图脚本可能跑不了'}")
    print()
    missing = []
    for mod, info in r["modules"].items():
        mark = "OK  " if info["ok"] else "缺  "
        print(f"  [{mark}] {info['pip']:<14} 用于 {info['used_by']}")
        if not info["ok"]:
            missing.append((mod, info["pip"]))
    if missing:
        core = [pip for mod, pip in missing if mod not in SOFT_OPTIONAL]
        soft = [pip for mod, pip in missing if mod in SOFT_OPTIONAL]
        if core:
            print(f"\n  一条命令补齐：pip3 install {' '.join(core)}")
        if soft:
            print(f"  另有可选的：pip3 install {' '.join(soft)}"
                  + ("；playwright 装完还要本机有 Chrome/Edge，或跑 playwright install chromium"
                     if "playwright" in soft else ""))
        print("  （技能规则本身不需要任何依赖）")
    print()
    for label, info in r["hosts"].items():
        if info["present"]:
            state = "已装本技能" if info["skill_installed"] else "在，但还没装本技能（跑 install/install.sh）"
            print(f"  {label}：{state}")
    if r["obsidian_hint"]:
        print("  Obsidian：检测到，案件图谱可以直接看")
    else:
        print("  Obsidian：未检测到（可选，装了才能看案件图谱；obsidian.md 官网免费下载）")
    print(ok_line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
