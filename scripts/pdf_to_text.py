#!/usr/bin/env python3
"""PDF 抽文本：对比文件、通知书 PDF 转成能喂给 agent 的纯文本。

用法：
  python3 pdf_to_text.py 文件.pdf                 # 输出到 文件.txt
  python3 pdf_to_text.py 文件.pdf -o 输出.txt
  python3 pdf_to_text.py 文件.pdf --json          # 元信息走 stdout JSON

依赖：pip3 install pypdf
两种"抽不出正文"的情况都会报出来，不会闷着交给 agent：
  - 扫描件：抽出来几乎没字。提示装 RapidOCR（pip3 install rapidocr-onnxruntime）加 --ocr 重跑。
  - 没有文字层：有字符，但都是 /uni0000004b 这种字体内部编号。这种 PDF 只能从网页版复制原文。

成功时 stdout 最后一行：OK: pages=.. chars=.. scanned=0/1 garbled=0/1 garbled_ratio=.. ocr=0/1 out=..
（--json 时 OK 行打到 stderr，stdout 只有 JSON）。scanned=1 / garbled=1 表示抽出来的内容不能当原文用。
失败时 stderr 一行 FAIL: 原因；退出码 2 = 缺依赖，1 = 输入或运行错误。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
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


SCANNED_THRESHOLD = 30  # 平均每页字符数低于这个值，判断为扫描件

# 有字但不是字：PDF 里的字体没带 ToUnicode 表时，抽出来的是字体内部的字形编号，
# 形如 /uni0000004b、/g23、(cid:113)。这种页字符数不少，扫描件那条判据抓不到，
# 但内容完全不可用——喂给 agent 会被当成正文读，比"没抽到"更危险。
GLYPH_JUNK = re.compile(r"/uni[0-9A-Fa-f]{4,8}|/g\d+|\(cid:\d+\)")
GARBLED_RATIO = 0.3  # 字形编号占掉的字符超过三成，判为没有可用文字层

GARBLED_BANNER = (
    "【警告】这份 PDF 没有可用的文字层：抽出来的是字体内部编号（如 /uni0000004b），不是文字。\n"
    "下面的内容不得当作原文引用，也不得据此写『未检索到』『未公开该特征』。\n"
    "取全文的办法：① 从国知局 / Google Patents 网页版复制原文；② 换一份带文字层的 PDF；\n"
    "③ 按扫描件处理（装 rapidocr-onnxruntime 后走 OCR）。拿到全文之前，该文献留在『需要取得全文』。\n"
)


def _garbled_ratio(text: str) -> float:
    """字形编号字符占全文非空白字符的比例。"""
    body = "".join(text.split())
    if not body:
        return 0.0
    junk = sum(len(m.group()) for m in GLYPH_JUNK.finditer(text))
    return junk / len(body)


def extract(pdf_path: Path, use_ocr: bool = False) -> dict:
    try:
        from pypdf import PdfReader
    except ImportError:
        msg = "需要先装 pypdf：pip3 install pypdf"
        print(f"FAIL: {msg}", file=sys.stderr)
        raise DependencyMissing(msg)

    reader = PdfReader(str(pdf_path))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    total_chars = sum(len(p.strip()) for p in pages)
    scanned = len(pages) > 0 and total_chars / len(pages) < SCANNED_THRESHOLD

    ratio = _garbled_ratio("\n".join(pages))
    garbled = ratio >= GARBLED_RATIO

    ocr_used = False
    if (scanned or garbled) and use_ocr:
        pages, ocr_used = _ocr(pdf_path, pages)
        if ocr_used:
            ratio = _garbled_ratio("\n".join(pages))
            garbled = ratio >= GARBLED_RATIO

    text = "\n\n".join(
        f"【第{i}页】\n{p.strip()}" for i, p in enumerate(pages, 1) if p.strip()
    )
    if garbled:
        # 警告写进正文，不只写 stderr：agent 读的是这个 txt，看不到终端。
        text = GARBLED_BANNER + "\n" + text
    return {
        "pages": len(pages), "chars": sum(len(p) for p in pages),
        "scanned_suspect": scanned, "garbled_suspect": garbled,
        "garbled_ratio": round(ratio, 3), "ocr_used": ocr_used, "text": text,
    }


def _ocr(pdf_path: Path, fallback: list[str]) -> tuple[list[str], bool]:
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
        import pypdf  # noqa: F401
    except ImportError:
        print("提示：这像扫描件，但没装 RapidOCR。装法：pip3 install rapidocr-onnxruntime",
              file=sys.stderr)
        return fallback, False
    # OCR 需要先把页面转图片；不引入额外渲染依赖，提示用户用图片版 OCR 工具处理
    print("提示：RapidOCR 已装，但本脚本不内置 PDF 渲染；请先把 PDF 导出为图片再 OCR，"
          "或使用国知局网页版原文复制。", file=sys.stderr)
    return fallback, False


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = _Parser(description=__doc__)
    ap.add_argument("pdf")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--ocr", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        print(f"FAIL: 找不到 {pdf_path}", file=sys.stderr)
        return 1
    try:
        r = extract(pdf_path, use_ocr=args.ocr)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: PDF 读不了：{e}", file=sys.stderr)
        return 1
    out = Path(args.output) if args.output else pdf_path.with_suffix(".txt")
    out.write_text(r["text"], encoding="utf-8")
    meta = {k: v for k, v in r.items() if k != "text"}
    meta["output"] = str(out)
    ok_line = (f"OK: pages={r['pages']} chars={r['chars']} scanned={int(r['scanned_suspect'])} "
               f"garbled={int(r['garbled_suspect'])} garbled_ratio={r['garbled_ratio']} "
               f"ocr={int(r['ocr_used'])} out={out}")
    if args.json:
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        print(ok_line, file=sys.stderr)
        return 0
    print(f"{r['pages']} 页，{r['chars']} 字符 → {out}")
    if r["scanned_suspect"]:
        print("看起来是扫描件（文字层几乎为空）。装 RapidOCR 后加 --ocr 重跑，"
              "或直接从国知局网页版复制原文。")
    if r["garbled_suspect"]:
        print(f"这份 PDF 有字符但没有可用文字层（{int(r['garbled_ratio'] * 100)}% 是字体内部编号）。"
              "抽出来的内容不能当原文用，请改从网页版复制原文或换一份 PDF。")
    print(ok_line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
