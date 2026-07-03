# -*- coding: utf-8 -*-
"""飞书采集器:多维表格(需求池)。凭证从 env(FEISHU_APP_ID/SECRET)读,绝不入库。
按日期范围 + 负责人(客户端过滤,API 不支持人员字段 filter)筛本人负责的需求。"""
import os
import urllib.parse

from .. import util

_token_cache = {}


def token(base_url):
    """取 tenant_access_token(env 凭证,进程内缓存)。"""
    if base_url in _token_cache:
        return _token_cache[base_url]
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        util.log("  [feishu] 缺 FEISHU_APP_ID/FEISHU_APP_SECRET(见 ~/.loom/.env),跳过")
        return None
    data = util.http_json("POST", f"{base_url}/auth/v3/tenant_access_token/internal",
                          body={"app_id": app_id, "app_secret": app_secret})
    if data.get("code") != 0:
        util.log(f"  [feishu] 取 token 失败: {data.get('msg')}")
        return None
    tok = data["tenant_access_token"]
    _token_cache[base_url] = tok
    return tok


def _field_text(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        return v.get("text") or v.get("name") or ""
    if isinstance(v, list):
        return ",".join(_field_text(x) for x in v if _field_text(x))
    return str(v)


def _field_people(v):
    if isinstance(v, list):
        return [x.get("name", "") for x in v if isinstance(x, dict)] or \
               [_field_text(x) for x in v]
    return [_field_text(v)] if v else []


def _field_date(v):
    if isinstance(v, (int, float)):
        return util.ms_to_iso(v)
    if isinstance(v, str) and v[:4].isdigit():
        return v[:19]
    return None


def _list_records(base_url, token, app_token, table_id):
    items = []
    page_token = None
    while True:
        q = {"page_size": 500}
        if page_token:
            q["page_token"] = page_token
        url = (f"{base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/records"
               f"?{urllib.parse.urlencode(q)}")
        data = util.http_json("GET", url, headers={"Authorization": f"Bearer {token}"})
        if data.get("code") != 0:
            util.log(f"  [feishu] 拉记录失败: {data.get('msg')}")
            break
        d = data.get("data", {})
        items.extend(d.get("items", []))
        if d.get("has_more") and d.get("page_token"):
            page_token = d["page_token"]
        else:
            break
    return items


def collect(cfg, since):
    fs = cfg.get("feishu", {})
    if not fs.get("enabled") or not fs.get("bitables"):
        return []
    util.load_env()
    base_url = fs.get("base_url", "https://open.feishu.cn/open-apis")
    tok = token(base_url)
    if not tok:
        return []
    who = (cfg.get("owner", {}) or {}).get("feishu_name", "").strip()
    entries = []
    for bt in fs["bitables"]:
        if not bt.get("app_token") or not bt.get("table_id"):
            util.log(f"  [feishu] {bt.get('name')} 缺 app_token/table_id,跳过")
            continue
        recs = _list_records(base_url, tok, bt["app_token"], bt["table_id"])
        for r in recs:
            f = r.get("fields", {})
            people = _field_people(f.get(bt["person_field"]))
            if who and not any(who in p for p in people):
                continue
            date = _field_date(f.get(bt["date_field"])) or util.ms_to_iso(r.get("last_modified_time"))
            if not date or date[:10] < since:
                continue
            title = _field_text(f.get(bt["title_field"])) or "(需求)"
            status = _field_text(f.get(bt["status_field"]))
            rid = r.get("record_id", "")
            url = (f"https://feishu.cn/base/{bt['app_token']}"
                   f"?table={bt['table_id']}&record={rid}")
            entries.append({
                "id": f"feishu:{bt['table_id']}:{rid}", "date": date[:10], "ts": date,
                "project": bt["name"], "tool": "feishu", "kind": "requirement",
                "summary": f"{title}  [{status}]" if status else title, "ref": url,
                "detail": {"status": status, "owners": people},
            })
    return entries
