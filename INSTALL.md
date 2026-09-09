# 安装说明

技能包就是一个带 `SKILL.md` 的文件夹。所有 agent 的装法都一样：**把这个文件夹放进它的 skills 目录**，
区别只在目录在哪。下面先给一键脚本，再给手动装法和排障。

## 一、一键装（推荐）

`git clone` 之后进到仓库目录里，跑一条命令：

**macOS / Linux / WSL / Git Bash**

```bash
bash install/install.sh
```

**Windows PowerShell**

```powershell
powershell -ExecutionPolicy Bypass -File install\install.ps1
```

脚本会挨个探测你电脑上已经装了哪些 agent，装进每一个探测到的，最后打印一句可以直接复制的验证台词。
它**不联网、不装任何依赖、不改别的文件**；如果目标位置已经有旧版本，会先备份成 `patent-writing-pro.bak-日期时间`。

想先看看会装到哪儿而不真装：

```bash
bash install/install.sh --dry-run          # Windows: -DryRun
```

想装到自己指定的地方（比如某个项目目录）：

```bash
bash install/install.sh --dest /你的/项目/.claude/skills
```

## 二、五个宿主的目录

| Agent | 全局目录 | 项目内目录 |
|---|---|---|
| Claude Code | `~/.claude/skills/patent-writing-pro/` | `<项目>/.claude/skills/patent-writing-pro/` |
| Codex CLI | `~/.codex/skills/patent-writing-pro/` | `<项目>/.codex/skills/patent-writing-pro/` |
| Cursor | `~/.cursor/skills/patent-writing-pro/` | `<项目>/.cursor/skills/patent-writing-pro/` |
| WorkBuddy | `~/.workbuddy/skills/patent-writing-pro/` | — |
| nanobot | `~/.nanobot/workspace/skills/patent-writing-pro/` | — |

Windows 上把 `~` 换成 `%USERPROFILE%`，斜杠换成反斜杠。

手动装就是把整个 `patent-writing-pro` 文件夹复制到上面任意一行的位置，然后重启 agent。

## 三、三个容易踩的坑

**1. 装到宿主目录之后，文件夹名不能改。** 必须就叫 `patent-writing-pro`，和 `SKILL.md` 里的 `name` 一致（一键脚本会自动用这个名字，克隆下来的仓库目录叫什么都不影响）。
Cursor 按这个名字匹配，改了名它就找不到。

**2. SKILL.md 不能带 BOM。** Codex 加载带 UTF-8 BOM 的 `SKILL.md` 会直接不认。
包里发出来的文件是不带 BOM 的，一键脚本装完还会再扫一遍去掉 BOM。
但如果你用 Windows 记事本打开 `SKILL.md` 另存过，记事本会偷偷加上 BOM——
这时候重新跑一遍安装脚本就行，或者用 VS Code 另存为「UTF-8」（不是「UTF-8 with BOM」）。

**3. 装完要重启 agent。** 几个宿主都是启动时扫 skills 目录，装好之后没重启就说"没这个技能"很正常。

## 四、检索不用配

技能包装完就是全部：没有检索服务要接、没有 key 要填、没有账号要注册。审查和撰写里的现有技术检索，
agent 用包内免 key 的 `scripts/prior_art_search.py` 加它自带的联网能力自己完成，能打开哪个库就查哪个库。

想提前知道你这台电脑能打开哪些库（几秒钟，不用模型）：

> Windows 上把下面的 `python3` 换成 `py -3`（没有 `py` 就用 `python`）——`python3.exe` 在 Windows 上常常是应用商店的占位程序，敲下去只会弹商店。

```bash
python3 scripts/prior_art_search.py probe
```

它会列一张表：Google Patents、Espacenet、PATENTSCOPE、Lens、国知局公布公告、OpenAlex、arXiv、GitHub、Bing 各自通不通。
**打不开的库不需要你做任何事**——agent 检索时会自动跳过，并在检索记录里写明「该入口不可用」；
一个库都打不开它也会把稿子写完，只是新颖性、创造性不下结论，报告末尾附一份检索式清单供你之后自己查。

想自己手动查一下也行，四条命令：

```bash
python3 scripts/prior_art_search.py cnipa 批任务调度 资源画像 异构算力            # 国知局公布公告（中文专利）
python3 scripts/prior_art_search.py patents "告警 抑制 滑动窗口" --country CN     # Google Patents 检索
python3 scripts/prior_art_search.py get CN107196804B --out D1.md                # 一件专利的全文
python3 scripts/prior_art_search.py papers "alert suppression sliding window"   # 论文（OpenAlex + arXiv）
```

