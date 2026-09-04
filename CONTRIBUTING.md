# 参与贡献 · Contributing

中文在前，English below.

## 最有价值的三类贡献

1. **规则文本的错误**——法条引用过期或引错条款号、某条检查项误报漏报、演练案例里埋的坑没标全。
   这类问题最难自己发现，也最影响用的人。核实后在 `CHANGELOG.md` 里署名致谢。
2. **新的检索入口**——多一个能打开的库，就多一分检索兜底。写成 `prior_art_search.py` 的一个子命令，
   带离线测试。
3. **新宿主的安装支持**——`install/install.sh` 和 `install.ps1` 里的宿主表加一行，说明你验过。

## 提 issue 之前

**不要贴你的真实申请文件、交底书或代码。** 未申请的技术方案贴到公开仓库就是公开，
可能直接毁掉新颖性。用 `examples/demo-case/` 里的虚构案例复现问题；复现不了，
就把材料替换成不相关的虚构内容再贴。

同理，**不要贴带个人信息的路径和日志**。发布前扫一遍：

```bash
python3 scripts/strip_personal.py .
```

内置的只有通用模式（邮箱、个人绝对路径、常见密钥前缀）。你自己的名字、账号、域名、
在审案件关键词写进 `strip_personal.rules.json`（已被 `.gitignore` 忽略），
样例见 `scripts/strip_personal.rules.example.json`。

## 改代码

- Python 3.9+，**标准库优先**。规则本体是纯 Markdown，装不装依赖都得能用；
  新增的第三方依赖必须是可选的：没装时功能降级并在 stderr 说一句，不能直接崩。
- **脚本的机读约定全包统一**：成功时 stdout 最后一行 `OK: 键=值 ...`；
  失败时 stderr 一行 `FAIL: 原因`，退出码 `2` 表示依赖或入口不可用、`1` 表示输入或运行错误。
  新脚本照这个来。
- **测试必须离线**：浏览器、网络、外部服务全部打桩。CI 和用户机器上都不该真的联网。
- 跑全套：

  ```bash
  python3 -m unittest discover -s scripts  -p 'test_*.py'
  python3 -m unittest discover -s obsidian -p 'test_*.py'
  python3 -m unittest discover -s mcp      -p 'test_*.py'
  ```

## 改规则

- 规则文本按 CC BY-NC-SA 4.0 授权，提交 PR 即表示你同意你的改动以同一许可发布。
- 一条规则要能被 agent 执行，不能只是一句正确的废话。写清楚**什么时候读这一节、
  读完要产出什么、什么情况下不适用**。
- 引法条要给条款号，并和 `references/official/` 里的原文对得上。2023 年实施细则改过编号，
  旧模板里的条款号大多是错的。
- 不要往规则里加"多写点显得专业"的要求。这个包的立场是最少但充分。

## 不接受的 PR

- 把中国专利之外的法域（美、欧、日）规则塞进现有文件——那需要一套独立的法域规则包，
  先开 issue 讨论结构。
- 把实用新型、外观设计混进发明专利的流程。
- 让工具自动 `pip install` 或自动下载浏览器。缺什么就说缺什么，装不装是用户的事。
- 承诺授权率、给授权概率百分比、或把内部模拟审查写成官方审查意见的措辞。

---

## English

**The three most valuable contributions**: errors in the rule text (stale or
wrong statutory citations, false positives/negatives in a check, unflagged traps
in the practice case); a new prior-art search entry point; installer support for
a new host.

**Before opening an issue: never paste a real application, disclosure or source
code.** An unfiled technical solution posted to a public repo is a public
disclosure and can destroy novelty. Reproduce with `examples/demo-case/`.
Scan before you publish anything: `python3 scripts/strip_personal.py .`

**Code**: Python 3.9+, standard library first; new third-party dependencies must
be optional and degrade gracefully. All scripts share one machine-readable
convention — last stdout line `OK: k=v ...` on success; one stderr line
`FAIL: reason` on failure, exit `2` for an unavailable dependency or entry
point, `1` for input or runtime errors. **Tests must be fully offline.**

**Rules**: licensed CC BY-NC-SA 4.0; opening a PR means you agree your changes
ship under the same license. A rule must be executable by an agent — say when to
read it, what it must produce, and when it does not apply. Cite article numbers
that match `references/official/`.

**Not accepted**: other jurisdictions bolted into the existing files (open an
issue first — that needs a separate rule pack); utility models or designs mixed
into the invention-patent flow; tools that auto-install packages or browsers;
anything that promises a grant, gives a grant-probability percentage, or dresses
an internal simulation up as an official CNIPA office action.
