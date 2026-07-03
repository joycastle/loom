#!/usr/bin/env bash
# worklog 一键部署:装 CLI 到 PATH → 引导配置 → 可选云端仓 / 定时任务。
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$REPO/bin/worklog"

echo "== 1. 校验 python3 =="
command -v python3 >/dev/null || { echo "需要 python3"; exit 1; }
python3 --version

echo "== 2. 软链 worklog 到 PATH =="
if [ -w /opt/homebrew/bin ]; then TARGET=/opt/homebrew/bin/worklog
elif [ -w /usr/local/bin ]; then TARGET=/usr/local/bin/worklog
else mkdir -p "$HOME/.local/bin"; TARGET="$HOME/.local/bin/worklog"
     case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "⚠ 把 ~/.local/bin 加进 PATH";; esac
fi
chmod +x "$BIN"; ln -sf "$BIN" "$TARGET"
echo "已链: $TARGET"

echo "== 3. 引导配置(worklog init)=="
"$BIN" init || true

echo "== 4. 首次同步 =="
"$BIN" sync || true

echo
echo "完成。日常一条命令:worklog sync   (或 AI 工具里说 run \`worklog sync\`)"
echo "可选:"
echo "  云端  → cd \$(worklog-vault-dir) && gh repo create worklog-vault --private --source=. --push"
echo "  定时  → crontab: 0 19 * * *  $TARGET sync --push"
echo "  检索底座 → uvx basic-memory project add worklog <vault>/journal;各工具 MCP 见 README"
