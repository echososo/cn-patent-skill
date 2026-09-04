#!/usr/bin/env python3
"""把一件案子的检索轨迹台账画成图：查过什么、比过什么、每一步为什么这么选。

输入：案件目录里的 `检索轨迹台账.md`（格式见 references/search-trail.md：候选、轮次、查询式、
      文献、对照五张固定列的表）。
输出：<案件目录>/图谱/检索轨迹/ 下
      检索轨迹总览.md            工作量数字、候选×轮次演变表、最终路线怎么来的、还有什么没查完
      检索轨迹图谱.html          双击即开、不联网的单文件网页：可拖拽缩放收放的知识图谱 + 四列流程图，
                                 都能导出 PNG；这是主要产物，任何浏览器都能打开
      候选/ 轮次/ 文献/          互相双链的 markdown 笔记，Obsidian 用户从总览点进去

用法：
  python3 build_search_trail.py <案件目录>
  python3 build_search_trail.py <案件目录> --ledger 某处/检索轨迹台账.md --out 图谱/检索轨迹 --json

词表封闭：最终去向、类型、全文状态、最终角色、判定、影响六列只认 references/search-trail.md
列出的词，遇到别的直接报错停下，不猜——同一件案子两轮各写各的，图就对不上了。

只读输入文件，生成的东西全在输出目录里；重跑会覆盖自己生成的文件，不动你手写的。
它和 build_case_graph.py 各管各的标记，可以并存在同一个 图谱/ 下。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path

GENERATED_MARK = "generated-by: build_search_trail"
LEDGER_TITLE = "检索轨迹台账"

# 对照表「文献」列除了 P 编号，还认三个不是文献的来源：
PSEUDO = {"公知常识": "CK", "实验": "EX", "决策": "DC"}
PSEUDO_LABEL = {
    "CK": ("公知常识", "靠常识或原理打的判定"),
    "EX": ("本案实验", "本案实测结果推翻或支持了候选"),
    "DC": ("人为决策", "用户或代理师基于篇幅、策略的取舍"),
}
# 文献和公知常识用前六个判定词；实验只能用实测推翻/实测支持；决策只能用人为取舍
VERDICT_DOC = ("明文记载", "毫无疑义确定", "部分接近", "未记载", "记载不清", "教导相反")
VERDICT_EX = ("实测推翻", "实测支持")
VERDICT_DC = ("人为取舍",)

VOCAB = {
    "最终去向": ("独权核心", "从属权项", "仅说明书", "放弃", "待定"),
    "类型": ("专利", "论文", "标准", "产品资料", "开源代码", "其他"),
    "全文状态": ("已读全文", "仅摘要", "未取得", "被阻断"),
    "判定": VERDICT_DOC + VERDICT_EX + VERDICT_DC,
    "影响": ("放弃", "降为从属", "降为说明书", "升为核心", "保留", "收窄", "新增候选", "无影响"),
}
ROLE_FIXED = ("背景技术", "答辩材料", "无关", "线索未解决")
ROLE_D = re.compile(r"^D\d{1,2}$")

ID_C = re.compile(r"^C\d{1,3}$")
ID_R = re.compile(r"^R\d{1,3}$")
ID_P = re.compile(r"^P\d{1,3}$")

# 判定 → 颜色语义（HTML 用）
VERDICT_KIND = {
    "明文记载": "killed", "毫无疑义确定": "killed", "实测推翻": "killed",
    "部分接近": "near", "记载不清": "near",
    "未记载": "clear", "教导相反": "away", "实测支持": "clear",
    "人为取舍": "decision",
}
HTML_COLOR = {"killed": "#d94a3d", "near": "#e0962e", "clear": "#3f9d5a", "away": "#2f7fc1", "found": "#9aa3ad", "decision": "#8a8f98"}
FATE_ORDER = ("独权核心", "从属权项", "仅说明书", "待定", "放弃")
FATE_HTML = {"独权核心": "#2f7fc1", "从属权项": "#7d5bb8", "仅说明书": "#c9a227", "待定": "#e0962e", "放弃": "#d94a3d"}


class LedgerError(Exception):
    """台账本身有问题（缺表、词不在词表里、编号对不上）。错误信息给人看，一次列全。"""


# ---------- 小工具 ----------

def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|#^\[\]\s]+", "_", value.strip())
    return value.strip("_") or "未命名"


def clean(cell_text: str) -> str:
    t = cell_text.strip().replace("**", "").replace("`", "")
    return "" if t in {"—", "-", "－", "无", "N/A", "n/a"} else t


def norm_id(text: str) -> str:
    t = clean(text).upper().replace(" ", "")
    # 全角字母数字转半角
    return "".join(chr(ord(ch) - 0xFEE0) if 0xFF01 <= ord(ch) <= 0xFF5E else ch for ch in t)


def iter_tables(text: str):
    """产出 (表头单元格列表, 行列表, 表格起始行号)。"""
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
                    rows.append((cells, j + 1))
                j += 1
            yield header, rows, i + 1
            i = j
        else:
            i += 1


def cell(row: list[str], idx: int) -> str:
    return clean(row[idx]) if idx < len(row) else ""


def round_key(rid: str) -> int:
    m = re.search(r"\d+", rid)
    return int(m.group()) if m else 0


# ---------- 找台账 ----------

def find_ledger(case_dir: Path, out_name: str, explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            p = case_dir / p
        if not p.is_file():
            raise LedgerError(f"指定的台账不存在：{p}")
        return p
    hits = []
    for p in sorted(case_dir.rglob("*.md")):
        rel = p.relative_to(case_dir)
        if any(part.startswith(".") for part in rel.parts) or rel.parts[0] == out_name.split("/")[0]:
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:400]
        except OSError:
            continue
        if GENERATED_MARK in head:
            continue
        if LEDGER_TITLE in p.name or re.search(r"^#\s*" + LEDGER_TITLE, head, re.M):
            hits.append(p)
    if not hits:
        raise LedgerError(f"{case_dir} 里没找到《{LEDGER_TITLE}.md》。格式见 references/search-trail.md；"
                          "台账放在别处时用 --ledger 指定。")
    if len(hits) > 1:
        raise LedgerError("找到多份台账，不知道该用哪份：\n  " + "\n  ".join(str(h) for h in hits)
                          + "\n用 --ledger 指定一份。")
    return hits[0]


# ---------- 解析 ----------

def parse_ledger(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    errors: list[str] = []
    warnings: list[str] = []

    meta: dict[str, str] = {}
    case_title = ""
    for line in lines:
        if line.lstrip().startswith("|"):
            break
        m = re.match(r"^#\s*" + LEDGER_TITLE + r"\s*[：:]?\s*(.*)$", line.strip())
        if m:
            case_title = m.group(1).strip()
            continue
        m = re.match(r"^\s*[-*]\s*([^：:]{1,20})[：:]\s*(.*)$", line)
        if m:
            meta[m.group(1).strip()] = m.group(2).strip()

    tables = {"候选": None, "轮次": None, "查询": None, "文献": None, "对照": None}
    for header, rows, at in iter_tables(text):
        head = "".join(header)
        first = header[0] if header else ""
        if "候选" in first and "去向" in head:
            key = "候选"
        elif "查询式" in head and "命中" in head:
            key = "查询"
        elif "轮次" in first and "入口" in head:
            key = "轮次"
        elif "文献号" in head and "角色" in head:
            key = "文献"
        elif "判定" in head and "影响" in head:
            key = "对照"
        else:
            continue
        if tables[key] is not None:
            errors.append(f"第 {at} 行：{key}表出现了第二次，一份台账里每张表只能有一张（要分段就在同一张表里加行）")
            continue
        tables[key] = rows

    need = {"候选": "候选…去向", "轮次": "轮次…入口", "文献": "文献号…角色", "对照": "判定…影响"}
    for key, hint in need.items():
        if tables[key] is None:
            errors.append(f"缺{key}表（表头至少要含：{hint}）")
    if errors:
        raise LedgerError("\n".join(errors))

    def vocab(col: str, value: str, where: str) -> str:
        if value and value not in VOCAB[col]:
            errors.append(f"{where}：{col}「{value}」不在词表里，只能用：{'、'.join(VOCAB[col])}")
        return value

    candidates: dict[str, dict] = {}
    for row, ln in tables["候选"]:
        cid = norm_id(cell(row, 0))
        if not cid:
            continue
        where = f"候选表第 {ln} 行"
        if not ID_C.match(cid):
            errors.append(f"{where}：候选编号「{cid}」要写成 C1、C2 这样")
            continue
        if cid in candidates:
            errors.append(f"{where}：候选 {cid} 重复")
            continue
        fate = vocab("最终去向", cell(row, 4), where)
        candidates[cid] = {
            "id": cid, "name": cell(row, 1) or cid, "summary": cell(row, 2),
            "since": norm_id(cell(row, 3)), "fate": fate or "待定", "landing": cell(row, 5),
            "line": ln, "events": [],
        }

    rounds: dict[str, dict] = {}
    for row, ln in tables["轮次"]:
        rid = norm_id(cell(row, 0))
        if not rid:
            continue
        where = f"轮次表第 {ln} 行"
        if not ID_R.match(rid):
            errors.append(f"{where}：轮次编号「{rid}」要写成 R0、R1 这样")
            continue
        if rid in rounds:
            errors.append(f"{where}：轮次 {rid} 重复")
            continue
        rounds[rid] = {
            "id": rid, "date": cell(row, 1), "purpose": cell(row, 2), "venue": cell(row, 3),
            "lang": cell(row, 4), "gaps": cell(row, 5), "record": cell(row, 6), "line": ln,
            "queries": [], "docs": [], "events": [],
        }
    round_order = sorted(rounds, key=round_key)
    round_index = {rid: i for i, rid in enumerate(round_order)}

    queries: list[dict] = []
    for row, ln in (tables["查询"] or []):
        rid = norm_id(cell(row, 0))
        q = cell(row, 1)
        if not q:
            continue
        where = f"查询式表第 {ln} 行"
        if rid not in rounds:
            errors.append(f"{where}：轮次「{rid or '（空）'}」在轮次表里没有")
            continue
        hits_raw = cell(row, 3)
        hits: int | None
        if hits_raw == "":
            hits = None
        else:
            m = re.search(r"\d+", hits_raw.replace(",", ""))
            hits = int(m.group()) if m else None
            if m is None:
                warnings.append(f"{where}：命中「{hits_raw}」不是数字，按未知处理")
        entry = {"round": rid, "query": q, "venue": cell(row, 2), "hits": hits, "note": cell(row, 4)}
        queries.append(entry)
        rounds[rid]["queries"].append(entry)

    docs: dict[str, dict] = {}
    for row, ln in tables["文献"]:
        pid = norm_id(cell(row, 0))
        if not pid:
            continue
        where = f"文献表第 {ln} 行"
        if not ID_P.match(pid):
            errors.append(f"{where}：文献编号「{pid}」要写成 P1、P2 这样")
            continue
        if pid in docs:
            errors.append(f"{where}：文献 {pid} 重复")
            continue
        role = cell(row, 7)
        if role and not (ROLE_D.match(role.upper()) or role in ROLE_FIXED):
            errors.append(f"{where}：最终角色「{role}」不在词表里，只能用：D1、D2…、{'、'.join(ROLE_FIXED)}")
        if ROLE_D.match(role.upper()):
            role = role.upper()
        found = norm_id(cell(row, 5))
        if found and found not in rounds:
            errors.append(f"{where}：检出轮次「{found}」在轮次表里没有")
        docs[pid] = {
            "id": pid, "number": cell(row, 1), "title": cell(row, 2),
            "kind": vocab("类型", cell(row, 3), where), "date": cell(row, 4),
            "found": found, "fulltext": vocab("全文状态", cell(row, 6), where),
            "role": role, "note": cell(row, 8), "line": ln, "events": [],
        }
        if found in rounds:
            rounds[found]["docs"].append(pid)

    events: list[dict] = []
    for row, ln in tables["对照"]:
        rid = norm_id(cell(row, 0))
        raw_docs = cell(row, 1)
        cid = norm_id(cell(row, 2))
        if not (rid or raw_docs or cid):
            continue
        where = f"对照表第 {ln} 行"
        ok = True
        if rid not in rounds:
            errors.append(f"{where}：轮次「{rid or '（空）'}」在轮次表里没有")
            ok = False
        if cid not in candidates:
            errors.append(f"{where}：候选「{cid or '（空）'}」在候选表里没有")
            ok = False
        doc_ids: list[str] = []
        pseudo: list[str] = []
        for tok in re.split(r"[、,，+/\s]+", raw_docs):
            tok = tok.strip()
            if not tok:
                continue
            if tok in PSEUDO:
                pseudo.append(PSEUDO[tok])
                continue
            t = norm_id(tok)
            if ID_P.match(t) and t in docs:
                doc_ids.append(t)
            else:
                errors.append(f"{where}：文献「{tok}」在文献表里没有（没有具体文献就写 {'、'.join(PSEUDO)} 之一）")
                ok = False
        if not doc_ids and not pseudo:
            errors.append(f"{where}：文献列是空的，写文献编号或 {'、'.join(PSEUDO)} 之一")
            ok = False
        verdict = vocab("判定", cell(row, 3), where)
        impact = vocab("影响", cell(row, 4), where)
        if not verdict:
            errors.append(f"{where}：判定不能为空")
            ok = False
        elif verdict in VOCAB["判定"]:
            exclusive = [x for x in pseudo if x in ("EX", "DC")]
            if exclusive and (doc_ids or len(pseudo) > 1):
                errors.append(f"{where}：「实验」「决策」要单独一行，不和文献或公知常识混写")
                ok = False
            elif "EX" in pseudo and verdict not in VERDICT_EX:
                errors.append(f"{where}：文献列是「实验」时判定只能用 {'、'.join(VERDICT_EX)}，不能用「{verdict}」")
                ok = False
            elif "DC" in pseudo and verdict not in VERDICT_DC:
                errors.append(f"{where}：文献列是「决策」时判定只能用 {'、'.join(VERDICT_DC)}，不能用「{verdict}」")
                ok = False
            elif not exclusive and verdict not in VERDICT_DOC:
                errors.append(f"{where}：判定「{verdict}」只能配「实验」或「决策」，对文献或公知常识用 {'、'.join(VERDICT_DOC)}")
                ok = False
        if not impact:
            errors.append(f"{where}：影响不能为空")
            ok = False
        if not ok:
            continue
        ev = {"round": rid, "docs": doc_ids, "pseudo": pseudo, "candidate": cid,
              "verdict": verdict, "impact": impact, "reason": cell(row, 5), "source": cell(row, 6), "line": ln}
        events.append(ev)
        candidates[cid]["events"].append(ev)
        rounds[rid]["events"].append(ev)
        for d in doc_ids:
            docs[d]["events"].append(ev)

    for c in candidates.values():
        if c["since"] and c["since"] not in rounds:
            errors.append(f"候选表第 {c['line']} 行：提出于「{c['since']}」在轮次表里没有")
        if not c["since"]:
            warnings.append(f"候选 {c['id']} 没写提出于，图上按第一轮算")
    for d in docs.values():
        if not d["found"]:
            warnings.append(f"文献 {d['id']} 没写检出轮次，图上按第一轮算")
        if not d["role"]:
            warnings.append(f"文献 {d['id']} 没写最终角色")
    for c in candidates.values():
        if c["fate"] == "待定":
            warnings.append(f"候选 {c['id']} 最终去向还是「待定」，交付前要填定")

    if errors:
        raise LedgerError("台账有问题，先改再画：\n" + "\n".join(f"  - {e}" for e in errors))

    # 事件按轮次排
    def ev_key(ev: dict):
        return (round_index.get(ev["round"], 0), ev["line"])
    events.sort(key=ev_key)
    for c in candidates.values():
        c["events"].sort(key=ev_key)
    for d in docs.values():
        d["events"].sort(key=ev_key)

    return {
        "path": path, "case": case_title, "meta": meta,
        "candidates": candidates, "rounds": rounds, "round_order": round_order,
        "queries": queries, "docs": docs, "events": events, "warnings": warnings,
    }


# ---------- 派生 ----------

def stats(led: dict) -> dict:
    docs, cands = led["docs"].values(), led["candidates"].values()
    by_kind: dict[str, int] = {}
    for d in docs:
        by_kind[d["kind"] or "未填"] = by_kind.get(d["kind"] or "未填", 0) + 1
    fates = {f: sum(1 for c in cands if c["fate"] == f) for f in FATE_ORDER}
    return {
        "rounds": len(led["rounds"]),
        "queries": len(led["queries"]),
        "zero_hit": sum(1 for q in led["queries"] if q["hits"] == 0),
        "docs": len(led["docs"]),
        "docs_by_kind": by_kind,
        "fulltext": sum(1 for d in docs if d["fulltext"] == "已读全文"),
        "blocked": sum(1 for d in docs if d["fulltext"] in ("未取得", "被阻断")),
        "unresolved": sum(1 for d in docs if d["role"] == "线索未解决"),
        "d_docs": sorted(d["id"] for d in docs if ROLE_D.match(d["role"])),
        "candidates": len(led["candidates"]),
        "fates": fates,
        "events": len(led["events"]),
        "killed": sum(1 for e in led["events"] if e["verdict"] in ("明文记载", "毫无疑义确定")),
        "refuted": sum(1 for e in led["events"] if e["verdict"] == "实测推翻"),
        "teach_away": sum(1 for e in led["events"] if e["verdict"] == "教导相反"),
    }


def evolution_table(led: dict) -> list[list[str]]:
    """候选 × 轮次：每格写这一轮对该候选的判定→影响。"""
    order = led["round_order"]
    head = ["候选"] + order + ["最终去向"]
    rows = []
    for cid in sorted(led["candidates"], key=round_key):
        c = led["candidates"][cid]
        line = [f"{cid} {c['name']}"]
        for rid in order:
            parts = []
            for ev in c["events"]:
                if ev["round"] != rid:
                    continue
                who = "+".join(ev["docs"] + [PSEUDO_LABEL[x][0] for x in ev["pseudo"]])
                parts.append(f"{who} {ev['verdict']}→{ev['impact']}")
            if not parts and c["since"] == rid:
                parts.append("提出")
            line.append("；".join(parts))
        line.append(c["fate"] + (f"（{c['landing']}）" if c["landing"] else ""))
        rows.append(line)
    return [head] + rows


def candidate_story(led: dict, c: dict, dates: bool = True) -> list[str]:
    """一个候选从提出到定局的一条线，每步一句。网页版不带日期（dates=False）。"""
    out = []
    if c["since"]:
        r = led["rounds"].get(c["since"])
        when = f"（{r['date']}）" if (dates and r and r["date"]) else ""
        out.append(f"{c['since']}{when}提出：{c['summary'] or c['name']}")
    for ev in c["events"]:
        who = "、".join([led["docs"][d]["number"] or d for d in ev["docs"]] + [PSEUDO_LABEL[x][0] for x in ev["pseudo"]])
        out.append(f"{ev['round']}：{who} — {ev['verdict']} → {ev['impact']}。{ev['reason']}")
    out.append(f"最终：{c['fate']}" + (f"，{c['landing']}" if c["landing"] else ""))
    return out


# ---------- 笔记名 ----------

def note_name_c(c: dict) -> str:
    return safe_name(f"{c['id']} {c['name'][:24]}")


def note_name_p(d: dict) -> str:
    return safe_name(f"{d['id']} {(d['number'] or d['title'])[:30]}")


def note_name_r(r: dict) -> str:
    return safe_name(f"{r['id']} {r['date']}".strip())


# ---------- 输出：Obsidian 笔记 ----------

def frontmatter(tags: list[str], case: str, extra: dict | None = None) -> str:
    out = ["---", GENERATED_MARK, f"case: {case}",
           f"generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", "tags:"] + [f"  - {t}" for t in tags]
    for k, v in (extra or {}).items():
        out.append(f"{k}: {v}")
    out.append("---")
    return "\n".join(out) + "\n\n"


def write_file(path: Path, content: str, written: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    written.append(str(path))


def md_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    esc = lambda s: str(s).replace("|", "／").replace("\n", " ")
    out = ["| " + " | ".join(esc(x) for x in rows[0]) + " |",
           "|" + "---|" * len(rows[0])]
    for r in rows[1:]:
        out.append("| " + " | ".join(esc(x) for x in r) + " |")
    return "\n".join(out) + "\n"


def sweep_stale(out_dir: Path, written: list[str]) -> list[str]:
    keep = {str(Path(p).resolve()) for p in written}
    removed = []
    if not out_dir.is_dir():
        return removed
    for p in sorted(out_dir.rglob("*")):
        if not p.is_file() or str(p.resolve()) in keep or p.suffix not in (".md", ".html"):
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:600]
        except OSError:
            continue
        if GENERATED_MARK in head:
            p.unlink()
            removed.append(str(p))
    for d in sorted(out_dir.rglob("*"), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return removed


def write_notes(led: dict, out_dir: Path, case: str, written: list[str], st: dict):
    cands, rounds, docs = led["candidates"], led["rounds"], led["docs"]
    linkc = lambda cid: f"[[{note_name_c(cands[cid])}|{cid} {cands[cid]['name']}]]"
    linkp = lambda pid: f"[[{note_name_p(docs[pid])}|{docs[pid]['number'] or pid}]]"
    linkr = lambda rid: f"[[{note_name_r(rounds[rid])}|{rid}]]"

    def ev_line(ev: dict, show_c=True, show_p=True) -> str:
        who = "、".join([linkp(d) for d in ev["docs"]] + [PSEUDO_LABEL[x][0] for x in ev["pseudo"]])
        bits = [linkr(ev["round"])]
        if show_p:
            bits.append(who)
        if show_c:
            bits.append(linkc(ev["candidate"]))
        return (f"- {' · '.join(bits)}：**{ev['verdict']} → {ev['impact']}**。{ev['reason']}"
                + (f"（{ev['source']}）" if ev["source"] else ""))

    for c in cands.values():
        body = frontmatter(["检索轨迹", "候选", c["fate"]], case, {"fate": c["fate"]})
        body += f"# {c['id']} {c['name']}\n\n> {c['summary'] or '（一句话没填）'}\n\n"
        body += f"- 提出于：{linkr(c['since']) if c['since'] in rounds else '未填'}\n"
        body += f"- 最终去向：**{c['fate']}**{'，' + c['landing'] if c['landing'] else ''}\n\n"
        body += "## 来龙去脉\n\n" + "".join(f"{i}. {s}\n" for i, s in enumerate(candidate_story(led, c), 1)) + "\n"
        if c["events"]:
            body += "## 对照记录\n\n" + "".join(ev_line(ev, show_c=False) + "\n" for ev in c["events"]) + "\n"
        write_file(out_dir / "候选" / f"{note_name_c(c)}.md", body, written)

    for d in docs.values():
        tags = ["检索轨迹", "检索文献"] + ([d["role"]] if d["role"] else [])
        body = frontmatter(tags, case, {"role": d["role"] or "未填", "fulltext": d["fulltext"] or "未填"})
        body += f"# {d['id']} {d['number']}\n\n{d['title']}\n\n"
        body += (f"- 类型：{d['kind'] or '未填'}　公开日：{d['date'] or '未填'}\n"
                 f"- 检出于：{linkr(d['found']) if d['found'] in rounds else '未填'}\n"
                 f"- 全文状态：{d['fulltext'] or '未填'}\n- 最终角色：**{d['role'] or '未填'}**\n")
        if d["note"]:
            body += f"- 备注：{d['note']}\n"
        if d["events"]:
            body += "\n## 打过哪些候选\n\n" + "".join(ev_line(ev, show_p=False) + "\n" for ev in d["events"])
        write_file(out_dir / "文献" / f"{note_name_p(d)}.md", body, written)

    for rid in led["round_order"]:
        r = rounds[rid]
        body = frontmatter(["检索轨迹", "轮次"], case)
        body += f"# {rid}：{r['purpose'] or '（目的没填）'}\n\n"
        body += (f"- 日期：{r['date'] or '未填'}\n- 入口：{r['venue'] or '未填'}\n- 语言：{r['lang'] or '未填'}\n"
                 f"- 未覆盖：{r['gaps'] or '未填'}\n- 详细记录：{r['record'] or '未填'}\n\n")
        if r["queries"]:
            body += "## 查询式\n\n" + md_table([["查询式", "入口", "命中", "说明"]] + [
                [q["query"], q["venue"], "—" if q["hits"] is None else str(q["hits"]), q["note"]] for q in r["queries"]]) + "\n"
        if r["docs"]:
            body += "## 本轮检出\n\n" + "".join(
                f"- {linkp(p)} {docs[p]['title'][:40]}（{docs[p]['fulltext'] or '未填'}，{docs[p]['role'] or '未填'}）\n"
                for p in r["docs"]) + "\n"
        if r["events"]:
            body += "## 本轮对照\n\n" + "".join(ev_line(ev) + "\n" for ev in r["events"]) + "\n"
        write_file(out_dir / "轮次" / f"{note_name_r(r)}.md", body, written)

    # 总览
    f = st["fates"]
    body = frontmatter(["检索轨迹", "总览"], case)
    body += f"# 检索轨迹总览：{case}\n\n"
    body += ("看图：双击同目录的 `检索轨迹图谱.html`（任何浏览器，不联网，可导出 PNG）。下面的链接是同一批内容的文字版。"
             + ("案件本身的结果图见 [[案件总览]]。" if (out_dir.parent / "案件总览.md").exists() else "") + "\n\n")
    for k, v in led["meta"].items():
        body += f"- {k}：{v}\n"
    body += ("\n## 干了多少活\n\n"
             f"{st['rounds']} 轮（检索、实测与取舍各算一轮），{st['queries']} 条查询式（其中 {st['zero_hit']} 条命中为 0），"
             f"看过 {st['docs']} 篇文献（{'，'.join(f'{k} {n}' for k, n in st['docs_by_kind'].items())}），"
             f"读了全文 {st['fulltext']} 篇；提过 {st['candidates']} 个候选，打掉 {f['放弃']} 个，"
             f"{f['独权核心']} 个进独立权利要求，{f['从属权项']} 个进从属权项，{f['仅说明书']} 个只写进说明书"
             + (f"，{f['待定']} 个还没定" if f["待定"] else "") + f"；{st['events']} 次逐篇对照，"
             f"其中 {st['killed']} 次判为新颖性层面已公开，{st['teach_away']} 次发现教导相反"
             + (f"，{st['refuted']} 次被本案实测推翻" if st["refuted"] else "")
             + (f"；还有 {st['unresolved']} 条线索没查完" if st["unresolved"] else "") + "。\n\n")
    body += "## 最终路线是怎么来的\n\n"
    for c in sorted(cands.values(), key=lambda c: (FATE_ORDER.index(c["fate"]), round_key(c["id"]))):
        body += f"### {linkc(c['id'])} → {c['fate']}{'（' + c['landing'] + '）' if c['landing'] else ''}\n\n"
        body += "".join(f"{i}. {s}\n" for i, s in enumerate(candidate_story(led, c), 1)) + "\n"
    body += "## 候选 × 轮次\n\n" + md_table(evolution_table(led)) + "\n"
    roles: dict[str, list[str]] = {}
    for d in docs.values():
        roles.setdefault(d["role"] or "未填", []).append(d["id"])
    body += "## 文献清单（按最终角色）\n\n"
    for role in sorted(roles, key=lambda r: (0 if ROLE_D.match(r) else 1, r)):
        body += f"- **{role}**：" + "、".join(
            f"{linkp(p)} {docs[p]['title'][:30]}" for p in sorted(roles[role], key=round_key)) + "\n"
    body += "\n## 还没查完的\n\n"
    gaps = [(r["id"], r["gaps"]) for r in (rounds[x] for x in led["round_order"]) if r["gaps"]]
    unresolved = [d for d in docs.values() if d["role"] == "线索未解决"]
    if not gaps and not unresolved:
        body += "台账里没有记未覆盖范围和未解决线索。\n"
    for rid, g in gaps:
        body += f"- {linkr(rid)} 未覆盖：{g}\n"
    for d in unresolved:
        body += f"- 线索未解决：{linkp(d['id'])} {d['title'][:40]}（{d['fulltext'] or '未填'}）{'—' + d['note'] if d['note'] else ''}\n"
    body += "\n## 轮次\n\n" + "".join(
        f"- {linkr(rid)} {rounds[rid]['date']} {rounds[rid]['purpose']}\n" for rid in led["round_order"]) + "\n"
    body += "本输出为撰写辅助，不构成法律意见，不保证授权，不代为提交。\n"
    write_file(out_dir / "检索轨迹总览.md", body, written)


# ---------- 输出：单文件 HTML ----------

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>检索轨迹图谱：__CASE__</title>
<style>
:root{--bg:#f6f4ef;--panel:#fff;--ink:#1f2328;--muted:#6b7280;--line:#d9d4c7;--acc:#2f7fc1}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",sans-serif}
header{padding:22px 28px 0;background:var(--panel)}
.eyebrow{font-size:11px;letter-spacing:.18em;color:var(--muted);text-transform:uppercase;margin-bottom:6px}
h1{margin:0;font-size:22px;font-weight:600;letter-spacing:.01em}
.sub{color:var(--muted);font-size:12.5px;margin-top:6px}
.sub span{margin-right:18px}
.stats{display:flex;flex-wrap:wrap;gap:12px;padding:14px 28px 18px;background:var(--panel);border-bottom:1px solid var(--line)}
.sg{display:flex;flex-direction:column;gap:8px;padding:10px 16px 12px;border:1px solid var(--line);border-radius:10px;background:#fbfaf7;box-shadow:0 1px 0 rgba(0,0,0,.02)}
.sg .cap{font-size:11px;letter-spacing:.14em;color:var(--muted);display:flex;align-items:center;gap:6px}
.sg .cap i{display:inline-block;width:8px;height:8px;border-radius:2px}
.sg .row{display:flex;gap:0}
.st{min-width:78px;padding:0 14px;border-left:1px solid var(--line)}
.st:first-child{padding-left:0;border-left:0}
.st b{display:block;font-size:26px;font-weight:600;line-height:1;font-variant-numeric:tabular-nums}
.st span{display:block;font-size:12px;color:var(--muted);margin-top:5px;white-space:nowrap}
.bar{display:flex;flex-wrap:wrap;align-items:center;gap:8px 16px;padding:10px 24px;font-size:13px}
.bar button{font:inherit;padding:4px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:pointer}
.bar button:hover{border-color:var(--acc)}
.bar .cur{font-weight:600;min-width:12em}
.bar .hint{color:var(--muted);font-size:12px}
.lg{display:grid;grid-template-columns:30px 1fr;gap:3px 8px;align-items:center;font-size:12.5px}
.lg svg{display:block}
.lg .n{color:var(--ink)}
.lg .n small{color:var(--muted);margin-left:4px}
.lgh{font-size:11px;color:var(--muted);letter-spacing:.12em;margin:12px 0 5px;padding-bottom:3px;border-bottom:1px solid var(--line)}
.lgh:first-child{margin-top:0}
.lgk{display:inline-block;min-width:22px;text-align:center;white-space:nowrap;font-size:12px;color:var(--ink);background:#fff;border:1px solid var(--line);border-radius:5px;padding:1px 5px}
.back{font:inherit;font-size:12px;padding:2px 8px;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:pointer;margin-bottom:8px}
main{display:grid;grid-template-columns:1fr 320px;gap:0;min-height:520px}
.gwrap{overflow:auto;background:var(--panel)}
.ftools{display:flex;gap:12px;align-items:center;padding:8px 12px;font-size:12px;color:var(--muted);background:#f1ede3;border-bottom:1px solid var(--line)}
.ftools button{font:inherit;font-size:12px;padding:3px 9px;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:pointer}
svg{display:block}
.node{cursor:pointer}
.node rect{stroke-width:1.5;stroke:#8a8f98;fill:#fff}
.node text{font-size:12px;fill:var(--ink);pointer-events:none}
.node .id{font-weight:600}
.node.round rect{fill:#fff7d6;stroke:#c9a227}
.node.doc rect{fill:#fff1e3;stroke:#e0962e}
.node.common rect{fill:#f1f1f1;stroke:#9aa3ad;stroke-dasharray:3 3}
.node.cand rect{fill:#f1ebfa;stroke:#7d5bb8}
.node.fate rect{fill:#e8f1fa;stroke:#2f7fc1}
.edge{fill:none;stroke-width:1.6;opacity:.85}
.edge.found{stroke:#b9b2a3;stroke-width:1.1}
.edge.fate{stroke-width:2.2}
.edgelabel{font-size:10.5px;fill:#444;display:none;paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round}
.lit .edgelabel{display:block}
.ghost{opacity:.1}
.dim{opacity:.18}
.lit{opacity:1 !important}
.lit rect{stroke-width:2.5}
.col{font-size:12px;fill:var(--muted);font-weight:600}
aside{padding:14px 16px;overflow:auto;background:#fbfaf7;font-size:13px}
aside h2{font-size:15px;margin:0 0 6px}
aside .k{color:var(--muted)}
aside ol{padding-left:18px;margin:6px 0}
aside li{margin:4px 0}
aside .tag{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;color:#fff;margin-right:4px}
section{padding:16px 24px;border-top:1px solid var(--line)}
section h2{font-size:16px;margin:0 0 8px}
table{border-collapse:collapse;width:100%;font-size:12.5px;background:#fff}
th,td{border:1px solid var(--line);padding:5px 8px;vertical-align:top;text-align:left}
th{background:#f1ede3}
td.c{white-space:nowrap}
.glossary{background:var(--panel)}
.gcols{display:grid;grid-template-columns:repeat(3,minmax(240px,1fr));gap:18px 36px}
.gcols h3{font-size:12px;letter-spacing:.14em;color:var(--muted);margin:0 0 8px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.gcols dl{display:grid;grid-template-columns:max-content 1fr;gap:5px 12px;margin:0;font-size:12.5px;align-items:baseline}
.gcols dt{font-weight:600;color:var(--ink);white-space:nowrap}
.gcols dt.killed{color:#d94a3d}.gcols dt.near{color:#c27a12}.gcols dt.clear{color:#2f8a48}.gcols dt.away{color:#2f7fc1}.gcols dt.dim{color:#6b7280}
.gcols dd{margin:0;color:var(--muted)}
@media (max-width:1000px){.gcols{grid-template-columns:1fr 1fr}}
@media (max-width:640px){.gcols{grid-template-columns:1fr}}
.killed{color:#d94a3d}.near{color:#c27a12}.clear{color:#2f8a48}.away{color:#2f7fc1}
footer{padding:16px 28px 30px;color:var(--muted);font-size:11.5px;border-top:1px solid var(--line);display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px 24px}
.left{min-width:0;border-right:1px solid var(--line);background:var(--panel)}
.tabs{display:flex;gap:6px;padding:8px 12px 0;background:var(--panel);border-bottom:1px solid var(--line)}
.tabs button{font:inherit;padding:6px 14px;border:1px solid var(--line);border-bottom:0;border-radius:8px 8px 0 0;background:#f1ede3;cursor:pointer;color:var(--muted)}
.tabs button.on{background:#fff;color:var(--ink);font-weight:600}
#gview{position:relative;background:#0f1420}
#gview.light{background:#fbfaf7}
.gtools{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;padding:8px 12px;font-size:12px;background:rgba(255,255,255,.05);color:#c7cdd8;border-bottom:1px solid rgba(255,255,255,.08)}
#gview.light .gtools{background:#f1ede3;color:var(--muted);border-bottom-color:var(--line)}
.gtools button{font:inherit;font-size:12px;padding:3px 9px;border:1px solid rgba(255,255,255,.22);border-radius:6px;background:transparent;color:inherit;cursor:pointer}
.gtools button:hover{border-color:#8ab4f8}
#gview.light .gtools button{border-color:var(--line);color:var(--ink);background:#fff}
.gtools .chip{display:inline-flex;align-items:center;gap:4px;cursor:pointer;user-select:none}
.gtools .chip.off{opacity:.3;text-decoration:line-through}
.gtools .chip i{display:inline-block;width:14px;height:3px;border-radius:2px}
.gtools .sep{width:1px;height:16px;background:rgba(255,255,255,.18)}
#gview.light .gtools .sep{background:var(--line)}
#gc{display:block;cursor:grab}
#gtip{position:absolute;pointer-events:none;background:rgba(20,24,34,.96);color:#e6e9ef;padding:7px 10px;border-radius:7px;font-size:12px;line-height:1.5;max-width:340px;display:none;border:1px solid rgba(255,255,255,.14);box-shadow:0 6px 20px rgba(0,0,0,.45)}
#gtip b{color:#fff}
.ghint{position:absolute;right:12px;bottom:8px;font-size:11px;color:#7d8798;pointer-events:none}
#gview.light .ghint{color:var(--muted)}
@media (max-width:900px){main{grid-template-columns:1fr}.left{border-right:0}}
</style>
</head>
<body>
<header>
  <div class="eyebrow">检索轨迹图谱 · Search Trail</div>
  <h1>__CASE__</h1>
  <div class="sub" id="sub"></div>
</header>
<div class="stats" id="tiles"></div>
<div class="bar">
  <button id="prev">◀ 上一轮</button><span class="cur" id="cur"></span><button id="next">下一轮 ▶</button>
  <button id="all">显示全部</button>
  <span class="hint">按时间回放：每按一次「下一轮」，这一轮查到的文献和它对候选的打击就点亮</span>
</div>
<main>
  <div class="left">
    <div class="tabs"><button id="tab-graph" class="on">图谱视图</button><button id="tab-flow">流程视图</button></div>
    <div id="gview">
      <div class="gtools">
        <button id="g-expand">展开全部轮次</button><button id="g-collapse">收起全部轮次</button><button id="g-relayout">重新排布</button><button id="g-fit">适应窗口</button><button id="g-theme">浅色</button><button id="g-png">导出 PNG</button>
        <span class="sep"></span>
        <span class="chip" data-f="killed"><i style="background:#d94a3d"></i>已公开/实测推翻</span>
        <span class="chip" data-f="near"><i style="background:#e0962e"></i>部分接近</span>
        <span class="chip" data-f="clear"><i style="background:#3f9d5a"></i>未记载</span>
        <span class="chip" data-f="away"><i style="background:#2f7fc1"></i>教导相反</span>
        <span class="chip" data-f="decision"><i style="background:#8a8f98"></i>人为取舍</span>
        <span class="chip" data-f="found"><i style="background:#5b6478"></i>检出</span>
        <span class="chip" data-f="fate"><i style="background:#7d5bb8"></i>去向</span>
      </div>
      <canvas id="gc"></canvas><div id="gtip"></div>
      <div class="ghint">拖动节点 · 滚轮缩放 · 拖空白平移 · 双击空白复位 · 点轮次收放它查到的文献 · 点节点看右侧详情</div>
    </div>
    <div class="gwrap" style="display:none"><div class="ftools"><button id="f-png">导出 PNG</button><span>四列：轮次 → 文献 → 候选 → 最终去向；点节点看详情</span></div><svg id="g" xmlns="http://www.w3.org/2000/svg"></svg></div>
  </div>
  <aside id="panel"></aside>
</main>
<section>
  <h2>候选 × 轮次</h2>
  <p class="k" style="margin:0 0 8px;font-size:12.5px;color:var(--muted)">每一格：哪篇文献打了这个候选，判定是什么，候选因此怎么变。</p>
  <div style="overflow:auto"><table id="evo"></table></div>
</section>
<section class="glossary">
  <h2>词汇表</h2>
  <div class="gcols">
    <div><h3>顶部数字</h3><dl>
      <dt>轮次</dt><dd>查一轮、比一轮、改一轮方案，算一轮</dd>
      <dt>检索式</dt><dd>在数据库里实际敲过的检索条件</dd>
      <dt>零命中</dt><dd>这些条件下查不到任何在先文献</dd>
      <dt>看过</dt><dd>打开并逐篇作过判断的文献</dd>
      <dt>通读全文</dt><dd>其中读完全文的</dd>
      <dt>逐篇对照</dt><dd>一篇文献比一个技术点，算一次</dd>
      <dt>提出</dt><dd>考虑过要保护的技术点</dd>
      <dt>放弃</dt><dd>已有人做过、实测不成立或主动砍掉</dd>
      <dt>进独立权利要求</dt><dd>最终写进权 1 的核心</dd>
    </dl></div>
    <div><h3>判定 · 连线颜色</h3><dl>
      <dt class="killed">明文记载</dt><dd>文献白纸黑字写了</dd>
      <dt class="killed">毫无疑义确定</dt><dd>没明写，但必然如此</dd>
      <dt class="near">部分接近</dt><dd>有相似之处，但不是一回事</dd>
      <dt class="near">记载不清</dt><dd>拿到的文本不够下结论</dd>
      <dt class="clear">未记载</dt><dd>文献里没有</dd>
      <dt class="away">教导相反</dt><dd>文献明确反对这条路，是答辩支点</dd>
      <dt class="killed">实测推翻</dt><dd>本案实验证明不成立</dd>
      <dt class="clear">实测支持</dt><dd>本案实验证明成立</dd>
      <dt class="dim">人为取舍</dt><dd>为篇幅或策略主动决定</dd>
    </dl></div>
    <div><h3>影响 · 候选怎么变</h3><dl>
      <dt>放弃</dt><dd>不再作为发明点</dd>
      <dt>降为从属</dt><dd>从权 1 退到从属权项</dd>
      <dt>降为说明书</dt><dd>不进权项，只写进说明书</dd>
      <dt>升为核心</dt><dd>提到权 1</dd>
      <dt>保留</dt><dd>维持原判</dd>
      <dt>收窄</dt><dd>范围缩小以避开</dd>
      <dt>新增候选</dt><dd>由此想到新的点</dd>
      <dt>无影响</dt><dd>记录在案，不改变去向</dd>
    </dl></div>
  </div>
</section>
<footer><span>本输出为撰写辅助，不构成法律意见，不保证授权，不代为提交。</span><span>数据来自《__LEDGER__》</span></footer>
<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
const D = JSON.parse(document.getElementById('data').textContent);
const NS = 'http://www.w3.org/2000/svg';
const COL = {round:36, doc:244, common:514, cand:664, fate:970};
const W = {round:190, doc:260, common:140, cand:280, fate:170};
const H = {round:56, doc:60, common:52, cand:66, fate:56};
const PITCH = 84, TOP = 40;
const VC = {killed:'#d94a3d', near:'#e0962e', clear:'#3f9d5a', away:'#2f7fc1', decision:'#8a8f98'};
const FC = D.fate_colors;
const rIndex = {}; D.rounds.forEach((r,i)=>rIndex[r.id]=i);

// 摘要条
document.getElementById('sub').innerHTML = Object.entries(D.meta).map(([k,v])=>'<span><b style="font-weight:500;color:var(--ink)">'+esc0(k)+'</b>　'+esc0(v)+'</span>').join('');
function esc0(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
const S = D.stats, tiles = document.getElementById('tiles');
[['检索','#e6c04a',[[S.rounds,'轮次'],[S.queries,'检索式'],[S.zero_hit,'零命中']]],
 ['文献','#f0a35e',[[S.docs,'看过'],[S.fulltext,'通读全文'],[S.events,'逐篇对照']]],
 ['候选发明点','#b48cf2',[[S.candidates,'提出'],[S.fates['放弃'],'放弃'],[S.fates['独权核心'],'进独立权利要求']]]]
 .forEach(([cap,col,items])=>{const g=document.createElement('div');g.className='sg';g.innerHTML='<div class="cap"><i style="background:'+col+'"></i>'+cap+'</div><div class="row">'+items.map(([n,l])=>'<div class="st"><b>'+n+'</b><span>'+l+'</span></div>').join('')+'</div>';tiles.appendChild(g);});

// 节点
const nodes = [], byId = {};
function push(n){nodes.push(n);byId[n.key]=n;}
D.rounds.forEach((r,i)=>push({key:'R:'+r.id,kind:'round',row:i,intro:i,l1:r.id,l2:r.purpose,data:r}));
const docs = D.docs.slice().sort((a,b)=>(rIndex[a.found]||0)-(rIndex[b.found]||0)||a.n-b.n);
docs.forEach((d,i)=>push({key:'P:'+d.id,kind:'doc',row:i,intro:rIndex[d.found]||0,l1:d.id+'  '+d.number,l2:d.title,data:d}));
D.pseudo.forEach((p,j)=>push({key:p.code,kind:'common',row:docs.length+j,intro:rIndex[p.round]||0,l1:p.label,l2:p.desc,data:p}));
const cands = D.candidates.slice().sort((a,b)=>(rIndex[a.since]||0)-(rIndex[b.since]||0)||a.n-b.n);
cands.forEach((c,i)=>push({key:'C:'+c.id,kind:'cand',row:i,intro:rIndex[c.since]||0,l1:c.id+'  '+c.name,l2:'→ '+c.fate+(c.landing?'：'+c.landing:''),data:c}));
const fates = D.fate_order.filter(f=>cands.some(c=>c.fate===f));
fates.forEach((f,i)=>push({key:'F:'+f,kind:'fate',row:i,intro:D.rounds.length-1,l1:f,l2:cands.filter(c=>c.fate===f).map(c=>c.id).join('、'),data:{fate:f}}));
nodes.forEach(n=>{n.x=COL[n.kind];n.w=W[n.kind];n.h=H[n.kind];});

// 边
const edges = [];
docs.forEach(d=>{if(rIndex[d.found]!==undefined)edges.push({a:'R:'+d.found,b:'P:'+d.id,cls:'found',intro:rIndex[d.found],label:''});});
D.pseudo.forEach(p=>edges.push({a:'R:'+p.round,b:p.code,cls:'found',intro:rIndex[p.round],label:''}));
D.events.forEach(e=>{const srcs=e.docs.map(p=>'P:'+p).concat(e.pseudo);
  srcs.forEach(s=>edges.push({a:s,b:'C:'+e.candidate,cls:'verdict',color:VC[e.kind],intro:rIndex[e.round],label:e.round+' '+e.verdict+'→'+e.impact,ev:e}));});
cands.forEach(c=>edges.push({a:'C:'+c.id,b:'F:'+c.fate,cls:'fate',color:FC[c.fate],intro:D.rounds.length-1,label:c.landing}));

// 排版：文献列按轮次顺序排；候选贴着打它的文献（取相连文献的平均纵坐标）、去向贴着它的候选、
// 轮次贴着它检出的文献，重叠的往下推。几十篇文献时线才不会全挤成一团。
const GAP = 18;
function neigh(n, kinds){const ys=[];edges.forEach(e=>{const o=e.a===n.key?byId[e.b]:(e.b===n.key?byId[e.a]:null);if(o&&kinds.includes(o.kind)&&o.y!=null)ys.push(o.y+o.h/2);});return ys.length?ys.reduce((a,b)=>a+b,0)/ys.length:null;}
function placeSeq(list){let y=TOP;list.forEach(n=>{n.y=(n.bary==null)?y:Math.max(y,n.bary-n.h/2);y=n.y+n.h+GAP;});}
function placeFree(n, col){let y=Math.max(TOP,(n.bary==null?TOP:n.bary-n.h/2));for(let guard=0;guard<500;guard++){const hit=col.find(o=>o!==n&&o.y!=null&&!(y+n.h+GAP<=o.y||o.y+o.h+GAP<=y));if(!hit)break;y=hit.y+hit.h+GAP;}n.y=y;}
const colDocs=nodes.filter(n=>n.kind==='doc'), colPseudo=nodes.filter(n=>n.kind==='common'), colR=nodes.filter(n=>n.kind==='round'), colC=nodes.filter(n=>n.kind==='cand'), colF=nodes.filter(n=>n.kind==='fate');
nodes.forEach(n=>{n.y=null;n.bary=null;});
placeSeq(colDocs);
const cA=colC.filter(n=>(n.bary=neigh(n,['doc']))!=null).sort((a,b)=>a.bary-b.bary||a.row-b.row);
placeSeq(cA);
colPseudo.forEach(n=>{n.bary=neigh(n,['cand']);placeFree(n,colPseudo);});
colC.filter(n=>n.y==null).sort((a,b)=>a.row-b.row).forEach(n=>{n.bary=neigh(n,['common']);placeFree(n,colC);});
colR.forEach(n=>n.bary=neigh(n,['doc'])); placeSeq(colR);
colF.forEach(n=>n.bary=neigh(n,['cand'])); placeSeq(colF);
// 画
const svg = document.getElementById('g');
const bottom = Math.max(...nodes.map(n=>n.y+n.h));
svg.setAttribute('width', COL.fate+W.fate+30); svg.setAttribute('height', bottom + 40);
function el(t,attrs,parent){const e=document.createElementNS(NS,t);for(const k in attrs)e.setAttribute(k,attrs[k]);(parent||svg).appendChild(e);return e;}
[['轮次',COL.round],['查到的文献',COL.doc],['候选发明点',COL.cand],['最终去向',COL.fate]].forEach(([t,x])=>{const c=el('text',{x:x,y:22,'class':'col'});c.textContent=t;});
function wrap(s, maxw){s=s||'';let out=[],cur='',w=0;const cw=ch=>ch.charCodeAt(0)>255?12:6.6;
  for(let i=0;i<s.length;i++){const ch=s[i];if(w+cw(ch)>maxw){const sp=cur.lastIndexOf(' ');
      if(sp>maxw/6.6*0.5&&ch.charCodeAt(0)<256){out.push(cur.slice(0,sp));cur=cur.slice(sp+1);w=0;for(const c of cur)w+=cw(c);}else{out.push(cur);cur='';w=0;}
      if(out.length===2){cur='';break;}}
    cur+=ch;w+=cw(ch);}
  if(cur&&out.length<2)out.push(cur);
  if(out.length===2&&s.replace(/ /g,'').length>out.join('').replace(/ /g,'').length)out[1]=out[1].slice(0,-1)+'…';return out;}
const eg = el('g',{}), ng = el('g',{});
edges.forEach(e=>{const A=byId[e.a],B=byId[e.b];if(!A||!B)return;const x1=A.x+A.w,y1=A.y+A.h/2,x2=B.x,y2=B.y+B.h/2,mx=(x1+x2)/2;
  const g=el('g',{'class':'edgeg'},eg);e.g=g;
  el('path',{d:`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`,'class':'edge '+e.cls,stroke:e.color||''},g);
  if(e.label){const t=el('text',{x:mx,y:(y1+y2)/2-4,'class':'edgelabel','text-anchor':'middle'},g);t.textContent=e.label;}});
nodes.forEach(n=>{const g=el('g',{'class':'node '+n.kind,transform:`translate(${n.x},${n.y})`},ng);n.g=g;
  el('rect',{width:n.w,height:n.h,rx:7},g);
  const t1=el('text',{x:9,y:19,'class':'id'},g);t1.textContent=wrap(n.l1,n.w-18)[0]||'';
  const ls=wrap(n.l2,n.w-18);ls.forEach((s,i)=>{const t=el('text',{x:9,y:35+i*14},g);t.textContent=s;});
  const ttl=el('title',{},g);ttl.textContent=n.l1+'\n'+(n.l2||'');
  g.addEventListener('click',ev=>{ev.stopPropagation();select(n.key);});});
svg.addEventListener('click',()=>select(null));

// 回放 + 高亮
let upto = D.rounds.length-1, selected = null;
function apply(){
  nodes.forEach(n=>{n.g.classList.toggle('ghost', n.intro>upto);});
  edges.forEach(e=>{if(!e.g)return;e.g.classList.toggle('ghost', e.intro>upto);});
  const cur=document.getElementById('cur');
  cur.textContent = upto>=D.rounds.length-1 ? '全部 '+D.rounds.length+' 轮' : '到 '+D.rounds[upto].id+' 为止';
  if(selected){const keep=new Set([selected]);edges.forEach(e=>{if(e.a===selected||e.b===selected){keep.add(e.a);keep.add(e.b);}});
    nodes.forEach(n=>{n.g.classList.toggle('dim',!keep.has(n.key));n.g.classList.toggle('lit',keep.has(n.key));});
    edges.forEach(e=>{if(!e.g)return;const on=e.a===selected||e.b===selected;e.g.classList.toggle('dim',!on);e.g.classList.toggle('lit',on);});
  } else {nodes.forEach(n=>{n.g.classList.remove('dim','lit');});edges.forEach(e=>{if(e.g){e.g.classList.remove('dim','lit');}});}
  GV.refresh();
}
function select(key){selected=key;apply();panel(key);}
document.getElementById('prev').onclick=()=>{upto=Math.max(0,upto-1);apply();};
document.getElementById('next').onclick=()=>{upto=Math.min(D.rounds.length-1,upto+1);apply();};
document.getElementById('all').onclick=()=>{upto=D.rounds.length-1;select(null);};

// 右侧面板
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function tag(t,color){return '<span class="tag" style="background:'+color+'">'+esc(t)+'</span>';}
function docName(p){const d=D.docs.find(x=>x.id===p);return d?(d.number||d.id):p;}
const ROLE_SHOW={D1:'最接近的现有技术（D1）',D2:'第二对比文件（D2）',背景技术:'写进背景技术',答辩材料:'留作答辩材料'};
function roleShow(r){if(!r)return '';if(ROLE_SHOW[r])return ROLE_SHOW[r];if(/^D\d+$/.test(r))return '对比文件 '+r;return '';}
const FT_SHOW={已读全文:'通读全文',仅摘要:'读了摘要',未取得:'未取得全文',被阻断:'未取得全文'};
function ftShow(f){return FT_SHOW[f]||f||'';}
const PL={CK:'公知常识',EX:'本案实验',DC:'人为决策'};
function evLine(e,opts){opts=opts||{};let who=e.docs.map(docName).concat(e.pseudo.map(x=>PL[x])).join('、');let s='<li><b>'+esc(e.round)+'</b>';
  if(!opts.noDoc)s+=' · '+esc(who);if(!opts.noCand)s+=' · '+esc(e.candidate);
  s+='：<span class="'+e.kind+'">'+esc(e.verdict)+' → '+esc(e.impact)+'</span>。'+esc(e.reason)+(e.source?'<span class="k">（'+esc(e.source)+'）</span>':'')+'</li>';return s;}

// ===== 图例（地图图例式，默认显示在右侧；两个视图各一套）=====
let curView='graph';
function flowLegendHTML(){
  const box=(fill,stroke,dash)=>'<svg width="30" height="22"><rect x="3" y="4" width="24" height="14" rx="4" fill="'+fill+'" stroke="'+stroke+'" stroke-width="1.5" '+(dash?'stroke-dasharray="4 3"':'')+'/></svg>';
  const line=(c,w)=>'<svg width="30" height="22"><path d="M2 11 L28 11" stroke="'+c+'" stroke-width="'+w+'" stroke-linecap="round"/></svg>';
  const row=(sw,t,sub)=>sw+'<span class="n">'+t+(sub?'<small>'+sub+'</small>':'')+'</span>';
  const key=(k,t)=>'<span class="lgk">'+k+'</span><span class="n">'+t+'</span>';
  return '<div class="lg">'
   +'<div class="lgh" style="grid-column:1/-1">四列，从左到右</div>'
   +row(box('#fff7d6','#c9a227'),'检索轮次','按时间从上到下')
   +row(box('#fff1e3','#e0962e'),'查到的文献','按检出轮次排')
   +row(box('#f1ebfa','#7d5bb8'),'候选发明点','贴着打它的文献放')
   +row(box('#e8f1fa','#2f7fc1'),'最终去向','独权核心 · 从属权项 · 仅说明书 · 放弃')
   +row(box('#f1f1f1','#9aa3ad',true),'公知常识 · 本案实验 · 人为决策')
   +'<div class="lgh" style="grid-column:1/-1">连线 ＝ 判定</div>'
   +row(line('#d94a3d',2.5),'被打掉','明文记载 · 毫无疑义确定 · 实测推翻')
   +row(line('#e0962e',2.5),'部分接近','含记载不清')
   +row(line('#3f9d5a',2.5),'未记载','含实测支持')
   +row(line('#2f7fc1',2.5),'教导相反','答辩支点')
   +row(line('#8a8f98',2.5),'人为取舍')
   +row(line('#b9b2a3',1),'检出','轮次 → 文献')
   +'<div class="lgh" style="grid-column:1/-1">操作</div>'
   +key('点','节点 → 右侧看来龙去脉，连线上显示判定')
   +key('◀▶','顶部按钮按轮次回放，没到的轮次变淡')
   +key('PNG','导出整张图，适合打印')
   +'</div>';
}
function legendHTML(){ if(curView==='flow') return flowLegendHTML();
  const dot=(c,r,t,tc)=>'<svg width="30" height="24"><circle cx="15" cy="12" r="'+r+'" fill="'+c+'"/>'+(t?'<text x="15" y="12.5" text-anchor="middle" dominant-baseline="middle" font-size="'+(r>8?9:7)+'" font-weight="700" fill="'+(tc||'#fff')+'">'+t+'</text>':'')+'</svg>';
  const ring=(c,rc)=>'<svg width="30" height="24"><circle cx="15" cy="12" r="7.5" fill="'+c+'"/><circle cx="15" cy="12" r="10" fill="none" stroke="'+rc+'" stroke-width="2.5"/><text x="15" y="12.5" text-anchor="middle" dominant-baseline="middle" font-size="8" font-weight="700" fill="#fff">C</text></svg>';
  const pillsw=(bg,fg,dash)=>'<svg width="30" height="24"><rect x="2" y="5" width="26" height="14" rx="7" fill="'+bg+'" stroke="'+(dash?'#9aa3ad':'none')+'" '+(dash?'stroke-dasharray="3 2"':'')+'/><text x="15" y="12.5" text-anchor="middle" dominant-baseline="middle" font-size="7.5" font-weight="700" fill="'+fg+'">去向</text></svg>';
  const line=(c,w,dash)=>'<svg width="30" height="22"><path d="M2 11 L28 11" stroke="'+c+'" stroke-width="'+w+'" '+(dash?'stroke-dasharray="5 3"':'')+' stroke-linecap="round"/></svg>';
  const row=(sw,t,sub)=>sw+'<span class="n">'+t+(sub?'<small>'+sub+'</small>':'')+'</span>';
  const key=(k,t)=>'<span class="lgk">'+k+'</span><span class="n">'+t+'</span>';
  return '<div class="lg">'
   +'<div class="lgh" style="grid-column:1/-1">节点</div>'
   +row(dot('#e6c04a',10,'R','#3a2f05'),'检索轮次 R','越大，这轮看的文献越多；角标 ＋／− 收放')
   +row(dot('#f0a35e',7.5,'P','#3a2a10'),'文献 P','越大，打过的候选越多')
   +row(ring('#b48cf2','#2f7fc1'),'候选发明点 C','外圈颜色＝最终去向')
   +row(pillsw('#2f7fc1','#fff'),'最终去向','蓝 独权核心 · 紫 从属权项 · 黄 仅说明书 · 红 放弃')
   +row(pillsw('#e9e6df','#333',true),'公知常识 · 本案实验 · 人为决策')
   +'<div class="lgh" style="grid-column:1/-1">候选外圈 ＝ 最终去向</div>'
   +row(ring('#b48cf2','#2f7fc1'),'独权核心')
   +row(ring('#b48cf2','#7d5bb8'),'从属权项')
   +row(ring('#b48cf2','#c9a227'),'仅说明书')
   +row(ring('#b48cf2','#d94a3d'),'放弃')
   +'<div class="lgh" style="grid-column:1/-1">连线 ＝ 判定</div>'
   +row(line('#d94a3d',2.5),'被打掉','明文记载 · 毫无疑义确定 · 实测推翻')
   +row(line('#e0962e',2.5),'部分接近','含记载不清')
   +row(line('#3f9d5a',2.5),'未记载','含实测支持')
   +row(line('#2f7fc1',2.5),'教导相反','答辩支点')
   +row(line('#8a8f98',2.5),'人为取舍')
   +row(line('#8a8f98',1),'检出','轮次 → 文献')
   +row(line('#e0962e',3,true),'合并打击 ×n','轮次收起后')
   +'<div class="lgh" style="grid-column:1/-1">操作</div>'
   +key('点','节点 → 右侧看来龙去脉')
   +key('＋／−','轮次 → 收起／展开文献')
   +key('拖','节点可拖，拖空白平移')
   +key('滚','缩放；双击空白复位')
   +key('◀▶','顶部按钮按轮次回放')
   +key('PNG','工具栏导出 2 倍清晰度图片')
   +'</div>';
}
function panel(key){const P=document.getElementById('panel');if(!key){P.innerHTML='<h2>图例</h2>'+legendHTML();return;}
  const n=byId[key];let h='<button class="back" id="backbtn">‹ 图例</button>';
  if(n.kind==='cand'){const c=n.data;h='<h2>'+esc(c.id+' '+c.name)+'</h2>'+tag(c.fate,FC[c.fate])+(c.landing?'<span class="k">'+esc(c.landing)+'</span>':'')+'<p>'+esc(c.summary)+'</p><div class="k">来龙去脉</div><ol>'+c.story.map(s=>'<li>'+esc(s)+'</li>').join('')+'</ol>';}
  else if(n.kind==='doc'){const d=n.data;h='<h2>'+esc(d.id+' '+d.number)+'</h2><p>'+esc(d.title)+'</p><p><span class="k">类型</span> '+esc(d.kind)+'　<span class="k">公开日</span> '+esc(d.date)+'<br><span class="k">检出于</span> '+esc(d.found)+'　<span class="k">阅读</span> '+esc(ftShow(d.fulltext))+(roleShow(d.role)?'<br><span class="k">在本案中</span> <b>'+esc(roleShow(d.role))+'</b>':'')+(d.note?'<br><span class="k">备注</span> '+esc(d.note):'')+'</p>';
    const evs=D.events.filter(e=>e.docs.includes(d.id));if(evs.length)h+='<div class="k">打过哪些候选</div><ol>'+evs.map(e=>evLine(e,{noDoc:true})).join('')+'</ol>';}
  else if(n.kind==='common'){const evs=D.events.filter(e=>e.pseudo.includes(n.key));h='<h2>'+esc(n.l1)+'</h2><p class="k">'+esc(n.l2)+'</p><ol>'+evs.map(e=>evLine(e,{noDoc:true})).join('')+'</ol>';}
  else if(n.kind==='round'){const r=n.data;h='<h2>'+esc(r.id)+'</h2><p>'+esc(r.purpose)+'</p><p><span class="k">入口</span> '+esc(r.venue)+'<br><span class="k">语言</span> '+esc(r.lang)+(r.gaps?'<br><span class="k">未覆盖的库</span> '+esc(r.gaps):'')+'<br><span class="k">详细记录</span> '+esc(r.record)+'</p>';
    if(r.queries.length)h+='<div class="k">查询式（'+r.queries.length+'）</div><ol>'+r.queries.map(q=>'<li>'+esc(q.query)+' <span class="k">'+esc(q.venue)+'</span> → <b>'+(q.hits===null?'—':q.hits)+'</b>'+(q.note?' <span class="k">'+esc(q.note)+'</span>':'')+'</li>').join('')+'</ol>';
    const evs=D.events.filter(e=>e.round===r.id);if(evs.length)h+='<div class="k">本轮对照</div><ol>'+evs.map(e=>evLine(e)).join('')+'</ol>';}
  else if(n.kind==='fate'){const f=n.data.fate;h='<h2>'+esc(f)+'</h2><ol>'+cands.filter(c=>c.fate===f).map(c=>'<li><b>'+esc(c.id+' '+c.name)+'</b>'+(c.landing?'：'+esc(c.landing):'')+'</li>').join('')+'</ol>';}
  P.innerHTML=h;const bb=document.getElementById('backbtn');if(bb)bb.onclick=()=>select(null);}


// ===== 图谱视图：力导向、可拖拽缩放、轮次可收放 =====
const GV=(function(){
  const wrap=document.getElementById('gview'), cv=document.getElementById('gc'), tip=document.getElementById('gtip');
  const ctxRef={ctx:cv.getContext('2d')};
  const KC={round:'#e6c04a',doc:'#f0a35e',common:'#9aa3ad',cand:'#b48cf2',fate:'#5aa9e6'};
  const TX={round:0.09,doc:0.34,common:0.50,cand:0.67,fate:0.93};
  let W=0,H=0,dpr=1,zoom=1,panX=0,panY=0,alpha=1,raf=null,dragging=null,dragMoved=false,panning=null,hover=null,dark=true,seeded=false;
  const expanded=new Set(D.rounds.map(r=>r.id));
  const filter={killed:true,near:true,clear:true,away:true,decision:true,found:true,fate:true};
  function radius(n){
    if(n.kind==='round'){const c=D.docs.filter(d=>d.found===n.data.id).length;return 16+Math.min(12,c)*0.6+Math.min(10,n.data.queries.length)*0.3;}
    if(n.kind==='doc')return 9+Math.min(6,D.events.filter(e=>e.docs.includes(n.data.id)).length)*1.1;
    if(n.kind==='cand')return 13+Math.min(12,D.events.filter(e=>e.candidate===n.data.id).length)*0.8;
    if(n.kind==='fate')return 13; return 12;}
  // 胶囊形节点（最终去向、公知常识/实验/决策）：文字写在里面，半径只用来算碰撞
  function pillW(g){return Math.max(g.r*2, (g.kind==='fate'?g.n.data.fate:g.n.l1).length*12+22);}
  const gn=nodes.map(n=>({n,key:n.key,kind:n.kind,x:0,y:0,vx:0,vy:0,r:radius(n),fixed:false}));
  const gById={};gn.forEach(g=>gById[g.key]=g);
  function seed(){gn.forEach(g=>{g.x=W*TX[g.kind]+(Math.random()-0.5)*90;g.y=H*0.5+(Math.random()-0.5)*H*0.85;g.vx=g.vy=0;g.fixed=false;});
    // 文献先靠着自己的轮次
    gn.forEach(g=>{if(g.kind==='doc'){const R=gById['R:'+g.n.data.found];if(R){g.x=R.x+70+(Math.random()-0.5)*60;g.y=R.y+(Math.random()-0.5)*120;}}});
    alpha=1;seeded=true;}
  function visible(g){const n=g.n;if(n.intro>upto)return false;if(n.kind==='doc'&&!expanded.has(n.data.found))return false;return true;}
  function activeEdges(){
    const out=[],agg={};
    edges.forEach(e=>{if(e.intro>upto)return;const A=gById[e.a],B=gById[e.b];if(!A||!B)return;const va=visible(A),vb=visible(B);
      if(e.cls==='verdict'){if(!filter[e.ev.kind])return;
        if(va&&vb){out.push({a:A,b:B,color:e.color,w:1.4,kind:e.ev.kind,label:e.label});}
        else if(!va&&A.kind==='doc'&&vb){const R=gById['R:'+A.n.data.found];if(!R||!visible(R))return;const k=R.key+'|'+B.key;const a=(agg[k]=agg[k]||{a:R,b:B,kinds:{},count:0});a.kinds[e.ev.kind]=(a.kinds[e.ev.kind]||0)+1;a.count++;}}
      else if(e.cls==='found'){if(!filter.found)return;if(va&&vb)out.push({a:A,b:B,color:dark?'#3d4760':'#cfc9bb',w:1,kind:'found'});}
      else if(e.cls==='fate'){if(!filter.fate)return;if(va&&vb)out.push({a:A,b:B,color:e.color,w:2,kind:'fate',label:e.label});}});
    const order=['killed','away','near','clear','decision'];
    Object.values(agg).forEach(a=>{const k=order.find(x=>a.kinds[x])||'clear';out.push({a:a.a,b:a.b,color:VC[k],w:1+Math.min(4,a.count*0.5),kind:k,agg:a.count});});
    return out;}
  function physics(vis,es){const k=alpha;const sparse=Math.max(1,Math.min(2.6,70/Math.max(vis.length,1)));
    vis.forEach(g=>{if(g.fixed)return;g.vx+=(W*TX[g.kind]-g.x)*0.035*k;g.vy+=(H/2-g.y)*0.0015*k;});
    for(let i=0;i<vis.length;i++){const a=vis[i];for(let j=i+1;j<vis.length;j++){const b=vis[j];let dx=b.x-a.x,dy=b.y-a.y,d2=dx*dx+dy*dy;if(d2<1){dx=Math.random()-0.5;dy=Math.random()-0.5;d2=1;}const d=Math.sqrt(d2);const both=a.kind!=='doc'&&b.kind!=='doc';const ra=(a.kind==='fate'||a.kind==='common')?pillW(a)/2:a.r,rb=(b.kind==='fate'||b.kind==='common')?pillW(b)/2:b.r;const min=ra+rb+(both?70:16);const wgt=(a.kind==='doc'?1:2.2)*(b.kind==='doc'?1:2.2);let f=1500*sparse*wgt*k/d2;if(d<min)f+=(min-d)*(both?0.5:0.3);const fx=dx/d*f,fy=dy/d*f;if(!a.fixed){a.vx-=fx;a.vy-=fy;}if(!b.fixed){b.vx+=fx;b.vy+=fy;}}}
    es.forEach(e=>{const a=e.a,b=e.b,dx=b.x-a.x,dy=b.y-a.y,d=Math.sqrt(dx*dx+dy*dy)||1;const rest=(e.kind==='found'?75:(e.kind==='fate'?130:170))*Math.sqrt(sparse);const f=(d-rest)*0.02*k,fx=dx/d*f,fy=dy/d*f;if(!a.fixed){a.vx+=fx;a.vy+=fy;}if(!b.fixed){b.vx-=fx;b.vy-=fy;}});
    vis.forEach(g=>{if(g.fixed)return;g.vx*=0.8;g.vy*=0.8;g.x+=g.vx;g.y+=g.vy;g.x=Math.max(24,Math.min(W-24,g.x));g.y=Math.max(24,Math.min(H-24,g.y));});}
  function label(g){const n=g.n;if(n.kind==='round'){const c=D.docs.filter(d=>d.found===n.data.id).length;return c?c+' 篇文献':'';}
    if(n.kind==='doc')return (n.data.number||n.data.title).slice(0,16);if(n.kind==='cand')return n.data.name.slice(0,14);return '';}
  function draw(vis,es){const ctx=ctxRef.ctx;
    ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle=dark?'#0d1220':'#f7f5f0';ctx.fillRect(0,0,W,H);
    if(dark){const g=ctx.createRadialGradient(W*0.5,H*0.45,60,W*0.5,H*0.45,Math.max(W,H)*0.75);g.addColorStop(0,'rgba(58,82,150,.22)');g.addColorStop(1,'rgba(0,0,0,0)');ctx.fillStyle=g;ctx.fillRect(0,0,W,H);}
    ctx.save();ctx.translate(panX,panY);ctx.scale(zoom,zoom);const step=40;const x0=Math.floor(-panX/zoom/step)*step,y0=Math.floor(-panY/zoom/step)*step,x1=(W-panX)/zoom,y1=(H-panY)/zoom;
    ctx.fillStyle=dark?'rgba(255,255,255,.07)':'rgba(0,0,0,.08)';for(let x=x0;x<x1;x+=step)for(let y=y0;y<y1;y+=step){ctx.fillRect(x-0.6,y-0.6,1.2,1.2);}ctx.restore();
    ctx.translate(panX,panY);ctx.scale(zoom,zoom);
    const sel=selected;const nb=new Set();if(sel){es.forEach(e=>{if(e.a.key===sel||e.b.key===sel){nb.add(e.a.key);nb.add(e.b.key);}});}
    const lw=1/Math.sqrt(zoom);const fewDocs=vis.filter(x=>x.kind==='doc').length<=16;const labels=[];
    es.forEach(e=>{const on=!sel||e.a.key===sel||e.b.key===sel;ctx.globalAlpha=on?(e.kind==='found'?0.55:0.85):0.06;ctx.strokeStyle=e.color;ctx.lineWidth=e.w*lw;ctx.setLineDash(e.agg?[7,5]:[]);
      const mx=(e.a.x+e.b.x)/2,my=(e.a.y+e.b.y)/2-(e.b.x-e.a.x)*0.06;ctx.beginPath();ctx.moveTo(e.a.x,e.a.y);ctx.quadraticCurveTo(mx,my,e.b.x,e.b.y);ctx.stroke();
      if(e.agg){ctx.setLineDash([]);ctx.font='bold 10px sans-serif';ctx.fillStyle=e.color;ctx.fillText('×'+e.agg,mx+3,my-3);}
      else if(sel&&on&&e.label&&e.kind!=='found'){ctx.font='10.5px -apple-system,"PingFang SC","Microsoft YaHei",sans-serif';ctx.fillStyle=dark?'#dfe3ea':'#333';ctx.strokeStyle=dark?'rgba(15,20,32,.9)':'rgba(255,255,255,.9)';ctx.lineWidth=3;ctx.lineJoin='round';ctx.strokeText(e.label,mx+3,my-3);ctx.fillText(e.label,mx+3,my-3);}});
    ctx.setLineDash([]);
    const FONT='-apple-system,"PingFang SC","Microsoft YaHei",sans-serif';
    function pill(x,y,w,h){const r=h/2;ctx.beginPath();ctx.moveTo(x-w/2+r,y-h/2);ctx.lineTo(x+w/2-r,y-h/2);ctx.arc(x+w/2-r,y,r,-Math.PI/2,Math.PI/2);ctx.lineTo(x-w/2+r,y+h/2);ctx.arc(x-w/2+r,y,r,Math.PI/2,Math.PI*1.5);ctx.closePath();}
    vis.forEach(g=>{const on=!sel||nb.has(g.key)||g.key===sel;ctx.globalAlpha=on?1:0.14;const col=g.kind==='fate'?FC[g.n.data.fate]:KC[g.kind];
      const isPill=g.kind==='fate'||g.kind==='common';
      if(isPill){const w=pillW(g),h=26;
        ctx.shadowBlur=(g.key===sel||g===hover)?24:(dark?8:0);ctx.shadowColor=col;pill(g.x,g.y,w,h);ctx.fillStyle=g.kind==='fate'?col:(dark?'#2a3040':'#e9e6df');ctx.fill();ctx.shadowBlur=0;
        pill(g.x,g.y,w,h);ctx.strokeStyle=g.kind==='fate'?'rgba(255,255,255,.45)':(dark?'#8a93a3':'#9aa3ad');ctx.lineWidth=1.2*lw;if(g.kind==='common')ctx.setLineDash([3,3]);ctx.stroke();ctx.setLineDash([]);
        if(g.key===sel){pill(g.x,g.y,w+10,h+10);ctx.strokeStyle=dark?'#fff':'#222';ctx.lineWidth=1.5*lw;ctx.setLineDash([3,3]);ctx.stroke();ctx.setLineDash([]);}
        ctx.fillStyle=g.kind==='fate'?'#fff':(dark?'#e8ebf1':'#333');ctx.font='600 12px '+FONT;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(g.kind==='fate'?g.n.data.fate:g.n.l1,g.x,g.y+0.5);ctx.textAlign='left';ctx.textBaseline='alphabetic';
        return;}
      if(g.kind!=='doc'){ctx.beginPath();ctx.arc(g.x,g.y,g.r+5,0,Math.PI*2);ctx.fillStyle=col;ctx.globalAlpha*=0.18;ctx.fill();ctx.globalAlpha=on?1:0.14;}
      ctx.shadowBlur=(g.key===sel||g===hover)?28:(dark?10:0);ctx.shadowColor=col;ctx.beginPath();ctx.arc(g.x,g.y,g.r,0,Math.PI*2);ctx.fillStyle=col;ctx.fill();ctx.shadowBlur=0;
      if(dark){ctx.strokeStyle='rgba(255,255,255,.35)';ctx.lineWidth=1*lw;ctx.stroke();}
      if(g.kind==='cand'){ctx.beginPath();ctx.arc(g.x,g.y,g.r+3.5,0,Math.PI*2);ctx.strokeStyle=FC[g.n.data.fate];ctx.lineWidth=2.6*lw;ctx.stroke();}
      if(g.key===sel){ctx.beginPath();ctx.arc(g.x,g.y,g.r+(g.kind==='cand'?7:4),0,Math.PI*2);ctx.strokeStyle=dark?'#fff':'#222';ctx.lineWidth=1.5*lw;ctx.setLineDash([3,3]);ctx.stroke();ctx.setLineDash([]);}
      // 圆里写编号：R5 / C7 / P12
      const idText=g.n.data.id;const fs=g.kind==='doc'?Math.max(7.5,Math.min(9.5,g.r*0.85)):Math.max(10,Math.min(13,g.r*0.72));
      ctx.fillStyle=g.kind==='doc'?(dark?'#1a1408':'#3a2a10'):(g.kind==='round'?'#3a2f05':'#fff');ctx.font='700 '+fs+'px '+FONT;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(idText,g.x,g.y+0.5);ctx.textAlign='left';ctx.textBaseline='alphabetic';
      // 轮次右下角的收放小标
      if(g.kind==='round'){const bx=g.x+g.r*0.72,by=g.y+g.r*0.72;ctx.beginPath();ctx.arc(bx,by,6.5,0,Math.PI*2);ctx.fillStyle=dark?'#0d1220':'#fff';ctx.fill();ctx.strokeStyle=col;ctx.lineWidth=1.2*lw;ctx.stroke();ctx.fillStyle=col;ctx.font='700 11px '+FONT;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(expanded.has(g.n.data.id)?'−':'+',bx,by+0.5);ctx.textAlign='left';ctx.textBaseline='alphabetic';}
      const show=(g.kind==='cand')||(g.kind==='round')||(g.kind==='doc'&&(fewDocs||zoom>1.15||g.key===sel||nb.has(g.key)||g===hover));
      if(show&&label(g))labels.push({g,on});});
    // 标签避让：按重要度排，后来的躲开先放的；右、下、上、左四个位置试一遍
    const placed=[];const prio={cand:0,fate:1,round:2,common:3,doc:4};
    // 胶囊节点和大圆本身也是障碍，标签别压在它们身上
    vis.forEach(g=>{if(g.kind==='fate'||g.kind==='common'){const w=pillW(g);placed.push({x:g.x-w/2-4,y:g.y-17,w:w+8,h:34});}else if(g.kind!=='doc'){placed.push({x:g.x-g.r-2,y:g.y-g.r-2,w:g.r*2+4,h:g.r*2+4});}});
    labels.sort((a,b)=>(prio[a.g.kind]-prio[b.g.kind])||(b.g.r-a.g.r));
    labels.forEach(({g,on})=>{const t=label(g);const font=(g.kind==='cand'||g.kind==='round'||g.kind==='fate'?'600 ':'')+(g.kind==='doc'?'11px':'12px')+' -apple-system,"PingFang SC","Microsoft YaHei",sans-serif';ctx.font=font;
      const w=ctx.measureText(t).width,h=14;const rr=g.kind==='round'?g.r+4:g.r;const cands=[[g.x+rr+5,g.y+4],[g.x-w/2,g.y+rr+15],[g.x-w/2,g.y-rr-6],[g.x-rr-5-w,g.y+4]];
      let pos=cands[0];for(const c of cands){const box={x:c[0],y:c[1]-h+3,w,h};if(!placed.some(b=>!(box.x>b.x+b.w||b.x>box.x+box.w||box.y>b.y+b.h||b.y>box.y+box.h))){pos=c;break;}}
      placed.push({x:pos[0],y:pos[1]-h+3,w,h});
      ctx.globalAlpha=on?1:0.14;ctx.fillStyle=g.kind==='round'?(dark?'#c9cfda':'#6b7280'):(dark?'#e8ebf1':'#1f2328');ctx.strokeStyle=dark?'rgba(13,18,32,.9)':'rgba(247,245,240,.92)';ctx.lineWidth=3;ctx.lineJoin='round';ctx.strokeText(t,pos[0],pos[1]);ctx.fillText(t,pos[0],pos[1]);});
    ctx.globalAlpha=1;}
  let fitPending=false;
  function fit(){const vis=gn.filter(visible);if(!vis.length)return;let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;vis.forEach(g=>{x0=Math.min(x0,g.x-g.r);y0=Math.min(y0,g.y-g.r);x1=Math.max(x1,g.x+g.r+(g.kind==='doc'?60:150));y1=Math.max(y1,g.y+g.r);});
    const pad=30;const z=Math.max(0.35,Math.min(1.6,Math.min((W-pad*2)/(x1-x0),(H-pad*2)/(y1-y0))));zoom=z;panX=(W-(x1-x0)*z)/2-x0*z;panY=(H-(y1-y0)*z)/2-y0*z;render();}
  let fc=0;
  function frame(){const vis=gn.filter(visible),es=activeEdges();physics(vis,es);fc++;if(fitPending&&fc%12===0)fit();else draw(vis,es);alpha*=0.975;if(alpha>0.02||dragging){raf=requestAnimationFrame(frame);}else{raf=null;if(fitPending){fitPending=false;fit();}}}
  function render(){const vis=gn.filter(visible);draw(vis,activeEdges());}
  function kick(a){alpha=Math.max(alpha,a==null?0.5:a);if(!raf)raf=requestAnimationFrame(frame);}
  function resize(){if(wrap.offsetParent===null)return;dpr=window.devicePixelRatio||1;W=wrap.clientWidth;H=Math.max(600,Math.min(900,window.innerHeight-250));cv.width=W*dpr;cv.height=H*dpr;cv.style.width=W+'px';cv.style.height=H+'px';if(!seeded){seed();fitPending=true;}kick(0.6);}
  function toWorld(ev){const r=cv.getBoundingClientRect();const sx=ev.clientX-r.left,sy=ev.clientY-r.top;return{x:(sx-panX)/zoom,y:(sy-panY)/zoom,sx,sy};}
  function hit(p){let best=null,bd=1e9;gn.filter(visible).forEach(g=>{const isPill=g.kind==='fate'||g.kind==='common';const d=Math.hypot(g.x-p.x,g.y-p.y);const lim=isPill?Math.max(15,pillW(g)/2):g.r+4;if(d<lim&&d<bd){bd=d;best=g;}});return best;}
  function tipHtml(g){const n=g.n;if(n.kind==='round'){const r=n.data;return '<b>'+esc(r.id)+'</b><br>'+esc(r.purpose)+'<br><span style="opacity:.7">查询式 '+r.queries.length+' 条 · 检出 '+D.docs.filter(d=>d.found===r.id).length+' 篇 · 点击'+(expanded.has(r.id)?'收起':'展开')+'</span>';}
    if(n.kind==='doc'){const d=n.data;return '<b>'+esc(d.id+' '+d.number)+'</b><br>'+esc(d.title)+'<br><span style="opacity:.7">'+esc([d.kind,ftShow(d.fulltext),roleShow(d.role)].filter(Boolean).join(' · '))+'</span>';}
    if(n.kind==='cand'){const c=n.data;return '<b>'+esc(c.id+' '+c.name)+'</b><br>'+esc(c.summary)+'<br><span style="opacity:.7">→ '+esc(c.fate+(c.landing?'：'+c.landing:''))+'</span>';}
    if(n.kind==='fate')return '<b>'+esc(n.data.fate)+'</b><br>'+esc(n.l2);return '<b>'+esc(n.l1)+'</b><br>'+esc(n.l2);}
  function showTip(g,ev){if(!g){tip.style.display='none';return;}tip.innerHTML=tipHtml(g);tip.style.display='block';moveTip(ev);}
  function moveTip(ev){const r=wrap.getBoundingClientRect();let x=ev.clientX-r.left+14,y=ev.clientY-r.top+14;if(x+tip.offsetWidth>W-8)x=Math.max(8,x-tip.offsetWidth-28);if(y+tip.offsetHeight>r.height-8)y=Math.max(8,y-tip.offsetHeight-28);tip.style.left=x+'px';tip.style.top=y+'px';}
  cv.addEventListener('mousedown',ev=>{const p=toWorld(ev);const g=hit(p);dragMoved=false;if(g){dragging=g;g.fixed=true;cv.style.cursor='grabbing';}else{panning={x:ev.clientX,y:ev.clientY,px:panX,py:panY};cv.style.cursor='grabbing';}tip.style.display='none';});
  window.addEventListener('mousemove',ev=>{if(dragging){const p=toWorld(ev);dragging.x=p.x;dragging.y=p.y;dragMoved=true;kick(0.3);return;}
    if(panning){panX=panning.px+(ev.clientX-panning.x);panY=panning.py+(ev.clientY-panning.y);if(Math.abs(ev.clientX-panning.x)+Math.abs(ev.clientY-panning.y)>3)dragMoved=true;render();return;}
    if(ev.target===cv){const g=hit(toWorld(ev));if(g!==hover){hover=g;cv.style.cursor=g?'pointer':'grab';showTip(g,ev);render();}else if(g)moveTip(ev);}});
  window.addEventListener('mouseup',ev=>{if(dragging){const g=dragging;dragging=null;g.fixed=false;cv.style.cursor='grab';if(!dragMoved)onClick(g);kick(0.3);return;}
    if(panning){panning=null;cv.style.cursor='grab';if(!dragMoved&&ev.target===cv)select(null);}});
  cv.addEventListener('wheel',ev=>{ev.preventDefault();const p=toWorld(ev);const f=ev.deltaY<0?1.12:1/1.12;const nz=Math.max(0.3,Math.min(3.5,zoom*f));panX=p.sx-p.x*nz;panY=p.sy-p.y*nz;zoom=nz;render();},{passive:false});
  cv.addEventListener('dblclick',ev=>{if(!hit(toWorld(ev))){zoom=1;panX=0;panY=0;render();}});
  cv.addEventListener('mouseleave',()=>{hover=null;tip.style.display='none';render();});
  function toggleRound(id){if(expanded.has(id)){expanded.delete(id);}else{expanded.add(id);const R=gById['R:'+id];gn.forEach(g=>{if(g.kind==='doc'&&g.n.data.found===id){g.x=R.x+60+(Math.random()-0.5)*50;g.y=R.y+(Math.random()-0.5)*80;g.vx=g.vy=0;}});}kick(0.7);}
  function onClick(g){if(g.kind==='round')toggleRound(g.n.data.id);select(g.key);}
  document.getElementById('g-expand').onclick=()=>{D.rounds.forEach(r=>{if(!expanded.has(r.id))toggleRound(r.id);});};
  document.getElementById('g-collapse').onclick=()=>{D.rounds.forEach(r=>expanded.delete(r.id));kick(0.7);};
  document.getElementById('g-relayout').onclick=()=>{seed();zoom=1;panX=0;panY=0;fitPending=true;kick(1);};
  document.getElementById('g-fit').onclick=()=>fit();
  document.getElementById('g-theme').onclick=function(){dark=!dark;wrap.classList.toggle('light',!dark);this.textContent=dark?'浅色':'深色';render();};
  function savePng(url,name){const a=document.createElement('a');a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();}
  document.getElementById('g-png').onclick=()=>{const scale=2;const c=document.createElement('canvas');c.width=W*scale;c.height=H*scale;const odpr=dpr;const c2=c.getContext('2d');
    // 借用同一套画法：临时把 ctx 指向导出画布
    const vis=gn.filter(visible),es=activeEdges();const saveCtx=ctxRef.ctx;ctxRef.ctx=c2;dpr=scale;draw(vis,es);ctxRef.ctx=saveCtx;dpr=odpr;render();
    savePng(c.toDataURL('image/png'),'检索轨迹图谱-'+D.case+'.png');};
  document.getElementById('f-png').onclick=()=>{const svgEl=document.getElementById('g');const w=+svgEl.getAttribute('width'),h=+svgEl.getAttribute('height');
    const clone=svgEl.cloneNode(true);clone.setAttribute('xmlns','http://www.w3.org/2000/svg');
    const css=document.querySelector('style').textContent;const st=document.createElementNS('http://www.w3.org/2000/svg','style');st.textContent=css;clone.insertBefore(st,clone.firstChild);
    const xml=new XMLSerializer().serializeToString(clone);const img=new Image();
    img.onload=()=>{const c=document.createElement('canvas');c.width=w*2;c.height=h*2;const x=c.getContext('2d');x.fillStyle='#fff';x.fillRect(0,0,c.width,c.height);x.scale(2,2);x.drawImage(img,0,0);savePng(c.toDataURL('image/png'),'检索轨迹流程图-'+D.case+'.png');};
    img.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(xml);};
  document.querySelectorAll('.gtools .chip').forEach(c=>{c.onclick=()=>{const f=c.dataset.f;filter[f]=!filter[f];c.classList.toggle('off',!filter[f]);kick(0.3);};});
  const tabG=document.getElementById('tab-graph'),tabF=document.getElementById('tab-flow'),gw=document.querySelector('.gwrap');
  tabG.onclick=()=>{tabG.classList.add('on');tabF.classList.remove('on');wrap.style.display='';gw.style.display='none';curView='graph';if(!selected)panel(null);resize();};
  tabF.onclick=()=>{tabF.classList.add('on');tabG.classList.remove('on');wrap.style.display='none';gw.style.display='';curView='flow';if(!selected)panel(null);};
  window.addEventListener('resize',()=>{if(wrap.style.display!=='none'){const os=seeded;resize();if(os)kick(0.4);}});
  resize();
  return {refresh:()=>{if(seeded)kick(0.4);}};
})();

panel(null);
// 演变表
const evo=document.getElementById('evo');const T=D.evolution;
evo.innerHTML='<tr>'+T[0].map(h=>'<th>'+esc(h)+'</th>').join('')+'</tr>'+T.slice(1).map(r=>'<tr>'+r.map((c,i)=>'<td class="'+(i===0?'c':'')+'">'+esc(c).replace(/(明文记载|毫无疑义确定)/g,'<span class="killed">$1</span>').replace(/(部分接近|记载不清)/g,'<span class="near">$1</span>').replace(/(未记载)/g,'<span class="clear">$1</span>').replace(/(教导相反)/g,'<span class="away">$1</span>').replace(/(实测推翻)/g,'<span class="killed">$1</span>').replace(/(实测支持)/g,'<span class="clear">$1</span>')+'</td>').join('')+'</tr>').join('');
apply();
})();
</script>
</body>
</html>
"""


