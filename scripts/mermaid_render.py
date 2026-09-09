#!/usr/bin/env python3
# Copyright (c) 2026 handsomestWei — MIT License
# 改编自 handsomestWei/patent-disclosure-skill（MIT）的 tools/mermaid_render.py。
# 改动：去掉 latex_delimiters / stdio_utf8 / math_render 三个包内依赖（只留标准库 + 可选 playwright）；
# 输出改成本包 md_to_docx.py 认的 `![图 N](mermaid_figures/fig_001.png)` 行（原版是保留围栏 + HTML 注释）；
# 围栏源码另存 .mmd；Word 改为 --docx 显式触发并直接 import md_to_docx.convert；
# 退出码与 OK:/FAIL: 行改为本包统一机读约定；--probe 并入本脚本。步骤号补可见标签的逻辑保留。
"""把 Markdown 里的 ```mermaid 围栏渲染成 PNG，写出一份"围栏换成图片引用"的定稿 Markdown。

做的事（输入文件不动）：
  1. 每个 ```mermaid 围栏 → 出图到 <输出md所在目录>/mermaid_figures/fig_001.png、fig_002.png……
  2. 输出 md 里把围栏整段换成一行  ![图 N](mermaid_figures/fig_001.png)
     N 从 1 起顺排；围栏上一行（可隔空行）若是 "图 N ……" 这种自定标题，就沿用那个 N。
  3. 围栏源码另存为 mermaid_figures/fig_001.mmd（存的是实际拿去渲染的那份，含下面第 4 点的修补），
     以后改图直接改 .mmd 再贴回去重跑。
  4. 流程图步骤号只写在节点 id 里的话 PNG 上看不见，脚本会把 S1[采集] 补成 S1["S1 采集"] 再出图。

出图靠 playwright 驱动本机浏览器（Chrome → Edge → playwright 自带 Chromium）加载
scripts/vendor/mermaid.min.js，不联网、不用 Node / mmdc / npx。本脚本**绝不**自动 pip install 或
playwright install，缺什么只在 stderr 提示。

用法：
  python3 mermaid_render.py -i 草稿.md -o 定稿.md
  python3 mermaid_render.py -i 草稿.md -o 定稿.md --docx 定稿.docx     # 顺手出 Word（调同目录 md_to_docx.py）
  python3 mermaid_render.py -i 草稿.md -o 定稿.md --keep-source        # 图片引用后再留一行 <!-- mermaid source: … -->
  python3 mermaid_render.py --probe                                     # 探测浏览器，stdout 一行 JSON

机读约定：
  成功    stdout 最后一行  OK: mermaid=2 fail=0 fixed=3 figures=mermaid_figures out=定稿.md [docx=定稿.docx]
  失败    stderr 一行      FAIL: 原因 …   退出码 2 = 浏览器/环境不可用（定稿 md 仍会写出，围栏原样保留）
                                          退出码 1 = 输入错误或某个围栏渲染失败（该围栏原样保留，其余照常出图）
  --probe stdout 一行 JSON；OK:/FAIL: 行打到 stderr
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import browser  # noqa: E402  同目录，模块级引用便于测试打桩
from browser import BrowserUnavailable  # noqa: E402

_MERMAID_JS = _HERE / "vendor" / "mermaid.min.js"
DEFAULT_ASSETS_DIR = "mermaid_figures"
DEFAULT_SCALE = 2.0
DEFAULT_WIDTH = 1400
DEFAULT_HEIGHT = 1050

RenderOne = Callable[[str, Path], None]

# ---------------------------------------------------------------- 浏览器渲染

_STAGE_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
html, body { margin: 0; background: #fff; }
#stage { display: inline-block; padding: 16px; background: #fff; }
</style>
</head>
<body>
<div id="stage"></div>
</body>
</html>
"""

_RENDER_JS = """async ({ src, rid }) => {
  try {
    mermaid.initialize({
      startOnLoad: false,
      theme: "default",
      securityLevel: "strict",
      fontFamily: '"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",Arial,sans-serif',
      flowchart: { htmlLabels: true, useMaxWidth: false }
    });
    const { svg } = await mermaid.render(rid, src);
    document.getElementById("stage").innerHTML = svg;
    return null;
  } catch (e) {
    return String(e && e.message ? e.message : e);
  }
}
"""


