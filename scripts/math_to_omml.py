#!/usr/bin/env python3
"""LaTeX → Word 可编辑公式（Office Math / OMML）。

Copyright (c) 2026 handsomestWei
改编自 handsomestWei/patent-disclosure-skill（MIT）tools/math_to_omml.py，改动：改为可选依赖（没装
latex2mathml 时 omml_available() 返回 False，调用方原文保留）；∑/∏/∫ 等大算子改出 m:nary（上下限
真正落在算子上下）；\\left…\\right 与 cases 改出 m:d 定界符（括号随内容伸缩）；\\hat/\\bar/\\vec 改出
m:acc/m:bar 而不是上标；单字母变量保留 Word 默认斜体，只有 \\mathrm/函数名/数字/运算符设为正体；
补 count_omml_in_docx() 供测试与核对用。

路线：latex2mathml 把 LaTeX 转成 MathML，本文件再把 MathML 映射为 m:oMath（行内）/ m:oMathPara（块级），
挂到 python-docx 段落的 <w:p> 上。不依赖本机 TeX 或 Word。

依赖：python-docx（必需）+ latex2mathml（可选，pip3 install latex2mathml）。
"""

from __future__ import annotations

import re
import zipfile
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

MATHML_NS = "{http://www.w3.org/1998/Math/MathML}"
MATH_FONT = "Cambria Math"
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# latex2mathml 不认识的单位/符号宏 → 宋体与 Cambria Math 都有的字符
_LATEX_CMD_TO_REPL: tuple[tuple[str, str], ...] = (
    ("perthousand", "‰"),
    ("textcelsius", "℃"),
    ("textfahrenheit", "℉"),
    ("textdegree", "°"),
    ("angstrom", "Å"),
    ("permil", "‰"),
    ("degree", "°"),
    ("micro", "µ"),
    ("ohm", "Ω"),
    ("AA", "Å"),
)

_CIRC_UNIT_PATTERNS: tuple[str, ...] = (
    r"\\mathrm\s*\{\s*\^\s*\{\s*\\circ\s*\}\s*([A-Z])\s*\}",
    r"\\mathrm\s*\{\s*\^\s*\\circ\s*([A-Z])\s*\}",
    r"\^\s*\{\s*\\circ\s*\}\s*\\mathrm\s*\{\s*([A-Z])\s*\}",
    r"\^\s*\\circ\s*\\mathrm\s*\{\s*([A-Z])\s*\}",
    r"\^\s*\{\s*\\circ\s*\}\s*([A-Z])\b",
    r"\^\s*\\circ\s*([A-Z])\b",
)
_CIRC_UNIT_CHARS = {"C": "℃", "F": "℉"}

# 大算子：作为 msub/msup/msubsup 的底时改出 m:nary
_NARY_UNDOVR = set("∑∏∐⋃⋂⋁⋀⨁⨂⨀")          # 上下限放算子上下
_NARY_SUBSUP = set("∫∬∭∮∯∰")                 # 上下限放算子右侧
# mover 的重音符 → m:acc 用的组合字符；横线类走 m:bar
_ACCENT_MAP = {
    "^": "\u0302", "\u02c6": "\u0302", "\u0302": "\u0302",
    "~": "\u0303", "\u02dc": "\u0303", "\u0303": "\u0303",
    "\u02d9": "\u0307", "\u0307": "\u0307", "\u00a8": "\u0308", "\u0308": "\u0308",
    "\u2192": "\u20d7", "\u20d7": "\u20d7", "\u02d8": "\u0306", "\u030c": "\u030c", "\u02c7": "\u030c",
}
_BAR_CHARS = {"\u00af", "\u2015", "\u203e", "\u0305", "-", "\u2212", "_"}


class OmmlUnavailable(RuntimeError):
    """没装 latex2mathml。"""


def omml_available() -> bool:
    try:
        import latex2mathml  # noqa: F401
        return True
    except ImportError:
        return False


def _circ_unit_repl(match: re.Match) -> str:
    letter = match.group(1)
    return _CIRC_UNIT_CHARS.get(letter, "°" + letter)


