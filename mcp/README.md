# mcp/：本地工具服务（可选，主流程不需要）

这个目录只干一件事：把包里的转换、附图、形式检查、案件图谱脚本包成一个 MCP 工具服务，
给**没有终端、agent 自己跑不了 Python 脚本**的宿主用。Claude Code / Codex / Cursor 这类
有终端的宿主不需要它，agent 直接跑 `scripts/` 和 `obsidian/` 下的脚本更省事。

> 检索不在这里配。检索什么都不用配：agent 用自带的联网能力，加上包里免 key 的
> `scripts/prior_art_search.py`，能打开哪个库就查哪个库（见 `references/search-and-materials.md`）。

## 什么时候需要

宿主装了技能、也读得懂规则，但你让它"把稿子转成 Word"或"做形式检查"时它说自己没法运行命令——
那就把这六个脚本注册成工具：

| 工具名 | 对应脚本 | 干什么 |
|---|---|---|
| `form_check` | `scripts/check_patent_package.py` | 不用模型的形式检查 |
| `docx_to_md` | `scripts/docx_to_md.py` | Word 转 Markdown |
| `md_to_docx` | `scripts/md_to_docx.py` | Markdown 转可提交排版的 Word |
| `pdf_to_text` | `scripts/pdf_to_text.py` | 对比文件或通知书 PDF 抽文本 |
| `make_figure` | `scripts/make_figure.py` | 画黑白专利附图 |
| `build_case_graph` | `obsidian/build_case_graph.py` | 生成案件图谱 |

## 怎么装（一条命令）

> Windows 上把 `python3` 换成 `py -3`（没有 `py` 就用 `python`）。

```bash
python3 mcp/register.py            # 探测到哪个宿主就写进哪个，原配置先备份
python3 mcp/register.py --dry-run  # 只看会改什么
```

写的是各宿主的 MCP 配置文件（Claude Code `~/.claude.json`、Cursor `~/.cursor/mcp.json`、
Codex `~/.codex/config.toml`、WorkBuddy `~/.workbuddy/.mcp.json`），同名条目原地替换，重复跑安全。
nanobot 的配置格式官方没写清，脚本会打印一段手动配置片段。

装完**重启 agent**，问它一句「用 form_check 检查 examples/demo-case/bad-draft.md」，能出结果就通了。

`local_tools.py` 本身只用标准库；个别工具运行时需要的库（python-docx、pypdf、matplotlib）
见 `requirements-min.txt`，缺哪个它会在结果里直接告诉你。

## 卸载

打开对应宿主的配置文件，删掉 `patent-local-tools` 那一条即可。
