"""prior_art_search.py 的单元测试。全部离线：HTTP 一律用假的 fetch 函数，不联网。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prior_art_search as pas  # noqa: E402

FIXTURE = json.loads((HERE / "fixtures" / "google_patents_xhr_sample.json").read_text(encoding="utf-8"))

# 仿 patents.google.com 专利页的关键骨架：各块用 itemprop 标记，中间夹着脚本、表格和其他噪音。
PAGE = """<!DOCTYPE html><html><head><meta name="DC.title" content="电力系统终端通信接入网告警集中监控系统及方法">
<script>var junk = "abstract 不该被抓进来";</script></head><body>
<h1><span itemprop="title">电力系统终端通信接入网告警集中监控系统及方法</span></h1>
<dl><dt>Publication date</dt><dd><time itemprop="publicationDate" datetime="2020-07-10">2020-07-10</time></dd>
<dd itemprop="priorityDate">2017-06-01</dd><dd itemprop="filingDate">2017-06-01</dd>
<dd itemprop="events"><time itemprop="filingDate">2017-06-01</time></dd><dd itemprop="priorityDate">2017-06-01</dd>
<dd itemprop="inventor" repeat>周洁</dd><dd itemprop="inventor" repeat>王五</dd>
<dd itemprop="assigneeOriginal">国网山东省电力公司信息通信公司</dd></dl>
<a href="https://patentimages.storage.googleapis.com/b8/96/f2/CN107196804B.pdf" itemprop="pdfLink">Download PDF</a>
<section itemprop="abstract" itemscope itemtype="http://schema.org/Article">
 <h2>Abstract</h2>
 <div class="abstract" itemprop="content">本发明公开了一种告警集中监控系统，包括告警采集、告警预处理。</div>
</section>
<section itemprop="claims" itemscope>
 <h2>Claims (<span itemprop="count">2</span>)</h2>
 <div itemprop="content"><div class="claims">
  <div class="claim"><div class="claim" num="00001" id="CLM-00001"><div class="claim-text">1.一种告警集中监控系统，其特征在于，包括：
   <div class="claim-text">告警采集模块，用于接收实时告警消息；</div>
   <div class="claim-text">告警预处理模块，用于归一化处理。</div></div></div></div>
  <div class="claim"><div class="claim-dependent" num="00002"><div class="claim-text">2.根据权利要求1所述的系统，其特征在于，还包括故障诊断模块。</div></div></div>
 </div></div>
</section>
<section itemprop="description" itemscope>
 <h2>Description</h2>
 <div itemprop="content">
  <heading>技术领域</heading>
  <div class="description-paragraph" num="0001">本发明涉及电力通信技术领域。</div>
  <div class="description-paragraph" num="0002">具体地，告警预处理对采集的告警信息进行归一化处理和分类压缩，压缩比为 3:1。</div>
 </div>
</section>
<section itemprop="citedBy"><table><tr><td><span itemprop="title">被引用专利的标题，不该覆盖主标题</span></td>
<td><span itemprop="assigneeOriginal">别家公司</span></td><td itemprop="priorityDate">2001-01-01</td>
<td itemprop="publicationDate">2002-02-02</td><td itemprop="inventor">路人甲</td></tr></table></section>
</body></html>"""

OPENALEX = {"results": [{
    "display_name": "Alert storm suppression with sliding windows",
    "authorships": [{"author": {"display_name": "A. Zhang"}}, {"author": {"display_name": "B. Li"}}],
    "publication_year": 2021, "doi": "https://doi.org/10.1000/xyz",
    "abstract_inverted_index": {"Sliding": [0], "windows": [1], "suppress": [2], "alerts": [3]},
    "open_access": {"oa_url": "https://example.org/paper.pdf"},
}]}

ARXIV = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>http://arxiv.org/abs/2101.00001v1</id><published>2021-01-01T00:00:00Z</published>
<title>Deduplicating   alert
 streams</title><summary>We   propose a method.</summary>
<author><name>C. Wang</name></author>
<link title="pdf" href="http://arxiv.org/pdf/2101.00001v1" rel="related" type="application/pdf"/>
</entry></feed>"""

