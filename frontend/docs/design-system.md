# 设计规范

前端所有页面的视觉规范。取值的唯一来源是 `src/design/tokens.ts`，`tailwind.config.ts` 只负责把它们接进 Tailwind。语音通话页（`screens/Clinic/VoiceCallScreen.tsx` 与 `components/voice/`）是第一个完全按本规范实现的页面，拿不准时以它为样板。

## 原则

1. **只用语义名，不用原始色系。** 写 `bg-brand-700`、`text-ink-600`，不写 `bg-teal-700`、`text-slate-600`、`text-emerald-500`。
2. **不写任意值。** 不写 `text-[10px]`、`rounded-[2rem]`、`shadow-[…]`。规范里没有的值，先讨论要不要加进 `tokens.ts`。
3. **层级靠字号和颜色，不靠加粗。** 一块内容里只有标题加粗（`font-semibold`），正文用常规字重；不要整屏都是粗体。
4. **浅色、安静、有层次。** 背景是极浅的冷色渐变，内容放在白色浮起的卡片上；颜色只用来表达状态和主操作，不做装饰。
5. **长辈模式是一等公民。** 每处文字都要考虑长辈模式下的字号（见下文），并保证对比度。

## 颜色

| 名称 | 色系 | 用途 |
| --- | --- | --- |
| `brand` | 青绿（teal） | 品牌色。主按钮（`brand-700`，悬停 `brand-800`）、选中态、已填写的信息、链接文字（`brand-800`）、浅底高亮（`brand-50`） |
| `ink` | 冷灰（slate） | 文字与表面。标题 `ink-900`，正文 `ink-700`，次要文字 `ink-600`，白底上最浅可用文字 `ink-500`；分隔线 `ink-200`，页面底 `ink-50` |
| `accent` | 紫（violet） | 只表示"助手在思考"。不用于别处 |
| `info` | 天蓝（sky） | 系统信息、"助手在说话"（播放音频） |
| `success` | 绿 | 成功、正常、连接正常 |
| `warning` | 琥珀 | 需要注意但不危险：待确认、待补充、建议尽快就诊 |
| `danger` | 玫红（rose） | 只用于挂断、急症、错误、删除 |

规则：

- 一个界面里，饱和色块只给最重要的一个操作（通常是 `brand-700` 主按钮或 `danger` 挂断）。
- 白底上的文字不浅于 `ink-500`；`ink-400` 只用于图标和占位符，不用于需要阅读的文字。
- 浅底色标签的写法：`bg-<色>-50 text-<色>-800 ring-1 ring-inset ring-<色>-200`。

## 字号

| 名称 | 字号 / 行高 | 用途 |
| --- | --- | --- |
| `text-caption` | 12 / 16 | 辅助信息、角标、时间。最小字号，不再往下 |
| `text-body` | 14 / 22 | 正文、按钮文字、卡片内容 |
| `text-callout` | 16 / 24 | 强调的正文、主按钮文字、对话气泡 |
| `text-title` | 18 / 26 | 卡片标题、页面副标题 |
| `text-headline` | 22 / 31 | 页面标题、关键数字 |
| `text-display` | 28 / 38 | 首屏主数字、语音页大字幕 |

**长辈模式至少上移一级**：`caption → body`、`body → callout`、`callout → title`，以此类推；阅读为主的长文本（对话气泡、字幕）可以上移两级。写法：

```tsx
className={isElderMode ? 'text-callout' : 'text-body'}
```

## 字体

`font-cn`：PingFang SC → HarmonyOS Sans SC → Noto Sans SC → 系统字体。只用系统字体，不下载网络字体。挂在页面根节点上，子元素继承。数字需要对齐时（计时器、金额、指标）加 `tabular-nums`。

## 圆角

| 名称 | 值 | 用途 |
| --- | --- | --- |
| `rounded-card` | 24px | 卡片、面板、底部抽屉 |
| `rounded-control` | 16px | 按钮、输入框、卡片内的小块 |
| `rounded-full` | — | 标签、胶囊按钮、圆形图标按钮、头像 |

只用这三种。卡片里再嵌的小块用 `rounded-control`，不要再出现 `rounded-xl`、`rounded-2xl`、`rounded-3xl`。

## 阴影

