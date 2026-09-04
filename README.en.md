# patent-writing-pro

**A skill for drafting, searching and stress-testing Chinese invention patents — installed into your coding agent.**

[![License: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE)
[![Docs: CC BY-NC-SA 4.0](https://img.shields.io/badge/rules-CC%20BY--NC--SA%204.0-lightgrey.svg)](LICENSE-DOCS)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776ab.svg)](#install)

English · [中文](README.md)

Engineers in China need patents for promotions, grant applications and
high-tech certification. The hard part was never *producing a document* — it is
whether the document survives examination. This skill is about that part:
mining a real inventive point out of your code, writing claims where every
substantive limitation traces back to evidence, and running the draft past two
independent examiner personas before it leaves your machine.

It is not a prompt collection and not a template. It is a set of **rules an
agent executes**, plus the scripts that do the deterministic work.

> Scope: **Chinese invention patents only** (CNIPA, 发明专利). Not utility
> models, not designs, not US/EP practice. The rules and the agent's output are
> in Chinese — that is the language the application is filed in.

---

## Try it in five minutes

After [installing](#install), say one sentence to your agent:

```
专利审查：examples/demo-case/bad-draft.md
```

`demo-case` is a **fictional** practice case shipped with the repo: an
application draft with 12 deliberate defects, plus fictional source code and
tests. You get back an issue ledger — location, problem, minimal fix — for each
one. No material of your own needed.

Prefer something with no model at all? The deterministic form check runs
offline in seconds:

```bash
python3 scripts/check_patent_package.py examples/demo-case/bad-draft.md
# expect 3 ERROR, 7 WARN
```

## What you say to the agent

No skill name to memorise, no prompt name. Any ordinary sentence containing
"专利" routes it:

| You type | What it does | Touches your files? |
|---|---|---|
| `专利审查：<file>` | Balanced simulated substantive examination; per-issue location / problem / minimal fix | No — report only |
| `专利驳回：<file>` | Adversarial rejection stress test; hunts the most lethal attack path | No — report only |
| `专利审查和专利驳回：<file>` | Both passes in order, then a regression check | No — report only |
| `专利撰写：<path>` | Full new application, from understanding the tech to search and verification | Creates files |
| `专利交底书：<path>` | Invention disclosure for your patent attorney; 7 sections + evidence-status appendix | Creates files |
| `专利修改：<file>` | Locks the master, saves a new version | New version, master untouched |
| `专利审查意见答复：<notice>` | Analyses a real office action and prepares a response (does not file it) | Creates a draft |
| `专利检索：<topic>` | Prior-art search and material filing | Creates a search record |
| `专利检索图谱：<case dir>` | Draws what was searched, compared and why this route won | Only under `图谱/检索轨迹/` |

**Unless the word 修改 ("revise") appears, review tasks only report — they never
edit your files.**

## What's inside

| Part | What it does |
|---|---|
| `SKILL.md` + 12 rule files in `references/` | New-case workflow, drafting & review, disclosure template, seven grantability gates, claim–evidence matrix, AI/software subject-matter eligibility, office-action response, pre-filing risk, filing formalities, search discipline, search-trail ledger |
| `references/prompts/` | Two long prompts: balanced substantive examination + adversarial rejection stress test. **Two independent passes, not a model arguing with itself** |
| `references/official/` | Verbatim excerpts of the Patent Law, its Implementing Regulations and CNIPA Order No. 84, so article numbers can be checked offline |
| `scripts/check_patent_package.py` | Model-free form check: sections, word limits, claim numbering and dependency, antecedent basis, placeholders, overclaiming, leaked code symbols |
| `scripts/prior_art_search.py` + `cnipa_search.py` | **Key-free** prior-art search: CNIPA official publication gazette (preferred for Chinese patents, two-round narrowing by IPC), Google Patents search + full text, OpenAlex / arXiv, GitHub, plus a probe of which sources this machine can actually reach |
| `scripts/mermaid_render.py` | Figures: `mermaid` fences in Markdown → PNG, fence replaced in place. Renders with your local Chrome/Edge — **no network, no Node** |
| `scripts/md_to_docx.py` + `math_to_omml.py` | Markdown → filing-formatted Word, with LaTeX turned into **native editable Word equations** |
| `scripts/pptx_to_md.py` / `docx_to_md.py` / `pdf_to_text.py` | Turn inventor-supplied PPT / Word / PDF into Markdown the agent can read whole |
| `obsidian/build_case_graph.py` | Case graph: claims, distinguishing features, cited references, evidence and examination issues wired into one Obsidian backlink graph |
| `obsidian/build_search_trail.py` | Search-trail graph: rounds → documents → candidates → final fate, as a single self-contained HTML page |
| `mcp/` | Optional: register the scripts as MCP tools for hosts without a terminal |

## Four ideas worth stating plainly

**Evidence matrix.** Every substantive limitation in every claim must trace to
source code, a test, a document, or an explicitly flagged proposed design.
No evidence, no claim. This is the single biggest difference from "ask a model
to write me a patent".

**Seven grantability gates.** Subject matter, novelty, inventive step,
sufficiency, support, clarity, amendment basis — each marked only `PASS` /
`RISK` / `BLOCKED` / `N/A`. An unresolved `BLOCKED` blocks the filing draft.
No grant-probability percentage is ever produced: a percentage detached from an
actual search scope is fiction.

**Two examiner passes.** Balanced first, over all six statutory grounds. After
fixes, an adversarial pass hunting the hardest attack — and it must write your
strongest rebuttal *before* deciding whether the attack survives. Two separate
runs, never merged into one long prompt.

**Search-trail graph.** By the end of a case you have read dozens of documents,
killed several candidates and promoted a dependent feature to the core — and
none of that appears in the filed application. One fixed-format ledger per
round plus one command gives you a force-directed graph of the whole route,
readable by the inventor and the attorney.

## Install

A skill is just a folder with a `SKILL.md`. Installing means putting it into
your agent's skills directory.

```bash
git clone https://github.com/<your-account>/patent-writing-pro.git
cd patent-writing-pro
bash install/install.sh        # macOS / Linux / WSL / Git Bash
```

```powershell
powershell -ExecutionPolicy Bypass -File install\install.ps1   # Windows
```

The installer detects which agents you have (Claude Code, Codex CLI, Cursor,
WorkBuddy, nanobot), installs into each, strips the UTF-8 BOM that makes Codex
reject a `SKILL.md`, and prints a line you can paste to verify. It does not
touch the network, install dependencies, or modify anything else; existing
installs are backed up. Then:

```bash
bash install/verify.sh
```

**The rules themselves are plain Markdown and need no dependencies.** Only two
things are optional installs:

```bash
pip3 install -r requirements-min.txt   # Word conversion + editable equations
pip3 install playwright                # figures and CNIPA search (uses your existing Chrome/Edge)
```

See [INSTALL.md](INSTALL.md) for manual installation, per-host paths and
troubleshooting (Chinese).

## Prior-art search needs no configuration

No key, no account, no service to connect. The agent probes what this machine
can reach, then uses whatever is available:

```bash
python3 scripts/prior_art_search.py probe
python3 scripts/prior_art_search.py cnipa 批任务调度 资源画像 异构算力
python3 scripts/prior_art_search.py patents "alert suppression sliding window" --country CN
python3 scripts/prior_art_search.py get CN107196804B --out D1.md
python3 scripts/prior_art_search.py papers "alert suppression sliding window"
```

**Stated up front: completeness is not promised.** What every search record
does state is which entry points were used, which were unreachable, what was
queried and what was not covered. An unreachable source is recorded as
"entry point unavailable" — **never** as "no prior art found". If nothing is
reachable at all, the draft still gets finished, novelty and inventive step are
left as open search items rather than conclusions, and a query list is attached
for you to run elsewhere.

Your draft, code and figures never leave your machine. Only query terms do.

## Tests

```bash
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 -m unittest discover -s obsidian -p 'test_*.py'
python3 -m unittest discover -s mcp -p 'test_*.py'
```

Fully offline — browsers and network are faked. No keys required.

## What it will not do

- No utility models, no designs, no US/EP practice.
- **It does not file anything, does not promise a grant, and is not legal
  advice.** It assists drafting; it does not replace a licensed patent attorney.
- **It does not invent experimental data.** `【占位待实测】` placeholders appear
  only if you explicitly ask for them, and must be replaced before filing.

## Contributing

Rule-text bugs (a stale statutory citation, a false positive in a check, an
unflagged trap in the practice case) are the most valuable issues — see
[CONTRIBUTING.md](CONTRIBUTING.md).

**Never paste a real application into an issue.** An unfiled application is an
undisclosed technical solution; posting it is a public disclosure. Reproduce
with `demo-case`.

## License

- **Code** (`scripts/`, `obsidian/*.py`, `mcp/`, `install/`): MIT — [LICENSE](LICENSE).
- **Rules and prose** (`SKILL.md`, `references/`, the docs): CC BY-NC-SA 4.0 —
  [LICENSE-DOCS](LICENSE-DOCS). Free for personal and in-house use; bundling
  them into a paid product or fee-charging service needs a separate license,
  open an issue.
- **Whatever you produce with it is yours**, commercial use included.
- Third-party code and assets: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
  The figure, equation and PPT-conversion toolchains are adapted under MIT from
  [handsomestWei/patent-disclosure-skill](https://github.com/handsomestWei/patent-disclosure-skill),
  with attribution and a per-file list of changes.

---

> Drafting assistance only. Not legal advice, no guarantee of grant, does not file on your behalf.
