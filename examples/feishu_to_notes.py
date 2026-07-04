# -*- coding: utf-8 -*-
"""示例:把飞书多维表格的行喂成 loom「散信息」note —— 薄薄一层,不是核心采集器。

要点:飞书只是散信息的【一个来源】。核心是 `intake.note()` 这个通用捕获口;换成
邮件/剪贴板/别的表格,照抄这个循环即可。所以 loom 核心里【没有】飞书专用采集逻辑。

用法:
  1. ~/.loom/.env 里配 FEISHU_APP_ID / FEISHU_APP_SECRET
  2. python3 examples/feishu_to_notes.py <多维表格URL 或 app_token> [table_id]
  3. loom sync   # 把新 note 纳入检索/日记;之后 loom topic 可给它们打标

凭证只从 env 读,绝不入库;文本入库前会走 loom 打码。纯标准库。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from loom import config, intake, util                      # noqa: E402
from loom.collectors import feishu                          # noqa: E402


def main(argv):
    if not argv:
        print("用法:python3 examples/feishu_to_notes.py <URL 或 app_token> [table_id]")
        return 1
    util.load_env()
    cfg = config.load()
    base = cfg["feishu"]["base_url"]
    arg = argv[0]
    app_token, table_id = config.parse_bitable_url(arg)     # URL → (app_token, table_id)
    app_token = app_token or arg
    table_id = (argv[1] if len(argv) > 1 else None) or table_id
    if not (app_token and table_id):
        print("需要 app_token + table_id(URL 里没解析到 table_id 就手传第二个参数)")
        return 1
    tok = feishu.token(base)
    if not tok:
        return 1

    rows = feishu._list_records(base, tok, app_token, table_id)   # 复用已有的分页拉取
    n = 0
    for r in rows:
        fields = r.get("fields", {}) if isinstance(r, dict) else {}
        # 把一行的所有字段拼成一段文本(散信息不假设固定结构)
        parts = [f"{k}: {feishu._field_text(v)}" for k, v in fields.items()
                 if feishu._field_text(v)]
        text = "\n".join(parts)
        if not text.strip():
            continue
        dest, msg = intake.note(cfg, text, to="inbox", tags=["feishu"])
        if dest:
            n += 1
    print(f"从飞书表喂入 {n} 条散信息 → notes/inbox/(跑 loom sync 纳入检索)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
