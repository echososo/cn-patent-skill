#!/usr/bin/env python3
"""Markdown 稿 → 可提交排版的 Word：宋体正文、黑体标题、A4、2.54cm 页边距、1.5 倍行距、页脚页码，
附图按 ![](路径) 原位嵌入，LaTeX 公式转成 Word 里能双击编辑的原生公式。

用法：
  python3 md_to_docx.py 申请文件.md                # 输出 申请文件.docx
  python3 md_to_docx.py 申请文件.md -o 提交稿.docx

依赖：pip3 install python-docx；公式要转成 Word 原生公式另需 pip3 install latex2mathml
      （没装就把公式按原文保留，统计里 text=N 会告诉你有几处）。
支持的 Markdown 子集：# ## ### 标题、普通段落、- 无序列表、1. 有序列表、| 表格 |、![](图片)、
行内公式 \\(...\\) 与 $...$、块级公式 \\[...\\] 与 $$...$$（单行或多行）、``` 围栏代码块（等宽字体成段）。
整行的 HTML 注释 <!-- ... --> 直接跳过，不当正文。
插图默认铺满版心宽度，竖长图（铺满宽度会超出版心高度的）改为限高等比缩，避免在 Word 里被截。
其余按普通段落处理（专利稿也用不上花哨语法）。

成功时 stdout 最后一行：OK: paragraphs=.. headings=.. tables=.. images=.. omml=.. text=.. out=..
失败时 stderr 一行 FAIL: 原因；退出码 2 = 缺依赖，1 = 输入或运行错误（缺图也算 1，但 docx 照样写出）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


class _Parser(argparse.ArgumentParser):
    """参数错误也走 FAIL: 行，退出码 1（argparse 默认 2，会和"缺依赖"混淆）。"""

    def error(self, message):
        print(f"FAIL: 参数错误：{message}", file=sys.stderr)
        raise SystemExit(1)


BODY_FONT_CN = "宋体"
BODY_FONT_EN = "Times New Roman"
HEAD_FONT_CN = "黑体"
MONO_FONT_CN = "宋体"      # 代码块：中文没有通用等宽字体，用宋体兜底
MONO_FONT_EN = "Consolas"
BODY_SIZE_PT = 12          # 小四
CODE_SIZE_PT = 10.5        # 代码块小一号，长行不容易折
MARGIN_CM = 2.54
MAX_IMG_CM = 14.6          # A4 减页边距后的可用宽度
MAX_IMG_H_CM = 24.0        # A4 减页边距后的可用高度约 24.6，留一点余量


class DependencyMissing(SystemExit):
    """缺依赖：退出码固定 2，str() 是人话（方便别的脚本 import 后 except SystemExit 拿到原因）。"""

    def __init__(self, msg: str):
        super().__init__(2)
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


def set_cn_font(run, cn: str, en: str, size_pt: int, bold: bool = False):
    from docx.oxml.ns import qn
    from docx.shared import Pt
    run.font.name = en
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run._element.rPr.rFonts.set(qn("w:eastAsia"), cn)


def add_page_number(doc):
    """页脚居中页码（PAGE 域）。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    footer = doc.sections[0].footer
    para = footer.paragraphs[0]
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = para.add_run()
    for tag, attrs, text in [
        ("w:fldChar", {"w:fldCharType": "begin"}, None),
        ("w:instrText", {"xml:space": "preserve"}, " PAGE "),
        ("w:fldChar", {"w:fldCharType": "end"}, None),
    ]:
        el = OxmlElement(tag)
        for k, v in attrs.items():
            el.set(qn(k), v)
        if text:
            el.text = text
        run._element.append(el)
    set_cn_font(run, BODY_FONT_CN, BODY_FONT_EN, 10)


def picture_size(img_path) -> dict:
    """按宽高比决定插图尺寸，返回给 add_picture 的关键字参数。

    默认铺满版心宽度；但竖长的流程图（如 1298×4084）铺满宽度后高度会到 45cm 开外，
    在 Word 里超出版心直接被截掉，所以超过可用高度就改成限高等比缩。
    读不出尺寸时退回按宽度处理。
    """
    from docx.shared import Cm
    try:
        from docx.image.image import Image as _DocxImage
        im = _DocxImage.from_file(str(img_path))
        w, h = im.px_width, im.px_height
        if w and h and MAX_IMG_CM * (h / w) > MAX_IMG_H_CM:
            return {"height": Cm(MAX_IMG_H_CM)}
    except Exception:  # noqa: BLE001
        pass
    return {"width": Cm(MAX_IMG_CM)}


# ---------- 公式定位 ----------