除了第一条，脚本只用 Python 标准库，不装任何依赖。Google 系在国内直连网络下打不开是正常的，
它会明说「入口不可用」，不是脚本坏了。

**第一条（`cnipa`）多要一样东西**：国知局这个站得在浏览器里跑一段脚本才放出检索框，纯 HTTP 抓不到，
所以它要本机有 Chrome 或 Edge，加一句 `pip3 install playwright`——和下一节出附图是同一套，装一次两用。
它给回的是中文标题、中文摘要、IPC 分类号和 `epub.cnipa.gov.cn` 的官方链接，
agent 会先用关键词拉一轮、拿到 IPC 分类号，再带 `--class G06F9,G06Q10` 收一轮口。
查不到东西（0 条）和站点打不开是两回事，脚本分得清，检索记录里也会分开写。

如果你的 agent 里本来就配了别的专利检索工具，规则会优先用它，不冲突。

**宿主没有终端**（agent 自己跑不了 Python 脚本）时，可以把包里的转换、附图、形式检查脚本注册成工具，
见 `mcp/README.md`——可选，不装也不影响规则本身。

## 五、出图和公式要装什么（可选，但很值）

规则本体是纯 Markdown，一个依赖都不装也能用。下面两样只影响交付物长什么样：

**装依赖（一条命令）**

```bash
pip3 install -r requirements-min.txt      # Word 转换 + 公式；Windows：py -3 -m pip install -r requirements-min.txt
pip3 install playwright                   # 只有要出附图才需要
```

`requirements-min.txt` 里的 `latex2mathml` 是这一版新加的，**公式要靠它**：装了以后 md 里的
`$\sum_i w_i x_i$` 转进 Word 是原生的可编辑公式，双击就能改；不装的话不报错，
但公式会按 LaTeX 原文留在 Word 里，代理人得自己重敲。

**出附图需要一个浏览器内核**。附图的主路径是在 md 里写 `mermaid` 代码围栏，
再跑 `scripts/mermaid_render.py` 出 PNG：

- **本机装了 Chrome 或 Edge**（绝大多数电脑都有）：`pip3 install playwright` 就够了，
  不用再下载任何浏览器
- **两个都没有**（干净的服务器、精简过的系统）：才需要多跑一次
  `python3 -m playwright install chromium`，它会下载一份约 150MB 的 Chromium

**脚本不会替你装任何东西**——不自动 `pip install`，也不自动 `playwright install`，
缺什么只在 stderr 里提示一句。先探一下这台机器行不行（一秒钟）：

```bash
python3 scripts/mermaid_render.py --probe
```

通了会打一行 `{"playwright": true, "channel": "chrome", "ok": true, ...}` 和
`OK: browser=chrome`；不通会告诉你缺的是 playwright 还是浏览器。
出图**不联网、不装 Node、不用 npx / mmdc**，mermaid 的 js 是包里自带的
（`scripts/vendor/mermaid.min.js`，见 `THIRD_PARTY_NOTICES.md`）。

出不了图也不至于卡住：`mermaid_render.py` 会照常写出定稿 md，只是 mermaid 围栏原样保留、
退出码 2；简单方框图还可以走不需要浏览器的 `scripts/make_figure.py`。

想一次把所有可选功能都打开（含 PPT 转换和 OCR）：`pip3 install -r requirements-full.txt`。
装完用 `python3 scripts/check_env.py` 看一眼哪些认出来了。

## 六、装完怎么验证

**最省事的办法**——跑一遍自检，它会挨个宿主看装上没有、文件全不全、SKILL.md 有没有被加上 BOM，
再拿演练案例跑一遍脚本和测试：

```bash
bash install/verify.sh                                          # macOS / Linux
powershell -ExecutionPolicy Bypass -File install\verify.ps1     # Windows
```

全绿就没问题。哪一条挂了它会直接写出来。两边检查的项目一样，输出格式也一样。

重启 agent 后，复制这句给它（路径换成你自己的）：

```
专利审查：~/.claude/skills/patent-writing-pro/examples/demo-case/bad-draft.md
```

它应该开始按客体、新颖性、创造性、充分公开、支持、清楚逐项审这份故意写坏的稿子，
最后给一张权项覆盖表。

不想动模型、只想几秒钟确认文件是好的，跑这个（纯规则检查，不用联网也不用模型）：

```bash
# macOS / Linux
python3 ~/.claude/skills/patent-writing-pro/scripts/check_patent_package.py \
        ~/.claude/skills/patent-writing-pro/examples/demo-case/bad-draft.md
```