class _PlaywrightMermaid:
    """一次定稿共用一个浏览器实例，逐块渲染。用作上下文管理器。"""

    def __init__(self, *, scale: float = DEFAULT_SCALE, width: int = DEFAULT_WIDTH,
                 height: int = DEFAULT_HEIGHT) -> None:
        self.scale = scale
        self.width = width
        self.height = height
        self.label = ""
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._block_i = 0

    def __enter__(self) -> "_PlaywrightMermaid":
        if not _MERMAID_JS.is_file():
            raise BrowserUnavailable(f"缺少内置 mermaid.min.js：{_MERMAID_JS}（包不完整，请重新解压）")
        if not browser.playwright_installed():
            raise BrowserUnavailable("未安装 playwright。" + browser.install_package_hint())
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        try:
            self._browser, self.label = browser.launch_chromium(self._pw, headless=True)
            self._context = self._browser.new_context(
                viewport={"width": self.width, "height": self.height},
                device_scale_factor=self.scale,
            )
            self._page = self._context.new_page()
        except Exception:
            self.close()
            raise
        return self

    def close(self) -> None:
        for closer in (self._context, self._browser):
            if closer is not None:
                try:
                    closer.close()
                except Exception:
                    pass
        self._context = self._browser = self._page = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None

    def __exit__(self, *exc: object) -> None:
        self.close()

    def render_one(self, mermaid_source: str, png_path: Path) -> None:
        if self._page is None:
            raise RuntimeError("浏览器未启动")
        png_path.parent.mkdir(parents=True, exist_ok=True)
        self._block_i += 1
        page = self._page
        page.set_content(_STAGE_HTML, wait_until="domcontentloaded")
        page.add_script_tag(path=str(_MERMAID_JS))
        page.wait_for_function("() => typeof mermaid !== 'undefined'", timeout=30_000)
        err = page.evaluate(_RENDER_JS, {"src": mermaid_source.strip(), "rid": f"mmd{self._block_i}"})
        if err:
            raise RuntimeError(err)
        page.locator("#stage").screenshot(path=str(png_path), type="png", timeout=60_000)


def _open_renderer(*, scale: float, width: int, height: int) -> _PlaywrightMermaid:
    """启动浏览器；起不来抛 BrowserUnavailable。单独拆出来是为了测试好打桩。"""
    r = _PlaywrightMermaid(scale=scale, width=width, height=height)
    return r.__enter__()


# ---------------------------------------------------------------- 步骤号补进可见标签

_STEP_NODE_RE = re.compile(
    r"(?P<id>[A-Za-z]+\d+)\s*"
    r"(?P<lbr>\[|\(|\{)"
    r"(?:"
    r'(?P<q>["\'])(?P<qlabel>.*?)(?P=q)'
    r"|"
    r"(?P<ulabel>[^\]\)\}]+)"
    r")"
    r"(?P<rbr>\]|\)|\})"
)
_STEP_SHAPE_PAIR = {"[": "]", "(": ")", "{": "}"}
# 形如 S1((…))、S1[[…]]、S1[(…)]、S1{{…}}、S1[/…/]、S1>…] 这些多字符形状不碰，免得把括号配坏
_SPECIAL_SHAPE_LEAD = set("([{|/\\>")


def _label_shows_step_id(label: str, nid: str) -> bool:
    text = label.strip()
    if text == nid:
        return True
    return text.startswith(nid) and (len(text) == len(nid) or text[len(nid)] in " 　:：.-/、")


def _quote_mermaid_label(text: str) -> str:
    if '"' not in text:
        return f'"{text}"'
    if "'" not in text:
        return f"'{text}'"
    return '"' + text.replace('"', "'") + '"'


def ensure_step_ids_in_visible_labels(src: str) -> tuple[str, int]:
    """把 S1[采集] 写成 S1["S1 采集"]，让 PNG 上看得见步骤号（id 本身不出图）。

    返回 (改后源码, 改动处数)。已经带号的标签、注释行、subgraph 行、多字符形状节点都不动。
    """
    n_fix = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal n_fix
        nid, lbr, rbr = m.group("id"), m.group("lbr"), m.group("rbr")
        if _STEP_SHAPE_PAIR.get(lbr) != rbr:
            return m.group(0)
        label = m.group("qlabel")
        if label is None:
            label = m.group("ulabel") or ""
            if label[:1] in _SPECIAL_SHAPE_LEAD:
                return m.group(0)
        if _label_shows_step_id(label, nid):
            return m.group(0)
        n_fix += 1
        return f"{nid}{lbr}{_quote_mermaid_label(f'{nid} {label.strip()}')}{rbr}"

    out: list[str] = []
    for raw in src.splitlines(keepends=True):
        core = raw.rstrip("\r\n")
        nl = raw[len(core):]
        stripped = core.lstrip()
        if stripped.startswith("%%") or stripped.startswith("subgraph "):
            out.append(raw)
            continue
        out.append(_STEP_NODE_RE.sub(repl, core) + nl)
    return "".join(out), n_fix