def inline_math_spans(text: str) -> list[tuple[int, int, str]]:
    """找出一行里的行内公式：\\(...\\) 和 $...$，返回 (起, 止, LaTeX)。

    $...$ 按 Pandoc 的规矩认：开头 $ 右边不能是空白，结尾 $ 左边不能是空白、右边不能是数字，
    这样"价格 $5 和 $10"这种不会被当成公式。$$ 不在这里处理（块级）。
    """
    spans: list[tuple[int, int, str]] = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith("\\(", i):
            j = text.find("\\)", i + 2)
            if j == -1:
                i += 2
                continue
            spans.append((i, j + 2, text[i + 2:j]))
            i = j + 2
            continue
        if text[i] == "$" and (i == 0 or text[i - 1] not in "$\\") and not text.startswith("$$", i):
            j = i + 1
            if j < n and not text[j].isspace():
                k = text.find("$", j)
                while k != -1:
                    ok_left = not text[k - 1].isspace() and text[k - 1] != "\\"
                    ok_right = k + 1 >= n or not text[k + 1].isdigit()
                    if ok_left and ok_right and not text.startswith("$$", k):
                        break
                    k = text.find("$", k + 1)
                if k != -1 and text[j:k].strip():
                    spans.append((i, k + 1, text[j:k]))
                    i = k + 1
                    continue
        i += 1
    return spans


_BLOCK_OPENERS = (("\\[", "\\]"), ("$$", "$$"))


def block_math_start(line: str) -> tuple[str, str] | None:
    """这一行是不是块级公式的开头；是就返回 (开符, 闭符)。"""
    s = line.strip()
    for opener, closer in _BLOCK_OPENERS:
        if s.startswith(opener):
            return opener, closer
    return None


def split_table_row(line: str) -> list[str]:
    """按 | 切表格行，但公式里的 |（如 \\(|x|\\)）不切。"""
    s = line.strip()
    spans = inline_math_spans(s)
    cells, buf = [], []
    for idx, ch in enumerate(s):
        if ch == "|" and not any(a <= idx < b for a, b, _ in spans):
            cells.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    cells.append("".join(buf))
    if cells and not cells[0].strip():
        cells = cells[1:]
    if cells and not cells[-1].strip():
        cells = cells[:-1]
    return [c.strip() for c in cells]


# ---------- 转换主体 ----------

