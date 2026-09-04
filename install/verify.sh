#!/usr/bin/env bash
# 装完自检：看看五个宿主里装上没有、装的那份是不是完好的。
# 不联网、不改任何文件。

set -uo pipefail

SKILL_NAME="patent-writing-pro"
PASS=0
FAIL=0

ok()   { echo "    [OK]   $1"; PASS=$((PASS+1)); }
bad()  { echo "    [失败] $1"; FAIL=$((FAIL+1)); }
skip() { echo "    [跳过] $1"; }

PY=""
for c in python3 python; do command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }; done

check_one() {
  local label="$1" dir="$2"
  echo "  ${label}：$dir"

  [ -f "$dir/SKILL.md" ] && ok "SKILL.md 在" || { bad "没有 SKILL.md"; return; }

  local head3
  head3="$(head -c 3 "$dir/SKILL.md" | od -An -tx1 | tr -d ' \n')"
  [ "$head3" = "efbbbf" ] && bad "SKILL.md 带 BOM，Codex 会不认" || ok "SKILL.md 没有 BOM"

  local name
  name="$(grep -m1 '^name:' "$dir/SKILL.md" | sed 's/^name:[[:space:]]*//' | tr -d '\r')"
  [ "$name" = "$(basename "$dir")" ] && ok "name 和文件夹名一致（${name}）" \
                                     || bad "name=$name 和文件夹名 $(basename "$dir") 不一致"

  local n
  n="$(find "$dir/references" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')"
  [ "$n" -ge 17 ] && ok "references 有 $n 份" || bad "references 只有 $n 份，应该 17 份（包里 12 份规则 + 2 份审查提示词 + 3 份官方法源摘录）"

  [ -f "$dir/examples/demo-case/bad-draft.md" ] && ok "演练案例在" || bad "演练案例缺失"

  # skills/ 里不能有第二个 patent-writing-pro：宿主按目录扫描，
  # 一个 .bak-… 残留就会被当成第二个技能注册，agent 可能加载到旧规则那份。
  local stray
  stray="$(find "$(dirname "$dir")" -maxdepth 1 -name "${SKILL_NAME}.bak-*" 2>/dev/null | wc -l | tr -d ' ')"
  [ "${stray}" = "0" ] && ok "skills/ 里没有重复的技能目录" \
                   || bad "skills/ 里还有 ${stray} 个 ${SKILL_NAME}.bak-* 残留，会被当成第二个技能；重跑 install.sh 会自动挪走"

  if [ -z "$PY" ]; then
    skip "没有 python3，跳过脚本检查（技能本身不需要 Python）"
    return
  fi

  # v1.2.0 起全包脚本统一机读约定：稿子有问题时 stdout 最后一行是中文的
  # 「汇总：ERROR=3，WARN=7」，再往后 stderr 还有一行 ASCII 的
  # 「FAIL: errors=3 warnings=7 files=1」，2>&1 之后最后一行是后者。
  # 判据只认 ASCII 片段：中文整句在中文 Windows 上被捕获时是 GBK 字节，拿它当判据必然误报。
  local out
  out="$("$PY" "$dir/scripts/check_patent_package.py" "$dir/examples/demo-case/bad-draft.md" 2>&1 | tail -1)"
  case "$out" in
    *"errors=3"*"warnings=7"*) ok "形式检查输出正确（${out}）" ;;
    *)                         bad "形式检查输出异常：$out" ;;
  esac

  out="$(cd "$dir/examples/demo-case/src" && PYTHONDONTWRITEBYTECODE=1 "$PY" -m unittest test_alert_suppressor 2>&1 | tail -1)"
  [ "$out" = "OK" ] && ok "演练案例 13 个测试全过" || bad "演练案例测试没过：$out"

  # v1.2.0 新增：附图主路径是 mermaid 围栏 → PNG。这台机器有浏览器就真渲染一张最小的图，
  # 没有就跳过（不算失败：规则本身不需要出图，附图还能走 make_figure.py）。
  # 只往临时目录写，不动装好的那份。
  if "$PY" "$dir/scripts/mermaid_render.py" --probe >/dev/null 2>&1; then
    local tmpd
    tmpd="$(mktemp -d 2>/dev/null || true)"
    if [ -z "${tmpd:-}" ] || [ ! -d "$tmpd" ]; then
      skip "建不了临时目录，跳过出图自检"
    else
      printf '%s\n' '# 出图自检' '' '```mermaid' 'flowchart LR' '  A[开始] --> B[结束]' '```' > "$tmpd/in.md"
      out="$("$PY" "$dir/scripts/mermaid_render.py" -i "$tmpd/in.md" -o "$tmpd/out.md" 2>&1 | tail -1)"
      if [ -s "$tmpd/mermaid_figures/fig_001.png" ]; then
        ok "出图链路正常（${out}）"
      else
        bad "出图链路不通：$out"
      fi
      rm -rf "$tmpd"
    fi
  else
    skip "这台机器出不了附图（没装 playwright，或既没有 Chrome/Edge 也没有 Chromium）——不影响规则，附图可改用 make_figure.py；装法见 INSTALL.md 第五节"
  fi
}

echo "自检开始（$(date '+%Y-%m-%d %H:%M:%S')）"
[ -n "$PY" ] && echo "Python：$($PY -V 2>&1)" || echo "Python：没找到（不影响技能本身）"
echo

FOUND=0
while IFS='|' read -r label root sub; do
  [ -n "${label:-}" ] || continue
  d="$root/$sub/$SKILL_NAME"
  if [ -d "$d" ]; then
    FOUND=$((FOUND+1))
    check_one "$label" "$d"
    echo
  else
    echo "  ${label}：没装（$d 不存在）"
    echo
  fi
done <<HOSTS
Claude Code|$HOME/.claude|skills
Codex CLI|$HOME/.codex|skills
Cursor|$HOME/.cursor|skills
WorkBuddy|$HOME/.workbuddy|skills
nanobot|$HOME/.nanobot|workspace/skills
HOSTS

echo "================================"
echo "装了 $FOUND 个宿主，检查项 通过 $PASS 条 / 失败 $FAIL 条"
if [ "$FOUND" = "0" ]; then
  # 一个宿主都没找到时，什么也没验成，别报「全部正常」——那是假通过。
  echo "结论：一个宿主都没找到，这次什么也没验。先跑 install.sh 装进去再来自检"
  exit 2
fi
[ "$FAIL" = "0" ] && echo "结论：全部正常" || echo "结论：有问题，看上面 [失败] 那几行"
[ "$FAIL" = "0" ] || exit 1
