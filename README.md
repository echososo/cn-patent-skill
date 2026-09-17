<div align="center">

# 中国发明专利.skill

> 不只是把技术讲清楚，是把它变成一件**能扛住审查**的申请。

[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](#安装)
[![Tests](https://img.shields.io/badge/tests-291%20passing-brightgreen.svg)](#跑测试)
[![No Node.js](https://img.shields.io/badge/Node.js-不需要-lightgrey.svg)](#安装)
[![AgentSkills](https://img.shields.io/badge/AgentSkills-Standard-green)](https://agentskills.io)

<br>

**技术交底书不知怎么写更好通过授权，一篇查新报告要7000**？<br>
**交底书写完了，心里没底会不会被驳，这里能帮你按照专利审查员的视角检索和审查**<br>
**根本原因：专利代理人不了解技术细节、技术人不了解专利法规，各有盲点，导致申请通过率不高**？<br>

[五分钟看效果](#五分钟看效果) · [运行效果](#运行效果) · [四个行业的完整成品](#四个行业的完整成品) · [你可以这样说](#你可以这样说) · [里面有什么](#里面有什么) · [安装](#安装) · [检索](#检索怎么办什么都不用配) · [跟同类的区别](#跟同类开源包的区别) · [English](README.en.md)

</div>

---

## 它想解决什么

写代码的人评职称、报项目、做高新认定都绕不开专利。但真正难的从来不是"产出一份文件"——
现在让任何一个模型写一份交底书都不难。难的是后面这一段：

**方案怎么收成一组能扛住审查的权利要求；每条限定凭什么写得进去；写完了自己怎么先打一遍。**

这个技能包做的就是这一段。它不是提示词合集，也不是模板，是一套**能被 agent 执行的规则**：
从代码和材料里挖发明点、把每条实质限定都追到证据、用审查员的两种眼光把稿子先审一遍再交出去，
并且把"查过什么、打掉了什么、为什么最后走这条路"画成一张图留下来。

---

## 五分钟看效果

装好之后（见[安装](#安装)），对你的 agent 说一句话：

```
专利审查：examples/demo-case/bad-draft.md
```

`demo-case` 是包里自带的虚构演练案例：一份**故意埋了 12 个坑**的申请文件，配着虚构的代码和测试。
这条命令跑完，你会拿到一份逐条「位置 — 问题 — 最小修改」的模拟审查报告。不用等你自己的材料。

不想动模型？纯规则的形式检查几秒钟出结果，不联网、不用 key：

```bash
python3 scripts/check_patent_package.py examples/demo-case/bad-draft.md
# 应该输出 3 个 ERROR、7 个 WARN
```

---

## 运行效果

### 模拟审查报告：不是"这里可以改改"，是审查员会怎么打你

<img src="docs/screenshot-examination-report.png" alt="模拟审查报告节选：INV-01 创造性意见，含审查员推理、申请人最佳回应、最小修改文字、原始披露依据、保护范围影响" width="100%" />

每条意见固定给八样东西：**审查标准、对比文件原文位置、审查员推理、申请人最佳回应、最小修改文字、
原始披露依据、保护范围影响、结论**。上图那条的落点是——审查员认为"容易组合"的方案，
拿申请人自己的调试数据一比，效果反而**退步**了。

### 检索轨迹图谱：把看不见的那部分工作画出来

<table width="100%">
<tr>
<th width="50%" align="center">图谱视图<br><sub>轮次 · 文献 · 候选 · 最终去向</sub></th>
<th width="50%" align="center">流程视图<br><sub>四列，从左到右一眼看完</sub></th>
</tr>
<tr>
<td width="50%" valign="top"><img src="docs/screenshot-search-trail-graph.png" alt="检索轨迹知识图谱：力导向图，轮次、文献、候选发明点与最终去向" width="100%" /></td>
<td width="50%" valign="top"><img src="docs/screenshot-search-trail-flow.png" alt="检索轨迹流程视图：轮次到文献到候选到最终去向的四列图" width="100%" /></td>
</tr>
</table>

一件案子写到最后，查过几十篇、打掉好几个候选、把某个从属特征升成核心，**申请文件里一个字都看不到**。
每轮检索记一张固定格式的台账，跑一条命令，就得到上面这张图：**单文件 HTML，下载后双击就开**，
不联网、不装东西，能导出 PNG 直接放进汇报材料。

```bash
python3 obsidian/build_search_trail.py examples/02-机械-极片辊压张力控制
```

---

## 四个行业的完整成品

**这是这个仓库最该看的地方。** 别家的 `examples/` 大多只放"扫描用的输入材料"，
这里放的是**跑完整条流程之后的成品**——不用装任何东西，在 GitHub 上直接点开就能读完。

| 案子 | 行业 | 看点 | 权项 | 检索轨迹 |
|---|---|---|---|---|
| [demo-case](examples/demo-case/) | 软件 / 运维 | 一份**故意写坏**的稿子，埋了 12 个坑，用来练"专利审查" | — | 4 轮 / 7 篇 |
| [极片辊压张力控制](examples/02-机械-极片辊压张力控制/) | 机械装备 / 过程控制 | 用申请人自己的数据证明"审查员认为容易组合的方案效果反而退步" | 8 项 | 5 轮 / 9 篇 / 18 次对照 |
| [透析管路气泡检测](examples/03-医疗器械-透析管路气泡检测/) | 医疗器械 / 信号处理 | **怎么绕开专利法第 25 条**"疾病的诊断和治疗方法"不授予专利权 | 9 项 | 5 轮 / 9 篇 / 20 次对照 |
| [磷酸铁锂选择性提锂](examples/04-化工材料-磷酸铁锂选择性提锂/) | 化工 / 湿法冶金 | 化学案件的**数值范围凭什么能被说明书支持**（26.3 / 26.4） | 9 项 | 5 轮 / 8 篇 / 17 次对照 |

后三个案子，每个都有一整套：

**输入材料**（粗糙、有口语，故意写成真实材料的样子）→ **技术交底书**（七章 + 证据状态）→
**申请文件**（权利要求书 + 说明书 + 摘要，附图在 GitHub 上直接渲染）→ **Word 定稿**（点开就能交给代理所）→
**检索轨迹台账 + 图谱** → **权项证据矩阵 + 授权七道门** → **模拟审查报告**。

目录导览和每份文件的看点：[`examples/README.md`](examples/README.md)。

> 四个案子全部虚构——技术方案、实验数据、文献号、日期都是编的，只用来演示产出什么形态的东西。

---

## 你可以这样说

不用记技能名，也不用记提示词名字。一句含"专利"两个字的常规话就能起手：

| 你输入 | 它做什么 | 会不会动你的文件 |
|---|---|---|
| `专利审查：文件名` | 平衡的模拟实质审查视角，逐条给「位置—问题—最小修改」 | 不动，只出报告 |
| `专利驳回：文件名` | 驳回视角的内部压力测试，专找最致命的评价路径 | 不动，只出报告 |
| `专利审查和专利驳回：文件名` | 先后跑完两个视角，再做一次回归核对 | 不动，只出报告 |
| `专利撰写：材料或项目路径` | 从吃透技术、定发明点、检索、验证开始写一件新申请 | 生成新文件 |
| `专利交底书：材料或项目路径` | 按模板成文，七章加一节证据状态，附图出 PNG | 生成新文件 |
| `专利修改：母版文件` | 锁定母版，另存一个新版本 | 生成新版本，不覆盖母版 |
| `专利审查意见答复：通知书文件` | 分析真实审查意见并准备答复（不代为提交） | 生成答复稿 |
| `专利检索：技术主题` | 现有技术检索与材料整理 | 生成检索记录 |
| `专利检索图谱：案件文件夹` | 把这件案子查过什么、比过什么、为什么选这条路画成图 | 只在 `图谱/检索轨迹/` 下生成 |

**只要话里没出现"修改"两个字，审查类任务就只报告问题、不改文件。**
要审完直接动手，说 `专利审查并修改`、`专利驳回分析并修改`。

---

## 里面有什么

| 部分 | 干什么 |
|---|---|
| `SKILL.md` + `references/` 12 份规则 | 新案工作流、撰写与评审、交底书模板、授权七道门、权项与证据矩阵、AI 与软件专利客体、审查意见答复、申请前风险、形式基线、检索规范、检索轨迹台账 |
| `references/prompts/` 两份长提示词 | 平衡模拟实质审查 + 对抗式驳回压力测试。**两个独立视角分两轮跑，不是模型自问自答** |
| `references/official/` | 专利法、实施细则、审查指南第 84 号令的条文**原文摘录**，断网也能核条款号。2023 年实施细则改过编号，旧模板里的条款号大多是错的 |
| `scripts/check_patent_package.py` | 不用模型的形式检查：栏目、字数、权项编号与引用、先行基础、占位、过强结论、泄漏的代码符号，几秒出结果 |
| `scripts/prior_art_search.py` + `cnipa_search.py` | **免 key** 的现有技术检索：国知局中国专利公布公告（中文专利首选，两轮收口）、Google Patents 检索与全文、OpenAlex / arXiv、GitHub，外加一条「这台机器能打开哪些库」的探测 |
| `scripts/mermaid_render.py` | 附图主路径：md 里的 ```mermaid 围栏 → PNG，围栏原地换成 `![图 N](…)`。用**本机 Chrome / Edge** 渲染，**不联网、不装 Node** |
| `scripts/md_to_docx.py` + `math_to_omml.py` | Markdown → Word：宋体、页脚页码、附图嵌进去，LaTeX 公式转成 Word 里**双击就能编辑**的原生公式 |
| `scripts/pptx_to_md.py` / `docx_to_md.py` / `pdf_to_text.py` | 把发明人给的 PPT、Word、PDF 材料转成 agent 能整段读的 Markdown |
| `scripts/make_figure.py` | 附图备选：按 JSON / YAML 描述直接出黑白框图、流程图，不用浏览器 |
| `obsidian/build_case_graph.py` | 案件图谱：权利要求、区别特征、对比文件、证据、审查问题连成一张 Obsidian 双链图 |
| `obsidian/build_search_trail.py` | 检索轨迹图谱：见上面的[运行效果](#运行效果) |
| `mcp/` | 可选。宿主没有终端、agent 自己跑不了 Python 时，把上面几个脚本注册成 MCP 工具 |
| `examples/` | **四个行业的完整成品**，见上 |

### 四个说法，先讲清楚

**证据矩阵**：每条权利要求的每个实质限定，都要能追到代码、测试、文档或明确标记的拟议方案；
写不出证据的不许进权项。这是"稿子有底气"的来源，也是这个包和"让模型写一份专利"最大的区别。

**授权七道门**：客体、新颖性、创造性、充分公开、支持、清楚、修改基础，每道只能标
`PASS` / `RISK` / `BLOCKED` / `N/A`，有未处置的 `BLOCKED` 就不出可提交稿。
**不给授权率百分比**——脱离检索范围的百分比是假的。

**两套审查视角**：先用平衡视角把六项法定审查逐项过一遍；改完再换驳回视角专找最难答复的攻击路径，
而且要求先写出你的最强反驳，再判断这个攻击成不成立。两份提示词分两轮跑，不合成一条。

**打不开就说打不开**：检索入口不可达一律写成「该入口不可用」，**绝不写成「未发现现有技术」**。
一个库都打不开时它也会把稿子写完，只是新颖性和创造性只列待检索项、不下结论。

---

## 安装

技能包就是一个带 `SKILL.md` 的文件夹，装法是**把它放进 agent 的 skills 目录**。

```bash
git clone https://github.com/echososo/cn-patent-skill.git
cd cn-patent-skill
bash install/install.sh        # macOS / Linux / WSL / Git Bash
```

```powershell
powershell -ExecutionPolicy Bypass -File install\install.ps1   # Windows
```

脚本探测你装了哪些 agent（Claude Code / Codex CLI / Cursor / WorkBuddy / nanobot），
装进每一个探测到的，去掉会让 Codex 加载失败的 UTF-8 BOM，最后打印一句可以直接复制的验证台词。
**不联网、不装依赖、不改别的文件**，旧版本自动备份。装完跑一次自检：

```bash
bash install/verify.sh                                          # macOS / Linux
powershell -ExecutionPolicy Bypass -File install\verify.ps1     # Windows
```

手动装法、五个宿主的目录、排障表见 [INSTALL.md](INSTALL.md)。

**规则本体是纯 Markdown，一个依赖都不装也能用。** 只有两件事需要动手，而且都是可选的：

```bash
pip3 install -r requirements-min.txt   # Word 转换 + 可编辑公式
pip3 install playwright                # 出附图、查国知局才需要；本机有 Chrome 或 Edge 就够，不用再下浏览器
```

**不需要 Node.js。** mermaid 出图用的是你本机已有的 Chrome / Edge，mermaid 的 js 在包里自带。

---

## 检索怎么办（什么都不用配）

没有 key，没有账号，没有服务要接。agent 先探测这台电脑能打开哪些库，然后能用哪个用哪个：

```bash
python3 scripts/prior_art_search.py probe

# 中文专利先查国知局官方库：两轮走，先关键词召回顺带拿 IPC，再带分类号收口
python3 scripts/prior_art_search.py cnipa 批任务调度 资源画像 异构算力
python3 scripts/prior_art_search.py cnipa 批任务调度 资源画像 --class G06F9,G06Q10

python3 scripts/prior_art_search.py patents "告警 抑制 滑动窗口" --country CN
python3 scripts/prior_art_search.py get CN107196804B --out D1.md      # 一件专利的全文
python3 scripts/prior_art_search.py papers "alert suppression sliding window"
python3 scripts/prior_art_search.py code "alert deduplication"
```

**边界先说清楚：不承诺检索得全。** 有海外网络的机器，Google Patents 和论文、代码三路都能自动查；
国内直连的机器 Google 系打不开，中文专利走国知局，论文和代码一般能查，其余靠 agent 自带的搜索兜底。
不管哪种情况，检索记录里都会写清用了哪些入口、哪些打不开、查了什么、没覆盖什么。

**你的稿子、代码、附图全程在你自己电脑上处理。出你电脑的只有检索词。**

---

## 跟同类开源包的区别

GitHub 上有一个做得很扎实的同类项目：[handsomestWei/patent-disclosure-skill](https://github.com/handsomestWei/patent-disclosure-skill)（MIT）。
它有两块本仓库**没有**的东西：**把公开专利读成通俗笔记**的阅读模式，以及围绕它的 Obsidian 专利情报库。
要读专利、建自己的专利知识库，去用它，那是它的主场。

两边真正的分工是这样：

| | 本仓库 | patent-disclosure-skill |
|---|---|---|
| 交底书 | ✅ 七章 + 附证据状态（每条机制标清是材料里本有的还是替你补写的） | ✅ 强项，章节完整、方案写得厚 |
| **权利要求书 + 说明书 + 摘要** | ✅ **走到可提交的申请文件** | ➖ 到交底书为止 |
| **模拟实质审查** | ✅ 两套独立视角，逐项法定审查，每条给「位置—问题—最小修改」 | ➖ 有自检，不做审查 |
| **授权风险判断** | ✅ 授权七道门 + 权项证据矩阵 + 退守梯度 | ➖ |
| **审查意见答复** | ✅ 含第 33 条修改超范围核验 | ➖ |
| **检索轨迹图谱** | ✅ 轮次→文献→候选→最终去向，交代过程 | ➖（它的图谱是"读专利"的图谱，是另一件事） |
| 专利通俗解读 | ➖ **不做** | ✅ 它的主场，做得好 |
| 现有技术检索 | ✅ 国知局 + Google Patents + OpenAlex/arXiv + GitHub + 入口探测 | ✅ 国知局优先，降级 WebSearch |
| 附图 → PNG → Word | ✅ **不用 Node**（本机 Chrome） | ✅ 需要 Node / mmdc |
| Word 可编辑公式 | ✅ LaTeX → OMML | ✅ |
| **示例** | ✅ **四个行业的完整成品**（交底书 + 申请文件 + Word + 图谱 + 审查报告） | ➖ 主要是输入材料样例 |
| **测试** | ✅ 291 条，全离线 | ➖ |
| 法条离线摘录 | ✅ 专利法 + 实施细则 + 84 号令 | ➖ |
| 许可 | CC BY-NC-SA 4.0（非商用） | MIT |

一句话：**它帮你把技术讲清楚，本仓库帮你把它变成一件能授权的申请。**
只需要一份交底书交给代理所，2个都够用；要的是"稿子交上去心里有底"，这是我们的重点。

出图、公式、PPT 转换三条工具链**本仓库是按 MIT 规矩改编自它的**，署名和逐条改动写在
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

---

## 跑测试

```bash
python3 -m unittest discover -s scripts   -p 'test_*.py'
python3 -m unittest discover -s obsidian  -p 'test_*.py'
python3 -m unittest discover -s mcp       -p 'test_*.py'
```

291 条用例，**全离线**——浏览器和网络都是假的，不需要任何 key，CI 里也能跑。

---

## 它不做什么

- **只做中国发明专利。** 不做实用新型、不做外观设计、不做美国和欧洲专利——那是另一套法域规则。
- **不做专利通俗解读。** 要读懂一件公开专利，用上面提到的那个项目。
- **不代为提交，不承诺授权，不构成法律意见。** 它是撰写辅助工具，不能替代执业专利代理师。
  拿不准的案子，建议用它把稿子打磨到七八成再找代理师把关：省的是钱，不省专业判断。
- **不编实验数据。** 只有你明确要求占位时才可能出现 `【占位待实测】`，提交稿必须替换或删除。

---

## 参与进来

- **规则文本的错误**最有价值：法条引用过期或引错条款号、某条检查项误报漏报、演练案例里埋的坑没标全。
  核实后在 `CHANGELOG.md` 里署名致谢。
- 想加一个检索入口、一个宿主、一种材料格式，欢迎 PR，先看 [CONTRIBUTING.md](CONTRIBUTING.md)。
- **提 issue 时不要贴你的真实申请文件。** 未申请的技术方案贴到公开仓库就是公开，
  可能直接毁掉新颖性。用 `examples/demo-case/` 复现。

---

## 许可

**CC BY-NC-SA 4.0**，规则和代码一样：个人和单位自己用免费，署名、相同方式共享，
**不能包进收费产品或收费服务流程**——要商用请开 issue 谈。
**你用它产出的申请文件、交底书、审查报告是你自己的**，不受本许可约束，商用也随意。

两处例外：`references/official/` 是法律法规原文（不适用著作权法）；
`THIRD_PARTY_NOTICES.md` 里列出的第三方代码保持其原有 MIT 许可。详见 [LICENSE](LICENSE)。

---

<div align="center">

本仓库是撰写辅助工具：不构成法律意见，不保证授权，不代为提交。

</div>
