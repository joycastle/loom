#!/bin/sh
# loom 一键安装 — 两种用法都可用(POSIX sh,零 pip / 零打包):
#
#   1) 任意终端一行(本地无需先 clone):
#        curl -fsSL https://raw.githubusercontent.com/joycastle/loom/main/install.sh | sh
#      脚本会把仓库浅克隆到 ${LOOM_APP_DIR:-$HOME/.loom-app}(已存在则 pull),再从那里装。
#
#   2) 已 clone 后本地运行:
#        cd loom && ./install.sh
#      直接用当前仓库。
#
# 做的事:校验 python3 → 软链 bin/loom 到 PATH → loom init → 把 loom-skill 装进在场的
# AI 助手(claude/codex/cursor/codebuddy)→ 提示日常 `loom sync`。幂等,重复跑不报错。
set -eu

REPO_URL="https://github.com/joycastle/loom.git"

# 解析 $1 目录为绝对路径(不可达则输出空)。
resolve_dir() { CDPATH= cd -- "$1" 2>/dev/null && pwd; }

# ---- 定位仓库:本地模式(旁边有 bin/loom)否则 clone 引导 ----------------
REPO=""
case "$0" in
  */*) cand=$(resolve_dir "$(dirname -- "$0")") ;;   # $0 是路径 → 取其目录
  *)   cand="" ;;                                     # piped 时 $0 常是 "sh"
esac
if [ -n "$cand" ] && [ -f "$cand/bin/loom" ]; then
  REPO="$cand"                       # 本地模式:脚本旁就是仓库
elif [ -f "./bin/loom" ]; then
  REPO=$(resolve_dir ".")            # 在仓库根里 `sh install.sh`
fi

if [ -z "$REPO" ]; then
  echo "== 0. 远程引导:克隆仓库 =="
  command -v git >/dev/null 2>&1 || { echo "需要 git(用于克隆仓库)"; exit 1; }
  APP_DIR="${LOOM_APP_DIR:-$HOME/.loom-app}"
  if [ -d "$APP_DIR/.git" ]; then
    echo "已存在 $APP_DIR,更新中…"; git -C "$APP_DIR" pull --ff-only || true
  else
    git clone --depth 1 "$REPO_URL" "$APP_DIR"
  fi
  REPO="$APP_DIR"
fi
BIN="$REPO/bin/loom"

echo "== 1. 校验 python3 =="
command -v python3 >/dev/null 2>&1 || { echo "需要 python3"; exit 1; }
python3 --version

echo "== 2. 软链 loom 到 PATH =="
if [ -w /opt/homebrew/bin ]; then TARGET=/opt/homebrew/bin/loom
elif [ -w /usr/local/bin ]; then TARGET=/usr/local/bin/loom
else mkdir -p "$HOME/.local/bin"; TARGET="$HOME/.local/bin/loom"
     case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "⚠ 把 ~/.local/bin 加进 PATH";; esac
fi
chmod +x "$BIN"; ln -sf "$BIN" "$TARGET"
echo "已链: $TARGET"

echo "== 3. 引导配置(loom init)=="
if [ -t 0 ]; then
  "$BIN" init || true               # 有终端:交互引导(本地 ./install.sh)
else
  echo "(非交互安装,跳过交互式 init;装好后手动运行:loom init)"
fi                                    # piped 时 stdin 是脚本本身,不能喂给 init

echo "== 4. 把 loom 技能装进在场的 AI 助手 =="
"$BIN" skill install --agent all </dev/null || true

echo
echo "完成。日常一条命令:loom sync   (或 AI 工具里说 run \`loom sync\`)"
echo "可选:"
echo "  云端  → cd \$(loom-vault-dir) && gh repo create loom-vault --private --source=. --push"
echo "  定时  → crontab: 0 19 * * *  $TARGET sync --push"
echo "  检索底座 → uvx basic-memory project add loom <vault>/journal;各工具 MCP 见 README"
