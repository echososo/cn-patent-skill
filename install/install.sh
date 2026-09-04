#!/usr/bin/env bash
# patent-writing-pro 一键安装（macOS / Linux / Git Bash / WSL）
# 只做三件事：把技能文件夹复制进你已有的 agent 的 skills 目录、去掉 UTF-8 BOM、打印验证用的一句话。
# 不联网、不装依赖、不改任何别的文件。

set -euo pipefail

SKILL_NAME="patent-writing-pro"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DRY_RUN=0
CUSTOM_DEST=""

usage() {
  cat <<'USAGE'
用法：bash install.sh [选项]

  （不带选项）  自动探测已装的 agent，装进每一个探测到的
  --dest 目录   装到指定目录下（会在该目录里建 patent-writing-pro/）
  --dry-run     只看会装到哪儿，不真的复制
  -h, --help    看这段

探测的五个宿主：
  Claude Code   ~/.claude/skills/
  Codex CLI     ~/.codex/skills/
  Cursor        ~/.cursor/skills/
  WorkBuddy     ~/.workbuddy/skills/
  nanobot       ~/.nanobot/workspace/skills/
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --dest) CUSTOM_DEST="${2:-}"; [ -n "$CUSTOM_DEST" ] || { echo "错误：--dest 后面要跟目录"; exit 2; }; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "不认识的选项：$1"; echo; usage; exit 2 ;;
  esac
done

if [ ! -f "$PKG_ROOT/SKILL.md" ]; then
  echo "错误：在 $PKG_ROOT 里没找到 SKILL.md。"
  echo "请把整个 $SKILL_NAME 文件夹解压好，再运行 install/install.sh。"
  exit 1
fi

# 宿主表：显示名|宿主根目录|skills 相对路径
HOSTS="
Claude Code|$HOME/.claude|skills
Codex CLI|$HOME/.codex|skills
Cursor|$HOME/.cursor|skills
WorkBuddy|$HOME/.workbuddy|skills
nanobot|$HOME/.nanobot|workspace/skills
"

strip_bom() {
  # Codex 加载 SKILL.md 时带 BOM 会失败，装完统一去一遍
  local dir="$1" f head3
  while IFS= read -r f; do
    head3="$(head -c 3 "$f" 2>/dev/null | od -An -tx1 | tr -d ' \n' || true)"
    if [ "$head3" = "efbbbf" ]; then
      tail -c +4 "$f" > "$f.__nobom" && mv "$f.__nobom" "$f"
      echo "    去掉 BOM：${f#$dir/}"
    fi
  done < <(find "$dir" -type f -name '*.md')
}

copy_skill() {
  local dest="$1"
  if [ -e "$dest" ]; then
    # 备份必须放在 skills/ **外面**。放在里面的话，宿主扫描 skills/ 时会把
    # patent-writing-pro.bak-… 当成第二个技能注册，agent 有可能加载到旧规则那一份。
    # 2026-09-02 实测：装完 Claude Code 的技能清单里真的同时出现了两个 patent-writing-pro。
    local bakroot="$(dirname "$(dirname "$dest")")/.patent-writing-pro-backups"
    mkdir -p "$bakroot"
    local backup="$bakroot/$(date +%Y%m%d-%H%M%S)" n=1
    while [ -e "$backup" ]; do backup="$bakroot/$(date +%Y%m%d-%H%M%S)-$n"; n=$((n+1)); done
    mv "$dest" "$backup"
    echo "    原来那份已备份到 $backup"
  fi
  # v1.0.2 及更早的安装把备份留在了 skills/ 里，那些残留同样会被当成技能注册。
  # 顺手搬走，不然买家升级完还是两个技能。
  for legacy in "$dest".bak-*; do
    [ -e "$legacy" ] || continue
    local bakroot2="$(dirname "$(dirname "$dest")")/.patent-writing-pro-backups"
    mkdir -p "$bakroot2"
    mv "$legacy" "$bakroot2/$(basename "$legacy")"
    echo "    旧版留在 skills/ 里的备份已挪走：$(basename "$legacy")"
  done
  mkdir -p "$dest"
  # 整目录拷贝，不是白名单：新加的 scripts/vendor/（内置 mermaid.min.js）会跟着一起过去。
  ( cd "$PKG_ROOT" && tar -cf - \
      --exclude='__pycache__' --exclude='*.pyc' \
      --exclude='.pytest_cache' \
      --exclude='.DS_Store' --exclude='.git' . ) | ( cd "$dest" && tar -xf - )
  strip_bom "$dest"
}

INSTALLED=""
COUNT=0

install_to() {
  local label="$1" skills_dir="$2"
  local dest="$skills_dir/$SKILL_NAME"
  echo "  ${label}：$dest"
  if [ "$DRY_RUN" = "1" ]; then
    echo "    （--dry-run，没有真的复制）"
  else
    mkdir -p "$skills_dir"
    copy_skill "$dest"
    echo "    装好了"
  fi
  INSTALLED="${INSTALLED}${label}\t${dest}\n"
  COUNT=$((COUNT + 1))
}

echo "包目录：$PKG_ROOT"
echo

if [ -n "$CUSTOM_DEST" ]; then
  mkdir -p "$CUSTOM_DEST"
  install_to "手动指定" "$(cd "$CUSTOM_DEST" && pwd)"
else
  echo "探测已安装的 agent……"
  while IFS='|' read -r label root sub; do
    [ -n "${label:-}" ] || continue
    if [ -d "$root" ]; then
      install_to "$label" "$root/$sub"
    else
      echo "  ${label}：没找到 ${root}，跳过"
    fi
  done <<< "$HOSTS"
fi

echo
if [ "$COUNT" = "0" ]; then
  cat <<MANUAL
一个 agent 都没探测到。手动装也很简单：把整个 $SKILL_NAME 文件夹复制到下面任意一个位置——

  Claude Code   ~/.claude/skills/$SKILL_NAME/
  Codex CLI     ~/.codex/skills/$SKILL_NAME/
  Cursor        ~/.cursor/skills/$SKILL_NAME/
  WorkBuddy     ~/.workbuddy/skills/$SKILL_NAME/
  nanobot       ~/.nanobot/workspace/skills/$SKILL_NAME/

复制完重启一下 agent。文件夹名必须就叫 ${SKILL_NAME}，Cursor 会按它匹配。
MANUAL
  exit 0
fi

if [ "$DRY_RUN" = "1" ]; then
  echo "会装到这 $COUNT 处（本次没有真的复制）："
else
  echo "装好 $COUNT 处："
fi
printf "$INSTALLED" | while IFS=$'\t' read -r label dest; do
  [ -n "${label:-}" ] && echo "  $label  ->  $dest"
done

FIRST_DEST="$(printf "$INSTALLED" | head -1 | cut -f2)"
cat <<NEXT

下一步：重启你的 agent，然后复制这句话给它——

  专利审查：$FIRST_DEST/examples/demo-case/bad-draft.md

想先不动模型、几秒钟看一眼形式检查：

  python3 "$FIRST_DEST/scripts/check_patent_package.py" "$FIRST_DEST/examples/demo-case/bad-draft.md"
NEXT