def normalize_latex_for_omml(latex: str) -> str:
    """去掉 Word 公式不友好的外壳，并把缺字符号换成可显示字符。"""
    body = (latex or "").strip()
    if not body:
        return ""
    body = re.sub(r"\\tag\s*\{([^{}]*)\}", r"\\quad (\1)", body)
    body = re.sub(r"\\notag\b", "", body)
    body = re.sub(r"\\label\s*\{[^{}]*\}", "", body)
    body = body.replace("\n", " ")
    body = re.sub(r"[ \t]{2,}", " ", body).strip()
    body = re.sub(r"\\le(?![A-Za-z])", r"\\leq", body)
    body = re.sub(r"\\ge(?![A-Za-z])", r"\\geq", body)
    body = re.sub(r"\\land(?![A-Za-z])", r"\\wedge", body)
    body = re.sub(r"\\lor(?![A-Za-z])", r"\\vee", body)
    body = re.sub(r"\\(big+|Big+|bigl|bigr|Bigl|Bigr)(?![A-Za-z])", "", body)
    for cmd, repl in _LATEX_CMD_TO_REPL:
        body = re.sub(rf"\\{re.escape(cmd)}(?![A-Za-z])", lambda _m, r=repl: r, body)
    for pattern in _CIRC_UNIT_PATTERNS:
        body = re.sub(pattern, _circ_unit_repl, body)
    body = re.sub(r"\^\s*\{\s*\\circ\s*\}", "°", body)
    body = re.sub(r"\^\s*\\circ(?![A-Za-z])", "°", body)
    body = re.sub(r"\\sim(?![A-Za-z])", "∼", body)
    return body


# ---------- MathML → OMML ----------

def _element(name: str):
    return OxmlElement(f"m:{name}")


def _map_glyphs(text: str, *, in_script: bool) -> str:
    """上标里的 RING OPERATOR 当度数用。"""
    if in_script and text:
        return text.replace("\u2218", "\u00b0")
    return text


def _text_run(text: str, *, plain: bool = True, in_script: bool = False):
    """一个 m:r。plain=True 写 m:sty=p（正体）；False 留给 Word 默认（字母斜体）。"""
    text = _map_glyphs(text, in_script=in_script)
    run = _element("r")
    if plain:
        properties = _element("rPr")
        style = _element("sty")
        style.set(qn("m:val"), "p")
        properties.append(style)
        run.append(properties)
    if text and not _CJK_RE.search(text):
        wrpr = OxmlElement("w:rPr")
        rfonts = OxmlElement("w:rFonts")
        for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
            rfonts.set(qn(f"w:{attr}"), MATH_FONT)
        wrpr.append(rfonts)
        run.append(wrpr)
    value = _element("t")
    value.set(qn("xml:space"), "preserve")
    value.text = text
    run.append(value)
    return run


def _tag(node) -> str:
    return node.tag[len(MATHML_NS):] if node.tag.startswith(MATHML_NS) else node.tag


def _node_text(node) -> str:
    return "".join(node.itertext())


def _is_empty_math_node(node) -> bool:
    if node is None:
        return True
    if _node_text(node).strip():
        return False
    children = list(node)
    if not children:
        return True
    return all(_is_empty_math_node(child) for child in children)


def _nary_base_char(node) -> str | None:
    """msub/msup/msubsup 的第一个孩子若是大算子，返回该字符。"""
    children = list(node)
    if not children:
        return None
    base = children[0]
    if _tag(base) == "mrow" and len(list(base)) == 1:
        base = list(base)[0]
    if _tag(base) != "mo":
        return None
    ch = _node_text(base).strip()
    if ch in _NARY_UNDOVR or ch in _NARY_SUBSUP:
        return ch
    return None


_BARE_DELIMS = {"|", "‖"}      # |x| 与 ‖x‖：成对的裸竖线配成 m:d，LibreOffice 才不会把 | 当"或"