# ---------------------------------------------------------------- 围栏提取与替换

_FENCE_OPEN_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*(\S*)")
_CAPTION_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\*\*)?图\s*(\d+)")
# 「附图说明」栏目里的条目长这样：图1 是……／图 2 为……。它们不是围栏的标题，
# 只是碰巧排在第一个围栏前面。把它们当标题会让整篇图号从 2 起排（实测踩过）。
_FIGURE_LIST_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\*\*)?图\s*\d+\s*[是为]")


@dataclass
class MermaidBlock:
    index: int                 # 第几个 mermaid 围栏，从 1 起；决定 fig_001 这个文件号
    start: int                 # 开围栏所在行号（0 起）
    end: int                   # 闭围栏所在行号（0 起，含）；没闭合时等于总行数
    source: str                # 围栏内原文
    caption_no: int | None     # 上一行 "图 N" 里的 N；没有则 None


@dataclass
class RenderResult:
    text: str                                  # 新 markdown 全文
    ok: int = 0                                # 换成图片的围栏数
    fail: int = 0                              # 渲染失败、原样保留的围栏数
    fixed: int = 0                             # 补进可见标签的步骤号总数
    figures: list[str] = field(default_factory=list)   # 成功出的 PNG 相对路径
    errors: list[str] = field(default_factory=list)    # 每个失败块一条说明


def _caption_number(lines: list[str], fence_idx: int) -> int | None:
    """围栏上方那行如果是「图 N ……」的自定标题，就沿用那个 N。

    两种情况不算标题，返回 None：
    - 那行是「附图说明」栏目的条目（图 N 是……／图 N 为……）；
    - 它上面还有一行「图 M ……」，说明这是一份图号清单而不是单张图的标题。
    """
    k = fence_idx - 1
    while k >= 0 and not lines[k].strip():
        k -= 1
    if k < 0:
        return None
    m = _CAPTION_RE.match(lines[k])
    if not m:
        return None
    if _FIGURE_LIST_RE.match(lines[k]):
        return None
    prev = k - 1
    while prev >= 0 and not lines[prev].strip():
        prev -= 1
    if prev >= 0 and _CAPTION_RE.match(lines[prev]):
        return None
    return int(m.group(1))


def extract_mermaid_blocks(md_text: str) -> list[MermaidBlock]:
    """找出所有 ```mermaid 围栏。其他语言的围栏会整段跳过，里面就算写着 ```mermaid 也不算。"""
    lines = md_text.splitlines()
    blocks: list[MermaidBlock] = []
    i = 0
    while i < len(lines):
        m = _FENCE_OPEN_RE.match(lines[i])
        if not m:
            i += 1
            continue
        marker, info = m.group(1), m.group(2)
        lang = re.split(r"[\s{]", info, maxsplit=1)[0].lower()
        close_re = re.compile(r"^\s{0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}\s*$")
        j = i + 1
        while j < len(lines) and not close_re.match(lines[j]):
            j += 1
        if lang == "mermaid":
            body = "\n".join(lines[i + 1:j])
            blocks.append(MermaidBlock(
                index=len(blocks) + 1, start=i, end=j,
                source=body + "\n" if body else "",
                caption_no=_caption_number(lines, i),
            ))
        i = j + 1
    return blocks


