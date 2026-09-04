# 第三方组件说明

从 v1.2.0 起，**本包包含少量第三方开源代码**（改编的 Python 脚本 + 一个原样内置的
JavaScript 文件），全部是 MIT 许可。以下逐个列清楚出处、许可证和改动情况。

除下面列出的以外，本包其余内容——`SKILL.md`、`references/` 全部规则文本、两份审查提示词、
`scripts/` 其余脚本、`obsidian/`、`mcp/`、`install/`、演练案例——均为原创，
适用随包的《许可协议》（`LICENSE.md`）。下面这些 MIT 文件本身仍按 MIT 许可，
MIT 允许你继续按 MIT 使用和再分发**这几个文件**（《许可协议》对本包整体的转售、公开分发限制，
不改变也不能改变这几个文件各自的 MIT 地位）。

## 一、含第三方代码的文件

| 本包中的文件 | 来源 | 许可证 | 关系 |
|---|---|---|---|
| `scripts/mermaid_render.py` | handsomestWei/patent-disclosure-skill 的 `tools/mermaid_render.py` | MIT | **改编**（见下「改了什么」） |
| `scripts/browser.py` | 同上，`tools/browser.py` | MIT | **改编** |
| `scripts/cnipa_search.py` | 同上，`tools/crawl/cnipa_epub_search.py` + `cnipa_epub_parse.py` + `cnipa_epub_crawler.py` + `tools/patent_type.py` 四合一 | MIT | **改编** |
| `scripts/math_to_omml.py` | 同上，`tools/math_to_omml.py` | MIT | **改编** |
| `scripts/pptx_to_md.py` | 同上，`tools/pptx_to_md.py` | MIT | **改编** |
| `scripts/vendor/mermaid.min.js` | mermaid-js/mermaid 官方发行版 11.4.1 | MIT | **原样内置，未改一个字节** |

上游项目：

- **handsomestWei/patent-disclosure-skill** — Copyright (c) 2026 handsomestWei，MIT 许可，
  https://github.com/handsomestWei/patent-disclosure-skill
- **mermaid** — mermaid-js 项目及其贡献者，MIT 许可，
  许可证全文见 https://github.com/mermaid-js/mermaid/blob/develop/LICENSE

每个改编文件的文件头都带着上游版权行和一段「改了什么」的说明，看文件本身最准。

### 改了什么（摘要）

- `mermaid_render.py`：去掉三个上游包内依赖，只留标准库 + 可选 playwright；输出改成本包
  `md_to_docx.py` 认的 `![图 N](mermaid_figures/fig_001.png)` 行（上游是保留围栏 + HTML 注释）；
  围栏源码另存 `.mmd`；Word 改为 `--docx` 显式触发；退出码和 `OK:`/`FAIL:` 行改成本包统一机读约定；
  `--probe` 并入本脚本。
- `browser.py`：去掉上游包内 `stdio_utf8` 依赖；`--probe` 的机读约定改成本包格式；文案按本包说法改写。
- `cnipa_search.py`：上游四个文件并成这一个；去掉 pyyaml 和包内 `stdio_utf8` 依赖（专利类型映射
  从 YAML 改成本文件里的 python 字典）；本包只做发明，`--type` 默认 `invention`；
  **开浏览器之前先判断这台机器能不能到这个站**，把「网络到不了」和「站开着但没等到检索框」分成两种
  不同的报错——上游把前者也报成「可增大 WAF 等待时间」，会让人一直去调等待时间；
  解析改成先认新版卡片布局再退回表格；退出码和 `OK:`/`FAIL:` 行改成本包统一机读约定；
  结果页 HTML 仍然只在内存里处理、不落盘（这条是上游的设计，照搬）。
- `math_to_omml.py`：改成可选依赖（没装 `latex2mathml` 时调用方原文保留）；∑/∏/∫ 等大算子改出
  `m:nary`；`\left…\right` 与 `cases` 改出 `m:d` 定界符；`\hat/\bar/\vec` 改出 `m:acc/m:bar`；
  正斜体规则重写；补 `count_omml_in_docx()`。
- `pptx_to_md.py`：每页标题并入 `## 第 N 页：标题`；表格补 Markdown 表头分隔行；命令行对齐本包
  `docx_to_md.py`；缺依赖退出码 2；输出统一 `OK:`/`FAIL:` 行；主体拆成可 import 的 `convert()`。

### 关于内置的 mermaid.min.js

版本 **11.4.1**，md5 `def493e96e3915c5dd101c4395d72dfa`，取自
`https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js`，本包未做任何改动。
它是 mermaid 官方的打包产物，内部还打进了 mermaid 自身依赖的若干开源库
（d3、dompurify、katex 等，各自的版权与许可声明保留在该文件内部）。
本包只在本机用浏览器加载它出 PNG，不联网、不从 CDN 拉、不需要 Node / npm / mmdc。
版本与校验值另见 `scripts/vendor/README.md`。

## 二、MIT 许可证全文

下面这份全文适用于第一节列出的全部文件。用于 handsomestWei/patent-disclosure-skill 的改编文件时，
版权行为 `Copyright (c) 2026 handsomestWei`；用于 `scripts/vendor/mermaid.min.js` 时，
版权归 mermaid-js 项目及其贡献者（以该项目 LICENSE 文件为准）。

```
MIT License

Copyright (c) 2026 handsomestWei

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 三、只参考过思路、没有复制代码的项目

写作过程中参考过产品思路（未复制其代码或文字）的公开项目，在此说明以示尊重：

| 项目 | 许可证 | 关系 |
|---|---|---|
| handsomestWei/patent-disclosure-skill | MIT | **本包含其改编代码，见第一节。** 除代码外，还参考了「专利笔记 + Obsidian 图谱」的产品思路和交底书的章节骨架；本包的案件图谱、检索轨迹图谱、交底书证据要求为独立实现 |
| RobThePCGuy/Claude-Patent-Creator | MIT | 参考了机械检查的思路，未复制代码 |
| gfodor/legal-skills | GPL-3.0 | 仅参考公开思路（独立审查视角、问题台账），未复制任何文字或代码 |

## 四、运行时可能用到的、你自己安装的开源软件

以下软件由你按需自行安装（`requirements-min.txt` / `requirements-full.txt`），各自遵循其许可证，
本包不分发它们：

| 软件 | 许可证 | 用途 |
|---|---|---|
| Python 3.9+ | PSF | 运行 `scripts/` 和 `obsidian/` 下的脚本（不装也不影响规则本身） |
| python-docx | MIT | Word 转换（`docx_to_md.py` / `md_to_docx.py`） |
| pypdf | BSD | PDF 抽文本（`pdf_to_text.py`） |
| matplotlib | PSF 类许可 | 画简单附图（`make_figure.py`） |
| latex2mathml | MIT | `md_to_docx.py` 把 LaTeX 公式转成 Word 可编辑公式；不装则公式按原文保留 |
| python-pptx | MIT | PPT 转 Markdown（`pptx_to_md.py`） |
| playwright | Apache-2.0 | `mermaid_render.py` 驱动本机 Chrome / Edge 出图 |
| pyyaml（可选） | MIT | `make_figure.py` 的 YAML 输入，JSON 不需要 |
| rapidocr-onnxruntime（可选） | Apache-2.0 | `pdf_to_text.py --ocr`，只有扫描版通知书才需要 |
| Google Chrome / Microsoft Edge | 各自的专有条款 | 出图时由 playwright 驱动的本机浏览器；本包不分发、不安装它们 |
| Obsidian | 专有软件，个人与商用免费 | 查看案件图谱；请从 obsidian.md 官网下载 |
