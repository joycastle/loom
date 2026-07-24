# loom Web UI Design

> 本地控制台（`loom serve` → `loom/assets/browse.html`）的界面设计系统。
> 借鉴 [Apple Design skill](https://github.com/emilkowalski/skills/blob/main/skills/apple-design/SKILL.md)
> （WWDC *Designing Fluid Interfaces* 等），落在**零依赖、单文件、系统字体**的约束里。

## 前端架构契约

- `loom/assets/browse.html` 是唯一前端与唯一界面真相；不保留第二套 React/Vite 实现。
- 页面直接消费 `loom serve` 的本地 JSON API，无构建、无 CDN、无 Node/npm 运行依赖。
- `/app` 只作为旧书签的一版兼容跳转，产品入口始终是 `/`。

## 核心立场

> 对齐人如何思考与移动时，界面不再像电脑，而像身体的延伸。

loom 服务四个人类需要：**可预期 / 可理解 / 可完成 / 愉悦**。
设计服务于它们，不为装饰本身存在。

**产品语境**：单人本地台账控制台——冷静、克制、信息优先。不是营销站，不是仪表盘玩具。

---

## 1. 八项原则（决策时用这些词）

1. **Purpose** — 每个控件都要回答「它帮用户完成什么」；拿不准就删。
2. **Agency** — 用户始终能走；破坏性操作二次确认，其余不拦。
3. **Responsibility** — 凭证/原始数据边界在 UI 上说清楚；不假装「已上云」。
4. **Familiarity** — 导航、开关、分页、抽屉遵循桌面/ iOS 既有心智。
5. **Flexibility** — 亮暗、中英、系统字号、触控与指针、reduced-motion。
6. **Simplicity ≠ minimalism** — 首页是**操作台概览**不是 landing page：日期语境 + 同步 + 搜索入口 + 今日/周指标 + 活动织物 + 来源 + 最近；口号级文案不要。高级项进管理更深一层。
7. **Craft** — 间距、字阶、材质、动效皆可辩护；不对齐即视为 bug。
8. **Delight** — 来自反馈准时与运动自然，不来自彩带与双色渐变字。

---

## 2. 响应（Response）

- 按下即反馈（`:active`），不要等 `click` 才变色。
- 拖拽/抽屉全程 1:1 跟随；禁止「松手才动画」。
- 输入路径去掉无意义 debounce（搜索保留 ~280ms；按钮零延迟）。
- 按钮默认：

```css
.act:active { transform: scale(0.97); transition: transform 100ms ease-out; }
```

---

## 3. 直接操纵与可中断

- 侧栏抽屉、模态从**当前呈现值**开启动画，可随时 Escape / 点遮罩关闭。
- 换页立刻关抽屉，不锁输入。
- 手势驱动不用写死 `@keyframes` 路径；用可打断的 transition / 将来的 spring。

**Web 默认弹簧（无库近似）**

| 场景 | 曲线 | 时长 |
| --- | --- | --- |
| 默认 UI | `cubic-bezier(0.32, 0.72, 0, 1)` | 360–420ms |
| 按下反馈 | `ease-out` | 100ms |
| 淡入层级 | `ease` | 200ms |
| 动量轻弹（仅 flick） | 略欠阻尼 | 300ms + 轻微 overshoot |

默认 **无 overshoot**；只有甩动手势才允许轻微回弹。

---

## 4. 空间一致性

- 进从哪来、回从哪走：抽屉自右侧进/出；模态自中心 scale+fade。
- 触发源与浮层空间相关（配置弹窗由「配置」按钮唤起）。
- 顶栏 sticky 恒在抽屉之上；遮罩从顶栏下沿开始，不挡导航。

---

## 5. 材质与纵深

Apple 用半透明材料分层，不靠厚重描边。

| 层 | 用途 | 实现 |
| --- | --- | --- |
| Base | 页面底 | 实色 `--bg` |
| Raised | 卡片/面板 | `--surface` + 极淡分隔 |
| Chrome | 顶栏/工具条 | `backdrop-filter: blur(20px) saturate(180%)` + 半透明 |
| Overlay | 抽屉/模态 | 更不透明的 material + 柔阴影 |
| Scrim | 模态/抽屉背后 | 半透明黑 + 轻 blur |

规则：

- **不要**把两层轻透材料叠在一起。
- 大表面更「厚」：更强 blur + 更深阴影。
- 滚动边缘用淡分隔/渐隐，不用 1px 硬线切满屏（顶栏可用全宽极淡 separator）。
- `prefers-reduced-transparency: reduce` 时升不透明度、关 blur。

---

## 6. 色彩

**单交互强调色**，不再金+青双主色抢视线。织物热力仍可用经纬双色；主题页可用有限的家族语义色，但同一父子家族必须保持节点、层级线与矩阵标识一致。

### Dark（默认偏控制台）

| Token | 值 | 角色 |
| --- | --- | --- |
| `--bg` | `#000000` | 页面 |
| `--surface` | `#1C1C1E` | 分组底 |
| `--surface-2` | `#2C2C2E` | 次级填充 |
| `--label` | `#F5F5F7` | 主文字 |
| `--secondary` | `rgba(235,235,245,.62)` | 次文字 |
| `--tertiary` | `rgba(235,235,245,.36)` | 辅文字 |
| `--separator` | `rgba(84,84,88,.65)` | 分隔 |
| `--accent` | `#5AC8A8` | 交互强调（loom 青绿） |
| `--accent-soft` | `rgba(90,200,168,.14)` | 选中底 |
| `--danger` | `#FF6961` | 破坏 |
| `--warn` | `#FFD60A` | 警告（文字用更深对比时降饱和） |
| `--ok` | `#32D74B` | 成功 |

### Light

| Token | 值 |
| --- | --- |
| `--bg` | `#F2F2F7` |
| `--surface` | `#FFFFFF` |
| `--surface-2` | `#E5E5EA` |
| `--label` | `#1C1C1E` |
| `--secondary` | `rgba(60,60,67,.64)` |
| `--tertiary` | `rgba(60,60,67,.36)` |
| `--separator` | `rgba(60,60,67,.14)` |
| `--accent` | `#0F8A6A` |
| `--danger` | `#D70015` |

语义色只用于状态，不用于大面积装饰。

---

## 7. 字体

- 栈：`-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", system-ui, sans-serif`
- 等宽：`ui-monospace, "SF Mono", Menlo, Consolas, monospace`
- **字距随字号**：大标题 `letter-spacing: -0.02em`～`-0.03em`；正文近 `0`。
- **行高随字号反比**：大标题 `1.1–1.2`；正文 `1.47`；密集 UI `1.35`。
- 层级靠 **字重 + 字号 + 颜色**，不靠彩色渐变字。
- 触控下表单 `font-size ≥ 16px`，防 iOS 聚焦缩放。

字阶：

| 角色 | 大小 | 字重 |
| --- | --- | --- |
| Large Title | 28–34 | 700 |
| Title | 20–22 | 650 |
| Headline | 15–17 | 600 |
| Body | 15 | 400 |
| Callout / Sub | 13 | 400 |
| Caption | 11–12 | 400–500 |

---

## 8. 布局与间距

- **8pt 网格**：4 / 8 / 12 / 16 / 20 / 24 / 32。
- 内容轨：`--page-track: 960px`；阅读/英雄：`760px`（与历史布局契约一致）。
- 圆角：控件 8–10；卡片/面板 12–14；大型表面 16–20；胶囊 999。
- 列表优先 **分组列表**（同组共享底，行间 separator），少「每卡一框」。
- 移动：导航可横滑；主按钮 ≥ 44×44 触控热区。

---

## 9. 组件语法

### 顶栏
半透明 material，内容从其下滚过；底部分隔用全宽 separator；右侧 segmented 导航。

### 分段导航（nav）
未选：次级文字；悬停：轻 fill；选中：raised 实底 + 主文字。按下即时高亮。

### 按钮
- 默认：细边或 light fill
- Primary：accent 实心 + 白/近白字
- Danger：仅悬停/强调时用 danger
- 禁用：opacity .4–.5，保留布局

### 卡片 / 行
可点行：整行命中；右侧可选 chevron。悬停轻微抬升 fill，不靠厚描边。

### 开关
iOS 式轨道；开=accent；拇指白圆 + 轻阴影；`aria-checked`。

### 抽屉
右缘 sheet；遮罩可点关；顶栏不被挡。动画用 §3 默认曲线。

### 模态
居中 sheet + scrim；大标题 + 分区；关闭对称。

### 空态 / 加载 / 错误
同一位置给出状态，不整页闪白；403 会话失效要可行动（重开 serve URL）。

---

## 10. 动效清单

- 换 view：即时切换 + `scrollTo(0,0)`（不继承长页滚动）。
- 抽屉/模态：transform + opacity，只动合成属性。
- 数字点缀可用短 count-up；`prefers-reduced-motion` 时直接定格。
- 避免全屏视差、慢循环呼吸灯、无意义无限 spin（加载 spinner 除外）。

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .01ms !important;
    transition-duration: .01ms !important;
  }
}
```

---

## 11. 无障碍

- 可见 `:focus-visible` 环（accent，offset 2）。
- 跳过链接、`aria-current`、对话框 `aria-*`、live region 同步结果。
- 对比：正文与底 ≥ 4.5:1；次级文字不靠过浅灰。
- `prefers-contrast: more` 时实底 + 明确边框。

---

## 12. 反模式（明确不做）

- 大标题双色渐变字、网格线背景墙
- 金+青双主色按钮/边框同时抢焦点
- 装饰性重阴影叠重描边
- 为「显得高级」加玻璃拟态到正文区块
- 锁死动画、无法 Escape
- 引入 CDN / 构建链 / 图标字体包（保持单文件零依赖）

---

## 13. 首页信息架构（Overview）

顺序即优先级，上 → 下：

1. **Large title 行**：当日日期 kicker · 「概览」· 一句动态副文案（今日/近 7 天数量）· 同步
2. **搜索入口**：位于顶栏；⌘K 仅聚焦，不切换页面
3. **指标条**（单组 surface，四分）：今日 · 近 7 天 · 记录总数 · 已归类
4. **洞察双栏**：活动（26 周单色热力）| 来源占比列表
5. **最近**：分组列表；空态给同步 CTA

禁止：营销 slogan、双色渐变数字、无语境的四块「总条数」堆砌、织物图大段说明文案。

管理页「概览」指标条与首页同一语言：分组 strip，不各自为卡。

### 交互细节（必须）

- **顶栏全局搜索**：⌘K 聚焦顶栏输入，**不跳转页面**；非记录页弹出结果层（↑↓/Enter）；记录页只过滤列表。
- **卡片**：整行可点 + `tabindex` + Enter/Space；右侧 chevron 悬停微移；相对时间；主题 chip。
- **对齐**：8pt 间距变量；控件统一 34px 高；页眉/分段标题同一 baseline 节奏；顶栏 grid（brand | search | nav）；窄屏导航收敛但不造成整页横向溢出。
- **指标 / 来源行**：可点跳转（今日→日历，记录→记录页，归类→主题，来源→记录页筛选）。
- **抽屉**：打开锁滚动；先骨架后内容；sticky 标题 + 关闭；meta chip；Escape 优先关抽屉。
- **模态**：打开锁滚动并聚焦面板；Escape / 遮罩关闭；换页自动关。
- **记录（内部路由仍为 `ledger`）**：筛选条 sticky；有筛选时显示「清除」；空态给 CTA；加载骨架。
- **主题**：层级 DAG 与自动结构关联明确分成两个视角；关系矩阵只展示强连接主题，详情抽屉保留一跳关联记录。
- **日报**：只导出本地原材料并展示历史日报；AI 合成明确交给外部工具，不伪装成本地能力。
- **AI 助手集成**：在管理设置中展示 skill 的真实安装状态；安装、修复和可恢复卸载都有明确反馈。
- **同步**：按钮 busy 旋转；底部 toast 反馈结果（成功/部分/失败）。
- **视图切换**：短 fade-in；`prefers-reduced-motion` 关闭动画。

---

## 14. 落地映射

| 文件 | 职责 |
| --- | --- |
| `loom/assets/browse.html` | 唯一 UI 实现（CSS + 结构 + JS） |
| `loom/serve.py` | 仅 127.0.0.1 静态下发 + API |
| `docs/design.md` | 本文件：改 UI 前先对照 |

改视觉时优先改 **token 与组件类**，避免页面级特例颜色。
改完跑：`python3 -m pytest tests/test_loom.py`。
