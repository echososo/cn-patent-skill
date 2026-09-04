#!/usr/bin/env python3
"""本地工具 MCP 服务（stdio）：把包里五个脚本包成工具，宿主没有终端也能调。

宿主有终端（Claude Code / Codex）可以不装它，直接跑 scripts/ 下的脚本。
注册方式见 mcp/README.md。纯标准库实现 MCP stdio 协议，无依赖；
个别工具运行时需要的库（python-docx 等）见 requirements-min.txt。

工具结果的 text 是脚本的 stdout + stderr 原样拼起来，所以包里统一的机读收尾行
（成功 `OK: 键=值 ...`，失败 `FAIL: 原因`）也在里面，agent 看最后一行就知道成没成。
isError 按退出码判：0 成功；form_check 的 1 是"稿子有问题"不是工具坏了，其余工具非 0 都算错。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_VERSION = "2025-06-18"

TOOLS = [
    {
        "name": "form_check",
        "description": "对申请文件（docx/md/txt）做不用模型的形式检查：栏目、字数、权项引用、占位、过强结论、代码符号。",
        "script": "scripts/check_patent_package.py",
        "inputSchema": {"type": "object", "properties": {
            "file": {"type": "string", "description": "要检查的文件路径"}},
            "required": ["file"]},
        "args": lambda a: [a["file"], "--json"],
        "ok_codes": (0, 1),   # 1 = 稿子有 ERROR（stderr 末行 FAIL: errors=N），检查本身是成功的
    },
    {
        "name": "docx_to_md",
        "description": "把 Word 稿转成 Markdown，图片抽到旁边的 _media 文件夹。",
        "script": "scripts/docx_to_md.py",
        "inputSchema": {"type": "object", "properties": {
            "file": {"type": "string"}, "output": {"type": "string"}},
            "required": ["file"]},
        "args": lambda a: [a["file"]] + (["-o", a["output"]] if a.get("output") else []),
    },
    {
        "name": "md_to_docx",
        "description": "把 Markdown 稿转成可提交排版的 Word（宋体/黑体、A4、页码、附图嵌入）。",
        "script": "scripts/md_to_docx.py",
        "inputSchema": {"type": "object", "properties": {
            "file": {"type": "string"}, "output": {"type": "string"}},
            "required": ["file"]},
        "args": lambda a: [a["file"]] + (["-o", a["output"]] if a.get("output") else []),
    },
    {
        "name": "pdf_to_text",
        "description": "把对比文件或通知书 PDF 抽成纯文本文件。",
        "script": "scripts/pdf_to_text.py",
        "inputSchema": {"type": "object", "properties": {
            "file": {"type": "string"}, "output": {"type": "string"}},
            "required": ["file"]},
        "args": lambda a: [a["file"], "--json"] + (["-o", a["output"]] if a.get("output") else []),
    },
    {
        "name": "make_figure",
        "description": "按 JSON/YAML 描述文件画黑白专利附图（框图/流程图）PNG。",
        "script": "scripts/make_figure.py",
        "inputSchema": {"type": "object", "properties": {
            "spec": {"type": "string", "description": "描述文件路径"},
            "output": {"type": "string"}},
            "required": ["spec"]},
        "args": lambda a: [a["spec"]] + (["-o", a["output"]] if a.get("output") else []),
    },
    {
        "name": "build_case_graph",
        "description": "把案件目录的审查材料连成 Obsidian 双链笔记和 Canvas 案件图谱。",
        "script": "obsidian/build_case_graph.py",
        "inputSchema": {"type": "object", "properties": {
            "case_dir": {"type": "string", "description": "案件目录路径"}},
            "required": ["case_dir"]},
        "args": lambda a: [a["case_dir"], "--json"],
    },
]


def run_tool(name: str, arguments: dict) -> dict:
    tool = next((t for t in TOOLS if t["name"] == name), None)
    if tool is None:
        return {"content": [{"type": "text", "text": f"没有叫 {name} 的工具"}], "isError": True}
    script = PKG_ROOT / tool["script"]
    try:
        argv = tool["args"](arguments or {})
    except KeyError as e:
        return {"content": [{"type": "text", "text": f"缺参数：{e}"}], "isError": True}
    proc = subprocess.run([sys.executable, str(script), *argv],
                          capture_output=True, text=True, timeout=300)
    # stdout 在前、stderr 在后：脚本的 OK/FAIL 收尾行（--json 时都在 stderr）落在 text 最后
    text = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return {"content": [{"type": "text", "text": text.strip() or "（无输出）"}],
            "isError": proc.returncode not in tool.get("ok_codes", (0,))}


def handle(msg: dict) -> dict | None:
    method = msg.get("method", "")
    msg_id = msg.get("id")
    if method == "initialize":
        client_ver = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": client_ver,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "patent-writing-pro-local-tools", "version": "1.0.0"},
        }}
    if method.startswith("notifications/"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        tools = [{"name": t["name"], "description": t["description"],
                  "inputSchema": t["inputSchema"]} for t in TOOLS]
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools}}
    if method == "tools/call":
        params = msg.get("params") or {}
        result = run_tool(params.get("name", ""), params.get("arguments") or {})
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    if msg_id is not None:
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"不支持的方法：{method}"}}
    return None


def main() -> int:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
