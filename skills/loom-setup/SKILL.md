---
name: loom-setup
description: 确保 loom CLI 已安装并在 PATH 上。当准备使用 loom 但命令行里 `loom` 不存在(command not found / 首次使用 loom 插件)时,先用本技能一行装好底层 CLI,再继续。仅负责安装引导,不负责日常使用(用法见 loom 技能)。
allowed-tools: Bash(command -v loom), Bash(curl *), Bash(loom *), Bash(git *)
---

# loom 安装引导

loom 的技能只是"怎么用",真正干活的是底层 `loom` CLI(纯标准库 Python,零 pip、零打包)。
本技能确保它已装好并在 PATH 上,然后就把工作交回 loom 技能。

## 前置检查(是否已安装)

当前是否已装:!`command -v loom >/dev/null 2>&1 && echo "OK: $(command -v loom)" || echo NEED_INSTALL`

- 输出 `OK: …` → 已安装,**无需任何操作**,直接按 loom 技能继续。
- 输出 `NEED_INSTALL` → 执行下面一行安装。

## 一行安装

```bash
curl -fsSL https://raw.githubusercontent.com/joycastle/loom/main/install.sh | sh
```

它会:浅克隆仓库到 `${LOOM_APP_DIR:-$HOME/.loom-app}` → 软链 `loom` 到 PATH →
`loom init` → 把 loom 技能装进在场的 AI 助手。装完用 `command -v loom` 复核。

若 `~/.local/bin` 不在 PATH,安装脚本会提示;把它加进 PATH 后新开终端,或本会话内直接用绝对路径
`~/.local/bin/loom` 调用一次即可。

## 装好之后

CLI 就绪后不再需要本技能。日常检索 / 同步 / 记录请遵循 **loom** 技能:
`loom search`、`loom sync`、`loom note` 等。
