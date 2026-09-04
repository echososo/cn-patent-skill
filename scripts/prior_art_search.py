#!/usr/bin/env python3
"""免 key 的现有技术检索：不用注册、不用配置、不用任何第三方库，能打开哪个入口就用哪个。

用法（Windows 上把 python3 换成 py -3）：
  python3 prior_art_search.py probe                                  # 这台机器能打开哪些检索入口
  python3 prior_art_search.py cnipa 批任务调度 资源画像 异构算力       # 国知局公布公告（中文专利首选）
                              [--class G06F9,G06Q10] [--max-terms 8] [--json]
  python3 prior_art_search.py patents "告警 抑制 滑动窗口" [更多查询式...]
                              [--before 2024-01-01] [--country CN] [--limit 10] [--json]
  python3 prior_art_search.py get CN107196804B [--lang zh|en] [--out 文件.md]   # 一件专利的全文
  python3 prior_art_search.py papers "alert suppression sliding window" [--since 2020-01-01]
  python3 prior_art_search.py code "alert deduplication" [--limit 10]

走的入口（全部免 key）：
  cnipa   → 国知局中国专利公布公告（epub.cnipa.gov.cn），本机浏览器驱动，见 cnipa_search.py
  patents → Google Patents 前端自用的接口（patents.google.com/xhr/query）
  get     → Google Patents 的专利页（摘要、权利要求、说明书正文、PDF 地址）
  papers  → OpenAlex 官方 API + arXiv 官方 API
  code    → GitHub 公开搜索 API（仓库）

两条实测过的脾气：
  · Google Patents 同一出口 IP 两分钟内发 6 次就会被拦（HTTP 503，整个 IP 拦约 20 分钟）。
    本脚本在两次 Google 请求之间强制至少隔 12 秒（跨进程也生效），一次多给几个查询式比多跑几次省。
  · 国内直连网络打不开 Google 系。打不开就明说"入口不可用"，并退出码 2，绝不把"打不开"写成"没查到"。
  · 中文专利先走 cnipa（国知局官方库，国内直连就能用），它另要本机 Chrome/Edge 加 pip3 install playwright。

机读约定（全包统一）：成功时 stdout 最后一行 `OK: 键=值 ...`（--json 时这一行打到 stderr，不污染 JSON）；
失败时 stderr 一行 `FAIL: 原因`，退出码 2 = 入口不可用，1 = 输入或运行错误。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
GP_XHR = "https://patents.google.com/xhr/query"
GP_PAGE = "https://patents.google.com/patent/{pub}/{lang}"
GP_PDF_CDN = "https://patentimages.storage.googleapis.com/"
GP_MIN_INTERVAL = 12.0          # 秒。实测两分钟 6 次即被拦，12 秒 ≈ 每分钟 5 次，留一档余量
GP_BLOCK_MARKERS = ("/sorry/", "unusual traffic", "captcha", "detected unusual")
GP_STAMP = Path(tempfile.gettempdir()) / "patent-writing-pro-google-patents.stamp"

# 探测用的入口。哪些能打开就在检索记录里写哪些；打不开的写"入口不可用"。
# 每条打的都是该入口真正会用到的检索接口，不是首页：首页能开不等于接口能用（代理常常只放行根路径，
# 实测 GitHub 根路径 200 而 search/repositories 403）。末位是校验方式，见 _probe_verdict。
PROBE_ENTRIES = [
    ("Google Patents", "https://patents.google.com/xhr/query?url=q%3Dtest%26num%3D10",
     "全球专利检索与全文，本脚本 patents / get 走这里", "google"),
    ("Espacenet（欧专局）", "https://worldwide.espacenet.com/patent/search?q=test",
     "全球专利著录与 PDF，有中文界面", "html"),
    ("PATENTSCOPE（WIPO）", "https://patentscope.wipo.int/search/en/result.jsf?query=test",
     "PCT 与各国专利", "html"),
    ("Lens.org", "https://www.lens.org/lens/search/patent/list?q=test",
     "专利 + 论文一起查", "html"),
    ("国知局公布公告", "https://epub.cnipa.gov.cn/patent/CN107196804B",
     "中国专利官方库，中文检索首选，本脚本 cnipa 走这里（要本机浏览器）", "epub"),
    ("国知局官网", "https://www.cnipa.gov.cn/col/col64/index.html",
     "专利法、细则、审查指南的官方页面（法律法规栏目）", "html"),
    ("OpenAlex", "https://api.openalex.org/works?search=test&per-page=1",
     "论文，本脚本 papers 走这里", "openalex"),
    ("arXiv", "https://export.arxiv.org/api/query?search_query=all:test&max_results=1",
     "预印本，本脚本 papers 走这里", "arxiv"),
    ("GitHub API", "https://api.github.com/search/repositories?q=test&per_page=1",
     "开源代码，本脚本 code 走这里", "github"),
    ("Bing", "https://www.bing.com/search?q=test",
     "国内可用的网页搜索，兜底查产品文档和博客", "html"),
]


def _ok(stats: dict, to_stderr: bool = False) -> None:
    """成功收尾行。--json 时打到 stderr，stdout 只留 JSON。"""
    line = "OK: " + " ".join(f"{k}={v}" for k, v in stats.items())
    print(line, file=sys.stderr if to_stderr else sys.stdout, flush=True)


def _fail(reason: str) -> None:
    """失败收尾行，永远在 stderr。先把 stdout 冲掉，免得 2>&1 时顺序乱。"""
    try:
        sys.stdout.flush()
    except (OSError, ValueError):
        pass
    print(f"FAIL: {reason}", file=sys.stderr, flush=True)


class EntryUnavailable(Exception):
    """入口打不开、被拦或返回了看不懂的东西。信息要能直接抄进检索记录。"""


# ---------------------------------------------------------------- HTTP

def http_get(url: str, headers: dict | None = None, timeout: float = 20.0) -> tuple[int, str]:
    h = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def _err(e: Exception) -> str:
    """把 urllib 的报错缩成一句人能看的话。"""
    msg = re.sub(r"^<urlopen error (.*)>$", r"\1", str(e).strip())
    return msg[:100]


def _clean(s: str) -> str:
    """去标签、去实体、压空白。"""
    if not s:
        return ""
    import html as _html
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


# ---------------------------------------------------------------- Google Patents：检索

class Pacer:
    """跨进程限速：把上次请求时间写进临时目录的一个小文件。"""

    def __init__(self, stamp: Path = GP_STAMP, interval: float = GP_MIN_INTERVAL,
                 clock=time.time, sleeper=time.sleep):
        self.stamp, self.interval, self.clock, self.sleep = stamp, interval, clock, sleeper

    def wait(self) -> float:
        last = 0.0
        try:
            last = float(self.stamp.read_text().strip() or 0)
        except (OSError, ValueError):
            pass
        gap = self.interval - (self.clock() - last)
        if gap > 0:
            self.sleep(gap)
        try:
            self.stamp.write_text(str(self.clock()))
        except OSError:
            pass
        return max(0.0, gap)


def gp_query_url(q: str, before: str = "", country: str = "", limit: int = 10) -> str:
    """接口把整个查询串塞在 url= 一个参数里；内层保持原样，只在最外层编码一次（真响应验证过的形态）。"""
    def raw(v: str) -> str:
        v = str(v).replace("&", " ").replace("#", " ").replace("%", " ")
        return "+".join(v.split())
    pairs = [("q", raw(q)), ("num", str(max(10, min(int(limit), 100))))]
    if country:
        pairs.append(("country", raw(country)))
    if before:
        pairs.append(("before", "publication:" + before.replace("-", "")))
    qs = "&".join(f"{k}={v}" for k, v in pairs)
    return f"{GP_XHR}?url={urllib.parse.quote(qs, safe='')}"


def gp_parse(status: int, body: str) -> tuple[list[dict], int]:
    low = (body or "")[:4000].lower()
    if status in (429, 503) or any(m in low for m in GP_BLOCK_MARKERS):
        raise EntryUnavailable("Google Patents 把这个出口 IP 当机器人拦了（约 20 分钟内都会被拦）；"
                               "别重试，先用别的入口，等一等再回来")
    if status != 200:
        raise EntryUnavailable(f"Google Patents 返回 HTTP {status}（多半是这台机器打不开 Google）")
    try:
        data = json.loads(body)
    except ValueError:
        raise EntryUnavailable("Google Patents 返回的不是数据，疑似被拦截页替换")
    results = data.get("results") or {}
    hits = []
    for cluster in results.get("cluster") or []:
        for item in cluster.get("result") or []:
            p = item.get("patent") or {}
            if not p:
                continue
            pub = (p.get("publication_number") or "").strip().upper()
            if not pub:
                parts = [x for x in str(item.get("id", "")).split("/") if x]
                pub = parts[1].upper() if len(parts) > 1 and parts[0] == "patent" else ""
            pdf = (p.get("pdf") or "").strip()
            hits.append({
                "pub_no": pub,
                "title": _clean(p.get("title", "")),
                "applicant": _clean(p.get("assignee", "")),
                "inventor": _clean(p.get("inventor", "")),
                "filing_date": p.get("filing_date") or "",
                "pub_date": p.get("publication_date") or p.get("grant_date") or "",
                "priority_date": p.get("priority_date") or "",
                "abstract": _clean(p.get("snippet", "")),
                "pdf_url": (pdf if pdf.startswith("http") else GP_PDF_CDN + pdf.lstrip("/")) if pdf else "",
                "link": f"https://patents.google.com/patent/{pub}/" if pub else "",
            })
    try:
        total = int(results.get("total_num_results"))
    except (TypeError, ValueError):
        total = -1
    return hits, total


def search_patents(q: str, before: str = "", country: str = "", limit: int = 10,
                   fetch=None, pacer: Pacer | None = None) -> dict:
    fetch = fetch or http_get
    (pacer or Pacer()).wait()
    try:
        status, body = fetch(gp_query_url(q, before, country, limit))
    except Exception as e:
        raise EntryUnavailable(f"连不上 Google Patents：{_err(e)}")
    hits, total = gp_parse(status, body)
    return {"query": q, "before": before, "country": country, "total": total, "hits": hits[:limit]}


# ---------------------------------------------------------------- Google Patents：全文

class _PatentPage(HTMLParser):
    """从 patents.google.com 的专利页抠出摘要、权利要求、说明书和著录项。
    页面用 itemprop 标记每一块，靠这个定位，不依赖 class 名。"""

    SECTIONS = {"abstract", "claims", "description"}
    METAS = {"publicationDate", "priorityDate", "filingDate", "assigneeOriginal", "inventor", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections: dict[str, list[str]] = {k: [] for k in self.SECTIONS}
        self.meta: dict[str, list[str]] = {k: [] for k in self.METAS}
        self.pdf_url = ""
        self._stack: list[tuple[str, str | None]] = []   # (tag, 正在采集的 section 名或 None)
        self._meta_target: str | None = None
        self._ignore_depth = 0
        self._tr_depth = 0          # 引用/被引用/相似文献表格里的行也带 itemprop，不能当本件的著录项

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        prop = a.get("itemprop", "")
        if tag == "a" and prop == "pdfLink" and a.get("href"):
            self.pdf_url = a["href"]
        if tag == "meta":
            return
        if tag in ("script", "style"):
            self._ignore_depth += 1
        if tag == "tr":
            self._tr_depth += 1
        cur = self._stack[-1][1] if self._stack else None
        if prop in self.SECTIONS and cur is None:
            cur = prop
        self._stack.append((tag, cur))
        if self._tr_depth:
            return
        if prop in self.METAS and prop != "title":
            self._meta_target = prop
        elif tag == "span" and prop == "title" and not self.meta["title"]:
            self._meta_target = "title"

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._ignore_depth:
            self._ignore_depth -= 1
        if tag == "tr" and self._tr_depth:
            self._tr_depth -= 1
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break
        self._meta_target = None
        if tag in ("div", "p", "li", "section", "h1", "h2", "h3", "br", "claim", "claim-text"):
            cur = self._stack[-1][1] if self._stack else None
            if cur:
                self.sections[cur].append("\n")

    def handle_data(self, data):
        if self._ignore_depth:
            return
        if self._meta_target:
            self.meta[self._meta_target].append(data.strip())
        cur = self._stack[-1][1] if self._stack else None
        if cur:
            self.sections[cur].append(data)

    HEADINGS = re.compile(r"^(abstract|claims?\s*\(\d+\)|claims|description|摘要|权利要求.*|说明书)$", re.I)

    def text(self, key: str) -> str:
        raw = "".join(self.sections[key])
        lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in raw.splitlines()]
        out, blank = [], False
        for ln in lines:
            if ln:
                out.append(ln)
                blank = False
            elif not blank:
                out.append("")
                blank = True
        while out and (not out[0] or self.HEADINGS.match(out[0])):   # 页面自带的 "Abstract" 这类小标题不要
            out.pop(0)
        return "\n".join(out).strip()


def parse_patent_page(body: str, pub: str) -> dict:
    p = _PatentPage()
    p.feed(body)
    # 同一个著录项页面里会出现好几遍（头部、申请事件、优先权列表），去重后再拼
    meta = {k: ("；" if k in ("inventor", "assigneeOriginal") else " / ").join(dict.fromkeys(x for x in v if x))
            for k, v in p.meta.items()}
    title = meta.get("title", "")
    if not title:
        m = re.search(r"<meta\s+name=\"DC.title\"\s+content=\"([^\"]*)\"", body)
        title = _clean(m.group(1)) if m else ""
    abstract, claims, desc = p.text("abstract"), p.text("claims"), p.text("description")
    if not (abstract or claims or desc):
        raise EntryUnavailable(f"打开了 {pub} 的页面但没抠出正文：不是专利页（号码打错？）或页面结构变了")
    return {
        "pub_no": pub, "title": title,
        "applicant": meta.get("assigneeOriginal", ""), "inventor": meta.get("inventor", ""),
        "pub_date": meta.get("publicationDate", ""), "priority_date": meta.get("priorityDate", ""),
        "filing_date": meta.get("filingDate", ""),
        "pdf_url": p.pdf_url, "abstract": abstract, "claims": claims, "description": desc,
    }


def get_patent(pub: str, lang: str = "", fetch=None, pacer: Pacer | None = None) -> dict:
    fetch = fetch or http_get
    pub = pub.strip().upper().replace(" ", "")
    lang = lang or ("zh" if pub.startswith("CN") else "en")
    (pacer or Pacer()).wait()
    url = GP_PAGE.format(pub=pub, lang=lang)
    try:
        status, body = fetch(url)
    except Exception as e:
        raise EntryUnavailable(f"连不上 Google Patents：{_err(e)}")
    low = (body or "")[:4000].lower()
    if status in (429, 503) or any(m in low for m in GP_BLOCK_MARKERS):
        raise EntryUnavailable("Google Patents 把这个出口 IP 当机器人拦了（约 20 分钟内都会被拦）；别重试")
    if status == 404:
        raise EntryUnavailable(f"Google Patents 没有 {pub} 这一件（核对公开号：国别 + 数字 + 种类码，如 CN107196804B）")
    if status != 200:
        raise EntryUnavailable(f"Google Patents 返回 HTTP {status}")
    rec = parse_patent_page(body, pub)
    rec["link"], rec["lang"] = url, lang
    return rec


def patent_markdown(rec: dict) -> str:
    head = [f"# {rec['pub_no']} {rec.get('title', '')}".rstrip(), ""]
    for label, key in (("申请人", "applicant"), ("发明人", "inventor"), ("优先权日", "priority_date"),
                       ("申请日", "filing_date"), ("公开日", "pub_date"), ("页面", "link"), ("PDF", "pdf_url")):
        if rec.get(key):
            head.append(f"- {label}：{rec[key]}")
    body = [
        "", "## 摘要", "", rec.get("abstract") or "（页面里没有摘要）",
        "", "## 权利要求", "", rec.get("claims") or "（页面里没有权利要求）",
        "", "## 说明书", "", rec.get("description") or "（页面里没有说明书正文）",
        "", f"（来源：Google Patents 专利页 `{rec.get('lang', '')}` 语言版；"
            "CN 号的 zh 版是原文，en 版是机器翻译，引用原文时以 zh 版或官方 PDF 为准）",
    ]
    return "\n".join(head + body) + "\n"


# ---------------------------------------------------------------- 论文

def _openalex_abstract(inv: dict | None, max_words: int = 120) -> str:
    if not inv:
        return ""
    slots: dict[int, str] = {}
    for word, positions in inv.items():
        for p in positions:
            slots[p] = word
    return " ".join(slots[i] for i in sorted(slots)[:max_words])


def search_openalex(q: str, since: str = "", limit: int = 10, fetch=None) -> list[dict]:
    fetch = fetch or http_get
    params = {"search": q, "per-page": min(limit, 25)}
    if since:
        params["filter"] = f"from_publication_date:{since}"
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    try:
        status, body = fetch(url)
    except Exception as e:
        raise EntryUnavailable(f"连不上 OpenAlex：{_err(e)}")
    if status != 200:
        raise EntryUnavailable(f"OpenAlex 返回 HTTP {status}")
    try:
        data = json.loads(body)
    except ValueError:
        raise EntryUnavailable("OpenAlex 返回的不是数据")
    out = []
    for w in data.get("results", []):
        out.append({
            "title": w.get("display_name") or "",
            "authors": [a.get("author", {}).get("display_name", "") for a in w.get("authorships", [])][:8],
            "year": w.get("publication_year") or "",
            "link": w.get("doi") or w.get("id", ""),
            "abstract": _openalex_abstract(w.get("abstract_inverted_index")),
            "oa_url": (w.get("open_access") or {}).get("oa_url") or "",
            "source": "OpenAlex",
        })
    return out


def search_arxiv(q: str, limit: int = 10, fetch=None) -> list[dict]:
    fetch = fetch or http_get
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": f"all:{q}", "max_results": min(limit, 20), "sortBy": "relevance"})
    try:
        status, body = fetch(url)
    except Exception as e:
        raise EntryUnavailable(f"连不上 arXiv：{_err(e)}")
    if status != 200:
        raise EntryUnavailable(f"arXiv 返回 HTTP {status}")
    ns = {"a": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise EntryUnavailable("arXiv 返回的不是数据")
    out = []
    for entry in root.findall("a:entry", ns):
        def text(tag):
            el = entry.find(f"a:{tag}", ns)
            return (el.text or "").strip() if el is not None else ""
        pdf = next((l.get("href", "") for l in entry.findall("a:link", ns) if l.get("title") == "pdf"), "")
        out.append({
            "title": " ".join(text("title").split()),
            "authors": [(a.find("a:name", ns).text or "") for a in entry.findall("a:author", ns)][:8],
            "year": text("published")[:4],
            "link": text("id"),
            "abstract": " ".join(text("summary").split())[:600],
            "oa_url": pdf,
            "source": "arXiv",
        })
    return out


# ---------------------------------------------------------------- 代码

def search_code(q: str, limit: int = 10, fetch=None) -> list[dict]:
    fetch = fetch or http_get
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": q, "per_page": min(limit, 20)})
    try:
        status, body = fetch(url, headers={"Accept": "application/vnd.github+json"})
    except Exception as e:
        raise EntryUnavailable(f"连不上 GitHub：{_err(e)}")
    if status in (403, 429):
        if "rate limit" in (body or "").lower():
            raise EntryUnavailable("GitHub 搜索限流（未登录每分钟 10 次），等一分钟再查")
        raise EntryUnavailable(f"GitHub 拒绝了这次请求（HTTP {status}）：{_clean(body)[:100]}")
    if status != 200:
        raise EntryUnavailable(f"GitHub 返回 HTTP {status}")
    try:
        data = json.loads(body)
    except ValueError:
        raise EntryUnavailable("GitHub 返回的不是数据")
    return [{
        "repo": it.get("full_name", ""), "url": it.get("html_url", ""),
        "desc": (it.get("description") or "")[:300],
        "stars": it.get("stargazers_count", 0),
        "created_at": (it.get("created_at") or "")[:10], "pushed_at": (it.get("pushed_at") or "")[:10],
    } for it in data.get("items", [])]


# ---------------------------------------------------------------- 入口探测

def _body_message(body: str) -> str:
    """接口报错时把原因抠出来：JSON 的 message 字段优先（取第一句），否则去标签取前 80 字。"""
    try:
        data = json.loads(body or "")
        if isinstance(data, dict) and data.get("message"):
            return str(data["message"]).split(". ")[0][:120]
    except ValueError:
        pass
    return _clean(body)[:80]


def _status_note(status: int, body: str) -> str:
    """非 2xx 的一句话说明。状态码一定带上，抄进检索记录时能看出是被谁拦的。"""
    if status in (401, 403):
        if "rate limit" in (body or "").lower():
            return f"HTTP {status}，限流"
        msg = _body_message(body)
        return f"HTTP {status}，被拒绝（鉴权、代理或反爬拦截）" + (f"：{msg}" if msg else "")
    if status == 429:
        return "HTTP 429，限流"
    if status == 404:
        return "HTTP 404，路径不存在（接口可能改了）"
    if status >= 500:
        return f"HTTP {status}，服务端出错"
    return f"HTTP {status}"


def _probe_verdict(kind: str, status: int, body: str) -> tuple[bool, str]:
    """把一次探测响应判成 (通, 说明)。

    只有 2xx 且回的是该入口该有的东西才算通；4xx（401/403/429 这些）一律不通——
    "有服务器在应答"不等于"能用"，探针假阳性比假阴性害人：会让人以为查过了。
    """
    if kind == "google" and (200 <= status < 300 or status in (429, 503)):
        # 走真正的检索解析：被拦（429/503/验证码页）、回的不是 JSON 都会被它识别出来
        try:
            gp_parse(status, body)
        except EntryUnavailable as e:
            return False, f"HTTP {status}，{str(e)[:60]}"
        return True, f"HTTP {status}，检索接口有数据"
    if not 200 <= status < 300:
        return False, _status_note(status, body)
    if kind == "epub":
        if len(body or "") < 200:
            return False, "打开了但只回了一个空壳（这个站要浏览器跑脚本才出内容），用 cnipa 子命令查"
        return True, f"HTTP {status}"
    if kind in ("openalex", "github"):
        want = "results" if kind == "openalex" else "items"
        try:
            data = json.loads(body or "")
        except ValueError:
            data = None
        if isinstance(data, dict) and want in data:
            return True, f"HTTP {status}，接口有数据"
        return False, f"HTTP {status}，回的不是数据（疑似拦截页）"
    if kind == "arxiv":
        if "<feed" in (body or ""):
            return True, f"HTTP {status}，接口有数据"
        return False, f"HTTP {status}，回的不是数据（疑似拦截页）"
    if not (body or "").strip():
        return False, f"HTTP {status}，但回了空页"
    return True, f"HTTP {status}"


def probe_one(name: str, url: str, note: str, kind: str = "html", fetch=None,
              pacer: Pacer | None = None) -> dict:
    fetch = fetch or http_get
    row = {"name": name, "url": url, "note": note, "ok": False, "status": None, "ms": 0, "detail": ""}
    if kind == "google":
        (pacer or Pacer()).wait()      # 探针也是一次真请求，得计入 Google 的限速
    start = time.monotonic()
    try:
        status, body = fetch(url, timeout=8.0)
    except Exception as e:
        row["ms"] = round((time.monotonic() - start) * 1000)
        row["detail"] = _err(e)
        return row
    row["ms"] = round((time.monotonic() - start) * 1000)
    row["status"] = status
    row["ok"], row["detail"] = _probe_verdict(kind, status, body)
    return row


def probe_all(fetch=None, entries=PROBE_ENTRIES, pacer: Pacer | None = None) -> list[dict]:
    with ThreadPoolExecutor(max_workers=len(entries)) as ex:
        return list(ex.map(lambda e: probe_one(*e, fetch=fetch, pacer=pacer), entries))


# ---------------------------------------------------------------- 输出

def _md_patents(res: dict) -> str:
    total = res["total"]
    lines = [f"## 专利检索：{res['query']}",
             f"（Google Patents，命中约 {total if total >= 0 else '未知'} 条，取前 {len(res['hits'])} 条"
             + (f"，公开日早于 {res['before']}" if res["before"] else "")
             + (f"，国别 {res['country']}" if res["country"] else "") + "）", ""]
    if not res["hits"]:
        lines.append("没有命中。这只说明这个查询式在 Google Patents 上没结果，不等于没有现有技术——换语义块再查。")
    for i, h in enumerate(res["hits"], 1):
        lines.append(f"{i}. **{h['pub_no']}** {h['title']}")
        meta = "；".join(x for x in (
            f"申请人：{h['applicant']}" if h["applicant"] else "",
            f"优先权日 {h['priority_date']}" if h["priority_date"] else "",
            f"公开日 {h['pub_date']}" if h["pub_date"] else "") if x)
        if meta:
            lines.append(f"   {meta}")
        if h["abstract"]:
            lines.append(f"   摘要：{h['abstract'][:300]}{'…' if len(h['abstract']) > 300 else ''}")
        lines.append(f"   页面：{h['link']}" + (f"　PDF：{h['pdf_url']}" if h["pdf_url"] else ""))
    lines.append("")
    lines.append("摘要只够决定要不要读全文；下新颖性/创造性结论前用 `get 公开号` 拿正文。")
    return "\n".join(lines)


def _md_papers(q: str, items: list[dict], errors: list[str]) -> str:
    lines = [f"## 论文检索：{q}", ""]
    for e in errors:
        lines.append(f"- 入口不可用：{e}")
    for i, p in enumerate(items, 1):
        who = "、".join(a for a in p["authors"][:3] if a) + ("等" if len(p["authors"]) > 3 else "")
        lines.append(f"{i}. **{p['title']}**（{p['source']}，{p['year']}）{who}")
        if p["abstract"]:
            lines.append(f"   {p['abstract'][:300]}{'…' if len(p['abstract']) > 300 else ''}")
        lines.append(f"   {p['link']}" + (f"　全文：{p['oa_url']}" if p["oa_url"] else ""))
    if not items and not errors:
        lines.append("没有命中。")
    return "\n".join(lines)


def _md_code(q: str, items: list[dict]) -> str:
    lines = [f"## 开源代码检索：{q}（GitHub 仓库）", ""]
    for i, r in enumerate(items, 1):
        lines.append(f"{i}. **{r['repo']}** ★{r['stars']}　建于 {r['created_at']}，最近推送 {r['pushed_at']}")
        if r["desc"]:
            lines.append(f"   {r['desc']}")
        lines.append(f"   {r['url']}")
    if not items:
        lines.append("没有命中。")
    lines.append("")
    lines.append("仓库的创建日期不等于某个特征的公开日；要拿它当现有技术，得进仓库看那段代码是哪个提交、哪一天进去的。")
    return "\n".join(lines)


def _md_probe(rows: list[dict]) -> str:
    lines = ["## 检索入口探测（这台机器、此刻）", "", "| 入口 | 能打开 | 用途 | 说明 |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['name']} | {'通' if r['ok'] else '不通'} | {r['note']} | {r['detail']}，{r['ms']}ms |")
    ok = [r["name"] for r in rows if r["ok"]]
    bad = [r["name"] for r in rows if not r["ok"]]
    lines += ["", f"能用：{('、'.join(ok)) or '一个都打不开（先确认本机能上网）'}",
              f"不能用：{('、'.join(bad)) or '无'}",
              "", "把这张表的日期和结果抄进检索记录的「入口」一栏；打不开的入口写「入口不可用」，不写「未检索到」。"]
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI

def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("probe", help="看这台机器能打开哪些检索入口")
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("cnipa", help="国知局公布公告检索（中文专利首选；要本机 Chrome/Edge + playwright）")
    sp.add_argument("term", nargs="+", help="2-8 个检索词，空格分开；别把一整句长中文当一个词")
    sp.add_argument("--class", "--ipc", dest="klass", default="",
                    help="第二轮收口用的分类号，如 G06F9,G06Q10（最多 3 个）")
    sp.add_argument("--max-terms", type=int, default=None, help="检索词上限，默认 8（带 --class 时 3）")
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("patents", help="Google Patents 检索")
    sp.add_argument("query", nargs="+", help="一个或多个查询式（多个之间会自动间隔 12 秒）")
    sp.add_argument("--before", default="", help="只要公开日早于这天的，如 2024-01-01")
    sp.add_argument("--country", default="", help="限国别，如 CN 或 CN,US")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("get", help="拿一件专利的全文")
    sp.add_argument("pub", help="公开号，如 CN107196804B / US11080336B2")
    sp.add_argument("--lang", default="", help="zh 原文 / en 英文（CN 号默认 zh，其他默认 en）")
    sp.add_argument("--out", default="", help="写到这个 Markdown 文件；不给就打印到屏幕")
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("papers", help="论文检索（OpenAlex + arXiv）")
    sp.add_argument("query")
    sp.add_argument("--since", default="", help="只要这天之后发表的（OpenAlex），如 2020-01-01")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("code", help="GitHub 仓库检索")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)
    rc = 0
    try:
        if args.cmd == "probe":
            rows = probe_all()
            print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else _md_probe(rows))
            reachable = sum(1 for r in rows if r["ok"])
            if not reachable:
                _fail(f"entry_unavailable reachable=0 total={len(rows)} 一个入口都打不开（先确认本机能上网）")
                return 2
            _ok({"reachable": reachable, "total": len(rows)}, to_stderr=args.json)
            return 0

        if args.cmd == "cnipa":
            # 单独一个脚本：它要 playwright 和本机浏览器，本文件其余部分只用标准库，所以用到才导入
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            try:
                import cnipa_search
            except ImportError as e:
                _fail(f"entry_unavailable 载入 cnipa_search.py 失败：{e}")
                return 2
            sub_argv = list(args.term)
            if args.klass:
                sub_argv += ["--class", args.klass]
            if args.max_terms is not None:
                sub_argv += ["--max-terms", str(args.max_terms)]
            if args.json:
                sub_argv.append("--json")
            return cnipa_search.main(sub_argv)

        if args.cmd == "patents":
            out, first_err = [], ""
            for q in args.query:
                try:
                    res = search_patents(q, args.before, args.country, args.limit)
                    out.append(res)
                    if not args.json:
                        print(_md_patents(res), "\n")
                except EntryUnavailable as e:
                    rc = 2
                    first_err = first_err or str(e)
                    out.append({"query": q, "error": str(e)})
                    if not args.json:
                        print(f"## 专利检索：{q}\n\n入口不可用：{e}\n")
                    if "拦" in str(e):
                        break      # 已经被拦，后面的查询式只会把封禁时间续上
            if args.json:
                print(json.dumps(out, ensure_ascii=False, indent=2))
            items = sum(len(r.get("hits") or []) for r in out)
            if rc:
                _fail(f"entry_unavailable items={items} queries={len(out)} {first_err}")
            else:
                _ok({"items": items, "queries": len(out)}, to_stderr=args.json)
            return rc

        if args.cmd == "get":
            rec = get_patent(args.pub, args.lang)
            if args.json:
                print(json.dumps(rec, ensure_ascii=False, indent=2))
            elif args.out:
                Path(args.out).write_text(patent_markdown(rec), encoding="utf-8")
                n = len(rec["description"])
                print(f"已写入 {args.out}：{rec['pub_no']} {rec['title']}\n"
                      f"摘要 {len(rec['abstract'])} 字，权利要求 {len(rec['claims'])} 字，说明书 {n} 字"
                      + ("" if n > 500 else "（说明书很短，页面可能没给全文，改用 PDF 核对）"))
            else:
                print(patent_markdown(rec))
            _ok({"items": 1, "pub": rec["pub_no"], "description_chars": len(rec["description"])},
                to_stderr=args.json)
            return 0

        if args.cmd == "papers":
            items, errors = [], []
            for fn in (lambda: search_openalex(args.query, args.since, args.limit),
                       lambda: search_arxiv(args.query, args.limit)):
                try:
                    items += fn()
                except EntryUnavailable as e:
                    errors.append(str(e))
            if args.json:
                print(json.dumps({"query": args.query, "items": items, "errors": errors},
                                 ensure_ascii=False, indent=2))
            else:
                print(_md_papers(args.query, items, errors))
            if errors and not items:
                # 两路都挂、或一路挂另一路空手，都当入口不可用；两路都正常只是没命中，那是查询式的事
                _fail(f"entry_unavailable items=0 errors={len(errors)} {'；'.join(errors)}")
                return 2
            _ok({"items": len(items), "errors": len(errors)}, to_stderr=args.json)
            return 0

        if args.cmd == "code":
            items = search_code(args.query, args.limit)
            print(json.dumps(items, ensure_ascii=False, indent=2) if args.json else _md_code(args.query, items))
            _ok({"items": len(items)}, to_stderr=args.json)
            return 0
    except EntryUnavailable as e:
        print(f"入口不可用：{e}")
        _fail(f"entry_unavailable {e}")
        return 2
    except BrokenPipeError:
        # 输出被 head 之类截断了，不算错，也别打一屏 Traceback
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return 0
    except Exception as e:   # 没料到的错：Traceback 照打（方便报 bug），末尾仍给一行机读的 FAIL
        import traceback
        traceback.print_exc()
        _fail(f"runtime_error {type(e).__name__}: {str(e)[:120]}")
        return 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
