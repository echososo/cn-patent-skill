#!/usr/bin/env python3
# Copyright (c) 2026 handsomestWei — MIT License
# 改编自 handsomestWei/patent-disclosure-skill（MIT）的 tools/crawl/cnipa_epub_search.py、
# cnipa_epub_parse.py、cnipa_epub_crawler.py 和 tools/patent_type.py。改动：四个文件并成这一个；
# 去掉 pyyaml 和上游包内的 stdio_utf8 依赖（类型映射直接写成本文件里的 python 字典）；只做发明，
# --type 默认 invention；**开浏览器之前先判断这台机器到底能不能到这个站**，把「网络到不了」和
# 「站开了但没等到检索框」分成两种 FAIL 文案（上游把前者也报成「可增大 WAF 等待时间」，会把人
# 带到调等待时间上去）；解析改成先认新版卡片布局再退回表格；退出码和 OK:/FAIL: 行改成本包统一
# 机读约定；结果页 HTML 仍然只在内存里处理、不落盘。
"""国知局「中国专利公布公告」检索（epub.cnipa.gov.cn）：中文专利检索的首选入口。

要本机装了 Chrome 或 Edge，加 `pip3 install playwright`。这个站要在浏览器里跑一段脚本才放出
检索框，纯 HTTP 抓不到，所以只能走浏览器。本脚本**绝不**自动装任何东西。

用法（Windows 上把 python3 换成 py -3）：
  python3 cnipa_search.py 批任务调度 资源画像 异构算力          # 第一轮：关键词召回
  python3 cnipa_search.py --class G06F9,G06Q10 批任务调度       # 第二轮：带分类号收口
  python3 cnipa_search.py 批任务调度 --json                     # stdout 只有 JSON

检索词怎么给：拆成 2～8 个有检索意义的语义块（专业术语、名词短语、名动组合），空格分开。
一次进程里同一个浏览器把这些词逐个查一遍，再按公开号去重合并。**别把一整句没有空格的长中文
当唯一参数**——公布站会当整句 AND，极易 0 条；真这么给了，脚本会在 stderr 里提醒一句再照查。

机读约定（全包统一）：
  成功  stdout 先一行 `EPUB_HITS_JSON: [...]`（给 agent 解析），最后一行
        `OK: hits=N terms=M type=invention [class=...]`；加 --json 时 stdout 只有 JSON 数组，
        OK 行改到 stderr。stderr 另有 `BROWSER:` / `EPUB_MERGE:` / `EPUB_CLASS_HINT:` /
        `EPUB_NOTE:` 等 ASCII 标记行。**stderr 有东西不等于失败**，看退出码。
  失败  stderr 一行 `FAIL: 原因`。退出码 2 = 浏览器不可用或站点打不开，1 = 输入或解析错误。

**0 条命中不是失败**（退出码 0、`OK: hits=0`）。入口打不开才是失败，那时按检索规范写「入口不可用」，
不许写成「未检索到」。

环境变量：
  EPUB_WAF_MAX_WAIT_SEC   等检索框出现的最长秒数，默认 180
  PLAYWRIGHT_HEADED=1     有界面启动，站点挡住时人工过一次
  CNIPA_SKIP_PRECHECK=1   跳过开浏览器前的可达性判断（这台机器只有浏览器能出网时用）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from browser import BrowserUnavailable, headed, launch_chromium  # noqa: E402

EPUB_BASE = "http://epub.cnipa.gov.cn/"
EPUB_ADVANCED = EPUB_BASE.rstrip("/") + "/Advanced"
EPUB_TITLE_RESULT = "专利查询结果展示"
EPUB_TITLE_NO_HIT = "无查询结果"

MAX_TERMS = 8
MAX_TERMS_WITH_CLASS = 3
MAX_CLASS_CODES = 3

# ---------------------------------------------------------------- 专利类型

TYPE_INVENTION = "invention"
TYPE_UTILITY_MODEL = "utility_model"
TYPE_DESIGN = "design"
TYPE_ALL = "all"
CANONICAL_TYPES = (TYPE_INVENTION, TYPE_UTILITY_MODEL, TYPE_DESIGN, TYPE_ALL)

# 本包只做发明。下面几种映射留着是为了别人拿去改，不在文档里宣传。
TYPE_ALIASES = {
    "发明": TYPE_INVENTION, "发明专利": TYPE_INVENTION, "invention": TYPE_INVENTION,
    "实用新型": TYPE_UTILITY_MODEL, "实用": TYPE_UTILITY_MODEL,
    "utility_model": TYPE_UTILITY_MODEL, "utility-model": TYPE_UTILITY_MODEL, "um": TYPE_UTILITY_MODEL,
    "外观": TYPE_DESIGN, "外观设计": TYPE_DESIGN, "design": TYPE_DESIGN,
    "全部": TYPE_ALL, "all": TYPE_ALL,
}

# 公布站首页的四个勾选框：发明公布 / 发明授权 / 实用新型 / 外观设计
EPUB_TYPE_CHECKBOXES = {
    TYPE_INVENTION: {"fmgb": True, "fmsq": True, "xxsq": False, "wgsq": False},
    TYPE_UTILITY_MODEL: {"fmgb": False, "fmsq": False, "xxsq": True, "wgsq": False},
    TYPE_DESIGN: {"fmgb": False, "fmsq": False, "xxsq": False, "wgsq": True},
    TYPE_ALL: {"fmgb": True, "fmsq": True, "xxsq": True, "wgsq": True},
}
# 高级查询页的勾选框 id 和首页不一样
EPUB_ADVANCED_CHECKBOX = {"fmgb": "isFmgb", "fmsq": "isFmsq", "xxsq": "isXx", "wgsq": "isWg"}


class BadInput(ValueError):
    """命令行参数不对。调用方据此退出码 1。"""


class SiteUnreachable(RuntimeError):
    """这台机器到不了 epub.cnipa.gov.cn：断网、代理没放行、站点本身挂了。退出码 2。"""


class SearchGateTimeout(RuntimeError):
    """站点打开了，但一直没等到检索框（前面挡着一道脚本校验）。退出码 2，和上面不是一回事。"""


def normalize_patent_type(raw: str | None, default: str = TYPE_INVENTION) -> str:
    if raw is None or not str(raw).strip():
        return default
    s = str(raw).strip()
    if s in TYPE_ALIASES:
        return TYPE_ALIASES[s]
    key = s.lower().replace(" ", "_").replace("-", "_")
    if key in TYPE_ALIASES:
        return TYPE_ALIASES[key]
    if key in CANONICAL_TYPES:
        return key
    raise BadInput(f"不认识的专利类型 {raw!r}，可用：{'、'.join(CANONICAL_TYPES)}")


def epub_checkbox_states(patent_type: str) -> dict[str, bool]:
    return dict(EPUB_TYPE_CHECKBOXES[normalize_patent_type(patent_type)])


# ---------------------------------------------------------------- 检索词

# 单独拿去检索没意义的泛词，拆词时别把它们当成一个检索单位
GENERIC_TERMS = {
    "系统", "方法", "装置", "设备", "平台", "模块", "智能", "数据", "信息",
    "处理", "管理", "技术", "服务", "应用", "控制", "优化",
}
_CJK = re.compile(r"[一-鿿]")
# 一个参数里塞了这么多汉字还不带空格，多半是把一整句话丢进来了
LONG_TERM_CJK_CHARS = 8


def split_terms(raw_args: list[str]) -> list[str]:
    """按空白拆成检索词，去重保序。脚本不做中文分词，拆词是调用方的事。"""
    terms: list[str] = []
    for a in raw_args or []:
        for part in (a or "").split():
            p = part.strip()
            if p and p not in terms:
                terms.append(p)
    return terms


def cjk_chars(term: str) -> int:
    return len(_CJK.findall(term or ""))


def term_warnings(terms: list[str]) -> list[str]:
    """检索词写法上的提醒。只提醒、不拦，返回给调用方打到 stderr。"""
    warns: list[str] = []
    long_terms = [t for t in terms if cjk_chars(t) >= LONG_TERM_CJK_CHARS]
    if long_terms:
        warns.append(
            "long_term chars=%d 这个词太长了：%s；公布站会当整句 AND，"
            "拆成 2-8 个语义块（专业术语、名词短语、名动组合）再查"
            % (cjk_chars(long_terms[0]), "、".join(long_terms[:3]))
        )
    generic = [t for t in terms if t in GENERIC_TERMS]
    if generic:
        warns.append("generic_term %s 是泛词，单独当检索词几乎筛不掉东西" % "、".join(generic))
    if len(terms) == 1 and cjk_chars(terms[0]) >= LONG_TERM_CJK_CHARS:
        warns.append("single_term 只有一个词，第一轮召回建议给 2-8 个")
    return warns


# ---------------------------------------------------------------- 解析

_IPC_RE = re.compile(r"\b([A-HY]\d{2}[A-Z]\s*\d{1,4}\s*/\s*\d{2,})\b", re.I)
_LOC_RE = re.compile(r"\b(\d{2}-\d{2})\b")
_APPLICATION_NUMBER_RE = re.compile(r"(?<!\d)(?:CN\s*)?(\d{12}(?:\.[0-9Xx]|[0-9Xx]))(?!\d)", re.I)


@dataclass
class EpubHit:
    """一条命中。字段随页面结构尽力解析，解析不到就是空。"""

    title: str | None = None
    pub_number: str | None = None
    application_number: str | None = None
    applicant: str | None = None
    inventors: list[str] | None = None
    filing_date: str | None = None
    publication_date: str | None = None
    link: str | None = None
    abstract: str | None = None
    ipc_codes: list[str] = field(default_factory=list)
    loc_codes: list[str] = field(default_factory=list)


def _plain(html_snippet: str) -> str:
    """一小段 HTML 抠成可读纯文本。"""
    t = re.sub(r"<script[^>]*>.*?</script>", " ", html_snippet or "", flags=re.I | re.S)
    t = re.sub(r"<style[^>]*>.*?</style>", " ", t, flags=re.I | re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"\s*全部\s*$", "", t).strip()


def _norm_ipc(code: str) -> str:
    return re.sub(r"\s+", "", code or "").upper()


def ipc_prefix(code: str) -> str:
    """第二轮收口用的分类号：G06F9/48 → G06F9（左前缀匹配）。"""
    compact = _norm_ipc(code)
    m = re.match(r"^([A-HY]\d{2}[A-Z]\d+)", compact, re.I)
    return (m.group(1) if m else compact).upper()


def extract_class_codes(html: str) -> tuple[list[str], list[str]]:
    """从一条命中的 HTML 里抠「分类号」栏的 IPC 和洛迦诺号。

    只截「分类号：」往后那一段、在「专利代理」之前停，免得把摘要里的数字当成分类号。
    """
    m = re.search(r"分类号\s*[：:]", html or "", flags=re.I)
    if not m:
        return [], []
    chunk = _plain(re.split(r"专利代理", (html or "")[m.start(): m.start() + 2500], maxsplit=1)[0])
    ipc: list[str] = []
    for g in _IPC_RE.finditer(chunk):
        code = _norm_ipc(g.group(1))
        if code not in ipc:
            ipc.append(code)
    loc: list[str] = []
    for g in _LOC_RE.finditer(chunk):
        if g.group(1) not in loc:
            loc.append(g.group(1))
    return ipc[:12], loc[:8]


def suggest_class_codes(hits: list[EpubHit], patent_type: str = TYPE_INVENTION,
                        limit: int = 3) -> tuple[str, list[str]]:
    """从第一轮命中里挑 1～3 个分类号，给第二轮 --class 用。发明取 IPC 前缀，外观取洛迦诺号。"""
    from collections import Counter

    kind = "loc" if normalize_patent_type(patent_type) == TYPE_DESIGN else "ipc"
    bag: list[str] = []
    for h in hits:
        if kind == "loc":
            bag.extend(h.loc_codes or [])
        else:
            bag.extend(ipc_prefix(c) for c in (h.ipc_codes or []) if c)
    if not bag:      # 一种都没有就换另一种试试，别白丢
        other = "ipc" if kind == "loc" else "loc"
        for h in hits:
            if other == "ipc":
                bag.extend(ipc_prefix(c) for c in (h.ipc_codes or []) if c)
            else:
                bag.extend(h.loc_codes or [])
        if bag:
            kind = other
    return kind, [c for c, _n in Counter(bag).most_common(limit)]


def normalize_application_number(value: str | None) -> str | None:
    if not value:
        return None
    m = _APPLICATION_NUMBER_RE.search(value.strip())
    if not m:
        return None
    number = m.group(1).upper()
    return number if "." in number else f"{number[:-1]}.{number[-1]}"


def _labeled_value(item_html: str, *labels: str) -> str | None:
    """取卡片里 <dt>标签：</dt><dd>值</dd> 的值。"""
    alts = "|".join(re.escape(x) for x in labels)
    m = re.search(rf"<dt[^>]*>\s*(?:{alts})\s*[：:]?\s*</dt>\s*<dd[^>]*>(.*?)</dd>",
                  item_html, flags=re.I | re.S)
    return (_plain(m.group(1)) or None) if m else None


def _split_people(value: str | None) -> list[str] | None:
    if not value:
        return None
    names = [re.sub(r"^全部\s*", "", p.strip()) for p in re.split(r"[;；,，、]", value) if p.strip()]
    return names or None


def _abs_url(href: str) -> str:
    if not href or href.lower().startswith(("javascript:", "#")):
        return ""
    if href.startswith(("http://", "https://")):
        return href
    return EPUB_BASE.rstrip("/") + "/" + href.lstrip("/")


def parse_result_html(html: str) -> list[EpubHit]:
    """解析检索结果页。先认新版卡片布局（有摘要的那种），认不出再退回表格行和裸链接。"""
    return _parse_cards(html) or _parse_rows(html) or _parse_links(html)


def _parse_cards(html: str) -> list[EpubHit]:
    """新版「公布模式」结果页：一条一个 div.item，题名在 h1.title，详情地址在二维码的 title 上。"""
    low = (html or "").lower()
    if "overview-default" not in low and 'class="item"' not in low:
        return []
    parts = re.split(r'(<div\s+class="item"\s*>)', html, flags=re.I)
    blocks = [parts[j] + parts[j + 1] for j in range(1, len(parts) - 1, 2)]
    if not blocks:
        return []

    hits: list[EpubHit] = []
    for item in blocks:
        tm = re.search(r'<h1[^>]*class="[^"]*\btitle\b[^"]*"[^>]*>\s*([^<]+?)\s*</h1>',
                       item, flags=re.I | re.S)
        title = re.sub(r"\s+", " ", tm.group(1)).strip() if tm else None
        lm = re.search(r'title="(https?://epub\.cnipa\.gov\.cn/patent/[^"]+)"', item, flags=re.I)
        link = lm.group(1).strip() if lm else None
        pm = re.search(r"(?:申请公布号|授权公告号)[：:]\s*</dt>\s*<dd[^>]*>([^<]+?)</dd>",
                       item, flags=re.I)
        pub_number = None
        if pm:
            cand = pm.group(1).strip().replace(" ", "")
            pub_number = cand if re.match(r"^(?:CN|ZL)", cand, re.I) else None
        if not link and pub_number:
            link = f"{EPUB_BASE.rstrip('/')}/patent/{pub_number}"
        if link and not pub_number:
            m_pub = re.search(r"/patent/((?:CN|ZL)[^/?#]+)", link, flags=re.I)
            if m_pub:
                pub_number = m_pub.group(1).strip()
        am = re.search(r"<dt[^>]*>\s*摘要\s*[：:]\s*</dt>\s*<dd[^>]*>(.*?)</dd>",
                       item, flags=re.I | re.S)
        abstract = None
        if am:
            plain = _plain(am.group(1))
            abstract = plain if len(plain) >= 4 else None
        if not title and not pub_number and not link:
            continue
        ipc, loc = extract_class_codes(item)
        hits.append(EpubHit(
            title=title,
            pub_number=pub_number,
            application_number=normalize_application_number(_labeled_value(item, "申请号")),
            applicant=_labeled_value(item, "申请人", "专利权人", "申请（专利权）人"),
            inventors=_split_people(_labeled_value(item, "发明人", "设计人")),
            filing_date=_labeled_value(item, "申请日"),
            publication_date=_labeled_value(item, "申请公布日", "授权公告日", "公开（公告）日"),
            link=link,
            abstract=abstract,
            ipc_codes=ipc,
            loc_codes=loc,
        ))
    return dedupe_hits([hits])


def _parse_rows(html: str) -> list[EpubHit]:
    """老版表格行结果页。"""
    hits: list[EpubHit] = []
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html or "", flags=re.I | re.S):
        row = m.group(1)
        low = row.lower()
        if "indexquery" in low or "searchstr" in low:
            continue
        cell_html = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.I | re.S)
        cells = [_plain(c) for c in cell_html]
        idx = next((i for i, c in enumerate(cells) if normalize_application_number(c)), None)
        application_number = normalize_application_number(cells[idx]) if idx is not None else None
        applicant = cells[idx + 1] if idx is not None and idx + 1 < len(cells) else None
        title = cells[idx + 2] if idx is not None and idx + 2 < len(cells) else None
        if not title:
            tm = re.search(r'title="([^"]+)"', row, re.I)
            title = tm.group(1).strip() if tm else None
        scope = cell_html[idx] if idx is not None and idx < len(cell_html) else row
        lm = re.search(r'href="([^"]+)"', scope, re.I)
        link = _abs_url(lm.group(1).strip()) if lm else ""
        pm = re.search(r"(CN\s*\d{9,}[A-Z]\s*|ZL\s*\d{9,}\.\d+)", row, re.I)
        pub_number = pm.group(1).replace(" ", "") if pm else None
        if not application_number and not pub_number:
            continue
        ipc, loc = extract_class_codes(row)
        text = _plain(row)
        hits.append(EpubHit(
            title=title or (text[:200] or None), pub_number=pub_number,
            application_number=application_number, applicant=applicant or None,
            link=link or None, ipc_codes=ipc, loc_codes=loc,
        ))
    return dedupe_hits([hits])


def _parse_links(html: str) -> list[EpubHit]:
    """兜底：页面结构全认不出时，捞指向专利详情的链接。"""
    hits: list[EpubHit] = []
    for m in re.finditer(r'<a\s+[^>]*href="([^"]+)"[^>]*>([^<]*)</a>', html or "", flags=re.I | re.S):
        href, title = (m.group(1) or "").strip(), (m.group(2) or "").strip()
        if not href.startswith("/") and "epub.cnipa.gov.cn" not in href:
            continue
        low = href.lower()
        if not any(x in low for x in ("/dxb/", "/sw/", "/patent/", "detail", "show")):
            continue
        if "javascript:" in low or ("article" in low and "indexquery" in low):
            continue
        pm = re.search(r"(CN\s*\d{9,}[A-Z]?|ZL\s*\d{9,}\.\d+)", href + title, re.I)
        pub_number = pm.group(1).replace(" ", "") if pm else None
        if len(title) < 2 and not pub_number:
            continue
        hits.append(EpubHit(title=title or None, pub_number=pub_number, link=_abs_url(href) or None))
    return dedupe_hits([hits])


def hit_key(h: EpubHit) -> str:
    """去重用的键：公开号最准，没有就退到链接、标题。"""
    return (h.pub_number or h.link or (h.title or "")[:120] or "").strip()


def dedupe_hits(hit_lists: list[list[EpubHit]]) -> list[EpubHit]:
    """多个词各查一次的结果按公开号合并去重，保留先出现的那条。"""
    seen: set[str] = set()
    out: list[EpubHit] = []
    for hits in hit_lists:
        for h in hits:
            key = hit_key(h)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(h)
    return out


def hits_to_json(hits: list[EpubHit]) -> list[dict]:
    rows = []
    for h in hits:
        d = asdict(h)
        d["ipc_codes"] = list(h.ipc_codes or [])
        d["loc_codes"] = list(h.loc_codes or [])
        rows.append(d)
    return rows


# ---------------------------------------------------------------- 站点可达性

# 代理或出网白名单挡住时的特征。命中这些就是「到不了这个站」，和站点自己的反爬不是一回事。
_PROXY_BLOCK_MARKERS = (
    "host_not_allowed", "not in allowlist", "allowlist", "egress",
    "tunnel connection failed", "proxy", "forbidden by",
)


def _looks_like_proxy_block(text: str) -> bool:
    low = (text or "").lower()
    return any(x in low for x in _PROXY_BLOCK_MARKERS)


def check_site_reachable(url: str = EPUB_BASE, timeout: float = 8.0,
                         opener: Callable[..., Any] | None = None) -> tuple[bool, str]:
    """开浏览器之前先花几秒判断这台机器能不能到这个站。返回 (能到, 说明)。

    判得保守：连不上、被代理挡住才算到不了；站点自己回了别的状态码一律放行，
    因为公布站对非浏览器请求本来就可能回怪东西，那要交给浏览器去试，不能在这里下结论。
    """
    if os.environ.get("CNIPA_SKIP_PRECHECK", "").strip().lower() in ("1", "true", "yes"):
        return True, "跳过（CNIPA_SKIP_PRECHECK=1）"
    req = urllib.request.Request(url, method="GET", headers={
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    fetch = opener or urllib.request.urlopen
    try:
        with fetch(req, timeout=timeout) as resp:
            return True, f"HTTP {getattr(resp, 'status', '?')}"
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read(400).decode("utf-8", errors="replace")
        except Exception:
            pass
        deny = ""
        try:
            deny = e.headers.get("x-deny-reason") or ""
        except Exception:
            pass
        if e.code == 407 or deny or _looks_like_proxy_block(body):
            why = deny or _plain(body)[:120] or f"HTTP {e.code}"
            return False, f"被网络策略挡住（HTTP {e.code}，{why}）"
        return True, f"HTTP {e.code}（站点应答了，交给浏览器试）"
    except urllib.error.URLError as e:
        why = str(getattr(e, "reason", "") or e)
        if _looks_like_proxy_block(why):
            return False, f"被网络策略挡住（{why[:120]}）"
        return False, f"连不上（{why[:120]}）"
    except Exception as e:      # socket.timeout 之类
        return False, f"连不上（{type(e).__name__}: {str(e)[:100]}）"


_NET_ERROR_MARKERS = (
    "net::err_", "err_name_not_resolved", "err_connection", "err_tunnel",
    "err_proxy", "err_internet_disconnected", "err_address_unreachable",
    "err_socks", "err_empty_response", "err_ssl", "err_cert",
)


def looks_like_net_error(msg: str) -> bool:
    low = (msg or "").lower()
    return any(x in low for x in _NET_ERROR_MARKERS)


# ---------------------------------------------------------------- 浏览器

def user_agent() -> str:
    """跟着本机平台报，别在 Mac 上自称 Windows——UA 和其它浏览器特征对不上更容易被挡。"""
    if sys.platform == "darwin":
        token = "Macintosh; Intel Mac OS X 10_15_7"
    elif sys.platform.startswith("linux"):
        token = "X11; Linux x86_64"
    else:
        token = "Windows NT 10.0; Win64; x64"
    return (f"Mozilla/5.0 ({token}) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/124.0.0.0 Safari/537.36")


def _max_wait_sec() -> float:
    try:
        return float(os.environ.get("EPUB_WAF_MAX_WAIT_SEC", "180"))
    except ValueError:
        return 180.0


def _goto(page: Any, url: str, timeout: int = 120_000) -> Any:
    """打开一个地址。到不了就抛 SiteUnreachable——这跟「开了但要等」要分清楚。"""
    try:
        resp = page.goto(url, wait_until="load", timeout=timeout)
    except Exception as e:
        msg = str(e).splitlines()[0] if str(e) else type(e).__name__
        if looks_like_net_error(msg) or "timeout" in msg.lower():
            raise SiteUnreachable(f"{url} 打不开（{msg[:140]}）") from e
        raise
    status = getattr(resp, "status", None) if resp is not None else None
    if isinstance(status, int) and status >= 400:
        raise SiteUnreachable(f"{url} 回了 HTTP {status}（网络策略拦截或站点故障）")
    return resp


def _ctx_gone(exc: Exception) -> bool:
    """站点的前置校验会把页面重新导航一次，这时候查元素、取内容都会报错。
    这类报错不是失败，等它跳完再查就行。"""
    low = str(exc).lower()
    return any(k in low for k in (
        "execution context was destroyed", "navigating", "changing",
        "target closed", "most likely because of a navigation",
    ))


def _wait_for_selector(page: Any, selector: str, where: str) -> None:
    """页面已经打开了，等那个框出现。等不到是「站点挡着」，不是「网络不通」。"""
    limit, elapsed, step = _max_wait_sec(), 0.0, 3.0
    while elapsed < limit:
        page.wait_for_timeout(int(step * 1000))
        elapsed += step
        try:
            if page.query_selector(selector):
                return
        except Exception as e:
            if not _ctx_gone(e):
                raise
            try:
                page.wait_for_load_state("load", timeout=15_000)
            except Exception:
                pass
    raise SearchGateTimeout(
        f"{where}打开了，但 {limit:.0f} 秒内没等到 {selector}：站点在前面挡了一道校验。"
        f"可以 EPUB_WAF_MAX_WAIT_SEC=300 再试一次，或 PLAYWRIGHT_HEADED=1 人工过一次"
    )


def wait_for_home_ready(page: Any) -> None:
    _goto(page, EPUB_BASE)
    _wait_for_selector(page, "#searchStr", "公布公告首页")


def wait_for_advanced_ready(page: Any) -> None:
    _goto(page, EPUB_ADVANCED)
    _wait_for_selector(page, "#e51", "高级查询页")


_RESULT_READY_JS = """(titles) => {
    const t = document.title.trim();
    if (t === titles.noHit) return true;
    if (t !== titles.result) return false;
    const r = document.querySelector("#result");
    if (!r) return false;
    if (r.querySelector("div.item, h1.title")) return true;
    const html = r.innerHTML;
    return html.includes("无查询结果") || html.includes("没有找到")
        || html.includes("未检索到") || html.includes("0条");
}"""


class _NotYet(Exception):
    """内部信号：还没到位，接着等。"""


def _wait_result_ready(page: Any, url_part: str | None = None) -> None:
    """等结果页出来。

    不用 ``wait_for_url``：站点的前置校验会在提交后再导航一两次，
    那个 ``load`` 事件常常等不到（实测高级查询这一路必踩），
    但结果其实已经出来了。所以改成轮询「URL 到位 + 结果页就绪」，
    中间因为跳转报的错一律忽略。
    """
    limit = max(_max_wait_sec(), 120.0)
    elapsed, step = 0.0, 2.0
    while elapsed < limit:
        try:
            if url_part and url_part not in (page.url or ""):
                raise _NotYet
            if page.evaluate(_RESULT_READY_JS,
                             {"result": EPUB_TITLE_RESULT, "noHit": EPUB_TITLE_NO_HIT}):
                return
        except _NotYet:
            pass
        except Exception as e:
            if not _ctx_gone(e):
                raise
        try:
            page.wait_for_timeout(int(step * 1000))
        except Exception:
            time.sleep(step)
        elapsed += step
    raise SearchGateTimeout(
        f"提交之后 {limit:.0f} 秒内没等到结果页"
        + (f"（URL 还停在 {page.url}）" if url_part else "")
        + "：站点在前面挡了一道校验。"
        "可以 EPUB_WAF_MAX_WAIT_SEC=300 再试一次，或 PLAYWRIGHT_HEADED=1 人工过一次"
    )


def _safe_content(page: Any, max_attempts: int = 10) -> str:
    """取整页 HTML。正在跳转时会报错，退避重试几次。"""
    last: Exception | None = None
    for i in range(max_attempts):
        try:
            return page.content()
        except Exception as e:
            low = str(e).lower()
            if "navigating" not in low and "changing" not in low:
                raise
            last = e
            try:
                page.wait_for_load_state("load", timeout=20_000)
            except Exception:
                pass
            page.wait_for_timeout(400 + 200 * i)
    raise last if last else RuntimeError("取不到页面内容")


def _set_checkboxes(page: Any, mapping: dict[str, str] | None, patent_type: str) -> None:
    for home_id, want in epub_checkbox_states(patent_type).items():
        cid = mapping.get(home_id) if mapping else home_id
        if not cid or not page.query_selector(f"#{cid}"):
            continue
        page.evaluate(
            """({id, checked}) => {
                const el = document.getElementById(id);
                if (!el) return;
                el.checked = checked;
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            {"id": cid, "checked": want},
        )


