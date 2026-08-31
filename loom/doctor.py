# -*- coding: utf-8 -*-
"""loom doctor:只读体检 + 每源给「可直接执行的修复命令」。

doctor 本身**不含任何逐源逻辑**——它只遍历 collectors.SUGGEST_REGISTRY,调用
每个源自带的 `suggest(cfg)`(见 loom/suggest.py 的共享底座),聚合成一份体检报告。
加新源、只要它带 suggest,就自动被 doctor 发现,不用改这里。

设计对齐 flutter/npm/brew doctor:纯读、可反复跑、不改任何东西(除非 --apply)。
每条 finding 带 `risk` 分流,专为 AI 驱动设计——
  - risk="zero":零风险(探测到的路径/可开启的源),AI 可 --apply 批量落地;
  - risk="needs_confirmation":个性化/登录/凭证,AI 必须逐条问用户点头才做。
`fix_command` 是这条建议对应的确切命令,AI 原样执行即可(别自己拼)。
"""
from . import collectors, config


def diagnose(cfg, only=None):
    """遍历每个源的 suggest(),聚合 finding 列表(只读)。only=源名则只体检该源。"""
    out = []
    for name, fn in collectors.SUGGEST_REGISTRY.items():
        if only is not None and only != name:
            continue
        try:
            out.extend(fn(cfg) or [])
        except Exception:
            pass          # 单个源的 suggest 出错不该拖垮整份体检
    return out


def apply(cfg, findings, dry_run=False):
    """只对 risk=zero 的项落地(目前=开启探测到的源)。返回执行的命令列表。"""
    done = []
    for f in findings:
        if f.get("risk") != "zero" or f.get("status") != "detected_disabled":
            continue
        if not dry_run:
            cfg.setdefault("sources", {}).setdefault(f["source"], {})["enabled"] = True
        done.append(f["fix_command"])
    if done and not dry_run:
        config.save(cfg)
    return done
