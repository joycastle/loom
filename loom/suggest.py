# -*- coding: utf-8 -*-
"""每个采集器「自荐配置」的共享底座。

每个 collector 可选暴露 `suggest(cfg) -> [finding]`,`loom doctor` 通过
collectors.SUGGEST_REGISTRY 统一调用、聚合。finding 结构见 finding();
`risk` 分流(zero 可自动 / needs_confirmation 需人确认)由 doctor 落地时用。
"""
import os

from . import util


def finding(source, status, risk, message, fix_command=None, detail=None):
    """一条配置建议。fix_command 是可直接执行的命令(AI 原样跑,别自己拼)。"""
    return {"source": source, "status": status, "risk": risk,
            "message": message, "fix_command": fix_command, "detail": detail or {}}


def path_source(cfg, name, key, default):
    """路径类源的通用自荐:目录有数据但源关闭 → 零风险建议开启;
    启用但目录缺失 → 报错(需确认)。claude/cursor/pi/opencode 都复用它。"""
    src = cfg.get("sources", {}).get(name, {})
    path = util.expand(src.get(key, default))
    exists = os.path.isdir(path)
    enabled = bool(src.get("enabled"))
    if exists and not enabled:
        return [finding(name, "detected_disabled", "zero",
                        f"检测到 {path} 有数据,但该源当前关闭",
                        f"loom source enable {name}", {"path": path})]
    if enabled and not exists:
        return [finding(name, "error", "needs_confirmation",
                        f"已启用但目录不存在:{path}", None, {"path": path})]
    return []