def _pair_bare_bars(children: list) -> list:
    """把 mrow 里成对出现的裸 | / ‖ 连同中间内容包成一个临时 <fence> 节点，后面按 m:d 输出。"""
    out: list = []
    i = 0
    while i < len(children):
        node = children[i]
        ch = _node_text(node).strip() if _tag(node) == "mo" else ""
        if ch in _BARE_DELIMS and node.attrib.get("form") not in {"prefix", "postfix"}:
            for j in range(i + 1, len(children)):
                other = children[j]
                if _tag(other) == "mo" and _node_text(other).strip() == ch \
                        and other.attrib.get("form") not in {"prefix", "postfix"}:
                    fence = ElementTree.Element("fence", {"open": ch, "close": ch})
                    fence.extend(children[i + 1:j])
                    out.append(fence)
                    i = j + 1
                    break
            else:
                out.append(node)
                i += 1
            continue
        out.append(node)
        i += 1
    return out


def _append_children(target, source, *, in_script: bool = False) -> None:
    """把 source 的文本与子节点依次追加到 target；遇到大算子时把后面的兄弟都收进它的 m:e。"""
    if source.text and source.text.strip():
        target.append(_text_run(source.text.strip(), in_script=in_script))
    children = _pair_bare_bars(list(source))
    for idx, child in enumerate(children):
        tag = _tag(child)
        if tag in {"msub", "msup", "msubsup", "munder", "mover", "munderover"} and _nary_base_char(child):
            _nary(target, child, children[idx + 1:], in_script=in_script)
            return
        _append_mathml(target, child, in_script=in_script)
        if child.tail and child.tail.strip():
            target.append(_text_run(child.tail.strip(), in_script=in_script))


def _space_text(node) -> str:
    """mspace → 真正的空格字符：\\, 用细空格，\\quad 每 1em 一个全角空格。"""
    width = node.attrib.get("width", "")
    m = re.match(r"([0-9.]+)\s*em", width)
    if not m:
        return " "
    em = float(m.group(1))
    if em < 0.5:
        return " "
    return " " * max(1, round(em))


def _nary(target, node, operand_nodes, *, in_script: bool = False) -> None:
    """∑_{a}^{b} X → m:nary（chr=∑，sub=a，sup=b，e=X）。"""
    ch = _nary_base_char(node) or "∑"
    kind = _tag(node)
    children = list(node)
    nary = _element("nary")
    pr = _element("naryPr")
    chr_el = _element("chr")
    chr_el.set(qn("m:val"), ch)
    pr.append(chr_el)
    lim = _element("limLoc")
    lim.set(qn("m:val"), "undOvr" if ch in _NARY_UNDOVR else "subSup")
    pr.append(lim)
    sub = _element("sub")
    sup = _element("sup")
    if kind in {"msub", "munder"} and len(children) > 1:
        _append_mathml(sub, children[1])
    elif kind in {"msup", "mover"} and len(children) > 1:
        _append_mathml(sup, children[1], in_script=True)
    else:
        if len(children) > 1:
            _append_mathml(sub, children[1])
        if len(children) > 2:
            _append_mathml(sup, children[2], in_script=True)
    if not len(sub):
        hide = _element("subHide")
        hide.set(qn("m:val"), "1")
        pr.append(hide)
    if not len(sup):
        hide = _element("supHide")
        hide.set(qn("m:val"), "1")
        pr.append(hide)
    expression = _element("e")
    for sibling in operand_nodes:
        _append_mathml(expression, sibling, in_script=in_script)
        if sibling.tail and sibling.tail.strip():
            expression.append(_text_run(sibling.tail.strip(), in_script=in_script))
    nary.extend((pr, sub, sup, expression))
    target.append(nary)