def convert(md_path: Path, out_path: Path) -> dict:
    try:
        import docx
        from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
        from docx.shared import Cm, Pt, RGBColor
    except ImportError:
        msg = "需要先装 python-docx：pip3 install python-docx"
        print(f"FAIL: {msg}", file=sys.stderr)
        raise DependencyMissing(msg)

    import math_to_omml
    use_omml = math_to_omml.omml_available()

    doc = docx.Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)   # A4
    for side in ("top", "bottom", "left", "right"):
        setattr(sec, f"{side}_margin", Cm(MARGIN_CM))

    stats = {"paragraphs": 0, "headings": 0, "images": 0, "tables": 0, "missing_images": [],
             "omml": 0, "math_text": 0, "omml_available": use_omml}

    def add_rich(p, text: str, cn=BODY_FONT_CN, en=BODY_FONT_EN, size=BODY_SIZE_PT, bold=False) -> list:
        """往段落里写文字，行内公式能转就转成 m:oMath，转不了就原文保留。返回创建的文字 run。"""
        runs = []

        def plain(seg: str):
            if seg:
                run = p.add_run(seg)
                set_cn_font(run, cn, en, size, bold)
                runs.append(run)

        pos = 0
        for start, end, latex in inline_math_spans(text):
            plain(text[pos:start])
            el = math_to_omml.try_latex_to_omml(latex, display=False) if use_omml else None
            if el is not None:
                p._p.append(el)
                stats["omml"] += 1
            else:
                plain(text[start:end])
                stats["math_text"] += 1
            pos = end
        plain(text[pos:])
        return runs

    def add_para(text: str, cn=BODY_FONT_CN, en=BODY_FONT_EN, size=BODY_SIZE_PT, bold=False):
        p = doc.add_paragraph()
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
        p.paragraph_format.space_after = Pt(0)
        add_rich(p, text, cn, en, size, bold)
        return p

    def add_block_math(latex: str, raw_lines: list[str]):
        """块级公式：居中一段 m:oMathPara；转不了就原文逐行保留。"""
        el = math_to_omml.try_latex_to_omml(latex, display=True) if use_omml else None
        if el is not None:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
            p.paragraph_format.space_after = Pt(0)
            p._p.append(el)
            stats["omml"] += 1
        else:
            for raw in raw_lines:
                p = doc.add_paragraph()
                p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
                p.paragraph_format.space_after = Pt(0)
                run = p.add_run(raw.rstrip())
                set_cn_font(run, BODY_FONT_CN, BODY_FONT_EN, BODY_SIZE_PT)
            stats["math_text"] += 1

    lines = md_path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        s = line.strip()
        if not s:
            i += 1
            continue

        # 整行 HTML 注释不进正文（mermaid 出图会留下 <!-- ![图示 1](fig_001.png) --> 这种行）
        if s.startswith("<!--"):
            if s.endswith("-->") and len(s) >= 7:
                i += 1
                continue
            if "-->" not in s[4:]:                       # 多行注释块：整块跳到闭合行
                j = i + 1
                while j < len(lines) and "-->" not in lines[j]:
                    j += 1
                if j < len(lines):
                    i = j + 1
                    continue
            # 注释没闭合：当普通段落，往下走

        # ``` 围栏代码块：块内原样用等宽字体输出，围栏行本身不进 Word，也不解析公式/标题
        if s.startswith("```"):
            j = i + 1
            body = []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                body.append(lines[j].rstrip())
                j += 1
            for raw in body:
                p = doc.add_paragraph()
                p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
                p.paragraph_format.space_after = Pt(0)
                run = p.add_run(raw)
                set_cn_font(run, MONO_FONT_CN, MONO_FONT_EN, CODE_SIZE_PT)
                stats["paragraphs"] += 1
            i = j + 1                                    # 跳过闭合围栏；没闭合时 j 已到末尾
            continue

        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            size = {1: 16, 2: 14, 3: 12}[level]
            p = doc.add_paragraph(style=f"Heading {level}")
            p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
            for run in add_rich(p, m.group(2).strip(), HEAD_FONT_CN, BODY_FONT_EN, size, bold=(level == 1)):
                run.font.color.rgb = RGBColor(0, 0, 0)
            stats["headings"] += 1
            i += 1
            continue

        m = re.match(r"^!\[[^\]]*\]\(([^)]+)\)\s*$", line)
        if m:
            img = (md_path.parent / m.group(1)).resolve()
            if img.is_file():
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.add_run().add_picture(str(img), **picture_size(img))
                stats["images"] += 1
            else:
                stats["missing_images"].append(m.group(1))
                add_para(f"（附图缺失：{m.group(1)}）")
            i += 1
            continue

        # 块级公式：\[ ... \] 或 $$ ... $$，同一行或跨多行
        bm = block_math_start(line)
        if bm:
            opener, closer = bm
            raw = [line]
            s = line.strip()
            body_end = s.endswith(closer) and len(s) >= len(opener) + len(closer) and s != opener
            j = i
            if not body_end and closer in s[len(opener):]:
                j = len(lines)                    # 闭符在行中间（如 "$$x$$ 是……"）：不当块级，按普通段落
            while not body_end and j + 1 < len(lines) and j - i < 40:
                j += 1
                raw.append(lines[j].rstrip())
                body_end = lines[j].strip().endswith(closer)
            if body_end:
                joined = "\n".join(r.strip() for r in raw)
                latex = joined[len(opener):]
                latex = latex[: -len(closer)] if latex.endswith(closer) else latex
                add_block_math(latex.strip(), raw)
                i = j + 1
                continue
            # 没找到闭合符：当普通段落，往下走

        if line.lstrip().startswith("|") and i + 1 < len(lines) \
           and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            header = split_table_row(line)
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append(split_table_row(lines[j]))
                j += 1
            table = doc.add_table(rows=1 + len(rows), cols=len(header))
            table.style = "Table Grid"
            for c, text in enumerate(header):
                add_rich(table.rows[0].cells[c].paragraphs[0], text, HEAD_FONT_CN, BODY_FONT_EN, 10.5, bold=True)
            for r, row in enumerate(rows, 1):
                for c in range(len(header)):
                    val = row[c] if c < len(row) else ""
                    add_rich(table.rows[r].cells[c].paragraphs[0], val, BODY_FONT_CN, BODY_FONT_EN, 10.5)
            stats["tables"] += 1
            i = j
            continue

        m = re.match(r"^\s*(?:[-*]|\d+[.．、])\s+(.*)$", line)
        if m and not re.match(r"^\s*\d+[.．、]\s*(一种|根据权利要求)", line):
            add_para("· " + m.group(1) if line.lstrip()[0] in "-*" else line.strip())
            stats["paragraphs"] += 1
            i += 1
            continue

        add_para(line.strip())
        stats["paragraphs"] += 1
        i += 1

    add_page_number(doc)
    doc.save(str(out_path))
    stats["output"] = str(out_path)
    return stats


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = _Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("md")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args(argv)
    md_path = Path(args.md)
    if not md_path.is_file():
        print(f"FAIL: 找不到 {md_path}", file=sys.stderr)
        return 1
    out = Path(args.output) if args.output else md_path.with_suffix(".docx")
    try:
        st = convert(md_path, out)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: 转换出错：{e}", file=sys.stderr)
        return 1
    print(f"{st['paragraphs']} 段、{st['headings']} 个标题、{st['tables']} 张表、"
          f"{st['images']} 张图，公式：omml={st['omml']} text={st['math_text']} → {out}")
    if st["math_text"] and not st["omml_available"]:
        print(f"提示：没装 latex2mathml，{st['math_text']} 处公式按原文保留。"
              "要转成 Word 可编辑公式：pip3 install latex2mathml", file=sys.stderr)
    elif st["math_text"]:
        print(f"提示：{st['math_text']} 处公式 latex2mathml 转不了，已按原文保留，请在 Word 里核对。",
              file=sys.stderr)
    if st["missing_images"]:
        print("FAIL: 缺图：" + "、".join(st["missing_images"]) + f"（docx 已写出：{out}）", file=sys.stderr)
        return 1
    print(f"OK: paragraphs={st['paragraphs']} headings={st['headings']} tables={st['tables']} "
          f"images={st['images']} omml={st['omml']} text={st['math_text']} out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
