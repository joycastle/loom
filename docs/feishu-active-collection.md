# 飞书主动采集(user OAuth)

以**用户身份**主动拉取「我」在飞书里可见的群 / 会话消息进 loom —— 不同于被动收
集箱(用户手动 @/转发才收),这里登录一次后由 loom 主动增量拉取。

> **默认关闭。** `sources.feishu_user.enabled=False`,且没登录时 `collect()` 只返
> 回空 + 诊断说明,不报错、不影响其它来源。真正采数据前需完成下面两步。

## 为什么必须走用户身份

飞书的隐私边界决定了方案形状:

| 能力 | 应用身份(机器人) | 用户身份(user OAuth) |
|---|---|---|
| 枚举群 | 只看到机器人已加入的群 | **我加入的全部群** |
| 群消息历史 | 需敏感权限且机器人在群 | 我参与的群,直接读 |
| 私聊 | 读不到 | **我参与的**单聊可读 |
| 别人之间、我不在场的私聊 | 读不到 | **读不到**(设计红线,无绕过) |

## 一次性配置:自建飞书应用(BYO)

loom **不捆绑任何飞书应用**,你自备一个自建应用(bring your own app):

1. 在[飞书开放平台](https://open.feishu.cn)创建企业自建应用。
2. 开启「网页应用」能力,配置重定向 URL:`http://localhost:8788/callback`
   (端口对应 `sources.feishu_user.redirect_port`)。
3. 申请并**发布新版本**以下 user scope:
   - `im:chat:readonly` — 枚举我加入的群
   - `im:message:readonly`(读取用户发送和接收的消息)— 读我参与的会话历史(群 +
     私聊)。**注意**:列历史 `GET /im/v1/messages` 认的是这个;`im:message.*:get_as_user`
     是按 message_id 读单条用的,列历史接口不认(错误码 99991679)。
   - `offline_access` — 拿 refresh_token,免每 2 小时重登
4. 把应用的 App ID / Secret 写入 `~/.loom/.env`(**绝不入库**):
   ```
   FEISHU_APP_ID=cli_xxx
   FEISHU_APP_SECRET=xxx
   ```

个人授权**不需要企业管理员审核**;但申请敏感 scope 仍要过一次应用发版。

## 登录 & 采集

```bash
loom feishu login            # 浏览器授权我的账号 → 存 refresh_token(~/.loom,600)
loom feishu status           # 看登录状态 / token 剩余时长(不打印 token 本身)
loom source enable feishu_user
loom sync --source feishu_user
loom feishu logout           # 清除本地 token
```

`~/.loom/feishu_user_token.json` 等同长期以我身份读飞书,按凭证对待:600 权限、和
`.env` 同级、绝不进 vault。改过 scope 后需**重新 `loom feishu login`**,旧 token 不
带新 scope。

## 隐私

- 这份数据是「我账号视角的全量」,含大量他人在群里的发言。入库前会走 loom 的
  `redact`(默认开)抹掉 token/密钥;是否进一步只留摘要/脱敏,按需在采集器里加。
- 目前只入**文本消息**;图片/文件/卡片不进正文,富文本 post 暂跳过。

## 代码位置

- 采集器 + OAuth:`loom/collectors/feishu_user.py`(纯标准库,所有飞书请求走
  `_request()` 单一出口,便于测试打桩)
- CLI 登录:`loom/cli.py` 的 `cmd_feishu` / `_feishu_login`
- 控制台面板:`loom serve` → 来源设置 → 飞书主动采集(显示登录状态 + 要申请的
  scope + 回调 URL)
- 测试:`tests/test_loom.py::FeishuUserCollectorTest`(全程打桩,不触网)