GITHUB = {"items": [{"full_name": "acme/alert-dedup", "html_url": "https://github.com/acme/alert-dedup",
                     "description": "Sliding-window alert deduplication", "stargazers_count": 42,
                     "created_at": "2019-03-04T00:00:00Z", "pushed_at": "2024-05-06T00:00:00Z"}]}


class FakeFetch:
    """按 URL 关键字返回预设响应，并记下访问过哪些地址。"""

    def __init__(self, routes: dict):
        self.routes, self.seen = routes, []

    def __call__(self, url, headers=None, timeout=20.0):
        self.seen.append(url)
        for key, (status, body) in self.routes.items():
            if key in url:
                return status, body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        raise OSError("connection refused")


class NoWaitPacer(pas.Pacer):
    def wait(self):
        return 0.0


class QueryUrlTest(unittest.TestCase):
    def test_内层原样外层编码一次(self):
        url = pas.gp_query_url("告警 抑制 sliding window", before="2024-01-01", country="CN", limit=5)
        self.assertTrue(url.startswith(pas.GP_XHR + "?url="))
        inner = urllib.parse.unquote(url.split("?url=", 1)[1])
        self.assertEqual(inner, "q=告警+抑制+sliding+window&num=10&country=CN&before=publication:20240101")

    def test_会截断查询串的字符被去掉(self):
        inner = urllib.parse.unquote(pas.gp_query_url("a&b#c%d").split("?url=", 1)[1])
        self.assertEqual(inner, "q=a+b+c+d&num=10")


class PatentsParseTest(unittest.TestCase):
    def test_正常响应整形(self):
        hits, total = pas.gp_parse(200, json.dumps(FIXTURE, ensure_ascii=False))
        self.assertEqual(total, 514)
        self.assertEqual(len(hits), 2)
        h = hits[0]
        self.assertEqual(h["pub_no"], "CN107196804B")
        self.assertEqual(h["title"], "电力系统终端通信接入网告警集中监控系统及方法")
        self.assertEqual(h["applicant"], "国网山东省电力公司信息通信公司")
        self.assertEqual(h["priority_date"], "2017-06-01")
        self.assertEqual(h["pub_date"], "2020-07-10")
        self.assertTrue(h["abstract"].startswith("本发明公开了"))
        self.assertEqual(h["pdf_url"], pas.GP_PDF_CDN + "b8/96/f2/a2af6b8d184319/CN107196804B.pdf")
        self.assertEqual(h["link"], "https://patents.google.com/patent/CN107196804B/")

    def test_零结果(self):
        hits, total = pas.gp_parse(200, '{"results": {"total_num_results": 0, "cluster": [{}]}}')
        self.assertEqual((hits, total), ([], 0))

    def test_被限流要明说且不当成没查到(self):
        for status, body in ((503, "<html>/sorry/ unusual traffic</html>"), (200, "<html>captcha</html>"),
                             (429, "")):
            with self.assertRaises(pas.EntryUnavailable) as cm:
                pas.gp_parse(status, body)
            self.assertIn("拦", str(cm.exception))

    def test_打不开是入口问题(self):
        with self.assertRaises(pas.EntryUnavailable) as cm:
            pas.gp_parse(404, "")
        self.assertIn("HTTP 404", str(cm.exception))
        with self.assertRaises(pas.EntryUnavailable):
            pas.gp_parse(200, "not json at all")

    def test_search_patents_连不上也是入口问题(self):
        with self.assertRaises(pas.EntryUnavailable) as cm:
            pas.search_patents("x", fetch=FakeFetch({}), pacer=NoWaitPacer())
        self.assertIn("连不上", str(cm.exception))

    def test_search_patents_走完整链路并按limit截断(self):
        f = FakeFetch({"xhr/query": (200, FIXTURE)})
        res = pas.search_patents("告警", limit=1, fetch=f, pacer=NoWaitPacer())
        self.assertEqual(len(res["hits"]), 1)
        self.assertEqual(res["total"], 514)
        self.assertIn("num=10", urllib.parse.unquote(f.seen[0]))   # 接口最少要 10


