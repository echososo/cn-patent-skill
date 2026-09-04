#!/usr/bin/env python3
"""按描述文件画专利附图：黑白框图 / 流程图 PNG，300 DPI。

用法：
  python3 make_figure.py 图1.json                # 输出 图1.png
  python3 make_figure.py 图1.yaml -o 说明书附图1.png

依赖：pip3 install matplotlib（YAML 输入另需 pyyaml；用 JSON 就不用）

描述文件格式（JSON 或 YAML 同构）：
  {
    "type": "flow",                 # flow 流程图（纵向）| block 框图
    "title": "图1",
    "nodes": [
      {"id": "S101", "label": "接收告警消息"},
      {"id": "S102", "label": "计算指纹", "shape": "box"}   # box|rounded|diamond
    ],
    "edges": [["S101", "S102"], ["S102", "S103", "是"]],    # [起, 止, 可选边标签]
    "rows": [["101"], ["102", "103"]]                       # 仅 block：手动分行；不给则每行一个
  }

专利附图规矩已内置：纯黑白、无彩色、无底纹，节点标号写在框内。

成功时 stdout 最后一行：OK: nodes=.. edges=.. font=.. out=..
失败时 stderr 一行 FAIL: 原因；退出码 2 = 缺依赖，1 = 输入或运行错误。
"""

from __future__ import annotations

import argparse
import json
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


BOX_W, BOX_H = 3.6, 0.9
GAP_Y, GAP_X = 0.7, 0.8