def _script(target, node, kind: str) -> None:
    children = list(node)
    if kind == "sSup" and children and _is_empty_math_node(children[0]):
        # ^{\circ} 这类没有底的上标：直接当普通字符
        if len(children) > 1:
            _append_mathml(target, children[1], in_script=True)
        return

    result = _element(kind)
    expression = _element("e")
    if children:
        _append_mathml(expression, children[0])
    result.append(expression)
    if kind == "sSub":
        sub = _element("sub")
        if len(children) > 1:
            _append_mathml(sub, children[1])
        result.append(sub)
    elif kind == "sSup":
        sup = _element("sup")
        if len(children) > 1:
            _append_mathml(sup, children[1], in_script=True)
        result.append(sup)
    else:
        sub = _element("sub")
        sup = _element("sup")
        if len(children) > 1:
            _append_mathml(sub, children[1])
        if len(children) > 2:
            _append_mathml(sup, children[2], in_script=True)
        result.extend((sub, sup))
    target.append(result)


def _accent(target, node) -> None:
    """mover：\\hat/\\bar/\\vec → m:acc / m:bar；认不出的重音符退回上标。"""
    children = list(node)
    if len(children) < 2:
        _append_children(target, node)
        return
    base, mark = children[0], children[1]
    mark_text = _node_text(mark).strip()
    if mark_text in _BAR_CHARS:
        bar = _element("bar")
        pr = _element("barPr")
        pos = _element("pos")
        pos.set(qn("m:val"), "top")
        pr.append(pos)
        expression = _element("e")
        _append_mathml(expression, base)
        bar.extend((pr, expression))
        target.append(bar)
        return
    combining = _ACCENT_MAP.get(mark_text)
    if combining is None:
        _script(target, node, "sSup")
        return
    acc = _element("acc")
    pr = _element("accPr")
    chr_el = _element("chr")
    chr_el.set(qn("m:val"), combining)
    pr.append(chr_el)
    expression = _element("e")
    _append_mathml(expression, base)
    acc.extend((pr, expression))
    target.append(acc)


def _fenced_row(node):
    """mrow 首尾是 \\left/\\right 定界符 → (开, 闭, 内部节点)；不是则 None。"""
    children = list(node)
    if not children:
        return None
    first, last = children[0], children[-1]
    if _tag(first) != "mo" or first.attrib.get("form") != "prefix":
        return None
    open_ch = _node_text(first).strip()
    if _tag(last) == "mo" and last.attrib.get("form") == "postfix" and len(children) >= 2:
        return open_ch, _node_text(last).strip(), children[1:-1]
    return open_ch, "", children[1:]        # cases：只有左花括号


def _delimiter(target, open_ch: str, close_ch: str, inner_nodes, *, in_script: bool) -> None:
    delimiter = _element("d")
    properties = _element("dPr")
    begin = _element("begChr")
    begin.set(qn("m:val"), "" if open_ch == "." else open_ch)
    end = _element("endChr")
    end.set(qn("m:val"), "" if close_ch == "." else close_ch)
    properties.extend((begin, end))
    expression = _element("e")
    holder = ElementTree.Element("holder")
    holder.extend(inner_nodes)
    _append_children(expression, holder, in_script=in_script)
    delimiter.extend((properties, expression))
    target.append(delimiter)


