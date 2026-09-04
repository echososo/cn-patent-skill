#!/usr/bin/env python3
"""把一件案子的审查材料连成一张图。

输入：案件目录（里面放申请文件、证据矩阵、模拟审查报告等 .md 文件，
      表格按本技能 references/ 里的固定格式输出即可）。
输出：<案件目录>/图谱/ 下的一组互相双链的 markdown 笔记 + 一个 案件_图谱.canvas。
      装了 Obsidian 就能看图；没装也能当普通 markdown 读。

用法：
  python3 build_case_graph.py <案件目录>
  python3 build_case_graph.py <案件目录> --out 图谱 --json

解析的东西（都来自技能的固定输出格式，缺哪样就少画哪样）：
  权利要求      「权利要求书」栏目下的编号条目，含引用关系
  区别特征      矩阵 1（表头含「特征编号」和「D1」）
  说明书支持    矩阵 2（表头含「权项」和「说明书段落」），从中提取 SRC-XXX-000 证据编号
  技术效果      矩阵 3（表头含「技术效果」和「因果链」）
  对比文件      矩阵和审查意见里出现的 D1、D2……
  审查问题      「### <前缀>-01」块，前缀取技能的封闭集：OBJ/NOV/INV/SUP/CLR/CLM/EFF/FORM

只读输入文件，生成的东西全在输出目录里；重跑会覆盖自己生成的文件，不动你手写的。

机读约定（全包统一）：成功时 stdout 最后一行 `OK: files=N claims=.. issues=.. ...`（--json 时打到 stderr）；
失败（目录不存在、没解析到内容）时 stderr 一行 `FAIL: 原因`，退出码 1。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

GENERATED_MARK = "generated-by: build_case_graph"

SECTION_HEADINGS = {
    "发明名称", "权利要求书", "说明书", "说明书摘要", "摘要",
    "技术领域", "背景技术", "发明内容", "附图说明", "具体实施方式",
}

ISSUE_HEAD = re.compile(r"^#{2,4}\s*((?:OBJ|NOV|INV|SUP|CLR|CLM|EFF|FORM)-\d+)\s*(.*)$")
SRC_ID = re.compile(r"SRC-[A-Z]+-\d+")
D_REF = re.compile(r"(?<![A-Za-z0-9])D(\d{1,2})(?![0-9])")
PUB_NO = re.compile(r"\b(?:CN|US|WO|EP|JP|KR)\s?\d{6,}[A-Z]?\d?\b")


def norm_heading(line: str) -> str:
    line = line.strip()
    line = re.sub(r"^#{1,6}\s*", "", line)
    line = re.sub(r"^[*_-]+\s*|\s*[*_-]+$", "", line)
    return line.strip().rstrip("：:").strip()


def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|#^\[\]\s]+", "_", value.strip())
    return value.strip("_") or "未命名"


def parse_int_list(text: str) -> list[int]:
    """从「权利要求 1、2」「1-3」「1，3 和 5」这类写法里抠出数字。"""
    out: set[int] = set()
    for m in re.finditer(r"(\d+)\s*[-—至到]\s*(\d+)", text):
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo <= hi <= lo + 50:
            out.update(range(lo, hi + 1))
    cleaned = re.sub(r"(\d+)\s*[-—至到]\s*(\d+)", " ", text)
    out.update(int(n) for n in re.findall(r"\d+", cleaned))
    return sorted(out)


# ---------- 输入解析 ----------

def collect_files(case_dir: Path, out_name: str) -> list[Path]:
    files = []
    for p in sorted(case_dir.rglob("*.md")):
        rel = p.relative_to(case_dir)
        if out_name in rel.parts or any(part.startswith(".") for part in rel.parts):
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:400]
        except OSError:
            continue
        if GENERATED_MARK in head:
            continue
        files.append(p)
    return files


def parse_claims(files: list[Path]) -> tuple[dict[int, str], dict[int, set[int]], Path | None]:
    """返回 (权项文本, 权项引用关系, 来源文件)。取第一个能解析出编号权项的文件。"""
    for path in files:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = None
        for i, line in enumerate(lines):
            if norm_heading(line) == "权利要求书":
                start = i
                break
        if start is None:
            continue
        claims: dict[int, str] = {}
        current = None
        for line in lines[start + 1:]:
            if norm_heading(line) in SECTION_HEADINGS - {"权利要求书"}:
                break
            m = re.match(r"^\s*(\d+)\s*[.．、]\s*(.*)$", line)
            if m:
                current = int(m.group(1))
                claims[current] = m.group(2).strip()
            elif current is not None and line.strip():
                claims[current] = f"{claims[current]} {line.strip()}".strip()
        if claims:
            refs = {}
            for num, text in claims.items():
                found: set[int] = set()
                for m in re.finditer(r"权利要求\s*([0-9\s、,，和或至到\-—]+)", text):
                    found.update(parse_int_list(m.group(1)))
                refs[num] = {r for r in found if r != num}
            return claims, refs, path
    return {}, {}, None


def iter_tables(text: str):
    """产出 (表头单元格列表, 行列表[每行是单元格列表], 表格起始行号)。"""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("|") and i + 1 < len(lines) \
           and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                if any(cells):
                    rows.append(cells)
                j += 1
            yield header, rows, i
            i = j
        else:
            i += 1


def nearest_claim_heading(lines: list[str], table_line: int) -> int | None:
    for k in range(table_line - 1, max(-1, table_line - 16), -1):
        line = lines[k].strip()
        if not line or line.startswith("|"):
            continue
        m = re.search(r"权利要求\s*(\d+)", line)
        if m and len(line) <= 60:
            return int(m.group(1))
    return None


def cell(row: list[str], idx: int) -> str:
    return row[idx].strip() if idx < len(row) else ""


def parse_corpus(files: list[Path]):
    features: dict[str, dict] = {}     # id -> {text, effect, problem, conclusion, claim, d_refs, source}
    evidence: dict[str, dict] = {}     # SRC id -> {contexts: [..], claims: set}
    effects: list[dict] = []           # 矩阵3 行
    d_docs: dict[str, dict] = {}       # D1 -> {label, pubs: set, claims: set, mentions: [...]}
    issues: dict[str, dict] = {}       # INV-01 -> {...}
    support_rows: list[dict] = []      # 矩阵2 行

    def d_doc(key: str) -> dict:
        return d_docs.setdefault(key, {"label": "", "pubs": set(), "claims": set(), "mentions": []})

    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        # 全文里找 D1：CNxxxx《标题》 这类说明
        for m in re.finditer(r"(?<![A-Za-z0-9])D(\d{1,2})\s*[：:（(]\s*([^）)\n]{4,80})", text):
            doc = d_doc(f"D{m.group(1)}")
            if not doc["label"]:
                doc["label"] = m.group(2).strip().rstrip("，。；,;")

        for header, rows, at in iter_tables(text):
            head_join = "".join(header)

            if "特征编号" in head_join and "D1" in head_join:          # 矩阵 1
                claim_no = nearest_claim_heading(lines, at)
                for row in rows:
                    fid = cell(row, 0)
                    if not fid or set(fid) <= {"-", "—"}:
                        continue
                    d1_cell, d2_cell = cell(row, 2), cell(row, 6)
                    feat = features.setdefault(safe_name(fid), {
                        "raw": fid, "text": cell(row, 1), "d1_map": d1_cell,
                        "diff": cell(row, 3), "effect": cell(row, 4),
                        "problem": cell(row, 5), "d2": d2_cell,
                        "conclusion": cell(row, 8), "claim": claim_no,
                        "d_refs": set(), "source": path.name,
                    })
                    row_text = " ".join(row)
                    for dm in D_REF.finditer(row_text):
                        feat["d_refs"].add(f"D{dm.group(1)}")
                    if d1_cell:
                        doc = d_doc("D1")
                        doc["pubs"].update(PUB_NO.findall(d1_cell))
                        if claim_no:
                            doc["claims"].add(claim_no)
                        doc["mentions"].append(f"{path.name}：{fid} 映射「{d1_cell[:60]}」")
                    for dm in D_REF.finditer(d2_cell):
                        doc = d_doc(f"D{dm.group(1)}")
                        doc["pubs"].update(PUB_NO.findall(d2_cell))
                        if claim_no:
                            doc["claims"].add(claim_no)
                        doc["mentions"].append(f"{path.name}：{fid} 组合评价「{d2_cell[:60]}」")

            elif "权项" in header[0] and "说明书段落" in head_join:      # 矩阵 2
                for row in rows:
                    nums = parse_int_list(cell(row, 0))
                    entry = {
                        "claims": nums, "feature": cell(row, 1),
                        "paras": cell(row, 2), "steps": cell(row, 3),
                        "figures": cell(row, 4), "src": cell(row, 5),
                        "basis": cell(row, 6), "level": cell(row, 7),
                        "status": cell(row, 8), "source": path.name,
                    }
                    support_rows.append(entry)
                    for sid in SRC_ID.findall(" ".join(row)):
                        ev = evidence.setdefault(sid, {"contexts": [], "claims": set()})
                        ev["contexts"].append(
                            f"{path.name}·矩阵2：支持权项 {cell(row,0)} 的「{cell(row,1)[:40]}」，状态 {cell(row,8) or '未填'}")
                        ev["claims"].update(nums)

            elif "技术效果" in header[0] and "因果链" in head_join:      # 矩阵 3
                for row in rows:
                    entry = {
                        "effect": cell(row, 0), "baseline": cell(row, 1),
                        "metric": cell(row, 2), "raw": cell(row, 3),
                        "chain": cell(row, 4), "boundary": cell(row, 5),
                        "claim_text": cell(row, 6), "status": cell(row, 7),
                        "source": path.name,
                    }
                    effects.append(entry)
                    for sid in SRC_ID.findall(" ".join(row)):
                        ev = evidence.setdefault(sid, {"contexts": [], "claims": set()})
                        ev["contexts"].append(
                            f"{path.name}·矩阵3：效果「{cell(row,0)[:40]}」的原始结果，状态 {cell(row,7) or '未填'}")

        # INV 块
        current = None
        for line in lines:
            m = ISSUE_HEAD.match(line.strip())
            if m:
                current = m.group(1)
                issues[current] = {"title": m.group(2).strip(), "severity": "", "status": "",
                                   "claims": set(), "conclusion": "", "basis": "",
                                   "d_refs": set(), "source": path.name, "fields": []}
                continue
            if current is None:
                continue
            fm = re.match(r"^\s*-\s*([^：:]{2,12})[：:]\s*(.*)$", line)
            if not fm:
                if line.strip().startswith("#"):
                    current = None
                continue
            key, value = fm.group(1).strip(), fm.group(2).strip()
            rec = issues[current]
            rec["fields"].append((key, value))
            if "严重" in key or "强度" in key:
                rec["severity"] = value.replace("【", "").replace("】", "").split("/")[0].strip()
            elif "台账" in key:
                rec["status"] = value
            elif "涉及权项" in key or "针对位置" in key:
                rec["claims"].update(parse_int_list(value))
            elif key.startswith("结论"):
                rec["conclusion"] = value
            elif "审查标准" in key or "审查依据" in key or "法律" in key:
                rec["basis"] = value
            elif "对比文件" in key:
                for dm in D_REF.finditer(value):
                    rec["d_refs"].add(f"D{dm.group(1)}")

    return features, evidence, effects, d_docs, issues, support_rows


# ---------- 输出 ----------

def frontmatter(tags: list[str], case: str, extra: dict | None = None) -> str:
    out = ["---", GENERATED_MARK, f"case: {case}",
           f"generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
           "tags:"] + [f"  - {t}" for t in tags]
    for k, v in (extra or {}).items():
        out.append(f"{k}: {v}")
    out.append("---")
    return "\n".join(out) + "\n\n"


def write_note(path: Path, content: str, written: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    written.append(str(path))


def sweep_stale(out_dir: Path, written: list[str]) -> list[str]:
    """删掉上一轮生成、这一轮不再出现的笔记，只删自己生成的那些。

    存在的理由：审查报告改了问题编号（比如 INV-01 改判成 CLM-01）之后，旧编号那份笔记
    会一直躺在 图谱/ 里——Obsidian 照样显示、总览里也点得进去，看起来像这件案子真有
    这个问题。手写笔记（文件头没有 generated-by 标记）一律不碰。
    """
    keep = {str(Path(p).resolve()) for p in written}
    removed = []
    for p in sorted(out_dir.rglob("*.md")):
        if not p.is_file() or str(p.resolve()) in keep:
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:400]
        except OSError:
            continue
        if GENERATED_MARK in head:
            p.unlink()
            removed.append(str(p))
    # 清完可能空掉的子目录（比如这轮一个审查问题都没有）
    for d in sorted(out_dir.rglob("*"), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return removed


def build(case_dir: Path, out_name: str) -> dict:
    files = collect_files(case_dir, out_name)
    claims, claim_refs, claims_file = parse_claims(files)
    features, evidence, effects, d_docs, issues, support_rows = parse_corpus(files)

    if not (claims or features or issues or evidence):
        raise SystemExit("没解析到任何内容：案件目录里要有权利要求书、证据矩阵或模拟审查输出（.md）。")

    case = case_dir.name
    out_dir = case_dir / out_name
    written: list[str] = []

    def link(folder: str, name: str) -> str:
        return f"[[{name}]]"

    # 权利要求笔记
    for num in sorted(claims):
        deps = sorted(claim_refs.get(num, set()))
        kind = "独立" if not deps else "从属"
        feats = [f for f in features.values() if f["claim"] == num]
        srcs = sorted(sid for sid, ev in evidence.items() if num in ev["claims"])
        invs = sorted(k for k, v in issues.items() if num in v["claims"])
        hits = sorted(k for k, v in d_docs.items() if num in v["claims"])
        sup = [r for r in support_rows if num in r["claims"]]

        body = frontmatter(["案件图谱", "权利要求", kind], case)
        body += f"# 权利要求 {num}（{kind}）\n\n> {claims[num][:400]}\n\n"
        if deps:
            body += "引用：" + "、".join(f"[[权利要求 {d}]]" for d in deps) + "\n\n"
        if feats:
            body += "## 区别特征\n\n" + "".join(
                f"- [[特征 {safe_name(f['raw'])}]]：{f['text'][:60]}（结论：{f['conclusion'] or '未填'}）\n"
                for f in feats) + "\n"
        if sup:
            body += "## 说明书支持（矩阵 2）\n\n"
            for r in sup:
                body += (f"- {r['feature'][:50]} → {r['paras'] or '未填'}"
                         f"{'，退守 ' + r['level'] if r['level'] else ''}"
                         f"，状态 {r['status'] or '未填'}\n")
            body += "\n"
        if srcs:
            body += "## 证据\n\n" + "".join(f"- [[{s}]]\n" for s in srcs) + "\n"
        if hits:
            body += "## 对比文件命中\n\n" + "".join(f"- [[{d}]]\n" for d in hits) + "\n"
        if invs:
            body += "## 审查问题\n\n" + "".join(
                f"- [[{k}]] {issues[k]['severity']}（{issues[k]['conclusion'] or issues[k]['status'] or '未处置'}）\n"
                for k in invs) + "\n"
        write_note(out_dir / "权利要求" / f"权利要求 {num}.md", body, written)

    for fid, f in sorted(features.items()):
        body = frontmatter(["案件图谱", "区别特征"], case)
        body += f"# 特征 {f['raw']}\n\n> {f['text'] or '（矩阵 1 里没写权项表述）'}\n\n"
        if f["claim"]:
            body += f"所属：[[权利要求 {f['claim']}]]\n\n"
        body += (f"- D1 映射：{f['d1_map'] or '未填'}\n- 区别及关系：{f['diff'] or '未填'}\n"
                 f"- 技术效果：{f['effect'] or '未填'}\n- 实际技术问题：{f['problem'] or '未填'}\n"
                 f"- D2/公知常识：{f['d2'] or '未填'}\n- 结论：**{f['conclusion'] or '未填'}**\n")
        if f["d_refs"]:
            body += "\n涉及对比文件：" + "、".join(f"[[{d}]]" for d in sorted(f["d_refs"])) + "\n"
        body += f"\n来源：{f['source']}\n"
        write_note(out_dir / "区别特征" / f"特征 {fid}.md", body, written)

    for dkey, doc in sorted(d_docs.items()):
        body = frontmatter(["案件图谱", "对比文件"], case)
        title = doc["label"] or "（未在材料里找到文献描述，检索记录里补一行「D1：文献号 标题」即可）"
        body += f"# {dkey}\n\n{title}\n\n"
        if doc["pubs"]:
            body += "文献号：" + "、".join(sorted(doc["pubs"])) + "\n\n"
        if doc["claims"]:
            body += "命中：" + "、".join(f"[[权利要求 {c}]]" for c in sorted(doc["claims"])) + "\n\n"
        if doc["mentions"]:
            body += "## 材料里的出处\n\n" + "".join(f"- {m}\n" for m in doc["mentions"][:12])
        write_note(out_dir / "对比文件" / f"{dkey}.md", body, written)

    for sid, ev in sorted(evidence.items()):
        body = frontmatter(["案件图谱", "证据"], case)
        body += f"# {sid}\n\n"
        if ev["claims"]:
            body += "支撑：" + "、".join(f"[[权利要求 {c}]]" for c in sorted(ev["claims"])) + "\n\n"
        body += "## 出现位置\n\n" + "".join(f"- {c}\n" for c in ev["contexts"])
        write_note(out_dir / "证据" / f"{sid}.md", body, written)

    for key, rec in sorted(issues.items()):
        body = frontmatter(["案件图谱", "审查问题"], case)
        body += f"# {key} {rec['title']}\n\n"
        body += (f"- 严重程度：**{rec['severity'] or '未填'}**\n- 台账状态：{rec['status'] or '未填'}\n"
                 f"- 结论：{rec['conclusion'] or '未填'}\n- 依据：{rec['basis'] or '未填'}\n")
        if rec["claims"]:
            body += "- 指向：" + "、".join(f"[[权利要求 {c}]]" for c in sorted(rec["claims"])) + "\n"
        if rec["d_refs"]:
            body += "- 对比文件：" + "、".join(f"[[{d}]]" for d in sorted(rec["d_refs"])) + "\n"
        body += "\n## 原始字段\n\n" + "".join(f"- {k}：{v}\n" for k, v in rec["fields"] if v)
        body += f"\n来源：{rec['source']}\n"
        write_note(out_dir / "审查问题" / f"{key}.md", body, written)

    if effects:
        body = frontmatter(["案件图谱", "技术效果"], case)
        body += "# 技术效果台账（矩阵 3）\n\n"
        for i, e in enumerate(effects, 1):
            body += (f"## 效果 {i}：{e['effect'][:60]}\n\n"
                     f"- 对照基线：{e['baseline'] or '未填'}\n- 指标与算法：{e['metric'] or '未填'}\n"
                     f"- 原始结果：{e['raw'] or '未填'}\n- 因果链：{e['chain'] or '未填'}\n"
                     f"- 成立边界：{e['boundary'] or '未填'}\n- 状态：**{e['status'] or '未填'}**\n\n")
        write_note(out_dir / "技术效果台账.md", body, written)

    # 总览
    fatal = sum(1 for r in issues.values() if "致命" in r["severity"])
    major = sum(1 for r in issues.values() if "重要" in r["severity"])
    body = frontmatter(["案件图谱", "总览"], case)
    body += f"# 案件总览：{case}\n\n"
    body += f"打开 [[案件_图谱.canvas|案件_图谱]] 看整张图（要 Obsidian）；下面的链接点进去是一样的内容。\n\n"
    body += (f"| 权利要求 | 区别特征 | 对比文件 | 证据 | 审查问题 |\n|---|---|---|---|---|\n"
             f"| {len(claims)} | {len(features)} | {len(d_docs)} | {len(evidence)} "
             f"| {len(issues)}（致命 {fatal}，重要 {major}） |\n\n")
    if claims_file:
        body += f"申请文件：{claims_file.name}\n\n"
    for title, folder, names in [
        ("权利要求", "权利要求", [f"权利要求 {n}" for n in sorted(claims)]),
        ("审查问题", "审查问题", sorted(issues)),
        ("对比文件", "对比文件", sorted(d_docs)),
        ("区别特征", "区别特征", [f"特征 {k}" for k in sorted(features)]),
        ("证据", "证据", sorted(evidence)),
    ]:
        if names:
            body += f"## {title}\n\n" + "".join(f"- [[{n}]]\n" for n in names) + "\n"
    write_note(out_dir / "案件总览.md", body, written)

    canvas = build_canvas(case, claims, claim_refs, features, evidence, d_docs, issues)
    write_note(out_dir / "案件_图谱.canvas", json.dumps(canvas, ensure_ascii=False, indent=1), written)

    stale = sweep_stale(out_dir, written)

    return {
        "case": case, "out_dir": str(out_dir), "files_scanned": [f.name for f in files],
        "claims": len(claims), "features": len(features), "d_docs": len(d_docs),
        "evidence": len(evidence), "issues": len(issues), "effects": len(effects),
        "fatal_issues": fatal, "major_issues": major,
        "notes_written": len(written), "stale_removed": [Path(p).name for p in stale],
        "canvas_nodes": len(canvas["nodes"]), "canvas_edges": len(canvas["edges"]),
    }


def build_canvas(case, claims, claim_refs, features, evidence, d_docs, issues) -> dict:
    nodes, edges = [], []
    pos: dict[str, str] = {}   # 逻辑 id -> canvas node id

    def add(logical: str, text: str, x: int, y: int, color: str, w=340, h=130):
        nid = f"n{len(nodes):03d}"
        pos[logical] = nid
        nodes.append({"id": nid, "type": "text", "text": text,
                      "x": x, "y": y, "width": w, "height": h, "color": color})

    def connect(a: str, b: str, label: str, color: str, from_side="right", to_side="left"):
        if a in pos and b in pos:
            edges.append({"id": f"e{len(edges):03d}", "fromNode": pos[a], "fromSide": from_side,
                          "toNode": pos[b], "toSide": to_side, "label": label, "color": color})

    step = 170
    add("overview", f"## {case}\n[[案件总览]]", -420, -260, "3", 400, 100)

    for i, dkey in enumerate(sorted(d_docs)):
        label = d_docs[dkey]["label"]
        add(dkey, f"**[[{dkey}]]**\n{label[:50] if label else '对比文件'}", -1300, i * step, "2")
    for i, num in enumerate(sorted(claims)):
        kind = "独立" if not claim_refs.get(num) else "从属"
        add(f"c{num}", f"**[[权利要求 {num}]]**（{kind}）\n{claims[num][:60]}…", -420, i * step, "5", 400)
    for i, (fid, f) in enumerate(sorted(features.items())):
        add(f"f{fid}", f"**[[特征 {fid}]]**\n{(f['text'] or '')[:50]}\n结论：{f['conclusion'] or '未填'}", 240, i * step, "6")
    for i, sid in enumerate(sorted(evidence)):
        add(sid, f"**[[{sid}]]**", 880, i * step, "4", 260, 80)

    issue_y0 = len(claims) * step + 160
    for i, (key, rec) in enumerate(sorted(issues.items())):
        color = "4" if any(w in (rec["conclusion"] + rec["status"]) for w in ("已解决", "撤回")) \
                else ("1" if "致命" in rec["severity"] or "重要" in rec["severity"] else "2")
        add(key, f"**[[{key}]]** {rec['severity']}\n{rec['title'][:40]}", -420, issue_y0 + i * 130, color, 400, 100)

    for num, deps in claim_refs.items():
        for dep in deps:
            connect(f"c{num}", f"c{dep}", "引用", "5", "left", "right")
    for dkey, doc in d_docs.items():
        for num in doc["claims"]:
            connect(dkey, f"c{num}", "命中", "2")
    for fid, f in features.items():
        if f["claim"]:
            connect(f"c{f['claim']}", f"f{fid}", "区别特征", "6")
        for dkey in f["d_refs"]:
            connect(dkey, f"f{fid}", "映射/组合", "2")
    for sid, ev in evidence.items():
        for num in ev["claims"]:
            connect(f"c{num}", sid, "证据", "4")
    for key, rec in issues.items():
        for num in rec["claims"]:
            connect(key, f"c{num}", "指向", "1", "top", "bottom")

    return {"nodes": nodes, "edges": edges}


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


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="把一件案子的审查材料连成 Obsidian 双链笔记和 Canvas 图")
    ap.add_argument("case_dir", help="案件目录")
    ap.add_argument("--out", default="图谱", help="输出子目录名（默认：图谱）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args(argv)

    case_dir = Path(args.case_dir).resolve()
    if not case_dir.is_dir():
        print(f"错误：{case_dir} 不是目录", file=sys.stderr)
        _fail(f"not_a_directory {case_dir}")
        return 1      # 输入错误是 1；2 留给"依赖/入口不可用"
    try:
        summary = build(case_dir, args.out)
    except SystemExit as e:       # build() 没解析到内容时带着人话原因退出；原样转述，再补机读行
        if e.code in (None, 0):
            raise
        print(e.code, file=sys.stderr)
        _fail(f"nothing_parsed {e.code}")
        return 1
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"案件：{summary['case']}")
        print(f"扫描 {len(summary['files_scanned'])} 个文件，写出 {summary['notes_written']} 个文件到 {summary['out_dir']}")
        if summary["stale_removed"]:
            print(f"清掉 {len(summary['stale_removed'])} 个上一轮留下、这轮已不存在的笔记："
                  + "、".join(summary["stale_removed"]))
        print(f"权利要求 {summary['claims']}｜区别特征 {summary['features']}｜对比文件 {summary['d_docs']}"
              f"｜证据 {summary['evidence']}｜审查问题 {summary['issues']}（致命 {summary['fatal_issues']}）")
        print(f"图：{summary['canvas_nodes']} 个节点，{summary['canvas_edges']} 条边。"
              f"用 Obsidian 打开案件目录（或它所在的库），点 图谱/案件_图谱.canvas")
    _ok({"files": summary["notes_written"], "scanned": len(summary["files_scanned"]),
         "stale": len(summary["stale_removed"]), "claims": summary["claims"],
         "features": summary["features"], "d_docs": summary["d_docs"], "evidence": summary["evidence"],
         "issues": summary["issues"], "fatal": summary["fatal_issues"],
         "nodes": summary["canvas_nodes"], "edges": summary["canvas_edges"]}, to_stderr=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