| 名称 | 用途 |
| --- | --- |
| `shadow-raised` | 静止的卡片、普通按钮、浮在背景上的小胶囊 |
| `shadow-floating` | 底部抽屉、弹层、页面上唯一的主行动按钮 |
| `shadow-docked` | 贴在屏幕底边的表面（输入栏、底部导航），阴影朝上 |

两层阴影都是"贴近的细阴影 + 远处的柔和大阴影"叠成，带来浮起感。不要再叠加 `border`：卡片的边界由阴影表达；需要描边时用 `ring-1 ring-inset ring-ink-200`。

## 动效

| 名称 | 时长 | 用途 |
| --- | --- | --- |
| `duration-fast` | 150ms | 按下反馈（`active:scale-[0.98]`） |
| `duration-base` | 200ms | 颜色、状态切换 |
| `duration-slow` | 300ms | 抽屉、卡片进场 |

预置动画：`animate-rise`（内容从下方淡入，用于新出现的卡片）、`animate-breathe`（缓慢呼吸，用于待机状态）、`animate-soft-pulse`（琥珀色脉冲，提示需要用户操作）、`animate-spin-slow`。**每个动画都要配 `motion-reduce:animate-none`**，尊重系统的"减少动态效果"设置。

## 常用组合

```tsx
// 页面背景
'font-cn bg-gradient-to-b from-brand-50 via-white to-ink-50'

// 白色卡片
'rounded-card bg-white p-4 shadow-raised'

// 强调卡片（结果、结论）
'rounded-card bg-gradient-to-br from-white to-brand-50/70 p-4 shadow-raised'

// 主按钮
'h-12 rounded-control bg-brand-700 px-5 text-callout font-semibold text-white shadow-raised hover:bg-brand-800 active:scale-[0.98] transition duration-fast'

// 次按钮
'h-12 rounded-control bg-white px-5 text-callout font-semibold text-ink-800 shadow-raised ring-1 ring-inset ring-ink-200 active:scale-[0.98] transition duration-fast'

// 标签
'rounded-full bg-brand-50 px-3 py-1 text-body text-brand-800 ring-1 ring-inset ring-brand-200'

// 浮在背景上的状态胶囊
'rounded-full bg-white/90 px-3 py-1.5 shadow-raised'
```

## 共享组件

新写界面时先用这些，不要再手写一套卡片样式。

**`useTextScale()`**（`src/design/textScale.ts`）：按角色返回字号类名，长辈模式自动上移一级，免得每处都写 `isElderMode ? … : …`。

```tsx
const t = useTextScale();
<p className={`text-ink-800 ${t.body}`}>…</p>   // 角色：caption / body / callout / title / headline
```

**结果卡片**（`src/components/common/ResultCard.tsx`），对话里所有结果卡片都由它们拼成：

| 组件 | 用途 |
| --- | --- |
| `ResultCard` | 卡片外壳：白底浮起，左上图标块 + 标题，右上 `meta`（徽标或一行说明）。`tone` 决定图标块颜色；`alert` 给整张卡加危险红描边（急症） |
| `Badge` | 状态徽标，`tone` 取 `brand / success / warning / danger / neutral` |
| `Stat` | 浅灰小块里的"标签 + 数字"，放在 `grid` 里用 |
| `SectionLabel` | 卡片内的小节标题 |
| `Note` | 浅灰提示条：小贴士、说明 |

语义约定：正常 / 已完成用 `success`，需要注意（偏高偏低、待确认、建议尽快就诊）用 `warning`，只有急症和危险信号用 `danger`。医保电子凭证卡是唯一用整块品牌色做底的卡片。

## 可访问性

- 所有文字与背景的对比度至少达到 WCAG AA（正文 4.5:1，18px 以上或 14px 加粗的大字 3:1）。半透明层上的文字按叠加后的实际颜色计算。
- 可点击区域不小于 44×44px；长辈模式下主操作按钮高度 56px（`h-14`）。
- 只靠颜色区分的状态，要同时有文字或图标。
- 刘海和底部横条区域用 `env(safe-area-inset-*)` 让开。
- 全屏层（如语音通话页）打开时，下面的界面要设为 `inert` 并 `aria-hidden`，不能被聚焦或被读屏读到。