class PacerTest(unittest.TestCase):
    def test_跨进程间隔靠文件戳(self):
        with tempfile.TemporaryDirectory() as td:
            stamp = Path(td) / "stamp"
            now = [1000.0]
            slept = []
            p = pas.Pacer(stamp, interval=12.0, clock=lambda: now[0], sleeper=slept.append)
            self.assertEqual(p.wait(), 0.0)          # 第一次不用等
            now[0] = 1005.0
            self.assertAlmostEqual(p.wait(), 7.0)     # 只过了 5 秒，补睡 7 秒
            self.assertEqual(slept, [7.0])
            now[0] = 1030.0
            q = pas.Pacer(stamp, interval=12.0, clock=lambda: now[0], sleeper=slept.append)  # 模拟另一个进程
            self.assertEqual(q.wait(), 0.0)
            self.assertEqual(len(slept), 1)

    def test_戳文件坏了也不崩(self):
        with tempfile.TemporaryDirectory() as td:
            stamp = Path(td) / "stamp"
            stamp.write_text("garbage")
            p = pas.Pacer(stamp, interval=1.0, clock=lambda: 5.0, sleeper=lambda s: None)
            self.assertEqual(p.wait(), 0.0)


class PatentPageTest(unittest.TestCase):
    def test_抠出三块正文和著录项(self):
        rec = pas.parse_patent_page(PAGE, "CN107196804B")
        self.assertEqual(rec["title"], "电力系统终端通信接入网告警集中监控系统及方法")
        self.assertEqual(rec["pub_date"], "2020-07-10")
        self.assertEqual(rec["priority_date"], "2017-06-01")      # 页面里出现两遍，只留一个
        self.assertEqual(rec["filing_date"], "2017-06-01")
        self.assertEqual(rec["inventor"], "周洁；王五")
        self.assertNotIn("别家公司", rec["applicant"])         # 引用表里的申请人不算
        self.assertNotIn("路人甲", rec["inventor"])
        self.assertEqual(rec["pub_date"], "2020-07-10")       # 引用表里的日期也不算
        self.assertEqual(rec["applicant"], "国网山东省电力公司信息通信公司")
        self.assertTrue(rec["pdf_url"].endswith("CN107196804B.pdf"))
        self.assertEqual(rec["abstract"], "本发明公开了一种告警集中监控系统，包括告警采集、告警预处理。")
        self.assertTrue(rec["claims"].startswith("1.一种告警集中监控系统"))
        self.assertIn("告警预处理模块，用于归一化处理。", rec["claims"])
        self.assertIn("2.根据权利要求1所述的系统", rec["claims"])
        self.assertNotIn("Claims", rec["claims"])            # 页面自带的小标题不要
        self.assertIn("压缩比为 3:1", rec["description"])
        self.assertTrue(rec["description"].startswith("技术领域"))
        self.assertNotIn("Description", rec["description"])
        self.assertNotIn("不该被抓进来", rec["abstract"] + rec["claims"] + rec["description"])

    def test_不是专利页就报错(self):
        with self.assertRaises(pas.EntryUnavailable):
            pas.parse_patent_page("<html><body><h1>Not found</h1></body></html>", "CN1")

    def test_get_patent_语言与状态码(self):
        f = FakeFetch({"/CN107196804B/zh": (200, PAGE), "/US1/en": (404, ""),
                       "/US2/en": (503, "/sorry/")})
        rec = pas.get_patent("cn107196804b", fetch=f, pacer=NoWaitPacer())
        self.assertEqual(rec["lang"], "zh")                 # CN 号默认取原文
        self.assertEqual(rec["pub_no"], "CN107196804B")
        with self.assertRaises(pas.EntryUnavailable) as cm:
            pas.get_patent("US1", fetch=f, pacer=NoWaitPacer())
        self.assertIn("没有 US1", str(cm.exception))
        with self.assertRaises(pas.EntryUnavailable) as cm:
            pas.get_patent("US2", fetch=f, pacer=NoWaitPacer())
        self.assertIn("拦", str(cm.exception))

    def test_markdown_输出(self):
        md = pas.patent_markdown({**pas.parse_patent_page(PAGE, "CN107196804B"), "lang": "zh", "link": "L"})
        for piece in ("# CN107196804B", "## 摘要", "## 权利要求", "## 说明书", "申请人：国网", "PDF："):
            self.assertIn(piece, md)


