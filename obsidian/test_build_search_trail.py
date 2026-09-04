"""build_search_trail 的单元测试：python3 -m unittest 或 pytest 都能跑。"""

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
import build_search_trail as bst  # noqa: E402

LEDGER = """# 检索轨迹台账：演练案

- 案件：演练案（虚构）
- 检索截止：2026-08-20

## 候选

| 候选 | 名称 | 一句话 | 提出于 | 最终去向 | 落点 |
|---|---|---|---|---|---|
| C1 | 自适应窗口 | 窗口随吵闹程度指数变化并封顶 | R0 | 独权核心 | 权 1 |
| C2 | 时间桶聚合 | 每分钟汇总一次 | R0 | 放弃 | 被 P2 整篇公开 |
| C3 | 升级逃逸 | 高等级立即放行 | R0 | 从属权项 | 权 4 |
| C4 | 按来源分窗 | 同指纹不同来源各开窗口 | R2 | 放弃 | 只是 C1 变体 |

## 轮次

| 轮次 | 日期 | 目的 | 入口 | 语言 | 未覆盖 | 详细记录 |
|---|---|---|---|---|---|---|
| R0 | 2026-08-16 | 代码分析 | 无 | — | — | design.md |
| R1 | 2026-08-17 | 英文摸底 | Google Patents | 英 | CNKI | 检索记录-1.md |
| R2 | 2026-08-18 | 中文补检 | Google Patents CN | 中 | 国知局全文 | 检索记录-2.md |

## 查询式

| 轮次 | 查询式 | 入口 | 命中 | 说明 |
|---|---|---|---|---|
| R1 | alert window backoff | Google Patents | 12 | P1 在其中 |
| R2 | "告警" "退避" "封顶" | Google Patents CN | 0 | 核心组合无 |
| R2 | "告警收敛" | Google Patents CN | — | 入口没给数 |

## 文献

| 文献 | 文献号 | 标题 | 类型 | 公开日 | 检出轮次 | 全文状态 | 最终角色 | 备注 |
|---|---|---|---|---|---|---|---|---|
| P1 | CN100000001A | 固定静默期去重 | 专利 | 2025-01-01 | R1 | 已读全文 | D1 | |
| P2 | Lin 2023 | Bucketed aggregation | 论文 | 2023-06 | R1 | 已读全文 | 背景技术 | |
| P3 | CN100000003A | 告警收敛装置 | 专利 | 2025-05-20 | R2 | 被阻断 | 线索未解决 | 验证码 |
| P4 | Park 2022 | Never interrupt windows | 其他 | 2022 | R2 | 已读全文 | 答辩材料 | |

## 对照

| 轮次 | 文献 | 候选 | 判定 | 影响 | 理由 | 出处 |
|---|---|---|---|---|---|---|
| R1 | P1 | C1 | 未记载 | 保留 | 静默期固定 | 检索记录-1.md 第二节 |
| R1 | P2 | C2 | 明文记载 | 放弃 | 整篇就是它 | 检索记录-1.md 第三节 |
| R2 | P1+P4 | C3 | 教导相反 | 升为核心 | P4 反对中断窗口 | 检索记录-2.md |
| R2 | 公知常识 | C4 | 毫无疑义确定 | 放弃 | 只是拼来源 | 检索记录-2.md |
| R2 | P3 | C1 | 记载不清 | 无影响 | 只有摘要 | 检索记录-2.md |
| R2 | 实验 | C1 | 实测支持 | 保留 | 重放 1173 条降到 47 条 | 实验报告.md |
| R2 | 决策 | C3 | 人为取舍 | 降为从属 | 用户要控制篇幅，放到权 4 | 聊天记录 08-18 |
"""


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="trail_"))
        self.case = self.tmp / "演练案"
        (self.case / "04_检索").mkdir(parents=True)
        (self.case / "04_检索" / "检索轨迹台账.md").write_text(LEDGER, encoding="utf-8")
        self.summary = bst.build(self.case)
        self.out = self.case / "图谱" / "检索轨迹"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read(self, rel):
        return (self.out / rel).read_text(encoding="utf-8")

    def test_数量统计(self):
        st = self.summary["stats"]
        self.assertEqual(st["rounds"], 3)
        self.assertEqual(st["queries"], 3)
        self.assertEqual(st["zero_hit"], 1)
        self.assertEqual(st["docs"], 4)
        self.assertEqual(st["fulltext"], 3)
        self.assertEqual(st["unresolved"], 1)
        self.assertEqual(st["candidates"], 4)
        self.assertEqual(st["fates"]["放弃"], 2)
        self.assertEqual(st["fates"]["独权核心"], 1)
        self.assertEqual(st["events"], 7)
        self.assertEqual(st["killed"], 2)
        self.assertEqual(st["teach_away"], 1)
        self.assertEqual(st["d_docs"], ["P1"])
        self.assertEqual(self.summary["case"], "演练案")

    def test_该有的文件都在(self):
        for rel in ["检索轨迹总览.md", "检索轨迹图谱.html",
                    "候选/C1_自适应窗口.md", "候选/C4_按来源分窗.md",
                    "文献/P1_CN100000001A.md", "文献/P2_Lin_2023.md",
                    "轮次/R0_2026-08-16.md", "轮次/R2_2026-08-18.md"]:
            self.assertTrue((self.out / rel).exists(), rel)
        self.assertEqual(self.summary["notes_written"], 2 + 4 + 4 + 3)
        for p in self.out.rglob("*"):
            if p.is_file():
                self.assertIn(bst.GENERATED_MARK, p.read_text(encoding="utf-8")[:600], p.name)

    def test_总览内容(self):
        text = self.read("检索轨迹总览.md")
        self.assertIn("3 轮（检索、实测与取舍各算一轮），3 条查询式（其中 1 条命中为 0）", text)
        self.assertIn("提过 4 个候选，打掉 2 个，1 个进独立权利要求，1 个进从属权项", text)
        self.assertIn("1 次发现教导相反", text)
        self.assertIn("| C2 时间桶聚合 | 提出 | P2 明文记载→放弃 |  | 放弃（被 P2 整篇公开） |", text)
        self.assertIn("| C4 按来源分窗 |  |  | 公知常识 毫无疑义确定→放弃 |", text)
        self.assertIn("P1+P4 教导相反→升为核心", text)
        self.assertIn("本案实验 实测支持→保留", text)
        self.assertIn("人为决策 人为取舍→降为从属", text)
        self.assertIn("- **D1**：[[P1_CN100000001A|CN100000001A]]", text)
        self.assertIn("线索未解决：[[P3_CN100000003A|CN100000003A]]", text)
        self.assertIn("[[R1_2026-08-17|R1]] 未覆盖：CNKI", text)
        self.assertIn("不构成法律意见", text)

    def test_候选笔记的来龙去脉(self):
        text = self.read("候选/C3_升级逃逸.md")
        self.assertIn("fate: 从属权项", text)
        self.assertIn("R0（2026-08-16）提出：高等级立即放行", text)
        self.assertIn("R2：CN100000001A、Park 2022 — 教导相反 → 升为核心。P4 反对中断窗口", text)
        self.assertIn("R2：人为决策 — 人为取舍 → 降为从属。用户要控制篇幅，放到权 4", text)
        self.assertIn("[[P4_Park_2022|Park 2022]]", text)
        self.assertIn("[[R2_2026-08-18|R2]]", text)

    def test_文献与轮次笔记(self):
        text = self.read("文献/P3_CN100000003A.md")
        self.assertIn("role: 线索未解决", text)
        self.assertIn("- 全文状态：被阻断", text)
        self.assertIn("[[C1_自适应窗口|C1 自适应窗口]]", text)
        r2 = self.read("轮次/R2_2026-08-18.md")
        self.assertIn("| \"告警\" \"退避\" \"封顶\" | Google Patents CN | 0 | 核心组合无 |", r2)
        self.assertIn("| \"告警收敛\" | Google Patents CN | — | 入口没给数 |", r2)
        self.assertIn("## 本轮检出", r2)
        self.assertIn("## 本轮对照", r2)

    def test_不再生成canvas(self):
        self.assertFalse((self.out / "检索轨迹.canvas").exists())
        self.assertEqual(self.summary["graph_nodes"], 3 + 4 + 4)

    def test_html自包含且数据完整(self):
        page = self.read("检索轨迹图谱.html")
        self.assertNotIn("<script src=", page)
        self.assertNotIn("<link ", page)
        start = page.index('<script id="data" type="application/json">') + len('<script id="data" type="application/json">')
        end = page.index("</script>", start)
        data = json.loads(page[start:end].replace("<\\/", "</"))
        self.assertEqual(len(data["rounds"]), 3)
        self.assertEqual(len(data["docs"]), 4)
        self.assertEqual([p["code"] for p in data["pseudo"]], ["CK", "EX", "DC"])
        self.assertTrue(all(p["round"] == "R2" for p in data["pseudo"]))
        self.assertEqual(data["evolution"][0], ["候选", "R0", "R1", "R2", "最终去向"])
        c3 = next(c for c in data["candidates"] if c["id"] == "C3")
        self.assertEqual(c3["story"][-1], "最终：从属权项，权 4")
        self.assertIn("演练案", page)
        self.assertIn("不构成法律意见", page)
        for must in ('id="gc"', 'id="g-png"', 'id="f-png"', 'id="tab-graph"', "展开全部轮次", "收起全部轮次", "词汇表"):
            self.assertIn(must, page)
        # 网页不带过程日期：轮次日期、检索截止、生成时间都不能出现；文献公开日可以
        self.assertNotIn("2026-08", page)
        self.assertNotIn("检索截止", page)
        self.assertIn("2025-01-01", page)
        self.assertEqual(data["rounds"][0].get("date"), None)
        self.assertTrue(all("（20" not in s for c in data["candidates"] for s in c["story"]))

    def test_重跑不重复且清掉旧笔记(self):
        (self.out / "候选" / "C9_不存在的.md").write_text(bst.frontmatter(["x"], "演练案") + "# 旧的", encoding="utf-8")
        (self.out / "手写笔记.md").write_text("# 我自己写的\n", encoding="utf-8")
        s2 = bst.build(self.case)
        self.assertEqual(s2["notes_written"], self.summary["notes_written"])
        self.assertEqual(s2["stale_removed"], ["C9_不存在的.md"])
        self.assertTrue((self.out / "手写笔记.md").exists())

    def test_待定会给提醒(self):
        text = LEDGER.replace("| C3 | 升级逃逸 | 高等级立即放行 | R0 | 从属权项 | 权 4 |",
                              "| C3 | 升级逃逸 | 高等级立即放行 | R0 | 待定 | |")
        (self.case / "04_检索" / "检索轨迹台账.md").write_text(text, encoding="utf-8")
        s = bst.build(self.case)
        self.assertTrue(any("C3 最终去向还是「待定」" in w for w in s["warnings"]))


class ErrorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="trail_"))
        self.case = self.tmp / "案"
        self.case.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ledger(self, text):
        (self.case / "检索轨迹台账.md").write_text(text, encoding="utf-8")

    def test_没有台账直接报错(self):
        with self.assertRaises(bst.LedgerError) as cm:
            bst.build(self.case)
        self.assertIn("没找到", str(cm.exception))

    def test_两份台账要求指定(self):
        self.ledger(LEDGER)
        (self.case / "旧").mkdir()
        (self.case / "旧" / "检索轨迹台账.md").write_text(LEDGER, encoding="utf-8")
        with self.assertRaises(bst.LedgerError) as cm:
            bst.build(self.case)
        self.assertIn("多份台账", str(cm.exception))
        s = bst.build(self.case, ledger="旧/检索轨迹台账.md")
        self.assertTrue(s["ledger"].endswith("旧/检索轨迹台账.md"))

    def test_词表外的词报错并列出允许值(self):
        self.ledger(LEDGER.replace("| 未记载 | 保留 | 静默期固定", "| 没写 | 保留 | 静默期固定"))
        with self.assertRaises(bst.LedgerError) as cm:
            bst.build(self.case)
        msg = str(cm.exception)
        self.assertIn("判定「没写」不在词表里", msg)
        self.assertIn("明文记载、毫无疑义确定、部分接近、未记载、记载不清、教导相反", msg)

    def test_六列词表都受检(self):
        cases = [
            ("| R0 | 独权核心 | 权 1 |", "| R0 | 核心 | 权 1 |", "最终去向「核心」"),
            ("| 专利 | 2025-01-01 | R1 | 已读全文 | D1 |", "| 专利文献 | 2025-01-01 | R1 | 已读全文 | D1 |", "类型「专利文献」"),
            ("| R1 | 已读全文 | D1 |", "| R1 | 读过 | D1 |", "全文状态「读过」"),
            ("| 已读全文 | 背景技术 |", "| 已读全文 | 背景 |", "最终角色「背景」"),
            ("| 明文记载 | 放弃 | 整篇就是它", "| 明文记载 | 打掉 | 整篇就是它", "影响「打掉」"),
        ]
        for old, new, expect in cases:
            self.assertIn(old, LEDGER, old)
            self.ledger(LEDGER.replace(old, new, 1))
            with self.assertRaises(bst.LedgerError) as cm:
                bst.build(self.case)
            self.assertIn(expect, str(cm.exception), expect)

    def test_编号对不上报错(self):
        self.ledger(LEDGER.replace("| R2 | P3 | C1 |", "| R2 | P9 | C1 |"))
        with self.assertRaises(bst.LedgerError) as cm:
            bst.build(self.case)
        self.assertIn("文献「P9」在文献表里没有", str(cm.exception))
        self.ledger(LEDGER.replace("| R1 | P1 | C1 |", "| R7 | P1 | C1 |"))
        with self.assertRaises(bst.LedgerError) as cm:
            bst.build(self.case)
        self.assertIn("轮次「R7」在轮次表里没有", str(cm.exception))
        self.ledger(LEDGER.replace("| C4 | 按来源分窗 | 同指纹不同来源各开窗口 | R2 |",
                                   "| C4 | 按来源分窗 | 同指纹不同来源各开窗口 | R5 |"))
        with self.assertRaises(bst.LedgerError) as cm:
            bst.build(self.case)
        self.assertIn("提出于「R5」在轮次表里没有", str(cm.exception))

    def test_实验和决策的判定词受限(self):
        self.ledger(LEDGER.replace("| R2 | 实验 | C1 | 实测支持 |", "| R2 | 实验 | C1 | 未记载 |"))
        with self.assertRaises(bst.LedgerError) as cm:
            bst.build(self.case)
        self.assertIn("文献列是「实验」时判定只能用 实测推翻、实测支持", str(cm.exception))
        self.ledger(LEDGER.replace("| R2 | 决策 | C3 | 人为取舍 |", "| R2 | 决策 | C3 | 部分接近 |"))
        with self.assertRaises(bst.LedgerError) as cm:
            bst.build(self.case)
        self.assertIn("文献列是「决策」时判定只能用 人为取舍", str(cm.exception))
        self.ledger(LEDGER.replace("| R2 | P3 | C1 | 记载不清 |", "| R2 | P3 | C1 | 实测推翻 |"))
        with self.assertRaises(bst.LedgerError) as cm:
            bst.build(self.case)
        self.assertIn("判定「实测推翻」只能配「实验」或「决策」", str(cm.exception))
        self.ledger(LEDGER.replace("| R2 | 实验 | C1 | 实测支持 |", "| R2 | P1+实验 | C1 | 实测支持 |"))
        with self.assertRaises(bst.LedgerError) as cm:
            bst.build(self.case)
        self.assertIn("要单独一行", str(cm.exception))

    def test_缺表报错(self):
        self.ledger(LEDGER.split("## 对照")[0])
        with self.assertRaises(bst.LedgerError) as cm:
            bst.build(self.case)
        self.assertIn("缺对照表", str(cm.exception))

    def test_错误一次列全(self):
        text = LEDGER.replace("| 未记载 | 保留 | 静默期固定", "| 没写 | 保留 | 静默期固定") \
                     .replace("| R2 | P3 | C1 |", "| R2 | P9 | C1 |")
        self.ledger(text)
        with self.assertRaises(bst.LedgerError) as cm:
            bst.build(self.case)
        msg = str(cm.exception)
        self.assertIn("判定「没写」", msg)
        self.assertIn("文献「P9」", msg)

    def test_全角编号与加粗也认(self):
        text = LEDGER.replace("| C1 | 自适应窗口", "| **Ｃ1** | 自适应窗口").replace("| R1 | P1 | C1 |", "| R1 | P1 | ｃ1 |")
        self.ledger(text)
        s = bst.build(self.case)
        self.assertEqual(s["stats"]["candidates"], 4)
        self.assertTrue((self.case / "图谱" / "检索轨迹" / "候选" / "C1_自适应窗口.md").exists())

    def test_命令行入口(self):
        self.ledger(LEDGER)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(bst.main([str(self.case)]), 0)
            self.assertTrue((self.case / "图谱" / "检索轨迹" / "检索轨迹图谱.html").exists())
            # 成功时 stdout 最后一行是机读的 OK 行，数字照抄人话输出里的统计
            ok_line = out.getvalue().rstrip("\n").splitlines()[-1]
            self.assertEqual(ok_line, "OK: files=13 stale=0 rounds=3 queries=3 zero_hit=1 docs=4 fulltext=3 "
                                      "candidates=4 dropped=2 independent=1 dependent=1 events=7 unresolved=1 "
                                      "warnings=0 nodes=11 edges=15")
            self.assertEqual(bst.main([str(self.tmp / "不存在")]), 2)
            self.ledger(LEDGER.replace("| 明文记载 | 放弃 |", "| 公开 | 放弃 |"))
            self.assertEqual(bst.main([str(self.case)]), 1)
        self.assertIn("3 轮｜查询式 3（0 命中 1）", out.getvalue())
        self.assertIn("判定「公开」不在词表里", err.getvalue())
        self.assertEqual(out.getvalue().count("OK: "), 1)     # 失败的两次不许打 OK

    def test_命令行json时OK行在stderr(self):
        self.ledger(LEDGER)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(bst.main([str(self.case), "--json"]), 0)
        summary = json.loads(out.getvalue())                     # stdout 是干净的 JSON
        self.assertEqual(summary["notes_written"], 13)
        self.assertTrue(err.getvalue().rstrip("\n").splitlines()[-1].startswith("OK: files=13 "), err.getvalue())


if __name__ == "__main__":
    unittest.main()
