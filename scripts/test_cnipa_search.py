"""cnipa_search.py 的单元测试。全部离线：浏览器和网络都是假的，一次都不联网。"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
import unittest
import urllib.error
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cnipa_search as cs  # noqa: E402
from browser import BrowserUnavailable  # noqa: E402

FIXTURE = (HERE / "fixtures" / "cnipa_epub_sample.html").read_text(encoding="utf-8")

NO_HIT_HTML = ("<!DOCTYPE html><html><head><title>无查询结果</title></head>"
               "<body><div id='result'>无查询结果，请更换检索词</div></body></html>")


def split_fixture() -> tuple[str, list[str]]:
    """把 fixture 拆成页头和三个条目块，方便拼出「不同的词查出不同结果」的页面。"""
    parts = re.split(r'(<div class="item">)', FIXTURE)
    head = parts[0]
    blocks = [parts[i] + parts[i + 1] for i in range(1, len(parts) - 1, 2)]
    return head, blocks


HEAD, BLOCKS = split_fixture()


def compose(indexes: list[int]) -> str:
    return HEAD + "".join(BLOCKS[i] for i in indexes)


# ---------------------------------------------------------------- 假浏览器

class FakeResponse:
    def __init__(self, status: int = 200):
        self.status = status


class FakeElement:
    """高级查询页的 form / button 都用它顶着。"""

    def __init__(self, page=None):
        self.page = page

    def query_selector(self, sel):
        return FakeElement(self.page)

    def click(self):
        if self.page is not None:
            self.page.submitted += 1

    def evaluate(self, script, arg=None):
        return None


class FakePage:
    """够 cnipa_search 用的最小 Playwright Page。

    html_for(keyword) 决定每个词查出什么页面；goto_status / goto_error 用来模拟站点打不开；
    gate=False 模拟「站点开着但检索框一直不出来」。
    """

    def __init__(self, html_for, *, goto_status=200, goto_error=None, gate=True):
        self.html_for = html_for
        self.goto_status = goto_status
        self.goto_error = goto_error
        self.gate = gate
        self.keyword = ""
        self.submitted = 0
        self.gotos: list[str] = []
        self.waited_ms = 0

    def goto(self, url, wait_until=None, timeout=None):
        self.gotos.append(url)
        if self.goto_error:
            raise RuntimeError(self.goto_error)
        return FakeResponse(self.goto_status)

    def wait_for_timeout(self, ms):
        self.waited_ms += ms

    def query_selector(self, sel):
        if sel in ("#searchStr", "#e51") and not self.gate:
            return None
        return FakeElement(self)

    def fill(self, sel, value):
        if sel in ("#searchStr", "#ti"):
            self.keyword = value

    @property
    def url(self):
        # 提交过就当已经跳到结果页；高级查询那一路等的就是这个 URL。
        return ("http://epub.cnipa.gov.cn/Dxb/AdvancedQuery" if self.submitted
                else "http://epub.cnipa.gov.cn/Advanced")

    def evaluate(self, script, arg=None):
        s = str(script)
        if "indexForm" in s:
            self.submitted += 1
            return None
        if "advForm" in s:
            self.submitted += 1
            return "查询"          # 模拟点到了「查询」按钮
        if "document.title" in s:  # _RESULT_READY_JS：结果页就绪判定
            return True
        return None

    @contextmanager
    def expect_navigation(self, timeout=None, wait_until=None):
        yield

    def wait_for_function(self, script, arg=None, timeout=None):
        return True

    def wait_for_url(self, pattern, timeout=None):
        return True

    def wait_for_load_state(self, state, timeout=None):
        return True

    def content(self):
        return self.html_for(self.keyword)


class FakeContext:
    def __init__(self, page):
        self.page = page
        self.closed = False

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, page):
        self.context = FakeContext(page)
        self.closed = False
        self.version = "124.0.0.0"

    def new_context(self, **kw):
        return self.context

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, page, launch_error=None):
        self.page = page
        self.launch_error = launch_error
        self.channels: list[str | None] = []

    def launch(self, **kw):
        self.channels.append(kw.get("channel"))
        if self.launch_error:
            raise RuntimeError(self.launch_error)
        return FakeBrowser(self.page)


class FakePlaywright:
    def __init__(self, page, launch_error=None):
        self.chromium = FakeChromium(page, launch_error)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def factory_for(page, launch_error=None):
    return lambda: FakePlaywright(page, launch_error)


def run_main(argv, page=None, launch_error=None, reachable=(True, "HTTP 200")):
    """跑一次 main()，返回 (退出码, stdout, stderr)。"""
    pw = factory_for(page, launch_error) if (page is not None or launch_error) else None
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cs.main(argv, playwright_factory=pw, reach_check=lambda: reachable)
    return rc, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------- 解析

class TestParse(unittest.TestCase):
    def setUp(self):
        self.hits = cs.parse_result_html(FIXTURE)

    def test_three_hits(self):
        self.assertEqual(len(self.hits), 3)

    def test_pub_number(self):
        self.assertEqual([h.pub_number for h in self.hits],
                         ["CN114398178A", "CN115562840A", "CN116719613A"])

    def test_title(self):
        self.assertEqual(self.hits[0].title, "一种面向异构算力集群的批任务调度方法及装置")
        self.assertEqual(self.hits[2].title, "一种医疗机构人力排班与任务分派方法")

    def test_abstract_is_full_text_not_title(self):
        a = self.hits[0].abstract
        self.assertTrue(a.startswith("本发明公开了一种面向异构算力集群的批任务调度方法及装置"))
        # 折叠在 span.alltxt 里的后半段也要抓出来，不然只读到半句就下结论
        self.assertIn("匈牙利算法", a)
        self.assertIn("GPU空闲率下降12个百分点", a)
        # 「全部」是展开按钮的字，不该混进摘要
        self.assertFalse(a.endswith("全部"))

    def test_link_is_epub_not_google(self):
        for h in self.hits:
            self.assertTrue(h.link.startswith("http://epub.cnipa.gov.cn/patent/"), h.link)
            self.assertIn(h.pub_number, h.link)

    def test_ipc_codes(self):
        self.assertEqual(self.hits[0].ipc_codes, ["G06F9/48", "G06F9/50"])
        self.assertEqual(self.hits[1].ipc_codes, ["G06F9/50", "G06Q10/06"])
        self.assertEqual(self.hits[2].ipc_codes, ["G16H40/20", "G06Q10/1093"])

    def test_class_chunk_stops_before_abstract(self):
        # 摘要里有 27%、12 这类数字和 CPU/GPU，不能被当成分类号
        for h in self.hits:
            self.assertEqual(h.loc_codes, [])
            for code in h.ipc_codes:
                self.assertRegex(code, r"^[A-HY]\d{2}[A-Z]\d+/\d+$")

    def test_applicant_and_inventors(self):
        self.assertEqual(self.hits[0].applicant, "北京云枢智算科技有限公司")
        self.assertEqual(self.hits[0].inventors, ["张启明", "李文博", "王思远"])
        self.assertEqual(self.hits[1].applicant, "杭州栖云数据技术有限公司")

    def test_application_number_and_dates(self):
        self.assertEqual(self.hits[0].application_number, "202111529876.3")
        self.assertEqual(self.hits[0].filing_date, "2021.12.14")
        self.assertEqual(self.hits[0].publication_date, "2022.04.26")

    def test_no_hit_page_parses_to_empty(self):
        self.assertEqual(cs.parse_result_html(NO_HIT_HTML), [])

    def test_json_has_required_fields(self):
        row = cs.hits_to_json(self.hits)[0]
        for key in ("pub_number", "title", "abstract", "link", "ipc_codes", "applicant"):
            self.assertIn(key, row)
            self.assertTrue(row[key], key)


class TestClassCodes(unittest.TestCase):
    def test_ipc_prefix(self):
        self.assertEqual(cs.ipc_prefix("G06F9/48"), "G06F9")
        self.assertEqual(cs.ipc_prefix("G06Q10/1093"), "G06Q10")
        self.assertEqual(cs.ipc_prefix("B01J 20/26"), "B01J20")

    def test_suggest_takes_top_three_prefixes(self):
        kind, codes = cs.suggest_class_codes(cs.parse_result_html(FIXTURE))
        self.assertEqual(kind, "ipc")
        self.assertEqual(codes, ["G06F9", "G06Q10", "G16H40"])

    def test_suggest_empty_when_no_codes(self):
        self.assertEqual(cs.suggest_class_codes([cs.EpubHit(title="无分类号")]), ("ipc", []))


# ---------------------------------------------------------------- 合并去重

class TestMerge(unittest.TestCase):
    def test_dedupe_by_pub_number(self):
        a = cs.parse_result_html(compose([0, 1]))
        b = cs.parse_result_html(compose([1, 2]))
        self.assertEqual(len(a), 2)
        self.assertEqual(len(b), 2)
        merged = cs.dedupe_hits([a, b])
        self.assertEqual([h.pub_number for h in merged],
                         ["CN114398178A", "CN115562840A", "CN116719613A"])

    def test_dedupe_keeps_first_copy(self):
        rich = cs.parse_result_html(compose([0]))
        thin = [cs.EpubHit(pub_number="CN114398178A", title="同一件，字段更少")]
        merged = cs.dedupe_hits([rich, thin])
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0].abstract)

    def test_multi_term_search_merges_in_one_browser(self):
        pages = {"批任务调度": compose([0, 1]), "资源画像": compose([1, 2])}
        page = FakePage(lambda kw: pages.get(kw, NO_HIT_HTML))
        rc, out, err = run_main(["批任务调度", "资源画像"], page=page)
        self.assertEqual(rc, 0)
        self.assertIn("EPUB_MERGE: terms=2 type=invention merged_hits=3", err)
        self.assertIn("OK: hits=3 terms=2 type=invention", out)
        self.assertEqual(page.submitted, 2)          # 两个词各提交一次
        self.assertEqual(len(page.gotos), 2)         # 同一个 page，没有开第二个浏览器


# ---------------------------------------------------------------- 检索词

class TestTerms(unittest.TestCase):
    def test_split_on_whitespace_and_dedupe(self):
        self.assertEqual(cs.split_terms(["批任务调度 资源画像", "异构算力", "资源画像"]),
                         ["批任务调度", "资源画像", "异构算力"])

    def test_long_chinese_single_arg_warns(self):
        warns = cs.term_warnings(["知识库检索增强大语言模型"])
        self.assertTrue(any(w.startswith("long_term") for w in warns))
        self.assertTrue(any("拆成" in w for w in warns))

    def test_normal_terms_do_not_warn(self):
        self.assertEqual(cs.term_warnings(["批任务调度", "资源画像", "异构算力"]), [])

    def test_generic_term_warns(self):
        self.assertTrue(any(w.startswith("generic_term")
                            for w in cs.term_warnings(["批任务调度", "系统"])))

    def test_long_term_warning_reaches_stderr_but_still_searches(self):
        page = FakePage(lambda kw: compose([0]))
        rc, out, err = run_main(["知识库检索增强大语言模型"], page=page)
        self.assertEqual(rc, 0)
        self.assertIn("EPUB_TERM_WARN: long_term", err)
        self.assertIn("OK: hits=1", out)

    def test_too_many_terms_is_input_error(self):
        rc, out, err = run_main(["a", "b", "c", "d", "e", "f", "g", "h", "i"])
        self.assertEqual(rc, 1)
        self.assertIn("FAIL:", err)
        self.assertIn("超过上限 8", err)

    def test_max_terms_option(self):
        rc, out, err = run_main(["--max-terms", "2", "甲", "乙", "丙"])
        self.assertEqual(rc, 1)
        self.assertIn("超过上限 2", err)

    def test_no_terms_is_input_error(self):
        rc, out, err = run_main([])
        self.assertEqual(rc, 1)
        self.assertIn("FAIL:", err)


# ---------------------------------------------------------------- 类型映射

class TestPatentType(unittest.TestCase):
    def test_default_is_invention(self):
        self.assertEqual(cs.normalize_patent_type(None), "invention")
        self.assertEqual(cs.normalize_patent_type(""), "invention")

    def test_aliases(self):
        self.assertEqual(cs.normalize_patent_type("发明"), "invention")
        self.assertEqual(cs.normalize_patent_type("Invention"), "invention")
        self.assertEqual(cs.normalize_patent_type("实用新型"), "utility_model")
        self.assertEqual(cs.normalize_patent_type("utility-model"), "utility_model")
        self.assertEqual(cs.normalize_patent_type("外观设计"), "design")
        self.assertEqual(cs.normalize_patent_type("all"), "all")

    def test_unknown_type_rejected(self):
        with self.assertRaises(cs.BadInput):
            cs.normalize_patent_type("专利")

    def test_invention_checkboxes(self):
        # 发明 = 发明公布 + 发明授权，实用新型和外观都不勾
        self.assertEqual(cs.epub_checkbox_states("invention"),
                         {"fmgb": True, "fmsq": True, "xxsq": False, "wgsq": False})
        self.assertEqual(cs.epub_checkbox_states("design"),
                         {"fmgb": False, "fmsq": False, "xxsq": False, "wgsq": True})

    def test_checkbox_ids_cover_advanced_page(self):
        self.assertEqual(set(cs.EPUB_ADVANCED_CHECKBOX), set(cs.EPUB_TYPE_CHECKBOXES["all"]))

    def test_bad_type_on_cli(self):
        rc, out, err = run_main(["--type", "专利", "批任务调度"])
        self.assertEqual(rc, 1)
        self.assertIn("不认识的专利类型", err)


# ---------------------------------------------------------------- 失败与退出码

class TestFailures(unittest.TestCase):
    def test_browser_unavailable_is_exit_2(self):
        page = FakePage(lambda kw: FIXTURE)
        rc, out, err = run_main(["批任务调度"], page=page, launch_error="Executable doesn't exist")
        self.assertEqual(rc, 2)
        self.assertIn("FAIL: browser_unavailable", err)
        self.assertNotIn("EPUB_HITS_JSON:", out)

    def test_site_unreachable_says_so_not_waf(self):
        rc, out, err = run_main(["批任务调度"],
                                reachable=(False, "被网络策略挡住（HTTP 403，host_not_allowed）"))
        self.assertEqual(rc, 2)
        self.assertIn("FAIL: site_unreachable", err)
        self.assertIn("到不了这个站", err)
        # 这条是重点：不许把「网络到不了」说成「等待时间不够」，那会让人去调等待时间
        self.assertIn("不是等待时间不够", err)
        self.assertNotIn("search_gate_timeout", err)

    def test_precheck_runs_before_the_browser(self):
        page = FakePage(lambda kw: FIXTURE)
        rc, out, err = run_main(["批任务调度"], page=page, reachable=(False, "连不上（timed out）"))
        self.assertEqual(rc, 2)
        self.assertEqual(page.gotos, [])             # 站点到不了就没必要开浏览器
        self.assertNotIn("BROWSER:", err)

    def test_goto_net_error_is_site_unreachable(self):
        page = FakePage(lambda kw: FIXTURE, goto_error="net::ERR_CONNECTION_REFUSED at http://epub…")
        rc, out, err = run_main(["批任务调度"], page=page)
        self.assertEqual(rc, 2)
        self.assertIn("FAIL: site_unreachable", err)
        self.assertIn("不是等待时间不够", err)

    def test_goto_403_is_site_unreachable(self):
        page = FakePage(lambda kw: FIXTURE, goto_status=403)
        rc, out, err = run_main(["批任务调度"], page=page)
        self.assertEqual(rc, 2)
        self.assertIn("FAIL: site_unreachable", err)
        self.assertIn("HTTP 403", err)

    def test_gate_timeout_is_a_different_message(self):
        os.environ["EPUB_WAF_MAX_WAIT_SEC"] = "6"     # 别让测试真等 180 秒
        try:
            page = FakePage(lambda kw: FIXTURE, gate=False)
            rc, out, err = run_main(["批任务调度"], page=page)
        finally:
            os.environ.pop("EPUB_WAF_MAX_WAIT_SEC", None)
        self.assertEqual(rc, 2)
        self.assertIn("FAIL: search_gate_timeout", err)
        self.assertIn("站点在前面挡了一道校验", err)
        self.assertIn("EPUB_WAF_MAX_WAIT_SEC", err)   # 这种才该建议调等待时间
        self.assertNotIn("site_unreachable", err)

    def test_midway_timeout_is_entry_unavailable_not_input_error(self):
        class TimeoutErrorPage(FakePage):
            def fill(self, sel, value):
                raise TimeoutError("Timeout 120000ms exceeded")

        page = TimeoutErrorPage(lambda kw: FIXTURE)
        rc, out, err = run_main(["批任务调度"], page=page)
        self.assertEqual(rc, 2)                       # 站点卡住是入口问题，不是我们参数写错
        self.assertIn("FAIL: entry_unavailable", err)
        self.assertIn("不要写成「未检索到」", err)

    def test_提交后结果页一直不就绪_报校验没过而不是入口不通(self):
        """实测踩过：高级查询提交后站点还会再导航一两次，load 事件等不到。

        这时候该说「站点前面挡了一道校验、可以加等待时间」，
        不能说成「这台机器到不了这个站」。
        """
        class NeverReadyPage(FakePage):
            def evaluate(self, script, arg=None):
                out = super().evaluate(script, arg)
                return False if "document.title" in str(script) else out

        page = NeverReadyPage(lambda kw: FIXTURE)
        rc, out, err = run_main(["批任务调度"], page=page)
        self.assertEqual(rc, 2)
        self.assertIn("FAIL: search_gate_timeout", err)
        self.assertIn("站点在前面挡了一道校验", err)
        self.assertIn("EPUB_WAF_MAX_WAIT_SEC", err)
        self.assertNotIn("site_unreachable", err)

    def test_unexpected_error_is_exit_1(self):
        class BrokenPage(FakePage):
            def content(self):
                raise ValueError("解析不了")

        page = BrokenPage(lambda kw: FIXTURE)
        rc, out, err = run_main(["批任务调度"], page=page)
        self.assertEqual(rc, 1)
        self.assertIn("FAIL: runtime_error ValueError", err)

    def test_zero_hits_is_ok_not_fail(self):
        page = FakePage(lambda kw: NO_HIT_HTML)
        rc, out, err = run_main(["罕见词甲", "罕见词乙"], page=page)
        self.assertEqual(rc, 0)                       # 0 条不是失败
        self.assertIn("OK: hits=0 terms=2 type=invention", out)
        self.assertNotIn("FAIL:", err)
        self.assertIn("EPUB_HITS_JSON: []", out)
        self.assertIn("EPUB_HINT: 0 hits", err)


class TestReachCheck(unittest.TestCase):
    """开浏览器之前那次可达性判断：判得保守，只有真到不了才拦。"""

    def test_proxy_allowlist_403_is_unreachable(self):
        class Headers(dict):
            def get(self, k, d=None):
                return dict.get(self, k, d)

        def opener(req, timeout=None):
            raise urllib.error.HTTPError(
                cs.EPUB_BASE, 403, "Forbidden", Headers({"x-deny-reason": "host_not_allowed"}),
                io.BytesIO(b"Host not in allowlist: epub.cnipa.gov.cn."))

        ok, detail = cs.check_site_reachable(opener=opener)
        self.assertFalse(ok)
        self.assertIn("网络策略", detail)

    def test_site_own_403_still_goes_to_the_browser(self):
        def opener(req, timeout=None):
            raise urllib.error.HTTPError(cs.EPUB_BASE, 403, "Forbidden", {},
                                         io.BytesIO("<html>请开启JavaScript</html>".encode()))

        ok, detail = cs.check_site_reachable(opener=opener)
        # 站点自己回 403 很可能只是反爬看不惯 urllib，这时不能替浏览器下结论
        self.assertTrue(ok)
        self.assertIn("交给浏览器", detail)

    def test_dns_failure_is_unreachable(self):
        def opener(req, timeout=None):
            raise urllib.error.URLError("[Errno -2] Name or service not known")

        ok, detail = cs.check_site_reachable(opener=opener)
        self.assertFalse(ok)
        self.assertIn("连不上", detail)

    def test_tunnel_block_is_unreachable(self):
        def opener(req, timeout=None):
            raise urllib.error.URLError("Tunnel connection failed: 403 Forbidden")

        ok, detail = cs.check_site_reachable(opener=opener)
        self.assertFalse(ok)
        self.assertIn("网络策略", detail)

    def test_200_is_reachable(self):
        class Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        ok, detail = cs.check_site_reachable(opener=lambda req, timeout=None: Resp())
        self.assertTrue(ok)

    def test_env_switch_skips_the_check(self):
        os.environ["CNIPA_SKIP_PRECHECK"] = "1"
        try:
            def boom(req, timeout=None):
                raise AssertionError("设了跳过还去连网就是错的")

            ok, detail = cs.check_site_reachable(opener=boom)
        finally:
            os.environ.pop("CNIPA_SKIP_PRECHECK", None)
        self.assertTrue(ok)


# ---------------------------------------------------------------- 输出约定

class TestOutput(unittest.TestCase):
    def test_stdout_has_json_line_and_ok_line_last(self):
        page = FakePage(lambda kw: FIXTURE)
        rc, out, err = run_main(["批任务调度"], page=page)
        self.assertEqual(rc, 0)
        lines = [x for x in out.strip().splitlines() if x.strip()]
        self.assertTrue(lines[0].startswith("EPUB_HITS_JSON: "))
        self.assertTrue(lines[-1].startswith("OK: hits=3 terms=1 type=invention"))
        rows = json.loads(lines[0][len("EPUB_HITS_JSON: "):])
        self.assertEqual(rows[0]["pub_number"], "CN114398178A")

    def test_json_mode_stdout_is_pure_json(self):
        page = FakePage(lambda kw: FIXTURE)
        rc, out, err = run_main(["批任务调度", "--json"], page=page)
        self.assertEqual(rc, 0)
        rows = json.loads(out)                     # 整个 stdout 就是一个 JSON 数组
        self.assertEqual(len(rows), 3)
        self.assertIn("OK: hits=3", err)           # --json 时 OK 行改到 stderr
        self.assertNotIn("OK:", out)

    def test_class_hint_on_stderr(self):
        page = FakePage(lambda kw: FIXTURE)
        rc, out, err = run_main(["批任务调度"], page=page)
        self.assertIn("EPUB_CLASS_HINT: kind=ipc codes=G06F9,G06Q10,G16H40", err)

    def test_second_round_with_class_reports_it(self):
        page = FakePage(lambda kw: compose([0, 1]))
        rc, out, err = run_main(["--class", "G06F9,G06Q10", "批任务调度"], page=page)
        self.assertEqual(rc, 0)
        self.assertIn("EPUB_NOTE: class=G06F9,G06Q10", err)
        self.assertIn("class=G06F9,G06Q10", out)               # OK 行也带上
        self.assertNotIn("EPUB_CLASS_HINT:", err)              # 已经带号了就不用再提示
        self.assertEqual(page.gotos, [cs.EPUB_ADVANCED, cs.EPUB_ADVANCED])

    def test_too_many_class_codes_rejected(self):
        rc, out, err = run_main(["--class", "A01B,B01J,C08K,G06F", "词"])
        self.assertEqual(rc, 1)
        self.assertIn("最多 3 个", err)

    def test_class_narrows_term_cap_to_three(self):
        rc, out, err = run_main(["--class", "G06F9", "甲", "乙", "丙", "丁"])
        self.assertEqual(rc, 1)
        self.assertIn("超过上限 3", err)


class TestNoDisk(unittest.TestCase):
    """结果页 HTML 只在内存里处理，一个字节都不写盘——查新材料不该留在磁盘上。"""

    def test_search_writes_no_files(self):
        before = sorted(p.name for p in HERE.iterdir())
        fixtures_before = sorted(p.name for p in (HERE / "fixtures").iterdir())
        with tempfile.TemporaryDirectory() as td:
            cwd = os.getcwd()
            os.chdir(td)
            try:
                page = FakePage(lambda kw: FIXTURE)
                rc, out, err = run_main(["批任务调度", "资源画像"], page=page)
            finally:
                os.chdir(cwd)
            self.assertEqual(rc, 0)
            self.assertEqual(list(Path(td).iterdir()), [])          # 当前目录没多东西
        self.assertEqual(sorted(p.name for p in HERE.iterdir()), before)
        self.assertEqual(sorted(p.name for p in (HERE / "fixtures").iterdir()), fixtures_before)
        self.assertIn("disk=0", err)

    def test_html_bytes_reported_but_not_saved(self):
        page = FakePage(lambda kw: FIXTURE)
        rc, out, err = run_main(["批任务调度"], page=page)
        m = re.search(r"EPUB_NOTE: html_bytes=(\d+) disk=0", err)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), len(FIXTURE))

    def test_module_never_writes(self):
        # 源码里不该出现写文件的调用；真要落盘得是有意加的，不能悄悄溜进来。
        # \bopen 是为了不把 urlopen 误伤成写文件
        src = (HERE / "cnipa_search.py").read_text(encoding="utf-8")
        for bad in (r"\bopen\s*\(", r"\.write_text\s*\(", r"\.write_bytes\s*\(",
                    r"\.mkdir\s*\(", r"shutil\.copy"):
            self.assertIsNone(re.search(bad, src), f"cnipa_search.py 里不该有 {bad}")

    def test_the_write_check_would_catch_a_real_write(self):
        # 上面那条断言本身得有效：真写盘的代码要能被它抓到
        for sample in ("Path(p).write_text(html)", "with open(p, 'w') as f:"):
            hit = any(re.search(bad, sample) for bad in
                      (r"\bopen\s*\(", r"\.write_text\s*\(", r"\.write_bytes\s*\("))
            self.assertTrue(hit, sample)
        self.assertIsNone(re.search(r"\bopen\s*\(", "urllib.request.urlopen(req)"))


class TestBrowserWiring(unittest.TestCase):
    def test_reports_channel_and_closes_everything(self):
        page = FakePage(lambda kw: FIXTURE)
        pw_holder = {}

        def factory():
            pw = FakePlaywright(page)
            pw_holder["pw"] = pw
            return pw

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cs.main(["批任务调度"], playwright_factory=factory,
                         reach_check=lambda: (True, "HTTP 200"))
        self.assertEqual(rc, 0)
        self.assertIn("BROWSER: channel=chrome", err.getvalue())
        self.assertEqual(pw_holder["pw"].chromium.channels, ["chrome"])

    def test_browser_unavailable_exception_type(self):
        page = FakePage(lambda kw: FIXTURE)
        with self.assertRaises(BrowserUnavailable):
            cs.search_terms(["批任务调度"], playwright_factory=factory_for(page, "no chrome"))


if __name__ == "__main__":
    unittest.main()
