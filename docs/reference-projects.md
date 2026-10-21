# 参考项目名单

本项目吸收的是方法、schema 和编辑规则；**没有复制**这些仓库的源码、参考视频、字体或配方素材。

| 项目 | 记录 commit | 许可证 | 参考内容 | 实际吸收 | 未搬 |
| --- | --- | --- | --- | --- | --- |
| [yinyichen987-sketch/Edit-Skill](https://github.com/yinyichen987-sketch/Edit-Skill) | `acc7d6f85d802b21edf4059713f924c87fa05f02`（2026-09-14） | 仓库未发现 LICENSE | EDL、镜头表、操作/证据分离、反静默失败、风格规则 | draft-spec / draft-audit、operations、evidence-registry、styles、lessons、自适应切点与节奏分析 | 没有复制其代码/素材；其游戏视频工具链不适用 |
| [cytxnyu/auto-edit-pro](https://github.com/cytxnyu/auto-edit-pro) | `de21108bc7dd3462a26ac2491e81a8f69efd7aa1`（2026-10-11） | MIT | 四道门禁、visual-contract、71 风格/10 结构、72% 静帧/完整 beat 审查、字幕模式、overlay | 包装视觉合同、visual-review、caption modes、package-only、事实/证据边界 | 没有复制其代码/素材；不采用 71 风格全库、Remotion 技术栈 |
| [maomyu/talking-head-motion](https://github.com/maomyu/talking-head-motion) | `abbeea3d59aeb5eac48463fe0d28df03922b1f69`（2026-10-17） | MIT | 30 款固定口播风格、style-lock、单处底部字幕、字体/人物/审片规则 | style-lock、KB-TH-01 自有配方、caption-role、readiness、presenter/typography 规则 | 没有复制 30 款配方/视频/字体；没有搬 Node/HyperFrames 渲染链 |
| [jianying-editor-skill](https://github.com/luoluoluo22/jianying-editor-skill) | `32c56928ded4f9e2c2b80e099dc7abb793d2c30b`（2026-09-11） | MIT | 云端音乐库挖掘、music_id 索引、add_cloud_music 思路 | 扫描/导入/搜索/选曲、URL 刷新、下载为本地 BGM | 没有复制其代码/媒体；616 行 CSV 只导入本机缓存，不进仓库 |
| [Joho6666/video-replicate-studio](https://github.com/Joho6666/video-replicate-studio) | 2026-10-11 快照（main） | MIT | 抓取 → 切镜 → 三联图 → 导演拆解 → ≤15s 分段；证据条与漏检切点 | `reference_intake.py`、`workflow/reference_shots.py`、`workflow/reference_vision.py`：切镜/beat、strip、contact sheet、证据约束的镜头拆解、三态未检查 | 没有复制其 studio/MediaCrawler 代码或素材；不引入 MediaCrawler（NON-COMMERCIAL LEARNING LICENSE + 扫码登录），不用 TikHub/MOSI/MiniMax |
| [emfont/emfont-mcp](https://github.com/emfont/emfont-mcp) | 2026-10-20 快照（main） | Apache-2.0（字体授权另计） | 中文字体目录、字体详情、按文字生成子集字体的 MCP 工具 | `workflow/emfont.py` 直接调用其背后的 `/list` `/info` `/g` HTTP 接口；`workflow/font_picker.py` 的候选与子集下载 | 没有复制其工具代码/文档，不引入 Node/MCP 运行时；每个字体授权逐个记录，不默认可商用 |
| [alchaincyf/huashu-art-motion](https://github.com/alchaincyf/huashu-art-motion) | 上游 commit `9ff59339f934e08483ba0a5b1db20f4c2c421b35`（由 talking-head-motion 声明） | MIT | 艺术插镜/动画语法 | 仅作为上游背景了解，未直接接入 | 没有复制艺术配方/素材 |

## 说明

- **Edit-Skill**：仓库没有 LICENSE；只吸收方法，未复制代码/资源。
- **auto-edit-pro**：MIT；未复制其代码、参考素材或 71 款风格实现。
- **talking-head-motion**：MIT；其 30 款固定风格建立在第三方参考视频上，原视频/字体/工程不随包开源；本项目没有复制这些内容，只做自有 `KB-TH-01`。
- **huashu-art-motion**：是 talking-head-motion 的可选上游艺术分支；本项目未使用其配方或素材。
- **emfont-mcp**：Apache-2.0；本项目复用其公开 HTTP 接口（与 MCP 工具同一套），没有复制代码或字体文件。字体本身的授权以字体详情为准，工具开源不等于字体可商用。
- **video-replicate-studio**：MIT；只吸收「分享页取原片 → 自适应切镜 → 首/中/尾三联图 → 证据约束的导演拆解 → ≤15s 分段」这一层方法，代码为本项目重写；没有复制其 `apps/studio` 的 Node 实现、提示词资产或参考视频。其内置 MediaCrawler 使用 NON-COMMERCIAL LEARNING LICENSE，本项目只实现公开单条作品的分享页解析，不做批量抓取或登录自动化。

## HyperFrames

HyperFrames 不在上表的“吸收”列里，但它是 talking-head-motion 的主渲染器、auto-edit-pro 的可选 legacy adapter。按“高质量成片”定位重新评估见 [HyperFrames 评估](hyperframes-evaluation.md)：当前结论是**composition 层的主链候选**；剪映草稿降为可选导出。

## 本项目

- [redbin1024/koubo-studio](https://github.com/redbin1024/koubo-studio)：当前项目，MIT。