class PapersCodeTest(unittest.TestCase):
    def test_openalex(self):
        items = pas.search_openalex("alert", since="2020-01-01", limit=5,
                                    fetch=FakeFetch({"api.openalex.org": (200, OPENALEX)}))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["abstract"], "Sliding windows suppress alerts")
        self.assertEqual(items[0]["authors"], ["A. Zhang", "B. Li"])
        self.assertEqual(items[0]["oa_url"], "https://example.org/paper.pdf")
        f = FakeFetch({"api.openalex.org": (200, OPENALEX)})
        pas.search_openalex("alert", since="2020-01-01", fetch=f)
        self.assertIn("from_publication_date%3A2020-01-01", f.seen[0])

    def test_arxiv(self):
        items = pas.search_arxiv("alert", fetch=FakeFetch({"export.arxiv.org": (200, ARXIV)}))
        self.assertEqual(items[0]["title"], "Deduplicating alert streams")
        self.assertEqual(items[0]["year"], "2021")
        self.assertEqual(items[0]["oa_url"], "http://arxiv.org/pdf/2101.00001v1")
        self.assertEqual(items[0]["authors"], ["C. Wang"])

    def test_论文入口挂了报入口问题(self):
        with self.assertRaises(pas.EntryUnavailable):
            pas.search_openalex("x", fetch=FakeFetch({"api.openalex.org": (500, "")}))
        with self.assertRaises(pas.EntryUnavailable):
            pas.search_arxiv("x", fetch=FakeFetch({"export.arxiv.org": (200, "<not xml")}))
        with self.assertRaises(pas.EntryUnavailable):
            pas.search_arxiv("x", fetch=FakeFetch({}))

    def test_github(self):
        items = pas.search_code("alert", fetch=FakeFetch({"api.github.com": (200, GITHUB)}))
        self.assertEqual(items[0]["repo"], "acme/alert-dedup")
        self.assertEqual(items[0]["stars"], 42)
        self.assertEqual(items[0]["created_at"], "2019-03-04")
        with self.assertRaises(pas.EntryUnavailable) as cm:
            pas.search_code("alert", fetch=FakeFetch({"api.github.com": (403, '{"message": "API rate limit exceeded"}')}))
        self.assertIn("限流", str(cm.exception))
        with self.assertRaises(pas.EntryUnavailable) as cm:
            pas.search_code("alert", fetch=FakeFetch({"api.github.com": (403, '{"message": "path not available"}')}))
        self.assertIn("拒绝", str(cm.exception))


class CountingPacer(pas.Pacer):
    """不睡、只数：验证探针有没有计入 Google 限速。"""

    def __init__(self):
        self.calls = 0

    def wait(self):
        self.calls += 1
        return 0.0