def build_html(led: dict, case: str, st: dict, ledger_name: str) -> str:
    cands, rounds, docs = led["candidates"], led["rounds"], led["docs"]
    pseudo_nodes = []
    for code in ("CK", "EX", "DC"):
        rs = [ev["round"] for ev in led["events"] if code in ev["pseudo"]]
        if rs:
            first = min(rs, key=round_key)
            pseudo_nodes.append({"code": code, "label": PSEUDO_LABEL[code][0], "desc": PSEUDO_LABEL[code][1], "round": first})
    gaps = [f"{rid} 未覆盖：{rounds[rid]['gaps']}" for rid in led["round_order"] if rounds[rid]["gaps"]]
    gaps += [f"线索未解决：{d['id']} {d['number']} {d['title'][:40]}（{d['fulltext'] or '未填'}）{'—' + d['note'] if d['note'] else ''}"
             for d in docs.values() if d["role"] == "线索未解决"]
    web_meta = {k: v for k, v in led["meta"].items() if not re.search(r"日期|截止|时间|日$", k)}
    data = {
        "case": case, "meta": web_meta, "stats": st,
        "rounds": [{"id": r["id"], "purpose": r["purpose"], "venue": r["venue"], "lang": r["lang"],
                    "gaps": r["gaps"], "record": r["record"], "queries": r["queries"]}
                   for r in (rounds[x] for x in led["round_order"])],
        "docs": [{"id": d["id"], "n": round_key(d["id"]), "number": d["number"], "title": d["title"], "kind": d["kind"],
                  "date": d["date"], "found": d["found"], "fulltext": d["fulltext"], "role": d["role"], "note": d["note"]}
                 for d in docs.values()],
        "candidates": [{"id": c["id"], "n": round_key(c["id"]), "name": c["name"], "summary": c["summary"], "since": c["since"],
                        "fate": c["fate"], "landing": c["landing"], "story": candidate_story(led, c, dates=False)}
                       for c in cands.values()],
        "events": [{"round": e["round"], "docs": e["docs"], "pseudo": e["pseudo"], "candidate": e["candidate"],
                    "verdict": e["verdict"], "kind": VERDICT_KIND[e["verdict"]], "impact": e["impact"],
                    "reason": e["reason"], "source": e["source"]} for e in led["events"]],
        "pseudo": pseudo_nodes, "fate_order": list(FATE_ORDER), "fate_colors": FATE_HTML,
        "evolution": evolution_table(led), "gaps": gaps,
    }
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return (HTML_TEMPLATE.replace("__CASE__", html.escape(case))
            .replace("__LEDGER__", html.escape(ledger_name))
            .replace("__DATA__", blob))


