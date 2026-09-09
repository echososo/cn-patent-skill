"""mermaid_render.py / browser.py 的单元测试。

离线用例不需要浏览器（渲染器用桩子顶替）；真渲染用例只在本机 --probe 通过时跑，否则跳过。
跑法：python3 -m pytest scripts/test_mermaid_render.py -q   或   python3 scripts/test_mermaid_render.py
"""

from __future__ import annotations  # 3.9 上 `str | None` 注解要靠它，包声明支持 3.9+

import contextlib
import io
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import browser  # noqa: E402
import mermaid_render as mr  # noqa: E402


def 有(模块: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(模块) is not None


_PROBE: dict | None = None


def 浏览器能用() -> bool:
    """整个测试文件只探测一次（启动一次浏览器要一两秒）。"""
    global _PROBE
    if _PROBE is None:
        _PROBE = mr.probe() if 有("playwright") else {"ok": False, "error": "playwright_not_installed"}
    return bool(_PROBE.get("ok"))


需要docx = unittest.skipUnless(有("docx"), "没装 python-docx（pip install -r requirements-min.txt）")


def 假PNG(w: int = 2, h: int = 2) -> bytes:
    """凑一张合法的小 PNG，让桩渲染器有东西可写。"""
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def 桩渲染器(calls: list | None = None, fail_on: set[int] | None = None):
    """返回一个 render_one(源码, png路径)：写假 PNG，并把源码记到 calls；第 N 次调用可指定失败。"""
    n = {"i": 0}

    def render_one(src: str, png: Path) -> None:
        n["i"] += 1
        if calls is not None:
            calls.append(src)
        if fail_on and n["i"] in fail_on:
            raise RuntimeError("Parse error on line 2: 假装语法错")
        png.parent.mkdir(parents=True, exist_ok=True)
        png.write_bytes(假PNG())

    return render_one


def 没浏览器(**_kw):
    raise browser.BrowserUnavailable("无法启动浏览器（chrome: 装机没装 | msedge: 也没有 | chromium: 也没有）。请装 Chrome")


MD_两个围栏 = """# 发明名称：一种演练用的方法

## 3.2 系统框图

```mermaid
flowchart LR
  T[采集模块] --> Q[处理模块]
```

框图说明：略。

## 3.4 流程

图 5 处理流程

```mermaid
flowchart TD
  S1[采集] --> S2{"S2 判断"}
  S2 -->|是| S3(告警)
```

流程说明：略。
"""


# ---------------------------------------------------------------- 围栏提取

class ExtractTest(unittest.TestCase):
    def test_提取两个围栏(self):
        blocks = mr.extract_mermaid_blocks(MD_两个围栏)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].index, 1)
        self.assertEqual(blocks[1].index, 2)
        self.assertIn("T[采集模块] --> Q[处理模块]", blocks[0].source)
        self.assertTrue(blocks[0].source.endswith("\n"))
        self.assertIsNone(blocks[0].caption_no)
        self.assertEqual(blocks[1].caption_no, 5, "围栏上一行是「图 5 …」就该沿用 5")

    def test_行号对得上(self):
        lines = MD_两个围栏.splitlines()
        b = mr.extract_mermaid_blocks(MD_两个围栏)[0]
        self.assertEqual(lines[b.start], "```mermaid")
        self.assertEqual(lines[b.end], "```")

    def test_别的语言围栏里的mermaid不算(self):
        md = "````markdown\n```mermaid\nflowchart LR\n```\n````\n\n```mermaid\nflowchart TD\n  X1[x]\n```\n"
        blocks = mr.extract_mermaid_blocks(md)
        self.assertEqual(len(blocks), 1)
        self.assertIn("X1[x]", blocks[0].source)

    def test_大小写和波浪线围栏(self):
        md = "```Mermaid\nflowchart LR\n```\n~~~mermaid\nflowchart TD\n~~~\n"
        self.assertEqual(len(mr.extract_mermaid_blocks(md)), 2)

    def test_标题号识别几种写法(self):
        for cap, want in [("图 3 系统框图", 3), ("图3 流程", 3), ("**图 7** 说明", 7),
                          ("### 图 2 框图", 2), ("附图说明", None), ("", None)]:
            md = f"{cap}\n\n```mermaid\nflowchart LR\n```\n"
            self.assertEqual(mr.extract_mermaid_blocks(md)[0].caption_no, want, cap)

    def test_没围栏(self):
        self.assertEqual(mr.extract_mermaid_blocks("# 只有文字\n\n段落。\n"), [])