def submit_index_search(page: Any, keyword: str, patent_type: str = TYPE_INVENTION) -> None:
    """首页检索框提交一个词。"""
    _set_checkboxes(page, None, patent_type)
    page.fill("#searchStr", keyword)
    with page.expect_navigation(timeout=120_000, wait_until="commit"):
        page.evaluate("() => { const f = document.getElementById('indexForm'); if (f) f.submit(); }")
    _wait_result_ready(page)


def submit_advanced_search(page: Any, keyword: str, class_code: str,
                           patent_type: str = TYPE_INVENTION) -> None:
    """高级查询：分类号 + 名称，用于第二轮收口。"""
    _set_checkboxes(page, EPUB_ADVANCED_CHECKBOX, patent_type)
    page.fill("#e51", class_code)
    if page.query_selector("#ti"):
        page.fill("#ti", keyword or "")
    # 按钮认准「查询」那个（onclick 是 adv_Query），别点到旁边的「清空」（type=reset）。
    clicked = page.evaluate(
        """() => {
            const f = document.querySelector('#advForm');
            if (!f) return null;
            const btns = Array.from(f.querySelectorAll('button, input[type=submit], input[type=button]'));
            const pick = btns.find(b => /adv_Query/i.test(b.getAttribute('onclick') || ''))
                || btns.find(b => (b.type || '').toLowerCase() !== 'reset'
                                  && /查\\s*询|检\\s*索/.test((b.innerText || b.value || '')));
            if (!pick) return null;
            pick.click();
            return (pick.innerText || pick.value || 'button').trim().slice(0, 12);
        }"""
    )
    if not clicked:
        raise SearchGateTimeout("高级查询页没找到「查询」按钮，站点可能改版了")
    _wait_result_ready(page, url_part="/Dxb/AdvancedQuery")


