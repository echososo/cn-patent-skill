"""build_case_graph 的单元测试：python3 -m unittest 或 pytest 都能跑。"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_case_graph as bcg  # noqa: E402

DRAFT = """# 某虚构申请

## 权利要求书

1. 一种数据处理方法，其特征在于，包括步骤A、步骤B与步骤C。
2. 根据权利要求1所述的方法，其特征在于，所述步骤B使用滑动窗口。
3. 根据权利要求1或2所述的方法，其特征在于，还包括摘要补发步骤。

## 说明书

略。
"""

MATRIX = """# 检索与矩阵

D1：CN111222333A 《一种告警去重方法》
D2：US2020123456A1 《Adaptive alerting》

## 权利要求 1

| 特征编号 | 权项表述 | D1 映射类型与原文位置 | 区别及关系 | 本发明中的技术效果 | 实际技术问题 | D2/公知常识及证据 | 拟作修改、组合动机与障碍 | 结论 |
|---|---|---|---|---|---|---|---|---|
| F1 | 步骤B滑动窗口 | 未记载 | 窗口自适应 | 减少推送 | 如何控制风暴 | D2 记载固定窗口（US2020123456A1） | 动机不足 | 强支点 |
| F2 | 摘要补发 | 记载不清（第3段） | 补发摘要 | 不漏关键信息 | 如何兜底 | 主张公知常识 | 无 | 可争辩 |

## 矩阵 2

| 权项 | 技术特征/关系 | 说明书段落 | 实施例步骤与数字 | 附图 | 来源证据编号及状态 | 原始组合依据 | 退守层级 | 状态 |
|---|---|---|---|---|---|---|---|---|
| 1 | 滑动窗口 | 【发明内容-第3段】 | 步骤二 | 图1 | SRC-CODE-001 直接证据 | 同一实施例 | L1 | 已支持 |
| 2、3 | 摘要补发 | 【具体实施方式-第5段】 | 步骤五 | 图3 | SRC-TEST-002 参考实现支持 | 同一流程 | L3 | 表述需补强 |

## 矩阵 3

| 技术效果 | 对照基线 | 指标与算法 | 原始结果位置 | 因果链 | 成立条件与边界 | 可写入的结论 | 状态 |
|---|---|---|---|---|---|---|---|
| 推送量下降 | 固定静默期 | 条数对比 | SRC-DATA-003 | 窗口合并所以变少 | 重复告警场景 | 显著减少 | 实测支持 |
"""

REVIEW = """# 内部模拟审查

### INV-01 创造性存疑
- 严重程度：【致命】
- 台账状态：新增
- 涉及权项：权利要求 1、2
- 审查标准：专利法第22条第3款
- 对比文件及原文：D1 第3段；D2 摘要
- 结论：修改

