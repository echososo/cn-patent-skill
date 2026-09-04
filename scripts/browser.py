#!/usr/bin/env python3
# Copyright (c) 2026 handsomestWei — MIT License
# 改编自 handsomestWei/patent-disclosure-skill（MIT）的 tools/browser.py。
# 改动：去掉包内 stdio_utf8 依赖（改为本文件内三行 reconfigure）；--probe 的机读约定改为
# 本包统一格式（JSON 打 stdout，OK:/FAIL: 行打 stderr，浏览器不可用退出码 2）；文案按本包口径改写。
"""找一个能用的 Chromium 内核浏览器给 Playwright 用：本机 Chrome → 本机 Edge → playwright 自带 Chromium。

只给 mermaid_render.py 出图用。有本机 Chrome / Edge 时不需要 `playwright install chromium`。
本脚本**绝不**自动执行 pip install 或 playwright install，缺什么只在 stderr 里提示。

用法：
  python3 browser.py --probe        # 试着无头启动一次，stdout 一行 JSON
                                    # 成功：stderr `OK: browser=chrome`，退出码 0
                                    # 失败：stderr `FAIL: browser_unavailable ...`，退出码 2

环境变量：
  PLAYWRIGHT_HEADED=1                     有界面启动（调试用）
  PATENT_BROWSER_CHANNEL=chrome|msedge|chromium
                                          强制指定，跳过自动探测顺序
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
]

# 自动探测顺序：本机 Chrome、本机 Edge，最后才是 playwright 自带的 Chromium
_AUTO_CHANNELS: tuple[str | None, ...] = ("chrome", "msedge", None)
_AUTO = object()


class BrowserUnavailable(RuntimeError):
    """playwright 没装，或三种浏览器一个都起不来。调用方据此退出码 2。"""


def headed() -> bool:
    return os.environ.get("PLAYWRIGHT_HEADED", "").strip().lower() in ("1", "true", "yes")


def playwright_installed() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def channel_label(channel: str | None) -> str:
    return channel if channel else "chromium"


def _forced_channel() -> str | None | object:
    """None = 自带 Chromium；str = 指定 channel；_AUTO = 走自动顺序。"""
    raw = os.environ.get("PATENT_BROWSER_CHANNEL", "").strip().lower()
    if not raw:
        return _AUTO
    if raw in ("chromium", "bundled", "playwright"):
        return None
    if raw in ("chrome", "msedge"):
        return raw
    return _AUTO


def install_package_hint() -> str:
    return "需要先装 playwright：pip3 install playwright（本包不会自动装）"


def install_chromium_hint() -> str:
    return (
        "请装 Google Chrome 或 Microsoft Edge 后重试；"
        "两者都没有时再执行：python3 -m playwright install chromium（本包不会自动执行）"
    )


def launch_chromium(
    playwright: Any,
    *,
    headless: bool | None = None,
    extra_args: list[str] | None = None,
) -> tuple[Any, str]:
    """按顺序试着启动浏览器，返回 (browser, label)，label 为 chrome / msedge / chromium。

    全部失败抛 BrowserUnavailable，文案里带安装提示（只提示，不执行）。
    """
    if headless is None:
        headless = not headed()
    args = list(LAUNCH_ARGS)
    if extra_args:
        args.extend(extra_args)

    forced = _forced_channel()
    candidates: list[str | None] = list(_AUTO_CHANNELS) if forced is _AUTO else [forced]  # type: ignore[list-item]

    errors: list[str] = []
    for ch in candidates:
        kwargs: dict[str, Any] = {"headless": headless, "args": args}
        if ch:
            kwargs["channel"] = ch
        try:
            browser = playwright.chromium.launch(**kwargs)
        except Exception as e:  # playwright 各种 Error 都归到这里
            errors.append(f"{channel_label(ch)}: {str(e).splitlines()[0] if str(e) else type(e).__name__}")
            continue
        return browser, channel_label(ch)

    detail = " | ".join(errors[:3]) if errors else "unknown"
    raise BrowserUnavailable(f"无法启动浏览器（{detail}）。{install_chromium_hint()}")


def probe_launch() -> dict[str, Any]:
    """实际无头启动一次再关掉。返回字典：playwright / channel / ok / error / hint。"""
    out: dict[str, Any] = {
        "playwright": playwright_installed(),
        "channel": None,
        "ok": False,
        "error": None,
        "hint": None,
    }
    if not out["playwright"]:
        out["error"] = "playwright_not_installed"
        out["hint"] = install_package_hint()
        return out
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser, label = launch_chromium(p, headless=True)
            try:
                out["ok"] = True
                out["channel"] = label
            finally:
                browser.close()
    except Exception as e:
        out["error"] = str(e)
        out["hint"] = install_chromium_hint()
    return out


def report_probe(report: dict[str, Any]) -> int:
    """按本包机读约定打印探测结果：JSON 到 stdout，OK:/FAIL: 到 stderr。返回退出码。"""
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if report.get("ok"):
        print(f"OK: browser={report.get('channel')}", file=sys.stderr, flush=True)
        return 0
    err = report.get("error") or "unknown"
    hint = report.get("hint") or ""
    if hint and hint in err:  # launch_chromium 的报错文案里已经带了安装提示，别重复
        hint = ""
    print(f"FAIL: browser_unavailable {err} {hint}".rstrip(), file=sys.stderr, flush=True)
    return 2


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Playwright 浏览器探测（Chrome → Edge → 自带 Chromium）")
    ap.add_argument("--probe", action="store_true", help="试着无头启动一次；stdout 一行 JSON")
    args = ap.parse_args(argv)
    if not args.probe:
        ap.print_help()
        return 1
    return report_probe(probe_launch())


if __name__ == "__main__":
    raise SystemExit(main())