def search_terms(terms: list[str], patent_type: str = TYPE_INVENTION,
                 class_codes: list[str] | None = None,
                 playwright_factory: Callable[[], Any] | None = None,
                 on_browser: Callable[[str], None] | None = None) -> list[tuple[str, list[EpubHit]]]:
    """一场检索共用一个浏览器，一个词查一页。返回每次检索的 (页面HTML, 命中)。

    HTML 只在内存里传，不写任何文件——查新材料别落在磁盘上。
    """
    codes = [c.strip() for c in (class_codes or []) if c and str(c).strip()]
    if not terms and not codes:
        return []
    kw_list = list(terms) if terms else [""]

    if playwright_factory is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise BrowserUnavailable(
                "需要先装 playwright：pip3 install playwright（本包不会自动装）") from e
        playwright_factory = sync_playwright

    with playwright_factory() as p:
        browser, label = launch_chromium(p, headless=not headed())
        if on_browser:
            on_browser(label)
        context = browser.new_context(
            user_agent=user_agent(), locale="zh-CN", viewport={"width": 1280, "height": 900},
        )
        try:
            page = context.new_page()
            out: list[tuple[str, list[EpubHit]]] = []
            if not codes:
                for kw in kw_list:
                    if not kw:
                        continue
                    wait_for_home_ready(page)
                    submit_index_search(page, kw, patent_type)
                    html = _safe_content(page)
                    out.append((html, parse_result_html(html)))
                return out
            for code in codes:
                for kw in kw_list:
                    wait_for_advanced_ready(page)
                    submit_advanced_search(page, kw, code, patent_type)
                    html = _safe_content(page)
                    out.append((html, parse_result_html(html)))
            return out
        finally:
            context.close()
            browser.close()