### NOV-01 新颖性核对
- 严重程度：【建议】
- 台账状态：已解决
- 涉及权项：3
- 结论：保留
"""


def write_case(root: Path):
    (root / "申请文件.md").write_text(DRAFT, encoding="utf-8")
    (root / "检索与矩阵.md").write_text(MATRIX, encoding="utf-8")
    (root / "模拟审查.md").write_text(REVIEW, encoding="utf-8")


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="casegraph_"))
        self.case = self.tmp / "演练案"
        self.case.mkdir()
        write_case(self.case)
        self.summary = bcg.build(self.case, "图谱")
        self.out = self.case / "图谱"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read(self, rel):
        return (self.out / rel).read_text(encoding="utf-8")

    def canvas(self):
        return json.loads(self.read("案件_图谱.canvas"))

    def test_数量统计(self):
        s = self.summary
        self.assertEqual(s["claims"], 3)
        self.assertEqual(s["features"], 2)
        self.assertEqual(s["d_docs"], 2)
        self.assertEqual(s["evidence"], 3)
        self.assertEqual(s["issues"], 2)
        self.assertEqual(s["fatal_issues"], 1)

    def test_该有的笔记都在(self):
        for rel in ["案件总览.md", "案件_图谱.canvas", "技术效果台账.md",
                    "权利要求/权利要求 1.md", "权利要求/权利要求 3.md",
                    "区别特征/特征 F1.md", "对比文件/D1.md", "对比文件/D2.md",
                    "证据/SRC-CODE-001.md", "证据/SRC-DATA-003.md",
                    "审查问题/INV-01.md", "审查问题/NOV-01.md"]:
            self.assertTrue((self.out / rel).exists(), rel)

    def test_权项引用与从属(self):
        c3 = self.read("权利要求/权利要求 3.md")
        self.assertIn("从属", c3)
        self.assertIn("[[权利要求 1]]", c3)
        self.assertIn("[[权利要求 2]]", c3)
        c1 = self.read("权利要求/权利要求 1.md")
        self.assertIn("独立", c1)

    def test_权项笔记双链齐全(self):
        c1 = self.read("权利要求/权利要求 1.md")
        for want in ["[[特征 F1]]", "[[SRC-CODE-001]]", "[[D1]]", "[[INV-01]]"]:
            self.assertIn(want, c1)
        self.assertIn("退守 L1", c1)

    def test_对比文件信息(self):
        d1 = self.read("对比文件/D1.md")
        self.assertIn("CN111222333A", d1)
        self.assertIn("一种告警去重方法", d1)
        self.assertIn("[[权利要求 1]]", d1)
        d2 = self.read("对比文件/D2.md")
        self.assertIn("US2020123456A1", d2)

    def test_审查问题字段(self):
        inv = self.read("审查问题/INV-01.md")
        self.assertIn("致命", inv)
        self.assertIn("[[权利要求 1]]", inv)
        self.assertIn("[[权利要求 2]]", inv)
        self.assertIn("[[D1]]", inv)
        self.assertIn("第22条第3款", inv)

    def test_矩阵2跨权项证据(self):
        ev = self.read("证据/SRC-TEST-002.md")
        self.assertIn("[[权利要求 2]]", ev)
        self.assertIn("[[权利要求 3]]", ev)

    def test_canvas合法且边正确(self):
        cv = self.canvas()
        ids = {n["id"] for n in cv["nodes"]}
        self.assertEqual(len(ids), len(cv["nodes"]))
        for e in cv["edges"]:
            self.assertIn(e["fromNode"], ids)
            self.assertIn(e["toNode"], ids)
        text_of = {n["id"]: n["text"] for n in cv["nodes"]}
        def find_edge(frag_from, frag_to, label):
            return any(frag_from in text_of[e["fromNode"]] and frag_to in text_of[e["toNode"]]
                       and e["label"] == label for e in cv["edges"])
        self.assertTrue(find_edge("[[D1]]", "权利要求 1", "命中"))
        self.assertTrue(find_edge("权利要求 1", "[[特征 F1]]", "区别特征"))
        self.assertTrue(find_edge("权利要求 1", "SRC-CODE-001", "证据"))
        self.assertTrue(find_edge("[[INV-01]]", "权利要求 1", "指向"))
        self.assertTrue(find_edge("权利要求 2", "权利要求 1", "引用"))

    def test_已解决的问题是绿色(self):
        cv = self.canvas()
        nov = next(n for n in cv["nodes"] if "[[NOV-01]]" in n["text"])
        inv = next(n for n in cv["nodes"] if "[[INV-01]]" in n["text"])
        self.assertEqual(nov["color"], "4")
        self.assertEqual(inv["color"], "1")

    def test_重跑不重复计数(self):
        s2 = bcg.build(self.case, "图谱")
        self.assertEqual(s2["claims"], self.summary["claims"])
        self.assertEqual(s2["issues"], self.summary["issues"])
        self.assertEqual(s2["canvas_nodes"], self.summary["canvas_nodes"])

    def test_D标签提取(self):
        feats = bcg.parse_corpus([self.case / "检索与矩阵.md"])[3]
        self.assertEqual(feats["D1"]["label"], "CN111222333A 《一种告警去重方法》")


class EdgeCaseTest(unittest.TestCase):
    def test_空目录直接报错(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit):
                bcg.build(Path(td), "图谱")

    def test_只有权利要求也能出图(self):
        with tempfile.TemporaryDirectory() as td:
            case = Path(td) / "c"
            case.mkdir()
            (case / "稿.md").write_text(DRAFT, encoding="utf-8")
            s = bcg.build(case, "图谱")
            self.assertEqual(s["claims"], 3)
            self.assertEqual(s["issues"], 0)
            self.assertTrue((case / "图谱" / "案件_图谱.canvas").exists())

    def test_八个前缀一个都不能少(self):
        """技能把问题编号定成封闭集八个，图谱的正则要跟得上。

        v1.0.3 之前这里只认五个，报告里写 CLM- / EFF- / FORM- 的问题会静默从图上消失。
        """
        prefixes = ["OBJ", "NOV", "INV", "SUP", "CLR", "CLM", "EFF", "FORM"]
        report = "# 审查\n\n" + "".join(
            f"### {pre}-01 某问题\n- 严重程度：【建议】\n- 涉及权项：1\n- 结论：保留\n\n"
            for pre in prefixes)
        with tempfile.TemporaryDirectory() as td:
            case = Path(td) / "c"
            case.mkdir()
            (case / "稿.md").write_text(DRAFT, encoding="utf-8")
            (case / "模拟审查.md").write_text(report, encoding="utf-8")
            s = bcg.build(case, "图谱")
            self.assertEqual(s["issues"], 8)
            for pre in prefixes:
                self.assertTrue((case / "图谱" / "审查问题" / f"{pre}-01.md").exists(), pre)

    def test_改了问题编号会清掉旧笔记(self):
        """审查报告把 INV-01 改判成 CLM-01，图上不能还留着 INV-01。

        手写笔记（没有 generated-by 标记）一律不许动。
        """
        with tempfile.TemporaryDirectory() as td:
            case = Path(td) / "c"
            case.mkdir()
            (case / "稿.md").write_text(DRAFT, encoding="utf-8")
            (case / "模拟审查.md").write_text(
                "### INV-01 旧编号\n- 严重程度：【重要】\n- 涉及权项：1\n", encoding="utf-8")
            bcg.build(case, "图谱")
            mine = case / "图谱" / "我手写的.md"
            mine.write_text("这是我自己记的，不许删\n", encoding="utf-8")
            self.assertTrue((case / "图谱" / "审查问题" / "INV-01.md").exists())

            (case / "模拟审查.md").write_text(
                "### CLM-01 改判后的编号\n- 严重程度：【重要】\n- 涉及权项：1\n", encoding="utf-8")
            s = bcg.build(case, "图谱")
            self.assertFalse((case / "图谱" / "审查问题" / "INV-01.md").exists())
            self.assertTrue((case / "图谱" / "审查问题" / "CLM-01.md").exists())
            self.assertEqual(s["stale_removed"], ["INV-01.md"])
            self.assertTrue(mine.exists())

    def test_涉及权项各种写法(self):
        self.assertEqual(bcg.parse_int_list("权利要求 1、2"), [1, 2])
        self.assertEqual(bcg.parse_int_list("1-3"), [1, 2, 3])
        self.assertEqual(bcg.parse_int_list("2，4 和 6"), [2, 4, 6])
        self.assertEqual(bcg.parse_int_list("权利要求1至3"), [1, 2, 3])


class CliTest(unittest.TestCase):
    """走 main()：人话输出照旧，末尾多一行机读的 OK / FAIL。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="casegraph_cli_"))
        self.case = self.tmp / "演练案"
        self.case.mkdir()
        write_case(self.case)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = bcg.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    @staticmethod
    def last_line(text: str) -> str:
        return text.rstrip("\n").splitlines()[-1] if text.strip() else ""

    def test_成功时最后一行是OK(self):
        rc, out, err = self.run_main(str(self.case))
        self.assertEqual(rc, 0)
        self.assertIn("案件：演练案", out)
        self.assertIn("权利要求 3｜区别特征 2｜对比文件 2｜证据 3｜审查问题 2（致命 1）", out)
        last = self.last_line(out)
        self.assertTrue(last.startswith("OK: files="), last)
        for piece in ("claims=3", "features=2", "d_docs=2", "evidence=3", "issues=2", "fatal=1", "nodes=", "edges="):
            self.assertIn(piece, last)
        self.assertEqual(err, "")

    def test_json时OK行在stderr(self):
        rc, out, err = self.run_main(str(self.case), "--json")
        self.assertEqual(rc, 0)
        summary = json.loads(out)                       # stdout 是干净的 JSON
        self.assertEqual(summary["claims"], 3)
        self.assertTrue(self.last_line(err).startswith("OK: files="), err)

    def test_目录不存在(self):
        rc, out, err = self.run_main(str(self.tmp / "不存在"))
        self.assertEqual(rc, 1)
        self.assertIn("不是目录", err)
        self.assertTrue(self.last_line(err).startswith("FAIL: not_a_directory"), err)

    def test_空目录(self):
        empty = self.tmp / "空"
        empty.mkdir()
        rc, out, err = self.run_main(str(empty))
        self.assertEqual(rc, 1)
        self.assertIn("没解析到任何内容", err)
        self.assertTrue(self.last_line(err).startswith("FAIL: nothing_parsed"), err)
        self.assertNotIn("OK:", out)


if __name__ == "__main__":
    unittest.main()
