#!/usr/bin/env python3
"""Word 稿 → Markdown：代理师发来的 docx 转成 agent 能整段处理的 md，图片抽到旁边的 _media 文件夹。

用法：
  python3 docx_to_md.py 稿件.docx                 # 输出 稿件.md + 稿件_media/
  python3 docx_to_md.py 稿件.docx -o 输出.md

依赖：pip3 install python-docx

成功时 stdout 最后一行：OK: paragraphs=.. headings=.. tables=.. images=.. out=.. media_dir=..
失败时 stderr 一行 FAIL: 原因；退出码 2 = 缺依赖，1 = 输入或运行错误。
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path


class _Parser(argparse.ArgumentParser):
    """参数错误也走 FAIL: 行，退出码 1（argparse 默认 2，会和"缺依赖"混淆）。"""

    def error(self, message):
        print(f"FAIL: 参数错误：{message}", file=sys.stderr)
        raise SystemExit(1)


class DependencyMissing(SystemExit):
    """缺依赖：退出码固定 2，str() 是人话。"""

    def __init__(self, msg: str):
        super().__init__(2)
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


HEADING_MAP = {"Heading 1": "#", "Heading 2": "##", "Heading 3": "###",
               "标题 1": "#", "标题 2": "##", "标题 3": "###",
               "Title": "#"}


def extract_media(docx_path: Path, media_dir: Path) -> dict[str, str]:
    """word/media/* -> 落盘文件；返回 内部路径 -> 相对引用路径。"""
    mapping = {}
    with zipfile.ZipFile(docx_path) as z:
        for name in z.namelist():
            if name.startswith("word/media/"):
                media_dir.mkdir(parents=True, exist_ok=True)
                target = media_dir / Path(name).name
                target.write_bytes(z.read(name))
                mapping[name] = f"{media_dir.name}/{target.name}"
    return mapping


def rel_map(document) -> dict[str, str]:
    """rId -> word/media/xxx"""
    out = {}
    for rid, rel in document.part.rels.items():
        if "image" in rel.reltype:
            out[rid] = "word/" + rel.target_ref.lstrip("/") if not rel.target_ref.startswith("word/") \
                       else rel.target_ref
    return out


def para_images(para, rels: dict[str, str]) -> list[str]:
    from docx.oxml.ns import qn
    rids = []
    for blip in para._element.iter(qn("a:blip")):
        rid = blip.get(qn("r:embed"))
        if rid and rid in rels:
            rids.append(rels[rid])
    return rids


def convert(docx_path: Path, out_path: Path) -> dict:
    try:
        import docx
    except ImportError:
        msg = "需要先装 python-docx：pip3 install python-docx"
        print(f"FAIL: {msg}", file=sys.stderr)
        raise DependencyMissing(msg)

    document = docx.Document(str(docx_path))
    media_dir = out_path.parent / f"{out_path.stem}_media"
    media = extract_media(docx_path, media_dir)
    rels = rel_map(document)

    lines: list[str] = []
    stats = {"paragraphs": 0, "headings": 0, "images": 0, "tables": 0}

    from docx.table import Table
    from docx.text.paragraph import Paragraph
    body = document.element.body
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            para = Paragraph(child, document)
            text = para.text.strip()
            style = para.style.name if para.style is not None else ""
            for internal in para_images(para, rels):
                ref = media.get(internal)
                if ref:
                    lines.append(f"![]({ref})")
                    lines.append("")
                    stats["images"] += 1
            if not text:
                continue
            prefix = HEADING_MAP.get(style)
            if prefix:
                lines.append(f"{prefix} {text}")
                stats["headings"] += 1
            else:
                lines.append(text)
                stats["paragraphs"] += 1
            lines.append("")
        elif child.tag.endswith("}tbl"):
            table = Table(child, document)
            rows = [[re.sub(r"\s+", " ", cell.text).strip() for cell in row.cells]
                    for row in table.rows]
            if rows:
                lines.append("| " + " | ".join(rows[0]) + " |")
                lines.append("|" + "---|" * len(rows[0]))
                for row in rows[1:]:
                    lines.append("| " + " | ".join(row) + " |")
                lines.append("")
                stats["tables"] += 1

    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    stats["output"] = str(out_path)
    stats["media_dir"] = str(media_dir) if media else None
    return stats


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = _Parser(description=__doc__)
    ap.add_argument("docx")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args(argv)
    src = Path(args.docx)
    if not src.is_file():
        print(f"FAIL: 找不到 {src}", file=sys.stderr)
        return 1
    out = Path(args.output) if args.output else src.with_suffix(".md")
    try:
        st = convert(src, out)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: 转换出错：{e}", file=sys.stderr)
        return 1
    print(f"{st['paragraphs']} 段、{st['headings']} 个标题、{st['tables']} 张表、"
          f"{st['images']} 张图 → {out}")
    print(f"OK: paragraphs={st['paragraphs']} headings={st['headings']} tables={st['tables']} "
          f"images={st['images']} out={out} media_dir={st['media_dir'] or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