class ProbeTest(unittest.TestCase):
    def test_打的是业务接口不是首页(self):
        """v1.1.1 的探针打首页，GitHub 根路径 200 而 search/repositories 403，探针报"通"其实不通。"""
        by = {e[0]: e for e in pas.PROBE_ENTRIES}
        self.assertEqual(by["Google Patents"][1], pas.gp_query_url("test"))   # 和 patents 子命令同一个接口
        self.assertIn("search/repositories?", by["GitHub API"][1])
        self.assertIn("works?search=", by["OpenAlex"][1])
        self.assertIn("api/query?search_query=", by["arXiv"][1])
        self.assertIn("search?q=", by["Bing"][1])
        for name, url, *_ in pas.PROBE_ENTRIES:
            self.assertNotIn(urllib.parse.urlsplit(url).path, ("", "/"), f"{name} 还在打首页：{url}")

    def test_分类(self):
        def fetch(url, headers=None, timeout=8.0):
            if "epub.cnipa" in url:
                return 200, "<html><head></head><body></body></html>"   # 瑞数防爬的空壳
            if "patents.google" in url:
                raise OSError("timed out")
            if "github" in url:      # 沙盒代理实测：根路径 200，搜索接口 403
                return 403, '{"message": "This GitHub API path is not available: sessions are bound to repos"}'
            if "openalex" in url:
                return 200, json.dumps(OPENALEX)
            if "arxiv" in url:
                return 200, ARXIV
            if "lens.org" in url:
                return 403, "<html>Access denied</html>"
            if "espacenet" in url:
                return 429, ""
            if "patentscope" in url:
                return 401, ""
            if "www.cnipa" in url:
                return 404, ""
            return 200, "x" * 5000      # Bing
        rows = pas.probe_all(fetch=fetch, pacer=NoWaitPacer())
        by = {r["name"]: r for r in rows}
        self.assertFalse(by["Google Patents"]["ok"])
        self.assertIsNone(by["Google Patents"]["status"])
        self.assertIn("timed out", by["Google Patents"]["detail"])
        self.assertFalse(by["国知局公布公告"]["ok"])
        self.assertIn("空壳", by["国知局公布公告"]["detail"])
        # 4xx 一律不通，状态码要写进结果
        self.assertFalse(by["GitHub API"]["ok"])
        self.assertEqual(by["GitHub API"]["status"], 403)
        self.assertIn("HTTP 403", by["GitHub API"]["detail"])
        self.assertIn("sessions are bound", by["GitHub API"]["detail"])
        self.assertFalse(by["Lens.org"]["ok"])
        self.assertIn("HTTP 403", by["Lens.org"]["detail"])
        self.assertFalse(by["Espacenet（欧专局）"]["ok"])
        self.assertIn("HTTP 429", by["Espacenet（欧专局）"]["detail"])
        self.assertIn("限流", by["Espacenet（欧专局）"]["detail"])
        self.assertFalse(by["PATENTSCOPE（WIPO）"]["ok"])
        self.assertIn("HTTP 401", by["PATENTSCOPE（WIPO）"]["detail"])
        self.assertFalse(by["国知局官网"]["ok"])
        self.assertIn("HTTP 404", by["国知局官网"]["detail"])
        # 真回了数据的才算通
        self.assertTrue(by["OpenAlex"]["ok"])
        self.assertTrue(by["arXiv"]["ok"])
        self.assertTrue(by["Bing"]["ok"])
        self.assertEqual(by["Bing"]["status"], 200)
        md = pas._md_probe(rows)
        self.assertIn("| Google Patents | 不通 |", md)
        self.assertIn("| GitHub API | 不通 |", md)
        self.assertIn("HTTP 403", md)
        self.assertIn("能用：OpenAlex、arXiv、Bing", md)
        self.assertIn("入口不可用", md)

    def test_github_限流和被拒绝分开说(self):
        self.assertIn("限流", pas._probe_verdict("github", 403, '{"message": "API rate limit exceeded"}')[1])
        ok, detail = pas._probe_verdict("github", 403, '{"message": "path not available"}')
        self.assertFalse(ok)
        self.assertIn("被拒绝", detail)
        self.assertIn("path not available", detail)

    def test_google_探针走真正的检索解析(self):
        self.assertTrue(pas._probe_verdict("google", 200, json.dumps(FIXTURE, ensure_ascii=False))[0])
        for status, body in ((503, "/sorry/"), (200, "<html>captcha</html>"), (429, "")):
            ok, detail = pas._probe_verdict("google", status, body)
            self.assertFalse(ok)
            self.assertIn("拦", detail)
        ok, detail = pas._probe_verdict("google", 200, "<html>login</html>")
        self.assertFalse(ok)
        self.assertIn("不是数据", detail)
        ok, detail = pas._probe_verdict("google", 403, "")
        self.assertFalse(ok)
        self.assertIn("HTTP 403", detail)

    def test_接口通了但回的不是数据也算不通(self):
        self.assertFalse(pas._probe_verdict("openalex", 200, "<html>please login</html>")[0])
        self.assertFalse(pas._probe_verdict("github", 200, "{}")[0])
        self.assertFalse(pas._probe_verdict("arxiv", 200, "<html>blocked</html>")[0])
        self.assertFalse(pas._probe_verdict("html", 200, "   ")[0])
        self.assertTrue(pas._probe_verdict("html", 200, "<html>results</html>")[0])
        self.assertTrue(pas._probe_verdict("epub", 200, "<html>" + "正文" * 200 + "</html>")[0])

    def test_google_探针计入限速(self):
        pacer = CountingPacer()
        pas.probe_all(fetch=FakeFetch({}), pacer=pacer)
        self.assertEqual(pacer.calls, 1)      # 只有 Google 那一条要排队


