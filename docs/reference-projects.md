# 参考项目名单

本项目吸收的是方法、schema 和编辑规则；**没有复制**这些仓库的源码、参考视频、字体或配方素材。

| 项目 | 记录 commit | 许可证 | 参考内容 | 实际吸收 | 未搬 |
| --- | --- | --- | --- | --- | --- |
| [yinyichen987-sketch/Edit-Skill](https://github.com/yinyichen987-sketch/Edit-Skill) | `acc7d6f85d802b21edf4059713f924c87fa05f02`（2026-09-14） | 仓库未发现 LICENSE | EDL、镜头表、操作/证据分离、反静默失败、风格规则 | draft-spec / draft-audit、operations、evidence-registry、styles、lessons、自适应切点与节奏分析 | 没有复制其代码/素材；其游戏视频工具链不适用 |
| [cytxnyu/auto-edit-pro](https://github.com/cytxnyu/auto-edit-pro) | `de21108bc7dd3462a26ac2491e81a8f69efd7aa1`（2026-10-11） | MIT | 四道门禁、visual-contract、71 风格/10 结构、72% 静帧/完整 beat 审查、字幕模式、overlay | 包装视觉合同、visual-review、caption modes、package-only、事实/证据边界 | 没有复制其代码/素材；不采用 71 风格全库、Remotion 技术栈 |
| [maomyu/talking-head-motion](https://github.com/maomyu/talking-head-motion) | `abbeea3d59aeb5eac48463fe0d28df03922b1f69`（2026-10-17） | MIT | 30 款固定口播风格、style-lock、单处底部字幕、字体/人物/审片规则 | style-lock、KB-TH-01 自有配方、caption-role、readiness、presenter/typography 规则 | 没有复制 30 款配方/视频/字体；没有搬 Node/HyperFrames 渲染链 |
| [jianying-editor-skill](https://github.com/luoluoluo22/jianying-editor-skill) | `32c56928ded4f9e2c2b80e099dc7abb793d2c30b`（2026-09-11） | MIT | 云端音乐库挖掘、music_id 索引、add_cloud_music 思路 | 扫描/导入/搜索/选曲、URL 刷新、下载为本地 BGM | 没有复制其代码/媒体；616 行 CSV 只导入本机缓存，不进仓库 |
| [alchaincyf/huashu-art-motion](https://github.com/alchaincyf/huashu-art-motion) | 上游 commit `9ff59339f934e08483ba0a5b1db20f4c2c421b35`（由 talking-head-motion 声明） | MIT | 艺术插镜/动画语法 | 仅作为上游背景了解，未直接接入 | 没有复制艺术配方/素材 |

## 说明

- **Edit-Skill**：仓库没有 LICENSE；只吸收方法，未复制代码/资源。
- **auto-edit-pro**：MIT；未复制其代码、参考素材或 71 款风格实现。
- **talking-head-motion**：MIT；其 30 款固定风格建立在第三方参考视频上，原视频/字体/工程不随包开源；本项目没有复制这些内容，只做自有 `KB-TH-01`。
- **huashu-art-motion**：是 talking-head-motion 的可选上游艺术分支；本项目未使用其配方或素材。

## 本项目

- [redbin1024/koubo-studio](https://github.com/redbin1024/koubo-studio)：当前项目，MIT。