def render_markdown_mermaid(
    md_text: str,
    *,
    out_md_path: Path,
    assets_rel: str = DEFAULT_ASSETS_DIR,
    render_one: RenderOne | None = None,
    keep_source: bool = False,
    log: Callable[[str], None] | None = None,
) -> RenderResult:
    """核心：替换围栏、落盘 .mmd、调 render_one 出 PNG。

    render_one(源码, png路径) 出一张图，失败抛异常；传 None 表示没有渲染器（比如没浏览器），
    这时所有围栏原样保留、只落 .mmd，fail 计数照加。
    """
    say = log or (lambda s: print(s, file=sys.stderr))
    lines = md_text.splitlines()
    blocks = extract_mermaid_blocks(md_text)
    assets_rel = assets_rel.strip("/\\").replace("\\", "/") or DEFAULT_ASSETS_DIR
    assets_dir = out_md_path.parent / assets_rel
    res = RenderResult(text="")

    out: list[str] = []
    cursor = 0
    fig_no = 0
    for blk in blocks:
        out.extend(lines[cursor:blk.start])
        cursor = min(blk.end + 1, len(lines))

        fixed_src, n_fix = ensure_step_ids_in_visible_labels(blk.source)
        if n_fix:
            res.fixed += n_fix
            say(f"[mermaid_render] 第 {blk.index} 个围栏：{n_fix} 处步骤号已补进可见标签"
                "（S1[文案] → S1[\"S1 文案\"]，否则 PNG 上看不到序号）")
        if fixed_src and not fixed_src.endswith("\n"):
            fixed_src += "\n"

        fig_no = blk.caption_no if blk.caption_no is not None else fig_no + 1
        stem = f"fig_{blk.index:03d}"
        assets_dir.mkdir(parents=True, exist_ok=True)
        (assets_dir / f"{stem}.mmd").write_text(fixed_src, encoding="utf-8")
        png_path = assets_dir / f"{stem}.png"
        rel_png = f"{assets_rel}/{stem}.png"

        if render_one is None:  # 没浏览器：不逐块刷屏，由调用方汇总一句
            res.fail += 1
            res.errors.append(f"第 {blk.index} 个围栏（图 {fig_no}）未出图：无可用浏览器")
            out.extend(lines[blk.start:cursor])
            continue
        try:
            render_one(fixed_src, png_path)
            if not png_path.is_file() or png_path.stat().st_size == 0:
                raise RuntimeError("渲染器没有写出 PNG")
        except Exception as e:
            res.fail += 1
            msg = f"第 {blk.index} 个围栏（图 {fig_no}）渲染失败：{str(e).splitlines()[0] if str(e) else type(e).__name__}"
            res.errors.append(msg)
            say(f"[mermaid_render] {msg}；该围栏已原样保留")
            out.extend(lines[blk.start:cursor])
            continue

        res.ok += 1
        res.figures.append(rel_png)
        say(f"[mermaid_render] 图 {fig_no} → {rel_png}")
        out.append(f"![图 {fig_no}]({rel_png})")
        if keep_source:
            out.append(f"<!-- mermaid source: {assets_rel}/{stem}.mmd -->")

    out.extend(lines[cursor:])
    res.text = "\n".join(out) + "\n"
    return res


# ---------------------------------------------------------------- Word

def write_docx(md_path: Path, docx_path: Path) -> dict:
    """调同目录 md_to_docx.convert。python-docx 没装时它会 SystemExit，这里转成 BrowserUnavailable 之外的
    环境错误交给 main 统一处理。"""
    import md_to_docx  # 同目录

    docx_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return md_to_docx.convert(md_path, docx_path)
    except SystemExit as e:  # md_to_docx 用 SystemExit 报"没装 python-docx"
        raise EnvironmentError(str(e)) from None


# ---------------------------------------------------------------- CLI

