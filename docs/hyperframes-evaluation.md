# HyperFrames 评估（视频优先版）

> 修正定位：koubo-studio 是**视频剪辑工作流**，最终产品是**高质量成片**；剪映草稿、OTIO、FCPXML、预览 mp4 都是中间产物或可选导出，不是项目定位。  
> 在这个前提下，HyperFrames 不是“可选小工具”，而是 **composition / 动效包装层的主链候选**。

## 1. 它是什么

HyperFrames 是 HeyGen 开源的 **HTML → 视频** CLI：

| 项 | 内容 |
| --- | --- |
| 许可证 | Apache-2.0 |
| 运行时 | Node.js ≥ 22（0.8.180）、FFmpeg、Chrome/Chromium |
| 输入 | HTML/CSS/媒体 + 可 seek 的动画（GSAP timeline 等） |
| 输出 | MP4、WebM（VP9 alpha）、MOV（透明）、GIF、PNG sequence |
| 命令 | `init` / `preview` / `lint` / `check` / `render` / `doctor` / `browser` |
| 确定性 | `render --docker`；`check --at-transitions`；快照 |
| 定位 | 给 Agent/代码生成视频的 composition 引擎，不是剪辑器 |

关键能力：

- 透明 overlay：`--format webm`（VP9 alpha）或 `--format mov`；
- `lint` 校验 HTML/composition 语法，`check` 检查时间线和转场；
- `preview` 本地预览，`render --docker` 追求可复现；
- 参数化渲染：`data-composition-variables` + `--variables`；
- 有 Chrome/Chromium 管理、FFmpeg 探测和 `doctor`。

## 2. 两套参考项目怎么用

| 项目 | 角色 | 实际用法 |
| --- | --- | --- |
| talking-head-motion | **主渲染器** | `hyperframes 0.8.145` + GSAP 3.14.2；Python `motion.py` 生成 `public/index.html`，`check --at-transitions`，`render --fps --workers 1 --browser-gpu`，再用 FFmpeg 把原始人声 mux 回去 |
| auto-edit-pro | **可选 legacy adapter** | `npx hyperframes@0.7.99 lint/check`；默认 Remotion；HyperFrames 只用于 legacy 布局/风格，最终 Gate C/D 不用它 |
| huashu-art-motion | 未使用 | 自研 Canvas + Playwright + `renderFrame(t)` |

结论：

- HyperFrames **能**做整条口播合成，不只是小卡片；
- 复杂 React/全屏舞台场景，auto-edit-pro 仍选择 Remotion；
- 它的强项是 **HTML/CSS/GSAP + 固定模板 composition**，适合视频包装层。

## 3. 为什么视频优先后，它变重要了

如果项目定位是“草稿生成器”，HyperFrames 确实可以只做 sidecar：草稿才是交付，动效只是加分项。

但定位是“高质量成片”时：

- 动效、排版、节奏、包装是**产品本身**，不是附加项；
- 需要 `preview` 预览、`lint`/`check` 校验、`render` 出片，而不是只靠一个逐帧脚本；
- 需要透明 overlay / 全 composition 两种输出，方便合成与复用；
- 需要一套可维护的 composition 约定，而不是每个动效写一个 `renderAt(t)`；
- 需要可复现渲染，才能把“视觉质量”当工程指标来回归。

HyperFrames 正好覆盖这五点；当前自研 `render_motion.py` 只覆盖“短 overlay 逐帧截图”。

## 4. 与当前 `render_motion.py`、Remotion 的对比

当前动效栈：

```text
assets/motion/*.html
  → Playwright Chromium 逐帧截图（omit_background）
  → PNG sequence
  → FFmpeg prores_ks 4444 / yuva444p10le
  → work/motion/*.mov（透明 overlay）
```

| 维度 | 当前 `render_motion.py` | HyperFrames | Remotion |
| --- | --- | --- | --- |
| 运行时 | Python + Playwright + FFmpeg | Node ≥22 + Chromium + FFmpeg | Node + React + Chromium + FFmpeg |
| 作者模型 | 自己写 `window.renderAt(t)` | HTML/CSS/GSAP composition | React/TS 组件 + 帧函数 |
| 预览/检查 | 无内置 | `preview` / `lint` / `check` / snapshots | Remotion Studio / 类型检查 |
| 透明输出 | ProRes 4444 MOV | WebM VP9 alpha / MOV 透明 | ProRes 4444 / 透明视频 |
| 全片 composition | 不擅长 | 强 | 强 |
| 类型安全 | 弱 | 弱（HTML 约定） | 强（TS/Zod） |
| 许可证 | 自有 | Apache-2.0 | 注意公司授权条款 |
| 适合 | 1–2 个 hero overlay | 整片/模板化 HTML 包装 | 复杂 React 舞台/强类型组件 |