class CliTest(unittest.TestCase):
    """走 main()：把模块级的 http_get 换成假的，函数内部按名字取，所以能替换。"""

    def setUp(self):
        self._fetch, self._pacer = pas.http_get, pas.Pacer
        pas.Pacer = NoWaitPacer

    def tearDown(self):
        pas.http_get, pas.Pacer = self._fetch, self._pacer

    def _run(self, argv, routes):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        pas.http_get = FakeFetch(routes)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = pas.main(argv)
        return rc, out.getvalue(), err.getvalue()

    @staticmethod
    def _last(text: str) -> str:
        return text.rstrip("\n").splitlines()[-1] if text.strip() else ""

    def test_patents_markdown(self):
        rc, out, err = self._run(["patents", "告警 抑制", "--limit", "2"], {"xhr/query": (200, FIXTURE)})
        self.assertEqual(rc, 0)
        self.assertIn("## 专利检索：告警 抑制", out)
        self.assertIn("**CN107196804B**", out)
        self.assertIn("get 公开号", out)
        self.assertEqual(self._last(out), "OK: items=2 queries=1")
        self.assertEqual(err, "")

    def test_patents_入口不可用退出码2(self):
        rc, out, err = self._run(["patents", "告警"], {})
        self.assertEqual(rc, 2)
        self.assertIn("入口不可用", out)
        self.assertNotIn("OK:", out)
        self.assertTrue(self._last(err).startswith("FAIL: entry_unavailable"), err)
        self.assertIn("items=0", self._last(err))

    def test_patents_被拦就不再发后面的查询式(self):
        rc, out, err = self._run(["patents", "q1", "q2", "q3"], {"xhr/query": (503, "/sorry/")})
        self.assertEqual(rc, 2)
        self.assertEqual(out.count("## 专利检索"), 1)
        self.assertIn("FAIL: entry_unavailable", err)

    def test_patents_json时OK行在stderr(self):
        rc, out, err = self._run(["patents", "告警", "--json"], {"xhr/query": (200, FIXTURE)})
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)[0]["total"], 514)      # stdout 是干净的 JSON
        self.assertEqual(self._last(err), "OK: items=2 queries=1")

    def test_get_写文件(self):
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "D1.md"
            rc, out, err = self._run(["get", "CN107196804B", "--out", str(out_path)],
                                     {"/CN107196804B/zh": (200, PAGE)})
            self.assertEqual(rc, 0)
            self.assertIn("已写入", out)
            self.assertIn("说明书很短", out)          # 假页面说明书不到 500 字，要提醒
            self.assertIn("## 权利要求", out_path.read_text(encoding="utf-8"))
            self.assertTrue(self._last(out).startswith("OK: items=1 pub=CN107196804B"), out)

    def test_get_没这件是入口问题(self):
        rc, out, err = self._run(["get", "US1"], {"/US1/en": (404, "")})
        self.assertEqual(rc, 2)
        self.assertIn("入口不可用", out)
        self.assertIn("FAIL: entry_unavailable", err)
        self.assertIn("没有 US1", err)

    def test_papers_一路挂了另一路照出(self):
        rc, out, err = self._run(["papers", "alert"], {"api.openalex.org": (500, ""), "export.arxiv.org": (200, ARXIV)})
        self.assertEqual(rc, 0)
        self.assertIn("入口不可用：OpenAlex", out)
        self.assertIn("Deduplicating alert streams", out)
        self.assertEqual(self._last(out), "OK: items=1 errors=1")

    def test_papers_两路都挂退出码2(self):
        rc, out, err = self._run(["papers", "alert"], {})
        self.assertEqual(rc, 2)
        self.assertTrue(self._last(err).startswith("FAIL: entry_unavailable items=0 errors=2"), err)

    def test_code_json(self):
        rc, out, err = self._run(["code", "alert", "--json"], {"api.github.com": (200, GITHUB)})
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)[0]["repo"], "acme/alert-dedup")
        self.assertEqual(self._last(err), "OK: items=1")

    def test_code_被代理拦了(self):
        rc, out, err = self._run(["code", "alert"],
                                 {"api.github.com": (403, '{"message": "sessions are bound to their configured repositories"}')})
        self.assertEqual(rc, 2)
        self.assertIn("入口不可用", out)
        self.assertIn("FAIL: entry_unavailable", err)
        self.assertIn("HTTP 403", err)

    def test_probe_cli(self):
        rc, out, err = self._run(["probe"], {"api.github.com": (200, GITHUB), "api.openalex.org": (200, OPENALEX)})
        self.assertEqual(rc, 0)
        self.assertIn("| GitHub API | 通 |", out)
        self.assertIn("| Google Patents | 不通 |", out)
        self.assertEqual(self._last(out), f"OK: reachable=2 total={len(pas.PROBE_ENTRIES)}")
        rc, out, err = self._run(["probe", "--json"], {"api.github.com": (200, GITHUB)})
        self.assertEqual(rc, 0)
        rows = json.loads(out)
        self.assertEqual(sum(1 for r in rows if r["ok"]), 1)
        self.assertEqual(self._last(err), f"OK: reachable=1 total={len(pas.PROBE_ENTRIES)}")

    def test_probe_一个都不通退出码2(self):
        rc, out, err = self._run(["probe"], {})
        self.assertEqual(rc, 2)
        self.assertIn("一个都打不开", out)
        self.assertTrue(self._last(err).startswith("FAIL: entry_unavailable reachable=0"), err)


