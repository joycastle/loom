# Codex Feishu Bridge connector

将 Codex Feishu Bridge 绑定群里的协作话题采集为 Loom 记录。该来源默认关闭，且仅采集**本人真实发过消息**的话题；只被 `@` 不算参与。

## 前置条件

- Codex Feishu Bridge 已在 `~/.feishu-codex-bridge` 写入绑定项目。
- `lark-cli` 可从 `PATH` 调用，用户身份已登录并具备 `search:message` 权限。
- Loom 只调用本地 CLI，不需要把飞书凭证写进仓库。

## 启用

```bash
loom source enable codex_feishu_bridge
loom sync
```

默认配置：

```json
{
  "sources": {
    "codex_feishu_bridge": {
      "enabled": true,
      "home": "~/.feishu-codex-bridge",
      "user_open_id": ""
    }
  }
}
```

通常无需填写 `user_open_id`，connector 会通过 `lark-cli auth status --json` 读取当前用户。仅在身份探测不可用时手工设置。

## 采集边界

- 从 Bridge 的 `projects.json` 发现绑定群，并按 `chat_id` 去重。
- 先按真实 sender 搜索本人消息，再逐页读取完整话题，避免把“只被提及”误判为参与。
- 保留所有真人消息和非卡片机器人文本；机器人卡片、系统消息不进入正文。
- 附件只保存类型、key、名称等元数据，**不下载二进制原件**。
- 长正文不静默截断；消息或话题分页不完整时返回诊断错误，不用半截数据覆盖旧记录。
- 分页有 `MAX_PAGES` 硬上限(默认 1000 页):服务端若持续 `has_more`+新 `page_token`,到上限即报错中止,绝不无限翻页,也不静默截断。
- 记录按本地日期拆分,稳定 ID 为 `codex_feishu_bridge:<thread_id>:<date>`。

## 对 `lark-cli` 输出的契约(依赖,若换版本请核对)

connector 直接消费 `lark-cli` 的 JSON,依赖两点保持一致,否则会**静默失效**(采集为空或日期错乱,不报错):

- **身份 id 空间**:参与判定用 `auth status` 的 `identities.user.openId` 去比消息 `sender.id`。要求二者**同为 open_id 空间**;若某版本 `lark-cli` 把消息 `sender.id` 输出成 union_id / user_id,本人消息将匹配不上 → **一条都采不到**(fail-closed,不泄露)。可用 `user_open_id` 配置项手工兜底。
- **时间格式**:`create_time` 需为 `YYYY-MM-DD HH:MM` 或 `YYYY-MM-DD HH:MM:SS` 字符串(connector 据此按天分桶/排序/显示)。若某版本透传飞书原始的 **epoch 毫秒**,日期分桶会错乱。

管理页来源诊断会分别检查 Bridge 目录、绑定项目数量和 `lark-cli` 可用性。

---

## English summary

This opt-in connector discovers chats bound by Codex Feishu Bridge, qualifies a topic only when the signed-in user actually sent a message, and paginates through the complete thread. It keeps human messages and non-card bot text. Attachments are metadata-only and binaries are never downloaded. See the setup and configuration above; `user_open_id` is normally discovered from `lark-cli auth status --json`.
