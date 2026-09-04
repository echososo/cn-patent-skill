"""check_patent_package 的单元测试：python3 -m unittest 或 pytest 都能跑。

黄金用例用包里自带的 examples/demo-case/bad-draft.md 当固定输入。
那份坏稿子的应报结果（3 ERROR、7 WARN）同时写在三个地方：
demo-case/README.md 的答案表、INSTALL.md 的验证章节、以及这里。
三处必须一致——改了检查规则而忘了改文档，这个测试会先失败。
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_patent_package as cpp  # noqa: E402

PKG_ROOT = Path(__file__).resolve().parent.parent
BAD_DRAFT = PKG_ROOT / "examples" / "demo-case" / "bad-draft.md"

# 一份规矩的稿子：栏目齐、权项连续且只往前引、无占位无过强结论无代码符号。
# 用来防误报——检查项收紧过头会先在这里挂掉。
CLEAN_DRAFT = """发明名称：一种日志告警的窗口抑制方法

权利要求书

1. 一种日志告警的窗口抑制方法，其特征在于，包括：对告警计算归并键；在与告警等级相对应的时间窗口内，对具有相同归并键的告警只放行首条；在窗口结束时输出该窗口内被抑制的告警条数。
2. 根据权利要求1所述的方法，其特征在于，所述时间窗口的长度随该归并键连续命中的次数增大而增大，并以预设上限为限。

说明书

技术领域

本申请涉及运维监控领域，具体涉及告警消息的处理。

背景技术

现有做法按固定时长合并同类告警，等级不同的告警使用同一时长，高等级告警因此被延迟。

发明内容

本申请要解决的技术问题是：在抑制重复告警的同时，不延迟高等级告警的送达。

附图说明

图1是本方法一个实施例的流程示意图。

具体实施方式

在一个实施例中，基础窗口取60秒，等级每提高一级窗口折半，连续命中时窗口按2倍递增，上限取600秒。以某次演练为例，原始告警1200条，经本方法处理后送达47条，其中最高等级告警的送达延迟为0秒。

摘要

