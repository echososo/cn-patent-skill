"""mcp/ 两个脚本的单元测试（local_tools、register）。纯标准库。"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(HERE))
import register as register_mod  # noqa: E402


class LocalToolsTest(unittest.TestCase):
    def run_session(self, messages: list[dict]) -> list[dict]:
        inp = "\n".join(json.dumps(m, ensure_ascii=False) for m in messages) + "\n"
        proc = subprocess.run([sys.executable, str(HERE / "local_tools.py")],
                              input=inp, capture_output=True, text=True, timeout=120,
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]

    def test_初始化_列表_调用_未知方法(self):
        bad_draft = PKG / "examples" / "demo-case" / "bad-draft.md"
        out = self.run_session([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-03-26"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "form_check", "arguments": {"file": str(bad_draft)}}},
            {"jsonrpc": "2.0", "id": 4, "method": "no/such"},
        ])
        self.assertEqual(len(out), 4)  # 通知不回
        self.assertEqual(out[0]["result"]["protocolVersion"], "2025-03-26")
        names = {t["name"] for t in out[1]["result"]["tools"]}
        self.assertEqual(names, {"form_check", "docx_to_md", "md_to_docx",
                                 "pdf_to_text", "make_figure", "build_case_graph"})
        text = out[2]["result"]["content"][0]["text"]
        self.assertIn("abstract-over-300", text)
        self.assertFalse(out[2]["result"]["isError"])       # 稿子有问题 ≠ 工具坏了
        # 脚本的机读收尾行跟在 JSON 后面，agent 看最后一行就知道结果
        self.assertEqual(text.splitlines()[-1], "FAIL: errors=3 warnings=7 files=1")
        self.assertEqual(out[3]["error"]["code"], -32601)

    def test_缺参数返回isError(self):
        out = self.run_session([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "form_check", "arguments": {}}},
        ])
        self.assertTrue(out[0]["result"]["isError"])

    def test_干净稿子text末行是OK(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "稿.md"
            path.write_text("发明名称：一种方法\n\n权利要求书\n\n1. 一种方法。\n\n技术领域\n\n略。\n\n背景技术\n\n略。\n\n"
                            "发明内容\n\n略。\n\n具体实施方式\n\n略。\n\n摘要\n\n略。\n", encoding="utf-8")
            out = self.run_session([
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": "form_check", "arguments": {"file": str(path)}}},
            ])
            res = out[0]["result"]
            self.assertFalse(res["isError"])
            text = res["content"][0]["text"]
            self.assertEqual(json.loads(text.rsplit("\n", 1)[0])["errors"], 0)   # 前面是干净的 JSON
            self.assertEqual(text.splitlines()[-1], "OK: errors=0 warnings=0 files=1")

    def test_其他工具退出1算isError(self):
        """只有 form_check 的退出码 1 是"稿子有问题"；build_case_graph 的 1 是真错（目录不存在）。"""
        with tempfile.TemporaryDirectory() as td:
            out = self.run_session([
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": "build_case_graph", "arguments": {"case_dir": str(Path(td) / "不存在")}}},
            ])
            res = out[0]["result"]
            self.assertTrue(res["isError"])
            self.assertTrue(res["content"][0]["text"].splitlines()[-1].startswith("FAIL: not_a_directory"))


class RegisterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="reg_")
        self.home = Path(self.tmp.name)
        for d in (".claude", ".cursor", ".codex", ".workbuddy"):
            (self.home / d).mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_reg(self, *extra):
        return register_mod.main(["--home", str(self.home), *extra])

    def test_四宿主都写上本地工具(self):
        self.assertEqual(self.run_reg(), 0)
        claude = json.loads((self.home / ".claude.json").read_text(encoding="utf-8"))
        entry = claude["mcpServers"]["patent-local-tools"]
        self.assertEqual(entry["type"], "stdio")
        self.assertTrue(entry["args"][0].endswith("local_tools.py"))
        cursor = json.loads((self.home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
        self.assertIn("patent-local-tools", cursor["mcpServers"])
        wb = json.loads((self.home / ".workbuddy" / ".mcp.json").read_text(encoding="utf-8"))
        self.assertIn("patent-local-tools", wb["mcpServers"])
        toml = (self.home / ".codex" / "config.toml").read_text(encoding="utf-8")
        self.assertIn("[mcp_servers.patent-local-tools]", toml)
        self.assertIn("local_tools.py", toml)
        # 检索服务那套已经从包里拿掉了，配置里绝不能再冒出来
        for text in (json.dumps(claude), json.dumps(cursor), json.dumps(wb), toml):
            self.assertNotIn("patent-search", text)
            self.assertNotIn("PATENT_SEARCH", text)

    def test_重跑不重复且有备份(self):
        self.run_reg()
        self.run_reg()
        toml = (self.home / ".codex" / "config.toml").read_text(encoding="utf-8")
        self.assertEqual(toml.count("[mcp_servers.patent-local-tools]"), 1)
        backups = list(self.home.glob(".claude.json.bak-*"))
        self.assertTrue(backups)

    def test_保留宿主已有配置(self):
        (self.home / ".claude.json").write_text(
            json.dumps({"theme": "dark", "mcpServers": {"other": {"url": "x"}}}),
            encoding="utf-8")
        (self.home / ".codex" / "config.toml").write_text(
            'model = "o3"\n\n[mcp_servers.other]\ncommand = "x"\n', encoding="utf-8")
        self.run_reg()
        claude = json.loads((self.home / ".claude.json").read_text(encoding="utf-8"))
        self.assertEqual(claude["theme"], "dark")
        self.assertIn("other", claude["mcpServers"])
        toml = (self.home / ".codex" / "config.toml").read_text(encoding="utf-8")
        self.assertIn('model = "o3"', toml)
        self.assertIn("[mcp_servers.other]", toml)

    def test_dryrun不落盘(self):
        self.assertEqual(self.run_reg("--dry-run"), 0)
        self.assertFalse((self.home / ".claude.json").exists())
        self.assertFalse((self.home / ".codex" / "config.toml").exists())

    def test_一个宿主都没有就返回2(self):
        with tempfile.TemporaryDirectory(prefix="empty_") as td:
            self.assertEqual(register_mod.main(["--home", td]), 2)

    def test_机读收尾行(self):
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(self.run_reg("--dry-run"), 0)
        self.assertEqual(out.getvalue().rstrip("\n").splitlines()[-1], "OK: hosts=4 skipped=0 dry_run=1")
        self.assertEqual(err.getvalue(), "")
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory(prefix="empty_") as td, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(register_mod.main(["--home", td]), 2)
        self.assertNotIn("OK:", out.getvalue())
        self.assertEqual(err.getvalue().rstrip("\n").splitlines()[-1], "FAIL: no_host_detected hosts=0")


if __name__ == "__main__":
    unittest.main()