# ---------- 主流程 ----------

def build(case_dir: Path, out_name: str = "图谱/检索轨迹", ledger: str | None = None) -> dict:
    ledger_path = find_ledger(case_dir, out_name, ledger)
    led = parse_ledger(ledger_path)
    case = led["case"] or case_dir.name
    st = stats(led)
    out_dir = case_dir / out_name
    written: list[str] = []

    write_notes(led, out_dir, case, written, st)
    page = build_html(led, case, st, ledger_path.name)
    # HTML 头部塞标记，sweep 才认得出是自己生成的
    page = page.replace("<head>", f"<head>\n<!-- {GENERATED_MARK} -->", 1)
    write_file(out_dir / "检索轨迹图谱.html", page, written)
    stale = sweep_stale(out_dir, written)

    return {
        "case": case, "ledger": str(ledger_path), "out_dir": str(out_dir),
        "stats": st, "warnings": led["warnings"],
        "notes_written": len(written), "stale_removed": [Path(p).name for p in stale],
        "graph_nodes": len(led["rounds"]) + len(led["docs"]) + len(led["candidates"]),
        "graph_edges": len(led["events"]) + len(led["docs"]) + len(led["candidates"]),
    }


def _ok_line(summary: dict) -> str:
    """全包统一的机读收尾行：`OK: 键=值 ...`，数字照抄上面人话输出里的统计。"""
    st = summary["stats"]
    stats = {
        "files": summary["notes_written"], "stale": len(summary["stale_removed"]),
        "rounds": st["rounds"], "queries": st["queries"], "zero_hit": st["zero_hit"],
        "docs": st["docs"], "fulltext": st["fulltext"], "candidates": st["candidates"],
        "dropped": st["fates"]["放弃"], "independent": st["fates"]["独权核心"], "dependent": st["fates"]["从属权项"],
        "events": st["events"], "unresolved": st["unresolved"], "warnings": len(summary["warnings"]),
        "nodes": summary["graph_nodes"], "edges": summary["graph_edges"],
    }
    return "OK: " + " ".join(f"{k}={v}" for k, v in stats.items())


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="把检索轨迹台账画成 Obsidian 双链笔记、Canvas 和单文件网页")
    ap.add_argument("case_dir", help="案件目录")
    ap.add_argument("--ledger", help="台账文件（默认在案件目录里找《检索轨迹台账.md》）")
    ap.add_argument("--out", default="图谱/检索轨迹", help="输出子目录（默认：图谱/检索轨迹）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args(argv)

    case_dir = Path(args.case_dir).resolve()
    if not case_dir.is_dir():
        print(f"错误：{case_dir} 不是目录", file=sys.stderr)
        return 2
    try:
        summary = build(case_dir, args.out, args.ledger)
    except LedgerError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(_ok_line(summary), file=sys.stderr, flush=True)   # 机读行走 stderr，stdout 只留 JSON
        return 0
    st = summary["stats"]
    print(f"案件：{summary['case']}　台账：{Path(summary['ledger']).name}")
    print(f"写出 {summary['notes_written']} 个文件到 {summary['out_dir']}")
    if summary["stale_removed"]:
        print(f"清掉 {len(summary['stale_removed'])} 个上一轮留下、这轮已不存在的文件：" + "、".join(summary["stale_removed"]))
    print(f"{st['rounds']} 轮｜查询式 {st['queries']}（0 命中 {st['zero_hit']}）｜文献 {st['docs']}（全文 {st['fulltext']}）"
          f"｜候选 {st['candidates']}（放弃 {st['fates']['放弃']}，独权 {st['fates']['独权核心']}，从属 {st['fates']['从属权项']}）"
          f"｜对照 {st['events']}｜线索未解决 {st['unresolved']}")
    for w in summary["warnings"]:
        print(f"提醒：{w}")
    print(f"图：约 {summary['graph_nodes']} 个节点、{summary['graph_edges']} 条边。"
          f"双击 图谱/检索轨迹/检索轨迹图谱.html 看（任何浏览器，不联网）；Obsidian 用户另可从 检索轨迹总览.md 点双链")
    print(_ok_line(summary), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