def load_spec(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError:
            msg = "YAML 输入需要 pyyaml：pip3 install pyyaml（或改用 JSON）"
            print(f"FAIL: {msg}", file=sys.stderr)
            raise DependencyMissing(msg)
        return yaml.safe_load(text)
    return json.loads(text)


def pick_cjk_font():
    from matplotlib import font_manager
    preferred = ["Songti SC", "STSong", "SimSun", "SimHei", "PingFang SC",
                 "Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei", "WenQuanYi Zen Hei"]
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in preferred:
        if name in installed:
            return name
    return None


def layout(spec: dict) -> dict[str, tuple[float, float]]:
    nodes = spec.get("nodes", [])
    ids = [n["id"] for n in nodes]
    pos: dict[str, tuple[float, float]] = {}
    if spec.get("type") == "block":
        rows = spec.get("rows") or [[i] for i in ids]
        for r, row in enumerate(rows):
            n = len(row)
            for c, nid in enumerate(row):
                x = (c - (n - 1) / 2) * (BOX_W + GAP_X)
                pos[nid] = (x, -r * (BOX_H + GAP_Y))
    else:  # flow：纵向一条线
        for i, nid in enumerate(ids):
            pos[nid] = (0, -i * (BOX_H + GAP_Y))
    return pos


def draw(spec: dict, out_path: Path) -> dict:
    """画一张图。

    中文字体只在本次调用内生效：走 rc_context 而不是直接改 plt.rcParams，
    否则同一个进程里后面所有 matplotlib 输出都会跟着换字体——
    local_tools.py 的 MCP 进程是长驻的，一次画图污染全场，
    生成的 PDF 还会因为中文字体子集抽不出文字层。
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: F401
    except ImportError:
        msg = "需要先装 matplotlib：pip3 install matplotlib"
        print(f"FAIL: {msg}", file=sys.stderr)
        raise DependencyMissing(msg)

    font = pick_cjk_font()
    with plt.rc_context({"font.family": [font, "DejaVu Sans"]} if font else {}):
        return _draw_figure(spec, out_path, font)


def _draw_figure(spec: dict, out_path: Path, font: str | None) -> dict:
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

    warn = None if font else "本机没找到中文字体，中文可能显示为方块；装任一常见中文字体后重跑"

    nodes = {n["id"]: n for n in spec.get("nodes", [])}
    pos = layout(spec)

    fig, ax = plt.subplots(figsize=(8.27, max(4, 1.2 * len(pos))))  # A4 宽
    for nid, (x, y) in pos.items():
        node = nodes[nid]
        shape = node.get("shape", "box")
        label = f"{nid}\n{node['label']}" if node.get("label") else str(nid)
        common = dict(facecolor="white", edgecolor="black", linewidth=1.2)
        if shape == "rounded":
            ax.add_patch(FancyBboxPatch((x - BOX_W / 2, y - BOX_H / 2), BOX_W, BOX_H,
                                        boxstyle="round,pad=0.08", **common))
        elif shape == "diamond":
            ax.add_patch(plt.Polygon([(x, y + BOX_H * 0.75), (x + BOX_W / 2, y),
                                      (x, y - BOX_H * 0.75), (x - BOX_W / 2, y)], **common))
        else:
            ax.add_patch(Rectangle((x - BOX_W / 2, y - BOX_H / 2), BOX_W, BOX_H, **common))
        ax.text(x, y, label, ha="center", va="center", fontsize=10, color="black")

    def half_h(nid):
        return BOX_H * 0.75 if nodes[nid].get("shape") == "diamond" else BOX_H / 2

    order = {n["id"]: i for i, n in enumerate(spec.get("nodes", []))}
    for edge in spec.get("edges", []):
        a, b = edge[0], edge[1]
        label = edge[2] if len(edge) > 2 else None
        if a not in pos or b not in pos:
            continue
        (x1, y1), (x2, y2) = pos[a], pos[b]
        skip = spec.get("type") != "block" and x1 == x2 and abs(order.get(a, 0) - order.get(b, 0)) > 1
        if skip:
            # 跳过中间节点的边：从右侧绕行，不穿框
            xoff = max(x1, x2) + BOX_W / 2 + 0.9
            start = (x1 + BOX_W / 2, y1)
            end = (x2 + BOX_W / 2, y2)
            ax.plot([start[0], xoff, xoff], [y1, y1, y2], color="black", linewidth=1.1)
            ax.add_patch(FancyArrowPatch((xoff, y2), end, arrowstyle="-|>",
                                         mutation_scale=14, color="black", linewidth=1.1))
            if label:
                ax.text(xoff + 0.15, (y1 + y2) / 2, label, fontsize=9, ha="left", va="center")
            continue
        if abs(y2 - y1) >= abs(x2 - x1):
            start = (x1, y1 - half_h(a) if y2 < y1 else y1 + half_h(a))
            end = (x2, y2 + half_h(b) if y2 < y1 else y2 - half_h(b))
        else:
            start = (x1 + BOX_W / 2 if x2 > x1 else x1 - BOX_W / 2, y1)
            end = (x2 - BOX_W / 2 if x2 > x1 else x2 + BOX_W / 2, y2)
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=14,
                                     color="black", linewidth=1.1))
        if label:
            ax.text((start[0] + end[0]) / 2 + 0.15, (start[1] + end[1]) / 2,
                    label, fontsize=9, ha="left", va="center")

    if spec.get("title"):
        ys = [p[1] for p in pos.values()]
        ax.text(0, min(ys) - BOX_H - 0.3, spec["title"], ha="center", va="top", fontsize=11)

    ax.autoscale()
    ax.margins(0.15)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.savefig(str(out_path), dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return {"nodes": len(pos), "edges": len(spec.get("edges", [])),
            "output": str(out_path), "font": font, "warning": warn}


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = _Parser(description="按 JSON/YAML 描述画黑白专利附图")
    ap.add_argument("spec")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args(argv)
    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f"FAIL: 找不到 {spec_path}", file=sys.stderr)
        return 1
    try:
        spec = load_spec(spec_path)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: 描述文件读不了：{e}", file=sys.stderr)
        return 1
    out = Path(args.output) if args.output else spec_path.with_suffix(".png")
    try:
        r = draw(spec, out)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: 画图出错：{e}", file=sys.stderr)
        return 1
    print(f"{r['nodes']} 个节点、{r['edges']} 条边 → {r['output']}")
    if r["warning"]:
        print("警告：" + r["warning"], file=sys.stderr)
    print(f"OK: nodes={r['nodes']} edges={r['edges']} font={r['font'] or '-'} out={r['output']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
