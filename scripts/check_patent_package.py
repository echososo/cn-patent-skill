#!/usr/bin/env python3
"""Read-only surface checks for Chinese patent application files.

This helper catches deterministic drafting defects in DOCX, Markdown, and text
files. It does not decide novelty, inventive step, enablement, or grantability.

机读约定（全包统一）：退出码 0 时 stdout 最后一行 `OK: errors=0 warnings=N files=M`
（--json 时这一行打到 stderr，stdout 只留 JSON）；退出码 1（有 ERROR，或 --strict 下有 WARN）
时 stderr 一行 `FAIL: errors=N warnings=M files=K`。人话输出和 JSON 结构不变。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET


SUPPORTED_SUFFIXES = {".docx", ".md", ".txt"}
WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

SECTION_HEADINGS = {
    "发明名称",
    "权利要求书",
    "说明书",
    "说明书摘要",
    "摘要",
    "技术领域",
    "背景技术",
    "发明内容",
    "附图说明",
    "具体实施方式",
}

PLACEHOLDER_PATTERNS = {
    "placeholder-data": re.compile(r"【\s*占位待实测\s*】|待实测", re.I),
    "placeholder-edit": re.compile(r"\bTODO\b|\bFIXME\b|\bTBD\b|待补充|待填写|待确认", re.I),
    "placeholder-figure": re.compile(r"此处插图|插图占位|```\s*mermaid", re.I),
}

OVERSTRONG_PATTERNS = {
    "不漏解": re.compile(r"不漏解"),
    "穷尽保证": re.compile(r"穷尽保证"),
    "绝对结论": re.compile(r"完全消除|绝不|百分之百|100\s*%"),
}

FRAMEWORK_PATTERN = re.compile(
    r"\b(?:FastAPI|Django|Flask|Spring\s*Boot|LangChain|LlamaIndex|"
    r"SQLAlchemy|Pydantic|React|Vue|Angular|Neo4j|PostgreSQL|MySQL|Redis)\b",
    re.I,
)
SNAKE_CASE_PATTERN = re.compile(r"(?<![A-Za-z0-9])([a-z][a-z0-9]*(?:_[a-z0-9]+)+)(?![A-Za-z0-9])")
API_PATH_PATTERN = re.compile(r"(?<!\w)/(?:api|v\d+|internal)/[A-Za-z0-9_./{}-]+", re.I)


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    context: str = ""


@dataclass
class LoadedDocument:
    source: str
    paragraphs: list[str]
    media_count: int = 0
    content_sha256: str = ""

    @property
    def text(self) -> str:
        return "\n".join(self.paragraphs)


def normalize_heading(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^#{1,6}\s*", "", value)
    value = re.sub(r"^[*_-]+\s*|\s*[*_-]+$", "", value)
    return value.strip().rstrip("：:").strip()


def visible_length(value: str) -> int:
    return len(re.sub(r"\s+", "", value))


def load_docx(path: Path) -> LoadedDocument:
    if not zipfile.is_zipfile(path):
        raise ValueError("文件扩展名为 .docx，但不是有效的 DOCX 压缩包")

    with zipfile.ZipFile(path) as archive:
        try:
            document_xml = archive.read("word/document.xml")
        except KeyError as exc:
            raise ValueError("DOCX 缺少 word/document.xml") from exc

        root = ET.fromstring(document_xml)
        paragraphs: list[str] = []
        ns = {"w": WORD_NAMESPACE}
        for paragraph in root.findall(".//w:p", ns):
            pieces: list[str] = []
            for node in paragraph.iter():
                if node.tag == f"{{{WORD_NAMESPACE}}}t" and node.text:
                    pieces.append(node.text)
                elif node.tag == f"{{{WORD_NAMESPACE}}}tab":
                    pieces.append("\t")
                elif node.tag == f"{{{WORD_NAMESPACE}}}br":
                    pieces.append("\n")
            text = "".join(pieces).strip()
            if text:
                paragraphs.append(text)

        media_count = sum(
            1
            for name in archive.namelist()
            if name.startswith("word/media/") and not name.endswith("/")
        )

    return LoadedDocument(
        str(path),
        paragraphs,
        media_count,
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def load_text(path: Path) -> LoadedDocument:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    return LoadedDocument(
        str(path),
        [line.rstrip() for line in text.splitlines() if line.strip()],
        content_sha256=hashlib.sha256(raw).hexdigest(),
    )


def load_document(argument: str) -> LoadedDocument:
    if argument == "-":
        text = sys.stdin.read()
        return LoadedDocument(
            "<stdin>",
            [line.rstrip() for line in text.splitlines() if line.strip()],
            content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )

    path = Path(argument).expanduser()
    if not path.exists():
        raise ValueError(f"文件不存在：{path}")
    if not path.is_file():
        raise ValueError(f"不是文件：{path}")
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"不支持的文件类型：{path.suffix or '(无扩展名)'}")
    if path.suffix.lower() == ".docx":
        return load_docx(path)
    return load_text(path)


def find_heading(paragraphs: list[str], names: Iterable[str]) -> int | None:
    targets = set(names)
    for index, paragraph in enumerate(paragraphs):
        if normalize_heading(paragraph) in targets:
            return index
    return None


def extract_title(paragraphs: list[str]) -> str | None:
    for index, paragraph in enumerate(paragraphs):
        match = re.match(r"^\s*发明名称\s*[：:]\s*(.+?)\s*$", normalize_heading(paragraph))
        if match:
            return match.group(1).strip()
        if normalize_heading(paragraph) == "发明名称":
            for candidate in paragraphs[index + 1 :]:
                if candidate.strip():
                    return normalize_heading(candidate)
    # Many Chinese filing documents place the title directly on the first line
    # without a separate “发明名称” label.
    title_subjects = re.compile(r"(?:方法|系统|装置|设备|介质|组合物|结构|工艺|用途)$")
    for paragraph in paragraphs:
        normalized = normalize_heading(paragraph)
        if normalized in SECTION_HEADINGS:
            break
        if normalized in {"---", ""} or normalized.startswith(("name:", "description:")):
            continue
        looks_like_title = title_subjects.search(normalized) or normalized.startswith(("一种", "基于", "用于", "面向"))
        if 2 <= visible_length(normalized) <= 100 and looks_like_title:
            return normalized
    return None


def extract_section(paragraphs: list[str], names: set[str]) -> str | None:
    start = find_heading(paragraphs, names)
    if start is None:
        for paragraph in paragraphs:
            normalized = normalize_heading(paragraph)
            for name in names:
                match = re.match(rf"^{re.escape(name)}\s*[：:]\s*(.+)$", normalized)
                if match:
                    return match.group(1).strip()
        return None

    collected: list[str] = []
    for paragraph in paragraphs[start + 1 :]:
        normalized = normalize_heading(paragraph)
        if normalized in SECTION_HEADINGS:
            break
        collected.append(paragraph.strip())
    return "".join(collected).strip() or None


def extract_claims(paragraphs: list[str]) -> tuple[dict[int, str], list[int]]:
    start = find_heading(paragraphs, {"权利要求书"})
    if start is None:
        return {}, []

    claims: dict[int, str] = {}
    sequence: list[int] = []
    current_number: int | None = None
    for paragraph in paragraphs[start + 1 :]:
        normalized = normalize_heading(paragraph)
        if normalized in SECTION_HEADINGS - {"权利要求书"}:
            break
        match = re.match(r"^\s*(\d+)\s*[.．、]\s*(.*)$", paragraph)
        if match:
            current_number = int(match.group(1))
            sequence.append(current_number)
            claims[current_number] = match.group(2).strip()
        elif current_number is not None:
            claims[current_number] = f"{claims[current_number]} {paragraph.strip()}".strip()
    return claims, sequence


def claim_references(claim_text: str) -> set[int]:
    references: set[int] = set()
    for match in re.finditer(r"权利要求\s*([0-9\s、,，和或至到\-—]+)", claim_text):
        references.update(int(number) for number in re.findall(r"\d+", match.group(1)))
    return references


def snippet(text: str, match: re.Match[str], radius: int = 28) -> str:
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def analyze(document: LoadedDocument) -> tuple[list[Issue], dict[str, object]]:
    issues: list[Issue] = []
    text = document.text
    title = extract_title(document.paragraphs)
    abstract = extract_section(document.paragraphs, {"说明书摘要", "摘要"})
    claims, claim_sequence = extract_claims(document.paragraphs)

    if title is None:
        issues.append(Issue("WARN", "title-missing", "未识别到“发明名称”及其内容。"))
    else:
        title_length = visible_length(title)
        if title_length > 60:
            issues.append(Issue("ERROR", "title-over-60", f"发明名称约 {title_length} 字，超过 60 字。", title))
        elif title_length > 25:
            issues.append(Issue("WARN", "title-over-25", f"发明名称约 {title_length} 字；一般目标是不超过 25 字，必要时可放宽。", title))

    if abstract is None:
        issues.append(Issue("WARN", "abstract-missing", "未识别到“摘要”或“说明书摘要”正文。"))
    else:
        abstract_length = visible_length(abstract)
        if abstract_length > 300:
            issues.append(Issue("ERROR", "abstract-over-300", f"摘要可见字符约 {abstract_length} 个，超过 300 字限制。"))

    if not claims:
        issues.append(Issue("WARN", "claims-missing", "未识别到“权利要求书”或编号权项。"))
    else:
        numbers = sorted(claims)
        expected = list(range(1, numbers[-1] + 1))
        duplicate_numbers = sorted({number for number in claim_sequence if claim_sequence.count(number) > 1})
        if duplicate_numbers:
            issues.append(Issue("ERROR", "claim-number-duplicate", f"权项编号重复：{duplicate_numbers}。"))
        if claim_sequence != sorted(claim_sequence):
            issues.append(Issue("ERROR", "claim-number-order", f"权项出现顺序异常：{claim_sequence}。"))
        if numbers != expected:
            issues.append(Issue("ERROR", "claim-number-gap", f"权项编号不连续：识别到 {numbers}，预期 {expected}。"))
        if len(numbers) > 10:
            issues.append(Issue("WARN", "claims-over-10", f"共识别到 {len(numbers)} 项权利要求；超过 10 项可能产生附加费。"))

        for number, claim_text in claims.items():
            for reference in sorted(claim_references(claim_text)):
                if reference not in claims:
                    issues.append(Issue("ERROR", "claim-reference-missing", f"权利要求 {number} 引用了不存在的权利要求 {reference}。"))
                elif reference >= number:
                    issues.append(Issue("ERROR", "claim-reference-forward", f"权利要求 {number} 引用了自身或在后的权利要求 {reference}。"))

    for code, pattern in PLACEHOLDER_PATTERNS.items():
        for match in pattern.finditer(text):
            issues.append(Issue("ERROR", code, "发现未清理的占位或待办标记。", snippet(text, match)))

    for label, pattern in OVERSTRONG_PATTERNS.items():
        for match in pattern.finditer(text):
            issues.append(Issue("WARN", "overstrong-conclusion", f"发现可能缺少成立边界的过强结论：{label}。", snippet(text, match)))

    identifiers = sorted(set(SNAKE_CASE_PATTERN.findall(text)))
    frameworks = sorted(set(match.group(0) for match in FRAMEWORK_PATTERN.finditer(text)), key=str.lower)
    api_paths = sorted(set(API_PATH_PATTERN.findall(text)))
    if identifiers:
        sample = ", ".join(identifiers[:8])
        suffix = "……" if len(identifiers) > 8 else ""
        issues.append(Issue("WARN", "code-identifiers", f"发现疑似代码变量或函数标识：{sample}{suffix}"))
    if frameworks:
        issues.append(Issue("WARN", "framework-names", f"发现可能需要抽象化的框架或产品名：{', '.join(frameworks[:8])}"))
    if api_paths:
        issues.append(Issue("WARN", "api-paths", f"发现可能需要移除的接口路径：{', '.join(api_paths[:8])}"))

    figure_numbers = sorted({int(value) for value in re.findall(r"图\s*(\d+)", text)})
    if figure_numbers:
        expected_figures = list(range(1, figure_numbers[-1] + 1))
        if figure_numbers != expected_figures:
            issues.append(Issue("WARN", "figure-number-gap", f"图号可能不连续：识别到 {figure_numbers}，预期 {expected_figures}。"))
        if document.source.lower().endswith(".docx") and document.media_count == 0:
            issues.append(Issue("ERROR", "figures-not-embedded", "正文引用了附图，但 DOCX 的 word/media 中未发现内嵌图片。"))

    normalized_headings = {normalize_heading(paragraph) for paragraph in document.paragraphs}
    expected_sections = {"技术领域", "背景技术", "发明内容", "具体实施方式"}
    missing_sections = sorted(expected_sections - normalized_headings)
    if missing_sections:
        issues.append(Issue("WARN", "sections-missing", f"未识别到完整说明书常见栏目：{', '.join(missing_sections)}。"))
    if figure_numbers and "附图说明" not in normalized_headings:
        issues.append(Issue("WARN", "drawing-description-missing", "正文引用了附图，但未识别到“附图说明”栏目。"))

    metadata: dict[str, object] = {
        "source": document.source,
        "sha256": document.content_sha256,
        "paragraph_count": len(document.paragraphs),
        "media_count": document.media_count,
        "title": title,
        "title_length": visible_length(title) if title else None,
        "abstract_length": visible_length(abstract) if abstract else None,
        "claim_numbers": sorted(claims),
        "claim_sequence": claim_sequence,
        "figure_numbers": figure_numbers,
        "disclaimer": "仅为确定性表面检查，不判断新颖性、创造性、充分公开或授权前景。",
    }
    return issues, metadata


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", help="一个或多个 .docx/.md/.txt 文件；使用 - 从标准输入读取文本")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--strict", action="store_true", help="存在 WARN 时也返回非零状态")
    return parser.parse_args(argv)


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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    reports: list[dict[str, object]] = []
    error_count = 0
    warning_count = 0

    for argument in args.files:
        try:
            document = load_document(argument)
            issues, metadata = analyze(document)
        except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError) as exc:
            issues = [Issue("ERROR", "read-failed", str(exc))]
            metadata = {"source": argument, "disclaimer": "文件未完成检查。"}

        error_count += sum(issue.severity == "ERROR" for issue in issues)
        warning_count += sum(issue.severity == "WARN" for issue in issues)
        reports.append({"metadata": metadata, "issues": [asdict(issue) for issue in issues]})

    if args.json:
        print(json.dumps({"reports": reports, "errors": error_count, "warnings": warning_count}, ensure_ascii=False, indent=2))
    else:
        for report in reports:
            metadata = report["metadata"]
            print(f"\n检查：{metadata['source']}")
            if metadata.get("sha256"):
                print(f"版本指纹：SHA-256 {metadata['sha256']}")
            print(f"说明：{metadata.get('disclaimer', '')}")
            issues = report["issues"]
            if not issues:
                print("[OK] 未发现脚本可识别的表面问题。")
            for issue in issues:
                context = f" | {issue['context']}" if issue["context"] else ""
                print(f"[{issue['severity']}] {issue['code']}: {issue['message']}{context}")
        print(f"\n汇总：ERROR={error_count}，WARN={warning_count}")

    stats = {"errors": error_count, "warnings": warning_count, "files": len(reports)}
    if error_count or (args.strict and warning_count):
        if args.strict:
            stats["strict"] = 1
        _fail(" ".join(f"{k}={v}" for k, v in stats.items()))
        return 1
    _ok(stats, to_stderr=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