def probe() -> dict:
    """浏览器探测 + 内置 mermaid.min.js 在不在。"""
    report = browser.probe_launch()
    report["mermaid_js"] = _MERMAID_JS.is_file()
    if not report["mermaid_js"]:
        report["ok"] = False
        report["error"] = f"mermaid_js_missing {_MERMAID_JS}"
        report["hint"] = "scripts/vendor/mermaid.min.js 丢了，请重新解压技能包"
    return report


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(
        description="Markdown 里的 ```mermaid 围栏 → PNG，围栏换成 ![图 N](mermaid_figures/fig_001.png)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("用法：", 1)[-1] if __doc__ else None,
    )
    ap.add_argument("-i", "--input", type=Path, help="含 mermaid 围栏的 .md（不会被改）")
    ap.add_argument("-o", "--output", type=Path, help="输出 .md；PNG 放在它旁边的 mermaid_figures/")
    ap.add_argument("--assets-dir", default=DEFAULT_ASSETS_DIR,
                    help=f"PNG / .mmd 子目录名，相对输出 .md（默认 {DEFAULT_ASSETS_DIR}）")
    ap.add_argument("--keep-source", action="store_true",
                    help="图片引用后再留一行 <!-- mermaid source: … --> 指向 .mmd")
    ap.add_argument("--docx", type=Path, default=None, metavar="PATH",
                    help="渲染完顺手出 Word（调同目录 md_to_docx.py）；默认不出")
    ap.add_argument("--probe", action="store_true", help="只探测浏览器，stdout 一行 JSON")
    ap.add_argument("--scale", type=float, default=DEFAULT_SCALE, metavar="N",
                    help=f"device_scale_factor（默认 {DEFAULT_SCALE:g}；越大越清晰、文件越大）")
    ap.add_argument("--width", type=int, default=DEFAULT_WIDTH, metavar="PX",
                    help=f"渲染视口宽（默认 {DEFAULT_WIDTH}）")
    ap.add_argument("--height", type=int, default=DEFAULT_HEIGHT, metavar="PX",
                    help=f"渲染视口高（默认 {DEFAULT_HEIGHT}）")
    args = ap.parse_args(argv)

    def fail(reason: str, code: int) -> int:
        print(f"FAIL: {reason}", file=sys.stderr, flush=True)
        return code

    if args.probe:
        return browser.report_probe(probe())

    if args.input is None or args.output is None:
        return fail("missing_args 需要 -i 输入.md 和 -o 输出.md（或 --probe）", 1)
    if args.scale <= 0 or args.width < 400 or args.height < 400:
        return fail("bad_args --scale 须为正数，--width/--height 不小于 400", 1)

    in_path = args.input.resolve()
    out_path = args.output.resolve()
    if not in_path.is_file():
        return fail(f"input_not_found {in_path}", 1)
    if in_path == out_path:
        return fail("same_path 输出不能和输入是同一个文件（输入稿要保持不动）", 1)
    try:
        md = in_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        md = in_path.read_text(encoding="utf-8", errors="replace")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    blocks = extract_mermaid_blocks(md)
    renderer: _PlaywrightMermaid | None = None
    browser_err: str | None = None
    if blocks:
        try:
            renderer = _open_renderer(scale=args.scale, width=args.width, height=args.height)
            print(f"[mermaid_render] 浏览器：{renderer.label}，共 {len(blocks)} 个 mermaid 围栏", file=sys.stderr)
        except BrowserUnavailable as e:
            browser_err = str(e)
    try:
        res = render_markdown_mermaid(
            md,
            out_md_path=out_path,
            assets_rel=args.assets_dir,
            render_one=renderer.render_one if renderer else None,
            keep_source=args.keep_source,
        )
    finally:
        if renderer is not None:
            renderer.close()

    out_path.write_text(res.text, encoding="utf-8")
    print(f"[mermaid_render] 已写出 {out_path}", file=sys.stderr)

    if browser_err:
        print("[mermaid_render] 没有可用浏览器：围栏已原样保留，.mmd 已落盘；装好浏览器后重跑即可出图。"
              " --probe 可查原因。", file=sys.stderr)
        return fail(f"browser_unavailable {browser_err}", 2)
    if res.fail:
        for e in res.errors:
            print(f"[mermaid_render] {e}", file=sys.stderr)
        if args.docx:
            print("[mermaid_render] 有围栏没出图，跳过 Word（md_to_docx 不认代码块）。", file=sys.stderr)
        return fail(f"mermaid_render_failed fail={res.fail} ok={res.ok} out={out_path}", 1)

    docx_note = ""
    if args.docx:
        docx_path = args.docx.resolve()
        if args.keep_source:
            print("[mermaid_render] 提醒：md_to_docx.py 目前不跳过 HTML 注释，--keep-source 的注释行会以文字进 Word。",
                  file=sys.stderr)
        try:
            st = write_docx(out_path, docx_path)
        except ImportError as e:
            return fail(f"md_to_docx_missing 同目录找不到 md_to_docx.py：{e}", 1)
        except EnvironmentError as e:
            return fail(f"docx_unavailable {e}", 2)
        except Exception as e:
            return fail(f"docx_failed {type(e).__name__}: {e}", 1)
        print(f"[mermaid_render] Word：{st.get('images', 0)} 张图、{st.get('headings', 0)} 个标题 → {docx_path}",
              file=sys.stderr)
        if st.get("missing_images"):
            return fail(f"docx_missing_images {'、'.join(st['missing_images'])} docx={docx_path}", 1)
        docx_note = f" docx={docx_path}"

    print(f"OK: mermaid={res.ok} fail={res.fail} fixed={res.fixed} figures={args.assets_dir.strip('/')} "
          f"out={out_path}{docx_note}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
