# 内置 mermaid.min.js（给 mermaid_render.py 出图用）

| 文件 | 版本 | 许可证 | 来源 |
|---|---|---|---|
| `mermaid.min.js` | **11.4.1** | MIT（mermaid-js 项目，https://github.com/mermaid-js/mermaid/blob/develop/LICENSE） | https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js |

- md5：`def493e96e3915c5dd101c4395d72dfa`
- 这份文件原样取自 handsomestWei/patent-disclosure-skill（MIT，Copyright (c) 2026 handsomestWei）的 `tools/vendor/`，未做改动。
- `scripts/mermaid_render.py` 用 playwright 驱动本机 Chrome / Edge / 自带 Chromium 加载它出 PNG，**不联网、不从 CDN 拉、不用 Node / mmdc / npx**。
- 升级版本时：换掉 `mermaid.min.js`，同步改本表的版本号和 md5，再跑一遍 `python3 scripts/test_mermaid_render.py`。