# ---------------------------------------------------------------- 步骤号补标签

class StepIdTest(unittest.TestCase):
    def test_方括号圆括号花括号都补(self):
        src = "flowchart TD\n  S1[采集] --> S2(处理)\n  S2 --> S3{判断}\n"
        out, n = mr.ensure_step_ids_in_visible_labels(src)
        self.assertEqual(n, 3)
        self.assertIn('S1["S1 采集"]', out)
        self.assertIn('S2("S2 处理")', out)
        self.assertIn('S3{"S3 判断"}', out)

    def test_已带号的不重复补(self):
        src = 'S1["S1 采集"] --> S2["S2：处理"] --> S3[S3 判断]\n'
        out, n = mr.ensure_step_ids_in_visible_labels(src)
        self.assertEqual(n, 0)
        self.assertEqual(out, src)

    def test_带引号标签也补(self):
        out, n = mr.ensure_step_ids_in_visible_labels('S101["接收消息"]\n')
        self.assertEqual(n, 1)
        self.assertIn('S101["S101 接收消息"]', out)

    def test_注释行和subgraph行不动(self):
        src = "%% S1[注释] 不动\nsubgraph G1[分组一]\n  S1[采集]\nend\n"
        out, n = mr.ensure_step_ids_in_visible_labels(src)
        self.assertEqual(n, 1)
        self.assertIn("%% S1[注释] 不动", out)
        self.assertIn("subgraph G1[分组一]", out)
        self.assertIn('S1["S1 采集"]', out)

    def test_多字符形状不碰(self):
        for src in ("S1((圆))", "S1[[子程序]]", "S1[(数据库)]", "S1{{六边形}}", "S1[/平行四边形/]"):
            out, n = mr.ensure_step_ids_in_visible_labels(src + "\n")
            self.assertEqual(n, 0, src)
            self.assertEqual(out, src + "\n")

    def test_没数字的id不算步骤(self):
        out, n = mr.ensure_step_ids_in_visible_labels('T["批任务提交"] --> Q[队列]\n')
        self.assertEqual(n, 0)

    def test_标签里有双引号换单引号(self):
        out, n = mr.ensure_step_ids_in_visible_labels('S1["带\\"引号"]\n')
        self.assertEqual(n, 1)
        self.assertTrue(out.startswith("S1['S1 带"), out)


# ---------------------------------------------------------------- 围栏替换 + .mmd 落盘