# ---------------------------------------------------------------- CLI

def _ok(stats: dict, to_stderr: bool = False) -> None:
    line = "OK: " + " ".join(f"{k}={v}" for k, v in stats.items())
    print(line, file=sys.stderr if to_stderr else sys.stdout, flush=True)


def _fail(reason: str) -> None:
    try:
        sys.stdout.flush()
    except (OSError, ValueError):
        pass
    print(f"FAIL: {reason}", file=sys.stderr, flush=True)


def _note(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


class _Parser(argparse.ArgumentParser):
    """参数错误也走 FAIL: 行，退出码 1（argparse 默认 2，会和「入口不可用」混淆）。"""

    def error(self, message):
        _fail(f"参数错误：{message}")
        raise SystemExit(1)


def _split_codes(raw: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r"[,;，；\s]+", raw or ""):
        p = part.strip()
        if p and p not in out:
            out.append(p)
    return out


def main(argv: list[str] | None = None, playwright_factory: Callable[[], Any] | None = None,
         reach_check: Callable[[], tuple[bool, str]] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    ap = _Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("term", nargs="*", help="检索词，2-8 个，空格分开")
    ap.add_argument("--type", default=TYPE_INVENTION, help="本包只做发明，默认 invention")
    ap.add_argument("--class", "--ipc", dest="klass", default="",
                    help="分类号收口，如 G06F9,G06Q10；最多 3 个，带它时检索词最多 3 个")
    ap.add_argument("--max-terms", type=int, default=None, help=f"检索词上限，默认 {MAX_TERMS}")
    ap.add_argument("--json", action="store_true", help="stdout 只打 JSON 数组，OK 行改到 stderr")
    args = ap.parse_args(argv)

    try:
        patent_type = normalize_patent_type(args.type)
        terms = split_terms(args.term)
        codes = _split_codes(args.klass)
        if not terms and not codes:
            raise BadInput("至少给一个检索词，或者给 --class 分类号")
        if len(codes) > MAX_CLASS_CODES:
            raise BadInput(f"--class 给了 {len(codes)} 个分类号，最多 {MAX_CLASS_CODES} 个")
        cap = args.max_terms if args.max_terms is not None \
            else (MAX_TERMS_WITH_CLASS if codes else MAX_TERMS)
        if cap < 1:
            raise BadInput("--max-terms 至少是 1")
        if len(terms) > cap:
            raise BadInput(f"拆出 {len(terms)} 个检索词，超过上限 {cap}；挑最贴本案的几个，或分两批查")
    except BadInput as e:
        _fail(f"{e}")
        return 1

    for w in term_warnings(terms):
        _note(f"EPUB_TERM_WARN: {w}")

    check = reach_check or (lambda: check_site_reachable())
    reachable, detail = check()
    if not reachable:
        _fail(f"site_unreachable epub.cnipa.gov.cn {detail}。"
              f"这台机器到不了这个站（断网、代理或出网白名单），不是等待时间不够，"
              f"别去调 EPUB_WAF_MAX_WAIT_SEC；按检索规范写「入口不可用」，不要写成「未检索到」")
        return 2

    try:
        rows = search_terms(terms, patent_type, codes, playwright_factory=playwright_factory,
                            on_browser=lambda label: _note(f"BROWSER: channel={label}"))
    except BrowserUnavailable as e:
        _fail(f"browser_unavailable {e}")
        return 2
    except SiteUnreachable as e:
        _fail(f"site_unreachable {e}。这台机器到不了这个站（断网、代理或出网白名单），"
              f"不是等待时间不够，别去调 EPUB_WAF_MAX_WAIT_SEC；"
              f"按检索规范写「入口不可用」，不要写成「未检索到」")
        return 2
    except SearchGateTimeout as e:
        _fail(f"search_gate_timeout {e}")
        return 2
    except Exception as e:
        name, msg = type(e).__name__, str(e)
        # 站点中途卡住（结果页一直没就绪之类）也是入口没走通，不是我们输入错了，退出码要给 2
        if "Timeout" in name or looks_like_net_error(msg):
            _fail(f"entry_unavailable {name}: {msg[:160]}。这次没把检索流程走完，"
                  f"按检索规范写「入口不可用」，不要写成「未检索到」")
            return 2
        _fail(f"runtime_error {name}: {msg[:160]}")
        return 1

    hits = dedupe_hits([h for _html, h in rows])
    last_html = rows[-1][0] if rows else ""
    searches = len(rows)

    if searches > 1:
        _note(f"EPUB_MERGE: terms={len(terms)} type={patent_type} merged_hits={len(hits)}")
    if codes:
        _note(f"EPUB_NOTE: class={','.join(codes)}")
    else:
        kind, suggested = suggest_class_codes(hits, patent_type)
        if suggested:
            _note(f"EPUB_CLASS_HINT: kind={kind} codes={','.join(suggested)}")
    if not hits:
        _note("EPUB_HINT: 0 hits; 换更宽的词，或先不带 --class 再来一轮")
    # disk=0 是句实话：结果页 HTML 从头到尾只在内存里，没有落盘
    _note(f"EPUB_NOTE: html_bytes={len(last_html)} disk=0")

    payload = hits_to_json(hits)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False), flush=True)
    else:
        print("EPUB_HITS_JSON:", json.dumps(payload, ensure_ascii=False), flush=True)
    stats = {"hits": len(hits), "terms": len(terms), "type": patent_type}
    if codes:
        stats["class"] = ",".join(codes)
    _ok(stats, to_stderr=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
