"""strip_personal 的单元测试：python3 -m unittest 或 pytest 都能跑。"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strip_personal as sp  # noqa: E402


def make_pkg(root: Path, files: dict):
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")


def write_rules(root: Path, rules: dict, name: str = sp.RULES_FILENAME) -> Path:
    p = root / name
    p.write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
    return p


class StripTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="strip_")
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_干净的目录通过(self):
        make_pkg(self.root, {"SKILL.md": "# 技能\n正常内容", "scripts/a.py": "print(1)\n"})
        self.assertEqual(sp.scan(self.root), [])

    def test_内置模式都能抓到(self):
        cases = {
            "a.md": "有事发 someone@example.org",
            "b.md": "路径 /Users/someone/Desktop/x",
            "f.sh": 'echo "C:\\Users\\someone\\pkg"',
            "g.md": "日志在 /sessions/abc12345/mnt 下",
            "h.py": 'TOKEN = "ghp_AAAAAAAAAAAAAAAAAAAA"',
        }
        make_pkg(self.root, cases)
        hits = sp.scan(self.root)
        hit_files = {Path(h["file"]).name for h in hits}
        self.assertEqual(hit_files, set(cases))

    def test_版本号里的at不算邮箱(self):
        make_pkg(self.root, {"a.md": "用的是 mermaid@11.4.1 这一版"})
        self.assertEqual(sp.scan(self.root), [])

    def test_规则文件会被自动读到(self):
        make_pkg(self.root, {"a.md": "联系张三获取更新", "b.md": "没事"})
        self.assertEqual(sp.scan(self.root), [])          # 没有规则文件时不该命中
        write_rules(self.root, {"张三": "作者名"})
        hits = sp.scan(self.root)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["why"], "作者名")
        self.assertEqual(Path(hits[0]["file"]).name, "a.md")

    def test_规则文件自己不被扫(self):
        make_pkg(self.root, {"a.md": "干净"})
        write_rules(self.root, {"张三": "作者名"})
        self.assertEqual(sp.scan(self.root), [])

    def test_显式指定规则文件(self):
        make_pkg(self.root, {"a.md": "极性翻转复用"})
        rules = self.root.parent / "外部规则.json"
        rules.write_text(json.dumps({"极性翻转复用": "在审案件关键词"}, ensure_ascii=False), encoding="utf-8")
        try:
            self.assertEqual(sp.main([str(self.root)]), 0)                       # 不指定 → 不命中
            self.assertEqual(sp.main([str(self.root), "--rules", str(rules)]), 1)
            self.assertEqual(sp.main([str(self.root), "--rules", str(rules / "无")]), 1)
        finally:
            rules.unlink()

    def test_坏规则文件报错不崩(self):
        make_pkg(self.root, {"a.md": "干净"})
        (self.root / sp.RULES_FILENAME).write_text("[1,2,3]", encoding="utf-8")
        rc, _, err = self.run_main(str(self.root))
        self.assertEqual(rc, 1)
        self.assertTrue(self.last_line(err).startswith("FAIL: bad_rules"), err)

    def test_命中带行号和原因(self):
        make_pkg(self.root, {"x.md": "第一行没事\n第二行提到 zhangsan 了\n"})
        write_rules(self.root, {"zhangsan": "作者账号名"})
        hits = sp.scan(self.root)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["line"], 2)
        self.assertEqual(hits[0]["why"], "作者账号名")

    def test_跳过自身和测试(self):
        make_pkg(self.root, {
            "scripts/strip_personal.py": "BUILTIN_PATTERNS = {'x@y.com': 'x'}",
            "scripts/test_strip_personal.py": "扫 a@b.com 的用例",
        })
        self.assertEqual(sp.scan(self.root), [])

    def test_跳过二进制和隐藏目录(self):
        make_pkg(self.root, {
            "img.png": b"\x89PNG\x00a@b.com\x00",
            ".git/config": "email = a@b.com",
        })
        self.assertEqual(sp.scan(self.root), [])

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sp.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    @staticmethod
    def last_line(text: str) -> str:
        return text.rstrip("\n").splitlines()[-1] if text.strip() else ""

    def test_main_退出码(self):
        make_pkg(self.root, {"ok.md": "干净"})
        self.assertEqual(sp.main([str(self.root)]), 0)
        make_pkg(self.root, {"bad.md": "写信到 a@example.com"})
        self.assertEqual(sp.main([str(self.root)]), 1)
        # 目录不存在是输入错误 → 1（2 留给“依赖/入口不可用”）
        self.assertEqual(sp.main([str(self.root / "不存在")]), 1)

    def test_机读收尾行(self):
        make_pkg(self.root, {"ok.md": "干净", "b/c.py": "print(1)\n"})
        rc, out, err = self.run_main(str(self.root))
        self.assertEqual(rc, 0)
        self.assertIn("干净：", out)
        self.assertEqual(self.last_line(out), "OK: hits=0 files=2")
        self.assertEqual(err, "")

        rc, out, err = self.run_main(str(self.root), "--json")
        self.assertEqual(rc, 0)
        payload = json.loads(out)                        # stdout 是干净的 JSON
        self.assertTrue(payload["clean"])
        self.assertEqual(payload["files"], 2)
        self.assertEqual(self.last_line(err), "OK: hits=0 files=2")

        make_pkg(self.root, {"bad.md": "写信到 a@example.com"})
        rc, out, err = self.run_main(str(self.root))
        self.assertEqual(rc, 1)
        self.assertIn("发布中止", out)
        self.assertNotIn("OK:", out)
        self.assertEqual(self.last_line(err), "FAIL: hits=1 files=3")

        rc, out, err = self.run_main(str(self.root / "不存在"))
        self.assertEqual(rc, 1)
        self.assertTrue(self.last_line(err).startswith("FAIL: not_a_directory"), err)


if __name__ == "__main__":
    unittest.main()
