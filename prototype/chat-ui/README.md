# Loom Chat UI 原型（assistant-ui）

> 阶段一 de-risk：只验证聊天岛，**不重写**首页/台账/日报/设置等页面。

## 要证明的三件事

1. **严格 CSP**：构建产物在 `default-src 'self'` 下可运行（与 Tauri `tauri.conf.json` 一致）
2. **Runtime 适配**：`ExternalStoreRuntime` 对接 loom 现有 REST 形状（`POST /api/enterprise/v1/ai/messages` + job 轮询）
3. **提案审批卡**：`agent_proposal` / `agent_job` 卡片可确认/取消/查看详情

## 运行

```bash
cd prototype/chat-ui
npm install
npm run dev
```

浏览器打开终端提示的地址（默认 `http://localhost:5173`）。

### mock 模式（默认）

无需 sidecar / 飞书登录。试这几句：

- `帮我收编这些文件` → 弹出提案卡，可确认/取消
- `启动后台任务` → 模拟 job 轮询后返回结果
- `给我一些参考记录` → 带 citations 的普通回复

### live 模式

切到 **live**，填入桌面 sidecar 的 `baseUrl`（如 `http://127.0.0.1:xxxx`）和启动时 stdout ready JSON 里的 admin token，即可接真实 API。

### CSP 验证

```bash
npm run build
npm run preview
```

`vite preview` 会带上与 Tauri 相同的 CSP 响应头；确认页面可交互、可发送、提案卡可点。

## 架构

```
browse.html（保留）
  ├── 首页 / 台账 / 日报 / 设置  ← 不动
  └── #loom-chat-root            ← 未来嵌入 dist/assets/*.js

prototype/chat-ui（本目录）
  ├── LoomRuntimeProvider        ExternalStoreRuntime + loom API 适配
  ├── LoomChat                   ThreadPrimitive + ComposerPrimitive
  └── LoomCards                    提案卡 / job 卡（接 /api/agent/v1/* 形状）
```

## 下一步（阶段二，未开始）

原型三项通过后，再把 `dist/` 以 React 岛形式挂进 `loom/assets/browse.html` 的 `#v-assistant`，替换现有 vanilla JS 聊天层。