def _append_mathml(target, node, *, in_script: bool = False) -> None:
    tag = _tag(node)
    children = list(node)

    if tag == "mrow":
        fenced = _fenced_row(node)
        if fenced:
            _delimiter(target, fenced[0], fenced[1], fenced[2], in_script=in_script)
        else:
            _append_children(target, node, in_script=in_script)
    elif tag in {"math", "mstyle", "semantics", "annotation", "mpadded", "mphantom"}:
        _append_children(target, node, in_script=in_script)
    elif tag == "mi":
        text = _node_text(node)
        plain = node.attrib.get("mathvariant") == "normal" or len(text.strip()) > 1
        target.append(_text_run(text, plain=plain, in_script=in_script))
    elif tag in {"mn", "mo", "mtext"}:
        target.append(_text_run(_node_text(node), plain=True, in_script=in_script))
    elif tag == "mfrac":
        fraction = _element("f")
        numerator = _element("num")
        denominator = _element("den")
        if children:
            _append_mathml(numerator, children[0])
        if len(children) > 1:
            _append_mathml(denominator, children[1])
        fraction.extend((numerator, denominator))
        target.append(fraction)
    elif tag in {"msub", "msup", "msubsup", "munder", "mover", "munderover"} and _nary_base_char(node):
        _nary(target, node, [], in_script=in_script)
    elif tag == "msub":
        _script(target, node, "sSub")
    elif tag == "msup":
        _script(target, node, "sSup")
    elif tag in {"msubsup", "munderover"}:
        _script(target, node, "sSubSup")
    elif tag == "munder":
        _script(target, node, "sSub")
    elif tag == "mover":
        _accent(target, node)
    elif tag == "msqrt":
        radical = _element("rad")
        properties = _element("radPr")
        hide_degree = _element("degHide")
        hide_degree.set(qn("m:val"), "1")
        properties.append(hide_degree)
        degree = _element("deg")
        expression = _element("e")
        _append_children(expression, node)
        radical.extend((properties, degree, expression))
        target.append(radical)
    elif tag == "mroot":
        radical = _element("rad")
        degree = _element("deg")
        expression = _element("e")
        if children:
            _append_mathml(expression, children[0])
        if len(children) > 1:
            _append_mathml(degree, children[1])
        radical.extend((degree, expression))
        target.append(radical)
    elif tag in {"mfenced", "fence"}:
        _delimiter(target, node.attrib.get("open", "("), node.attrib.get("close", ")"),
                   children, in_script=in_script)
    elif tag == "mtable":
        matrix = _element("m")
        for row_node in children:
            row = _element("mr")
            for cell_node in list(row_node):
                cell = _element("e")
                _append_children(cell, cell_node)
                row.append(cell)
            matrix.append(row)
        target.append(matrix)
    elif tag in {"mtr", "mtd"}:
        _append_children(target, node, in_script=in_script)
    elif tag == "mspace":
        target.append(_text_run(_space_text(node)))
    else:
        _append_children(target, node, in_script=in_script)


# ---------- 对外接口 ----------

def latex_to_omml(latex: str, *, display: bool = True):
    """返回可挂到 paragraph._p 的 OMML 元素；display=True 出 m:oMathPara（块级），否则 m:oMath（行内）。

    没装 latex2mathml 抛 OmmlUnavailable；LaTeX 本身转不了抛其它异常，由调用方决定回退。
    """
    try:
        from latex2mathml.converter import convert
    except ImportError as error:
        raise OmmlUnavailable("需要 latex2mathml：pip3 install latex2mathml") from error

    body = normalize_latex_for_omml(latex)
    if not body:
        raise ValueError("公式为空")
    mathml = ElementTree.fromstring(convert(body))
    math = _element("oMath")
    _append_mathml(math, mathml)
    if _is_empty_math_node(math):
        raise ValueError("公式转换后为空")
    if display:
        paragraph = _element("oMathPara")
        paragraph.append(math)
        return paragraph
    return math


def try_latex_to_omml(latex: str, *, display: bool = True):
    """成功返回 OMML 元素，任何失败（含没装依赖）返回 None。"""
    try:
        return latex_to_omml(latex, display=display)
    except Exception:
        return None


def clone_omml(element):
    return deepcopy(element)


def count_omml_in_docx(docx_path) -> dict:
    """数一个 docx 正文里有多少 m:oMath / m:oMathPara，核对转换结果用。"""
    with zipfile.ZipFile(str(Path(docx_path))) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    ns_math = "http://schemas.openxmlformats.org/officeDocument/2006/math"
    root = ElementTree.fromstring(xml)
    return {
        "oMath": sum(1 for _ in root.iter(f"{{{ns_math}}}oMath")),
        "oMathPara": sum(1 for _ in root.iter(f"{{{ns_math}}}oMathPara")),
    }


if __name__ == "__main__":
    import sys
    src = " ".join(sys.argv[1:]) or r"\sum_{k=1}^{W} s_{(k)}"
    if not omml_available():
        print("FAIL: 没装 latex2mathml（pip3 install latex2mathml）", file=sys.stderr)
        raise SystemExit(2)
    from lxml import etree
    el = latex_to_omml(src, display=False)
    print(etree.tostring(el, pretty_print=True, encoding="unicode"))
    print("OK: omml=1")