class TestCnipa入口(unittest.TestCase):
    """cnipa 子命令只做一件事：把参数原样交给 cnipa_search.py，别的路径一概不碰。"""

    def setUp(self):
        sys.path.insert(0, str(HERE))
        import cnipa_search
        self.mod = cnipa_search
        self.real_main = cnipa_search.main
        self.seen = []

        def fake_main(argv=None, **kw):
            self.seen.append(list(argv or []))
            return 0

        cnipa_search.main = fake_main

    def tearDown(self):
        self.mod.main = self.real_main

    def _run(self, argv):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = pas.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_子命令在帮助里(self):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit):
            pas.main(["--help"])
        self.assertIn("cnipa", out.getvalue())

    def test_多个检索词原样传过去(self):
        rc, out, err = self._run(["cnipa", "批任务调度", "资源画像", "异构算力"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.seen, [["批任务调度", "资源画像", "异构算力"]])

    def test_class_和_json_一起传(self):
        rc, out, err = self._run(["cnipa", "批任务调度", "--class", "G06F9,G06Q10", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.seen, [["批任务调度", "--class", "G06F9,G06Q10", "--json"]])

    def test_max_terms(self):
        rc, out, err = self._run(["cnipa", "甲", "--max-terms", "3"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.seen, [["甲", "--max-terms", "3"]])

    def test_退出码原样返回(self):
        self.mod.main = lambda argv=None, **kw: 2
        rc, out, err = self._run(["cnipa", "甲"])
        self.assertEqual(rc, 2)

    def test_不碰_google_限速(self):
        # cnipa 走的是本机浏览器，跟 Google 那套限速没关系，不该动到时间戳
        before = pas.GP_STAMP.exists() and pas.GP_STAMP.stat().st_mtime
        self._run(["cnipa", "甲"])
        after = pas.GP_STAMP.exists() and pas.GP_STAMP.stat().st_mtime
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