## 5. 决策

### 主链候选：HyperFrames

- **定位**：composition / 动效包装层的第一候选；不是“可选 sidecar”。
- **输出**：透明 WebM/MOV overlay，或带源视频的完整 composition。
- **理由**：Apache-2.0；HTML/CSS/GSAP 对视频包装足够；CLI 工具链完整；talking-head-motion 已验证整片口播。
- **边界**：Node 22 + Chromium；浏览器/字体/媒体确定性；版本锁定；透明格式要实测 NLE/剪映导入。

### 保留：当前 Canvas `render_motion.py`

- 作为**微动效/应急 fallback**：1–2 个 hero overlay、已有 HTML 资产、HyperFrames 不可用时。
- 不作为整片主渲染器。

### 备选：Remotion

- 当需要**复杂 React 舞台、强类型组件、状态驱动动画**时再引入；
- 不在第一阶段同时上两套 renderer；
- 注意 Remotion 的公司授权条款。

### 降级：剪映草稿

- 从“主交付/质检门禁”降为**可选导出**；
- 最终验收以 `output/final-*.mp4` 为准；
- 不再因为“草稿没生成”阻塞成片交付。

## 6. 建议的渲染架构

```text
源素材
  → Python/FFmpeg：探测、ASR、选段、粗剪、音频/字幕
  → editorial timeline + visual plan（typed JSON）
  → HyperFrames composition：HTML/CSS/GSAP，源视频 + 包装层
  → render：MP4 / WebM alpha / MOV
  → FFmpeg：合成、混音、响度、色彩、编码
  → 视觉/音频/技术 QA
  → output/final-*.mp4
  → 可选：OTIO / FCPXML / xmeml / EDL / 剪映草稿
```

分工：

- **Python**：编辑决策、ASR、音频、时间线、QA、编排；
- **FFmpeg**：源素材剪切、合成、混音、响度、最终编码；
- **HyperFrames**：HTML/CSS/GSAP 包装层与整片 composition；
- **Node**：只做渲染，不进入编辑核心。

## 7. 视频质量技术栈

| 层 | 组件 |
| --- | --- |
| 视觉系统 | design tokens、字体、安全区、网格、色彩、动效原语 |
| 包装渲染 | HyperFrames + GSAP + 本地字体/素材 |
| 最终合成 | FFmpeg：overlay、concat、色彩、音频、编码 |
| 音频 | LUFS/true peak、对白优先、BGM ducking、SFX 峰值 |
| 视觉 QA | 代表帧/beat 片段、稳定帧比例、文字可读性、遮挡、安全区、字幕重叠 |
| 技术 QA | 完整解码、黑帧/冻结、时长/fps、A/V sync、码率 |
| 确定性 | 锁 HyperFrames/Chromium/GSAP/字体；本地资产；Docker；manifest 哈希 |
| 回归 | 合成素材 golden、逐帧/SSIM、契约测试 |

## 8. 最小验证（先做 10 秒，不先重写）

1. Node 22 + 固定 HyperFrames 版本，`npx hyperframes doctor` 通过；
2. 一条 10s 竖屏：源视频 + 一个动效卡 + 一个下三分之一 + BGM ducking；
3. 输出透明 WebM/MOV 和完整 MP4 各一份；
4. 看实际编码帧：字体、边缘、alpha、首尾帧、字幕安全区；
5. 同 composition 连续渲染两次，逐帧/哈希对比；
6. 与当前 `render_motion.py` 对比安装增量、渲染耗时、视觉质量；
7. 全过再把 `frames` 步骤切到 HyperFrames，保留 fallback。

## 9. 一句话

**视频优先时，HyperFrames 应该进入主链候选，而不是被归到“不搬的 Node 渲染链”。** 但先用 10 秒 vertical slice 验证质量和成本，再决定是否替换当前 Canvas 渲染；剪映草稿降为可选导出，不再定义项目。