class RenderMarkdownTest(unittest.TestCase):
    def test_围栏换成图片引用并落盘(self):
        with tempfile.TemporaryDirectory() as td:
            out_md = Path(td) / "定稿.md"
            calls: list[str] = []
            logs: list[str] = []
            res = mr.render_markdown_mermaid(MD_两个围栏, out_md_path=out_md,
                                             render_one=桩渲染器(calls), log=logs.append)
            self.assertEqual((res.ok, res.fail), (2, 0))
            self.assertEqual(res.fixed, 2, "S1[采集] 与 S3(告警) 两处该补号")
            self.assertEqual(res.figures, ["mermaid_figures/fig_001.png", "mermaid_figures/fig_002.png"])

            text = res.text
            self.assertNotIn("```mermaid", text)
            self.assertIn("\n![图 1](mermaid_figures/fig_001.png)\n", text)
            self.assertIn("\n![图 5](mermaid_figures/fig_002.png)\n", text, "沿用自定标题里的 5")
            self.assertNotIn("<!-- mermaid source", text, "默认不留注释")
            # 围栏以外的行原样保留
            self.assertIn("# 发明名称：一种演练用的方法\n", text)
            self.assertIn("框图说明：略。\n", text)
            self.assertIn("图 5 处理流程\n", text)
            self.assertTrue(text.endswith("流程说明：略。\n"))

            figs = out_md.parent / "mermaid_figures"
            for stem in ("fig_001", "fig_002"):
                self.assertTrue((figs / f"{stem}.png").is_file(), stem)
                self.assertTrue((figs / f"{stem}.mmd").is_file(), stem)
            mmd2 = (figs / "fig_002.mmd").read_text(encoding="utf-8")
            self.assertIn('S1["S1 采集"]', mmd2, ".mmd 存的是实际拿去渲染的（补号后）源码")
            self.assertIn('S3("S3 告警")', mmd2)
            self.assertEqual(calls[1], mmd2, "渲染器拿到的就是 .mmd 里那份")
            self.assertTrue((figs / "fig_001.png").read_bytes().startswith(b"\x89PNG"))
            self.assertTrue(any("步骤号已补进可见标签" in s for s in logs))

    def test_keep_source留注释(self):
        with tempfile.TemporaryDirectory() as td:
            res = mr.render_markdown_mermaid(MD_两个围栏, out_md_path=Path(td) / "o.md",
                                             render_one=桩渲染器(), keep_source=True, log=lambda s: None)
            self.assertIn("![图 1](mermaid_figures/fig_001.png)\n<!-- mermaid source: mermaid_figures/fig_001.mmd -->\n",
                          res.text)

    def test_自定义assets_dir(self):
        with tempfile.TemporaryDirectory() as td:
            res = mr.render_markdown_mermaid(MD_两个围栏, out_md_path=Path(td) / "o.md", assets_rel="figs/mm/",
                                             render_one=桩渲染器(), log=lambda s: None)
            self.assertIn("![图 1](figs/mm/fig_001.png)", res.text)
            self.assertTrue((Path(td) / "figs" / "mm" / "fig_001.png").is_file())

    def test_某块失败则原样保留其余照常(self):
        with tempfile.TemporaryDirectory() as td:
            res = mr.render_markdown_mermaid(MD_两个围栏, out_md_path=Path(td) / "o.md",
                                             render_one=桩渲染器(fail_on={1}), log=lambda s: None)
            self.assertEqual((res.ok, res.fail), (1, 1))
            self.assertEqual(len(res.errors), 1)
            self.assertIn("假装语法错", res.errors[0])
            self.assertIn("```mermaid\nflowchart LR\n  T[采集模块] --> Q[处理模块]\n```\n", res.text, "失败块原样")
            self.assertIn("![图 5](mermaid_figures/fig_002.png)", res.text)
            figs = Path(td) / "mermaid_figures"
            self.assertFalse((figs / "fig_001.png").exists())
            self.assertTrue((figs / "fig_001.mmd").is_file(), "失败块的 .mmd 也要落盘，方便改")
            self.assertTrue((figs / "fig_002.png").is_file(), "文件号按围栏顺序，不因前面失败而错位")

    def test_没渲染器全部保留(self):
        with tempfile.TemporaryDirectory() as td:
            res = mr.render_markdown_mermaid(MD_两个围栏, out_md_path=Path(td) / "o.md",
                                             render_one=None, log=lambda s: None)
            self.assertEqual((res.ok, res.fail), (0, 2))
            self.assertEqual(res.text, MD_两个围栏)
            self.assertTrue((Path(td) / "mermaid_figures" / "fig_002.mmd").is_file())

    def test_没围栏原样输出且不建目录(self):
        with tempfile.TemporaryDirectory() as td:
            md = "# 标题\n\n段落。\n"
            res = mr.render_markdown_mermaid(md, out_md_path=Path(td) / "o.md", render_one=None, log=lambda s: None)
            self.assertEqual(res.text, md)
            self.assertEqual((res.ok, res.fail), (0, 0))
            self.assertFalse((Path(td) / "mermaid_figures").exists())


# ---------------------------------------------------------------- 命令行：退出码与 OK/FAIL 行

