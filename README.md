# patent-writing-pro

**中国发明专利的撰写、检索与模拟审查技能包。装进你的 agent，用大白话指挥它干活。**

[![License: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE)
[![Docs: CC BY-NC-SA 4.0](https://img.shields.io/badge/rules-CC%20BY--NC--SA%204.0-lightgrey.svg)](LICENSE-DOCS)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776ab.svg)](#安装)
[![Tests](https://img.shields.io/badge/tests-286%20passing-brightgreen.svg)](#跑测试)

[English](README.en.md) · 中文

写代码的人评职称、报项目、做高新认定都绕不开专利。难的从来不是"写出一份文件"，
而是**这份文件交上去会不会被驳**——交底书不知道写多厚，权利要求不知道该留什么，
稿子写完心里没底。这个包管的就是这一段。

它不是提示词合集，也不是模板。是一套**能被 agent 执行的规则**：怎么从代码里挖发明点、
怎么把权利要求写到每条限定都有证据撑着、怎么用审查员的两种眼光把稿子先打一遍再交出去。

---

## 五分钟看效果

装好之后（见[安装](#安装)），对你的 agent 说一句话：

```
专利审查：examples/demo-case/bad-draft.md
```

`demo-case` 是包里自带的**虚构**演练案例：一份故意埋了 12 个坑的申请文件，配着虚构的代码和测试。
这条命令跑完，你会拿到一份逐条"位置 — 问题 — 最小修改"的模拟审查报告——不用等你自己的材料，
五分钟就知道它是干什么的。

不想动模型？跑纯规则的形式检查，几秒钟，不联网：

```bash
python3 scripts/check_patent_package.py examples/demo-case/bad-draft.md
# 应该输出 3 个 ERROR、7 个 WARN
```

## 你可以这样说

不用记技能名，也不用记提示词名字。一句含"专利"两个字的常规话就能起手：

| 你输入 | 它做什么 | 会不会动你的文件 |
|---|---|---|
| `专利审查：文件名` | 平衡的模拟实质审查视角，逐条给"位置—问题—最小修改" | 不动，只出报告 |
| `专利驳回：文件名` | 驳回视角的内部压力测试，专找最致命的评价路径 | 不动，只出报告 |
| `专利审查和专利驳回：文件名` | 先后跑完两个视角，再做一次回归核对 | 不动，只出报告 |
| `专利撰写：材料或项目路径` | 从吃透技术、定发明点、检索、验证开始写一件新申请 | 生成新文件 |
| `专利交底书：材料或项目路径` | 按模板成文，七章加一节证据状态，附图出 PNG | 生成新文件 |
| `专利修改：母版文件` | 锁定母版，另存一个新版本 | 生成新版本，不覆盖母版 |
| `专利审查意见答复：通知书文件` | 分析真实审查意见并准备答复（不代为提交） | 生成答复稿 |
| `专利检索：技术主题` | 现有技术检索与材料整理 | 生成检索记录 |
| `专利检索图谱：案件文件夹` | 把这件案子查过什么、比过什么、为什么选这条路画成图 | 只在 `图谱/检索轨迹/` 下生成 |

**只要话里没出现"修改"两个字，审查类任务就只报告问题、不改文件。** 要审完直接动手，
说 `专利审查并修改`、`专利驳回分析并修改`。

## 里面有什么

| 部分 | 干什么 |
|---|---|
| `SKILL.md` + `references/` 12 份规则 | 新案工作流、撰写与评审、交底书模板、授权七道门、权项与证据矩阵、AI 与软件专利客体、审查意见答复、申请前风险、形式基线、检索规范、检索轨迹台账 |
| `references/prompts/` 两份长提示词 | 平衡模拟实质审查 + 对抗式驳回压力测试。**两个独立视角，不是自问自答** |
| `references/official/` | 专利法、实施细则、审查指南第 84 号令的条文原文摘录，断网也能核条款号 |
| `scripts/check_patent_package.py` | 不用模型的形式检查：栏目、字数、权项引用、先行基础、占位、过强结论、代码符号，几秒出结果 |
| `scripts/prior_art_search.py` + `cnipa_search.py` | **免 key** 的现有技术检索：国知局中国专利公布公告（中文专利首选，两轮收口）、Google Patents 检索与全文、OpenAlex / arXiv 论文、GitHub 仓库，外加一条"这台机器能打开哪些库"的探测 |
| `scripts/mermaid_render.py` | 附图主路径：md 里的 `mermaid` 围栏 → PNG，围栏原地换成 `![图 N](…)`。用本机 Chrome / Edge 渲染，**不联网、不装 Node** |
| `scripts/md_to_docx.py` + `math_to_omml.py` | Markdown → Word：宋体、页脚页码、附图嵌进去，LaTeX 公式转成 Word 原生可编辑公式（双击就能改） |
| `scripts/pptx_to_md.py` / `docx_to_md.py` / `pdf_to_text.py` | 把发明人给的 PPT、Word、PDF 材料转成 agent 能整段读的 Markdown |
| `scripts/make_figure.py` | 附图备选：按 JSON / YAML 描述直接出黑白框图、流程图，不用浏览器 |
| `obsidian/build_case_graph.py` | 案件图谱：权利要求、区别特征、对比文件、证据、审查问题连成一张 Obsidian 双链图 |
| `obsidian/build_search_trail.py` | 检索轨迹图谱：每轮查了什么、打掉了哪些候选、为什么走这条路，出一个双击即开的单文件网页 |
| `mcp/` | 可选。宿主没有终端时，把上面几个脚本注册成 MCP 工具 |
| `examples/demo-case/` | 虚构演练案例 + 现成生成好的两张图谱 |

## 四个说法，先讲清楚

**证据矩阵**：每条权利要求的每个实质限定，都要能追到代码、测试、文档或明确标记的拟议方案；
写不出证据的不许进权项。这是"稿子有底气"的来源，也是这个包和"让模型写一份专利"最大的区别。

**授权七道门**：客体、新颖性、创造性、充分公开、支持、清楚、修改基础，每道只能标
`PASS` / `RISK` / `BLOCKED` / `N/A`，有未处置的 `BLOCKED` 就不出可提交稿。
不给授权率百分比——脱离检索范围的百分比是假的。

**两套审查视角**：先用平衡视角把六项法定审查逐项过一遍；改完再换驳回视角专找最难答复的攻击路径，
而且要求先写出你的最强反驳，再判断这个攻击成不成立。两份提示词分两轮跑，不合成一条。

**检索轨迹图谱**：一件案子写到最后，查过几十篇、打掉好几个候选、把某个从属特征升成核心，
申请文件里一个字都看不到。每轮检索记一张固定格式的台账，跑一条命令，
就得到一张"轮次 → 文献 → 候选 → 最终去向"的力导向图：查过什么、为什么最后走这条路，
发明人和代理人都看得懂。

## 安装

技能包就是一个带 `SKILL.md` 的文件夹，装法是**把它放进 agent 的 skills 目录**。

```bash
git clone https://github.com/<your-account>/patent-writing-pro.git
cd patent-writing-pro
bash install/install.sh        # macOS / Linux / WSL / Git Bash
```

```powershell
powershell -ExecutionPolicy Bypass -File install\install.ps1   # Windows
```

脚本探测你装了哪些 agent（Claude Code / Codex CLI / Cursor / WorkBuddy / nanobot），
装进每一个探测到的，去掉会让 Codex 加载失败的 BOM，最后打印一句可以直接复制的验证台词。
**不联网、不装依赖、不改别的文件**，旧版本自动备份。装完跑一次自检：

```bash
bash install/verify.sh                                          # macOS / Linux
powershell -ExecutionPolicy Bypass -File install\verify.ps1     # Windows
```

手动装法、五个宿主的目录、排障表见 [INSTALL.md](INSTALL.md)。

**规则本体是纯 Markdown，一个依赖都不装也能用。** 只有两件事需要动手：

```bash
pip3 install -r requirements-min.txt   # Word 转换 + 可编辑公式
pip3 install playwright                # 只有要出附图、查国知局才需要（本机有 Chrome 或 Edge 就够）
```

## 检索怎么办（什么都不用配）

没有 key，没有账号，没有服务要接。agent 先跑一下探测脚本，看这台电脑此刻能打开哪些库，
然后能用哪个用哪个：

```bash
python3 scripts/prior_art_search.py probe
```

```bash
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
不管哪种情况，检索记录里都会写清用了哪些入口、哪些打不开、查了什么、没覆盖什么——
**打不开只会写成"入口不可用"，绝不会写成"未发现现有技术"**。一个库都打不开时它也会把稿子写完：
新颖性和创造性只列待检索项、不下结论，报告末尾附一份检索式清单，你有条件时照单子自己查。

你的稿子、代码、附图全程在你自己电脑上处理。出你电脑的只有检索词。

## 跑测试

```bash
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 -m unittest discover -s obsidian -p 'test_*.py'
python3 -m unittest discover -s mcp -p 'test_*.py'
```

286 条用例（其中 5 条在缺可选依赖时跳过），全离线（浏览器和网络都是假的），不需要任何 key。

## 它不做什么

- **不做实用新型和外观**，只管中国发明专利。
- **不做美国、欧洲专利**——那是另一套法域规则。
- **不代为提交，不承诺授权，不构成法律意见。** 它是撰写辅助工具，不能替代执业专利代理师。
  拿不准的案子，建议用它把稿子打磨到七八成再找代理师把关：省的是钱，不省专业判断。
- **不编实验数据。** 只有你明确要求占位时才可能出现 `【占位待实测】`，提交稿必须替换或删除。

## 参与进来

- 发现规则文本的错误（法条引用过期、检查项误报漏报、演练案例的坑没标全）——开 issue，
  核实后在 `CHANGELOG.md` 里署名致谢。
- 想加一个检索入口、一个宿主、一种材料格式——欢迎 PR，先看 [CONTRIBUTING.md](CONTRIBUTING.md)。
- 提 issue 时**不要贴你的真实申请文件**：那是未公开的技术方案，贴出来就是公开。用 `demo-case` 复现。

## 许可

- **代码**（`scripts/` `obsidian/*.py` `mcp/` `install/`）：MIT，见 [LICENSE](LICENSE)。
- **规则与文档**（`SKILL.md` `references/` 及各 md）：CC BY-NC-SA 4.0，见 [LICENSE-DOCS](LICENSE-DOCS)。
  个人和单位自用免费；包进收费产品或收费服务流程需要另外授权，开 issue 谈。
- **你用它产出的东西是你的**，不受本许可约束，商用也随意。
- 第三方代码与资源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)——其中出图、公式、PPT 转换
  三条工具链按 MIT 规矩改编自 [handsomestWei/patent-disclosure-skill](https://github.com/handsomestWei/patent-disclosure-skill)，
  已署名并逐条写明改动。

---

> 本仓库是撰写辅助工具：不构成法律意见，不保证授权，不代为提交。