本申请公开一种日志告警的窗口抑制方法：对告警计算归并键，在与告警等级相对应的时间窗口内对相同归并键的告警只放行首条，并在窗口结束时输出被抑制的条数。
"""


def analyze_text(text: str, source: str = "<test>"):
    """把一段文本按脚本的加载口径变成 (issues, metadata)。"""
    document = cpp.LoadedDocument(
        source,
        [line.rstrip() for line in text.splitlines() if line.strip()],
    )
    return cpp.analyze(document)


def codes(issues) -> list[str]:
    return [issue.code for issue in issues]


class 黄金用例(unittest.TestCase):
    """演练案例的坏稿子：买家第一次跑看到的就是这个输出。"""

    @classmethod
    def setUpClass(cls):
        if not BAD_DRAFT.exists():  # pragma: no cover
            raise unittest.SkipTest(f"演练案例缺失：{BAD_DRAFT}")
        cls.issues, cls.metadata = cpp.analyze(cpp.load_document(str(BAD_DRAFT)))

    def test_恰好三个ERROR七个WARN(self):
        errors = [i for i in self.issues if i.severity == "ERROR"]
        warns = [i for i in self.issues if i.severity == "WARN"]
        self.assertEqual(
            (len(errors), len(warns)), (3, 7),
            f"和 demo-case/README.md、INSTALL.md 承诺的 3 ERROR/7 WARN 不一致：{codes(self.issues)}",
        )

    def test_报出的检查项集合(self):
        self.assertEqual(
            sorted(codes(self.issues)),
            sorted([
                "title-over-25",            # 埋坑 1：名称 34 字
                "abstract-over-300",        # 埋坑 2：摘要 429 字
                "claim-reference-forward",  # 埋坑 3：权4 引权5
                "placeholder-data",         # 埋坑 4：【占位待实测】
                "overstrong-conclusion",    # 埋坑 5：不漏解
                "overstrong-conclusion",    # 埋坑 5：完全消除
                "code-identifiers",         # 埋坑 6：蛇形变量
                "framework-names",          # 埋坑 7：FastAPI / Redis
                "api-paths",                # 埋坑 7：/api/v1/alerts
                "figure-number-gap",        # 埋坑 8：图号 1、3
            ]),
        )

    def test_埋坑1_名称超长(self):
        self.assertEqual(self.metadata["title_length"], 34)

    def test_埋坑2_摘要超300(self):
        self.assertGreater(self.metadata["abstract_length"], 300)

    def test_埋坑3_权项向后引用指到权5(self):
        (issue,) = [i for i in self.issues if i.code == "claim-reference-forward"]
        self.assertIn("权利要求 4", issue.message)
        self.assertIn("5", issue.message)

    def test_埋坑4_占位标记带上下文(self):
        (issue,) = [i for i in self.issues if i.code == "placeholder-data"]
        self.assertIn("占位待实测", issue.context)

    def test_埋坑5_两句过强结论都抓到(self):
        labels = [i.message for i in self.issues if i.code == "overstrong-conclusion"]
        self.assertEqual(len(labels), 2)
        self.assertTrue(any("不漏解" in m for m in labels))
        self.assertTrue(any("绝对结论" in m for m in labels))

    def test_埋坑6_蛇形变量点名(self):
        (issue,) = [i for i in self.issues if i.code == "code-identifiers"]
        self.assertIn("suppress_window_sec", issue.message)

    def test_埋坑7_框架名与接口路径(self):
        (fw,) = [i for i in self.issues if i.code == "framework-names"]
        (api,) = [i for i in self.issues if i.code == "api-paths"]
        self.assertIn("FastAPI", fw.message)
        self.assertIn("Redis", fw.message)
        self.assertIn("/api/v1/alerts", api.message)

    def test_埋坑8_图号跳2(self):
        self.assertEqual(self.metadata["figure_numbers"], [1, 3])

    def test_九到十二号埋坑形式检查抓不到(self):
        """独权塞满、术语不一致、无数字算例、背景没说清区别——这四条要靠审查视角。
        哪天有人给脚本加了这类"智能"判断，先在这里想清楚会不会误报。"""
        self.assertEqual(len(self.issues), 10)

    def test_版本指纹与免责声明都在(self):
        self.assertEqual(len(self.metadata["sha256"]), 64)
        self.assertIn("不判断新颖性", self.metadata["disclaimer"])


class 干净稿子不误报(unittest.TestCase):
    def test_零问题(self):
        issues, _ = analyze_text(CLEAN_DRAFT)
        self.assertEqual(issues, [], f"规矩的稿子被误报：{codes(issues)}")

    def test_正常引用在前的权项不报(self):
        issues, _ = analyze_text(CLEAN_DRAFT)
        self.assertNotIn("claim-reference-forward", codes(issues))


class 逐条检查项(unittest.TestCase):
    """每条规则的边界，用最小片段试，不依赖演练案例。"""

    def test_名称25到60字只WARN_超60升ERROR(self):
        base = "一种用于分布式日志系统中对重复告警消息进行窗口化归并与抑制处理的方法"
        issues, meta = analyze_text(f"发明名称：{base}\n")
        self.assertGreater(meta["title_length"], 25)
        self.assertIn("title-over-25", codes(issues))

        long_title = base + "以及相应的系统装置和计算机可读存储介质还包括对应的电子设备实现方式"
        issues, meta = analyze_text(f"发明名称：{long_title}\n")
        self.assertGreater(meta["title_length"], 60)
        self.assertIn("title-over-60", codes(issues))
        self.assertNotIn("title-over-25", codes(issues))

    def test_摘要正好300字不报_301报(self):
        for length, expected in ((300, False), (301, True)):
            issues, meta = analyze_text("摘要\n" + "本" * length + "\n")
            self.assertEqual(meta["abstract_length"], length)
            self.assertEqual("abstract-over-300" in codes(issues), expected, f"{length} 字")

    def test_权项编号重复(self):
        text = "权利要求书\n1. 一种方法。\n2. 根据权利要求1所述的方法。\n2. 根据权利要求1所述的方法。\n"
        self.assertIn("claim-number-duplicate", codes(analyze_text(text)[0]))

    def test_权项编号不连续(self):
        text = "权利要求书\n1. 一种方法。\n3. 根据权利要求1所述的方法。\n"
        self.assertIn("claim-number-gap", codes(analyze_text(text)[0]))

    def test_权项顺序颠倒(self):
        text = "权利要求书\n2. 根据权利要求1所述的方法。\n1. 一种方法。\n"
        self.assertIn("claim-number-order", codes(analyze_text(text)[0]))

    def test_引用不存在的权项(self):
        text = "权利要求书\n1. 一种方法。\n2. 根据权利要求9所述的方法。\n"
        self.assertIn("claim-reference-missing", codes(analyze_text(text)[0]))

    def test_权项自引用(self):
        text = "权利要求书\n1. 一种方法。\n2. 根据权利要求2所述的方法。\n"
        self.assertIn("claim-reference-forward", codes(analyze_text(text)[0]))

    def test_超10项只提醒附加费(self):
        lines = ["权利要求书", "1. 一种方法。"]
        lines += [f"{n}. 根据权利要求1所述的方法。" for n in range(2, 13)]
        issues = analyze_text("\n".join(lines) + "\n")[0]
        self.assertIn("claims-over-10", codes(issues))
        self.assertNotIn("claim-number-gap", codes(issues))

    def test_没有权利要求书栏目(self):
        self.assertIn("claims-missing", codes(analyze_text("说明书\n正文。\n")[0]))

    def test_三类占位标记(self):
        for fragment, code in (
            ("窗口上限【占位待实测】。", "placeholder-data"),
            ("此处 TODO 补一段。", "placeholder-edit"),
            ("此处插图，后面补。", "placeholder-figure"),
        ):
            self.assertIn(code, codes(analyze_text(fragment)[0]), fragment)

    def test_占位一律是ERROR(self):
        issues, _ = analyze_text("窗口上限【占位待实测】。")
        self.assertTrue(all(i.severity == "ERROR" for i in issues if i.code.startswith("placeholder")))

    def test_三类过强结论(self):
        for fragment, label in (
            ("做到告警不漏解。", "不漏解"),
            ("给出穷尽保证。", "穷尽保证"),
            ("能够完全消除告警风暴。", "绝对结论"),
            ("准确率百分之百。", "绝对结论"),
        ):
            issues = analyze_text(fragment)[0]
            hits = [i for i in issues if i.code == "overstrong-conclusion"]
            self.assertTrue(hits and label in hits[0].message, fragment)

    def test_驼峰和普通英文单词不算蛇形变量(self):
        issues = analyze_text("本方法使用 sliding window 策略，不涉及 alertLevel 字段。")[0]
        self.assertNotIn("code-identifiers", codes(issues))

    def test_附图说明缺栏目(self):
        issues = analyze_text("具体实施方式\n如图1所示的流程。\n")[0]
        self.assertIn("drawing-description-missing", codes(issues))

    def test_说明书栏目缺失点名到具体栏目(self):
        (issue,) = [i for i in analyze_text("说明书\n正文。\n")[0] if i.code == "sections-missing"]
        for name in ("技术领域", "背景技术", "发明内容", "具体实施方式"):
            self.assertIn(name, issue.message)

    def test_docx引用附图但没内嵌图片(self):
        document = cpp.LoadedDocument("稿.docx", ["具体实施方式", "如图1所示。"], media_count=0)
        self.assertIn("figures-not-embedded", codes(cpp.analyze(document)[0]))
        document = cpp.LoadedDocument("稿.docx", ["具体实施方式", "如图1所示。"], media_count=1)
        self.assertNotIn("figures-not-embedded", codes(cpp.analyze(document)[0]))


class 文件加载(unittest.TestCase):
    def test_带BOM的md照样读(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "稿.md"
            path.write_bytes("﻿发明名称：一种方法\n".encode("utf-8"))
            document = cpp.load_document(str(path))
            self.assertEqual(document.paragraphs[0], "发明名称：一种方法")

    def test_txt也支持(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "稿.txt"
            path.write_text("发明名称：一种方法\n", encoding="utf-8")
            self.assertEqual(cpp.analyze(cpp.load_document(str(path)))[1]["title"], "一种方法")

    def test_不支持的后缀直接拒(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "稿.pdf"
            path.write_text("x", encoding="utf-8")
            with self.assertRaises(ValueError):
                cpp.load_document(str(path))

    def test_文件不存在(self):
        with self.assertRaises(ValueError):
            cpp.load_document("/不存在的/稿.md")

    def test_同样内容指纹相同_改一个字就变(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b, c = (Path(tmp) / n for n in ("a.md", "b.md", "c.md"))
            a.write_text("发明名称：一种方法\n", encoding="utf-8")
            b.write_text("发明名称：一种方法\n", encoding="utf-8")
            c.write_text("发明名称：一种装置\n", encoding="utf-8")
            fp = lambda p: cpp.load_document(str(p)).content_sha256
            self.assertEqual(fp(a), fp(b))
            self.assertNotEqual(fp(a), fp(c))


class 命令行(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BAD_DRAFT.exists():  # pragma: no cover
            raise unittest.SkipTest("演练案例缺失")

    def run_cli(self, *args):
        proc = subprocess.run(
            [sys.executable, str(PKG_ROOT / "scripts" / "check_patent_package.py"), *args],
            capture_output=True, text=True,
        )
        return proc

    @staticmethod
    def last_line(text: str) -> str:
        return text.rstrip("\n").splitlines()[-1] if text.strip() else ""

    def test_有ERROR时退出码为1(self):
        proc = self.run_cli(str(BAD_DRAFT))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("汇总：ERROR=3，WARN=7", proc.stdout)
        # 机读约定：退出码 1 时 stderr 最后一行是 FAIL，stdout 里不出现 OK
        self.assertEqual(self.last_line(proc.stderr), "FAIL: errors=3 warnings=7 files=1")
        self.assertNotIn("OK:", proc.stdout)

    def test_strict下有ERROR照样FAIL并标明strict(self):
        proc = self.run_cli("--strict", str(BAD_DRAFT))
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.last_line(proc.stderr), "FAIL: errors=3 warnings=7 files=1 strict=1")

    def test_干净稿子退出码为0_strict下也是0(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "稿.md"
            path.write_text(CLEAN_DRAFT, encoding="utf-8")
            proc = self.run_cli(str(path))
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(self.last_line(proc.stdout), "OK: errors=0 warnings=0 files=1")
            self.assertEqual(proc.stderr, "")
            self.assertEqual(self.run_cli("--strict", str(path)).returncode, 0)

    def test_只有WARN时_strict才返回1(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "稿.md"
            path.write_text(CLEAN_DRAFT.replace("图1是", "图2是"), encoding="utf-8")
            proc = self.run_cli(str(path))
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(self.last_line(proc.stdout), "OK: errors=0 warnings=1 files=1")
            proc = self.run_cli("--strict", str(path))
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(self.last_line(proc.stderr), "FAIL: errors=0 warnings=1 files=1 strict=1")

    def test_json输出结构(self):
        proc = self.run_cli("--json", str(BAD_DRAFT))
        payload = json.loads(proc.stdout)
        self.assertEqual((payload["errors"], payload["warnings"]), (3, 7))
        (report,) = payload["reports"]
        self.assertEqual(len(report["issues"]), 10)
        self.assertIn("sha256", report["metadata"])
        self.assertIn("FAIL: errors=3", proc.stderr)

    def test_json时OK行在stderr不污染JSON(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "稿.md"
            path.write_text(CLEAN_DRAFT, encoding="utf-8")
            proc = self.run_cli("--json", str(path))
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(json.loads(proc.stdout)["errors"], 0)
            self.assertEqual(self.last_line(proc.stderr), "OK: errors=0 warnings=0 files=1")

    def test_读不了的文件不影响同批其他文件(self):
        proc = self.run_cli("--json", str(BAD_DRAFT), "/不存在的/稿.md")
        payload = json.loads(proc.stdout)
        self.assertEqual(len(payload["reports"]), 2)
        self.assertIn("read-failed", [i["code"] for i in payload["reports"][1]["issues"]])
        self.assertEqual(self.last_line(proc.stderr), "FAIL: errors=4 warnings=7 files=2")

    def test_标准输入(self):
        proc = subprocess.run(
            [sys.executable, str(PKG_ROOT / "scripts" / "check_patent_package.py"), "--json", "-"],
            input=CLEAN_DRAFT, capture_output=True, text=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["errors"], 0)
        self.assertEqual(payload["reports"][0]["metadata"]["source"], "<stdin>")

    def test_文字输出里有免责声明(self):
        self.assertIn("不判断新颖性", self.run_cli(str(BAD_DRAFT)).stdout)


if __name__ == "__main__":
    unittest.main()