def 跑main(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = mr.main(argv)
    return rc, out.getvalue(), err.getvalue()


class CliTest(unittest.TestCase):
    def test_无浏览器退出码2并写出md(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "草稿.md"
            src.write_text(MD_两个围栏, encoding="utf-8")
            out_md = Path(td) / "out" / "定稿.md"
            with mock.patch.object(mr, "_open_renderer", 没浏览器):
                rc, so, se = 跑main(["-i", str(src), "-o", str(out_md), "--docx", str(Path(td) / "x.docx")])
            self.assertEqual(rc, 2)
            fail_lines = [l for l in se.splitlines() if l.startswith("FAIL: ")]
            self.assertEqual(len(fail_lines), 1, se)
            self.assertTrue(fail_lines[0].startswith("FAIL: browser_unavailable "), fail_lines[0])
            self.assertIn("请装 Chrome", fail_lines[0])
            self.assertFalse(any(l.startswith("OK:") for l in so.splitlines()), "失败时 stdout 不能出现 OK 行")
            self.assertTrue(out_md.is_file(), "没浏览器也要把定稿 md 写出来")
            self.assertEqual(out_md.read_text(encoding="utf-8"), MD_两个围栏, "围栏原样保留")
            self.assertEqual(src.read_text(encoding="utf-8"), MD_两个围栏, "输入不动")
            self.assertFalse((Path(td) / "x.docx").exists(), "没出图就不该出 Word")
            self.assertTrue((out_md.parent / "mermaid_figures" / "fig_001.mmd").is_file())

    def test_成功时stdout最后一行是OK(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "草稿.md"
            src.write_text(MD_两个围栏, encoding="utf-8")
            out_md = Path(td) / "定稿.md"

            class 假渲染器:
                label = "fake"
                render_one = staticmethod(桩渲染器())

                def close(self):
                    pass

            with mock.patch.object(mr, "_open_renderer", lambda **kw: 假渲染器()):
                rc, so, se = 跑main(["-i", str(src), "-o", str(out_md)])
            self.assertEqual(rc, 0, se)
            last = so.rstrip("\n").splitlines()[-1]
            self.assertTrue(last.startswith("OK: "), last)
            kv = dict(p.split("=", 1) for p in last[4:].split(" ") if "=" in p)
            self.assertEqual(kv["mermaid"], "2")
            self.assertEqual(kv["fail"], "0")
            self.assertEqual(kv["fixed"], "2")
            self.assertEqual(kv["figures"], "mermaid_figures")
            self.assertEqual(Path(kv["out"]), out_md.resolve())
            self.assertNotIn("docx", kv, "没传 --docx 就不出 Word")
            self.assertNotIn("FAIL:", se)
            self.assertIn("![图 1](mermaid_figures/fig_001.png)", out_md.read_text(encoding="utf-8"))

    def test_某块失败退出码1(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "草稿.md"
            src.write_text(MD_两个围栏, encoding="utf-8")

            class 假渲染器:
                label = "fake"
                render_one = staticmethod(桩渲染器(fail_on={2}))

                def close(self):
                    pass

            with mock.patch.object(mr, "_open_renderer", lambda **kw: 假渲染器()):
                rc, so, se = 跑main(["-i", str(src), "-o", str(Path(td) / "定稿.md")])
            self.assertEqual(rc, 1)
            self.assertIn("FAIL: mermaid_render_failed fail=1 ok=1", se)
            self.assertNotIn("OK:", so)

    def test_没围栏不碰浏览器(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "a.md"
            src.write_text("# 纯文字\n\n段落。\n", encoding="utf-8")
            with mock.patch.object(mr, "_open_renderer", 没浏览器):
                rc, so, se = 跑main(["-i", str(src), "-o", str(Path(td) / "b.md")])
            self.assertEqual(rc, 0, se)
            self.assertTrue(so.rstrip().splitlines()[-1].startswith("OK: mermaid=0 fail=0"))

    def test_输入不存在退出码1(self):
        with tempfile.TemporaryDirectory() as td:
            rc, so, se = 跑main(["-i", str(Path(td) / "没有.md"), "-o", str(Path(td) / "o.md")])
            self.assertEqual(rc, 1)
            self.assertIn("FAIL: input_not_found", se)

    def test_输入输出同一文件拒绝(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.md"
            p.write_text("x\n", encoding="utf-8")
            rc, so, se = 跑main(["-i", str(p), "-o", str(p)])
            self.assertEqual(rc, 1)
            self.assertIn("FAIL: same_path", se)
            self.assertEqual(p.read_text(encoding="utf-8"), "x\n")

    def test_缺参数退出码1(self):
        rc, so, se = 跑main(["-i", "a.md"])
        self.assertEqual(rc, 1)
        self.assertIn("FAIL: missing_args", se)

    def test_probe_失败时JSON在stdout_FAIL在stderr(self):
        report = {"playwright": True, "channel": None, "ok": False, "error": "无法启动浏览器（chrome: no）", "hint": "请装"}
        with mock.patch.object(browser, "probe_launch", lambda: dict(report)):
            rc, so, se = 跑main(["--probe"])
        self.assertEqual(rc, 2)
        j = json.loads(so.strip().splitlines()[-1])
        self.assertFalse(j["ok"])
        self.assertTrue(j["mermaid_js"])
        self.assertIn("FAIL: browser_unavailable 无法启动浏览器", se)
        self.assertNotIn("OK:", so)

    def test_probe_成功时OK行在stderr(self):
        report = {"playwright": True, "channel": "msedge", "ok": True, "error": None, "hint": None}
        with mock.patch.object(browser, "probe_launch", lambda: dict(report)):
            rc, so, se = 跑main(["--probe"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(so.strip())["channel"], "msedge")
        self.assertIn("OK: browser=msedge", se)
        self.assertNotIn("OK:", so, "--probe 的 OK 行要打到 stderr，stdout 只留 JSON")

    def test_probe_缺mermaid_js算失败(self):
        report = {"playwright": True, "channel": "chrome", "ok": True, "error": None, "hint": None}
        with mock.patch.object(browser, "probe_launch", lambda: dict(report)), \
             mock.patch.object(mr, "_MERMAID_JS", Path("/不存在/mermaid.min.js")):
            rc, so, se = 跑main(["--probe"])
        self.assertEqual(rc, 2)
        self.assertIn("FAIL: browser_unavailable mermaid_js_missing", se)

    @需要docx
    def test_docx参数出Word并嵌图(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "草稿.md"
            src.write_text(MD_两个围栏, encoding="utf-8")
            out_md = Path(td) / "定稿.md"
            out_docx = Path(td) / "定稿.docx"

            class 假渲染器:
                label = "fake"
                render_one = staticmethod(桩渲染器())

                def close(self):
                    pass

            with mock.patch.object(mr, "_open_renderer", lambda **kw: 假渲染器()):
                rc, so, se = 跑main(["-i", str(src), "-o", str(out_md), "--docx", str(out_docx)])
            self.assertEqual(rc, 0, se)
            self.assertIn(f"docx={out_docx.resolve()}", so.rstrip().splitlines()[-1])
            import docx
            self.assertEqual(len(docx.Document(str(out_docx)).inline_shapes), 2)


class BrowserModuleTest(unittest.TestCase):
    def test_playwright_installed_是布尔(self):
        self.assertIsInstance(browser.playwright_installed(), bool)

    def test_launch_全失败抛BrowserUnavailable(self):
        class 假pw:
            class chromium:
                @staticmethod
                def launch(**kw):
                    raise RuntimeError("Executable doesn't exist")

        with self.assertRaises(browser.BrowserUnavailable) as cm:
            browser.launch_chromium(假pw(), headless=True)
        self.assertIn("chrome:", str(cm.exception))
        self.assertIn("playwright install chromium", str(cm.exception))

    def test_launch_按顺序回退(self):
        tried: list = []

        class 假pw:
            class chromium:
                @staticmethod
                def launch(**kw):
                    tried.append(kw.get("channel"))
                    if kw.get("channel") == "chrome":
                        raise RuntimeError("no chrome")
                    return "BROWSER"

        with mock.patch.dict("os.environ", {"PATENT_BROWSER_CHANNEL": ""}):
            b, label = browser.launch_chromium(假pw(), headless=True)
        self.assertEqual((b, label), ("BROWSER", "msedge"))
        self.assertEqual(tried, ["chrome", "msedge"])

    def test_report_probe_约定(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = browser.report_probe({"ok": False, "error": "playwright_not_installed", "hint": "pip3 install playwright"})
        self.assertEqual(rc, 2)
        self.assertIn("FAIL: browser_unavailable playwright_not_installed", err.getvalue())
        self.assertEqual(json.loads(out.getvalue())["error"], "playwright_not_installed")


# ---------------------------------------------------------------- 真渲染（本机有浏览器才跑）

class RealRenderTest(unittest.TestCase):
    def setUp(self):
        if not 浏览器能用():
            self.skipTest(f"本机没有可用浏览器（{(_PROBE or {}).get('error')}），跳过真渲染")

    def test_真出图(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "草稿.md"
            src.write_text(MD_两个围栏, encoding="utf-8")
            out_md = Path(td) / "定稿.md"
            rc, so, se = 跑main(["-i", str(src), "-o", str(out_md), "--keep-source"])
            self.assertEqual(rc, 0, se)
            self.assertTrue(so.rstrip().splitlines()[-1].startswith("OK: mermaid=2 fail=0"), so)
            figs = out_md.parent / "mermaid_figures"
            for stem in ("fig_001", "fig_002"):
                png = figs / f"{stem}.png"
                self.assertTrue(png.is_file())
                data = png.read_bytes()
                self.assertTrue(data.startswith(b"\x89PNG"))
                self.assertGreater(len(data), 5000, "真图不该只有几百字节")
                w, h = struct.unpack(">II", data[16:24])
                self.assertGreater(w, 200)
                self.assertGreater(h, 100)
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("![图 1](mermaid_figures/fig_001.png)\n<!-- mermaid source: mermaid_figures/fig_001.mmd -->", text)
            self.assertIn("![图 5](mermaid_figures/fig_002.png)", text)

    def test_语法错的围栏保留其余照出(self):
        md = "```mermaid\nflowchart LR\n  A1[好的] --> A2[节点]\n```\n\n```mermaid\nthis is not mermaid ---> [[[\n```\n"
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "a.md"
            src.write_text(md, encoding="utf-8")
            out_md = Path(td) / "b.md"
            rc, so, se = 跑main(["-i", str(src), "-o", str(out_md)])
            self.assertEqual(rc, 1)
            self.assertIn("FAIL: mermaid_render_failed fail=1 ok=1", se)
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("![图 1](mermaid_figures/fig_001.png)", text)
            self.assertIn("this is not mermaid ---> [[[", text)
            self.assertTrue((out_md.parent / "mermaid_figures" / "fig_001.png").is_file())
            self.assertFalse((out_md.parent / "mermaid_figures" / "fig_002.png").exists())



class 附图说明不当标题(unittest.TestCase):
    """「附图说明」栏目的条目排在第一个围栏前面时，图号必须仍从 1 起排。"""

    def test_附图说明条目不被当成标题(self):
        md = (
            "## 附图说明\n\n"
            "图1 是本发明实施例的工艺流程图；\n\n"
            "图2 是本发明实施例的状态迁移图。\n\n"
            "```mermaid\ngraph TD\n  A-->B\n```\n\n"
            "```mermaid\ngraph TD\n  C-->D\n```\n"
        )
        blocks = mr.extract_mermaid_blocks(md)
        self.assertEqual([b.caption_no for b in blocks], [None, None])

    def test_单张图的自定标题仍然沿用(self):
        md = "图 3 系统结构示意图\n\n```mermaid\ngraph TD\n  A-->B\n```\n"
        blocks = mr.extract_mermaid_blocks(md)
        self.assertEqual(blocks[0].caption_no, 3)

    def test_连续图号清单不被当成标题(self):
        md = "图 1 总体框图\n图 2 分解框图\n\n```mermaid\ngraph TD\n  A-->B\n```\n"
        blocks = mr.extract_mermaid_blocks(md)
        self.assertIsNone(blocks[0].caption_no)

if __name__ == "__main__":
    unittest.main()