```powershell
# Windows（安装脚本装完会把这条路径原样打给你，直接复制那条更省事）
py -3 "$env:USERPROFILE\.claude\skills\patent-writing-pro\scripts\check_patent_package.py" `
      "$env:USERPROFILE\.claude\skills\patent-writing-pro\examples\demo-case\bad-draft.md"
```

应该输出 3 个 ERROR、7 个 WARN。输出正常就说明包是完整的。

## 七、排障

| 现象 | 多半是什么 | 怎么办 |
|---|---|---|
| agent 说没有这个技能 | 没重启，或者装错目录 | 重启；确认目录里有 `SKILL.md` |
| Codex 装了不加载 | `SKILL.md` 带了 BOM | 重跑一遍安装脚本 |
| Cursor 装了不加载 | 文件夹改过名 | 改回 `patent-writing-pro` |
| Windows 报「禁止运行脚本」 | PowerShell 执行策略 | 用上面那条带 `-ExecutionPolicy Bypass` 的完整命令 |
| `python3: command not found` | 没装 Python | 技能本身是纯 Markdown，不装 Python 也能用；只有 `scripts/` 里的检查脚本需要 Python 3.9+ |
| Windows 上敲 `python3` 弹出应用商店 | `python3.exe` 在 Windows 上常常是商店的占位程序 | 本文档里的 `python3` 在 Windows 上一律换成 `py -3`（没有 `py` 就用 `python`）|
| 中文显示成乱码 | Windows 终端编码 | PowerShell 里先跑 `chcp 65001` |
| 说了「专利审查」但它没按规则走 | 话里没带文件路径，或者上下文里有别的规则在抢 | 把文件路径写全；或者明确说「用 patent-writing-pro 技能」 |
| 检索脚本说「入口不可用」 | 这台电脑打不开那个库（国内直连打不开 Google 系是常态），或 Google 临时限流 | 不是脚本坏了，也不用修：agent 会换别的入口继续，检索记录里会写明；被限流的等 20 分钟再试 |
| 查国知局说「站点打不开」 | 这台电脑到不了 `epub.cnipa.gov.cn`：断网、公司代理或出网白名单挡着 | 不是等待时间不够，别去调 `EPUB_WAF_MAX_WAIT_SEC`。先在浏览器里手动打开这个网址看看；打得开而脚本打不开，多半是命令行走了代理。agent 会写「该入口不可用」，换别的入口继续 |
| 查国知局说「没等到检索框」 | 站点开着，但它前面那道校验这次没过去 | 这种才该加时间：`EPUB_WAF_MAX_WAIT_SEC=300` 再跑一次；还不行就 `PLAYWRIGHT_HEADED=1`，会弹出浏览器窗口让你人工过一次 |
| 查国知局回 0 条 | 检索词太长或太偏 | **0 条不是故障**，是检索结论，可以写进检索记录。多半是把一整句话当成一个词了——拆成 2～8 个词（如 `批任务调度 资源画像 异构算力`）重来 |
| 检索结果比预期少 | 能打开的库少，或查询式偏 | 先跑 `python3 scripts/prior_art_search.py probe` 看哪些库通；本包不承诺检索得全，报告末尾的检索式清单可以拿到别的库自己补查 |
| 出图说「浏览器不可用」 | 没装 playwright，或这台机器上既没有 Chrome / Edge 也没有 playwright 自带的 Chromium | 先 `pip3 install playwright`；本机有 Chrome 或 Edge 就到此为止，两个都没有才再跑 `python3 -m playwright install chromium`。跑 `python3 scripts/mermaid_render.py --probe` 看它到底缺哪一样。脚本不会自动装东西，这是有意的。出不了图定稿 md 照样写出来，mermaid 围栏原样保留 |
| Word 里公式是一串 LaTeX 原文 | 没装 `latex2mathml`（这一版新加的可选依赖） | `pip3 install latex2mathml`（Windows：`py -3 -m pip install latex2mathml`），再重新跑一次 `md_to_docx.py`。用 `python3 scripts/check_env.py` 确认它认出来了。没装不报错，只是公式不转 |

## 八、更新和卸载

**更新**：`git pull` 之后重跑一次安装脚本。旧版会自动备份，不用先手动删。装完再跑一遍自检（`install/verify.sh`，Windows 是 `install\verify.ps1`）。改了什么看 `CHANGELOG.md`。

**卸载**：直接删掉对应目录下的 `patent-writing-pro` 文件夹（和 `.bak-` 开头的备份）。
技能不写注册表、不改任何配置文件，删了就干净了。
