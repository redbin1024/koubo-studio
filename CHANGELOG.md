# Changelog

## 1.22.0 — 2026-10-21

### 原生草稿：接上剪映真正读的那份

- 新增 `workflow/draft_native.py` + `scripts/draft_native.py` + `scripts/jytool_bridge.py`：
  可选接入 `jianying-tool==0.5.0`，用本机 `libvideoeditor.dylib` / `videoeditor.dll`
  解出剪映保存后的加密 `draft_info.json`；桥跑在独立的 3.10+ 环境
  （`python scripts/draft_native.py setup`，装到 `vendor/jytool-venv`，不动 `.venv`）。
- `draft_audit` 改为审**活动文件**（macOS `draft_info.json` / Windows `draft_content.json`），
  并新增 `draft-twin` 对账；不再只看明文副本。
- `verify` 新增 `draft-file` / `draft-doctor`：交付那份读不了（加密且没装桥）时退回
  工程内明文副本并记 `unchecked`，`draft-doctor` 也记 `unchecked`；`doctor` 新增
  `jianying-tool` 自检。
- `draft_native.py sync` 以**较新的明文**为默认方向（`--from active|twin` 可指定），
  写前备份到 `.koubo-backups/`；时间相同/目标加密时要求确认，不猜。
- 修复：`set_text_font` / `set_text_line_spacing` 之前只写 `draft_content.json`，
  而 macOS 剪映读 `draft_info.json`，会出现「预览对了、剪映打开还是 0.02 行距」。
  现在两份都写，构建收尾再做一次双向对齐。用真实旧草稿验证：活动文件 0.02、
  副本 0.22，`draft-audit` 现在会红；`sync` 一次后两份一致并转绿。
- `koubo native` 别名；新增 [原生草稿适配层](docs/native-backend.md)；新增 21 项原生草稿测试，全量通过。

## 1.21.0 — 2026-10-21

### 素材库：可检索、可调用、授权台账

- 新增 `koubo assets`：`init/scan/add/search/show/path/set-license/verify/export/audit/suggest/stats/seed`。
  索引正本 `assets/library/registry.jsonl`，每个素材带 kind/tags/mood/scene/use_for/
  duration/bpm/sync/许可/来源/哈希；文件旁写 `.asset.json` sidecar。
- 配置可用 `asset:<id>` 稳定引用：`broll.items[].source` 与 `sfx.events[].clip`
  已接入；文件改名/换目录不再改配置。
- 许可目录 `workflow/asset_licenses.py`：CC0/CC-BY/CC-BY-SA/CC-BY-ND/CC-BY-NC/
  OFL/Apache/MIT/BSD/Pixabay/Mixkit/Pexels/剪映云端/项目自有/用户提供等，
  统一判 `pass / unchecked / fail`；授权快照与核对日期让条款变化可被发现。
- 字体许可记录 `fonts/licenses/*.json`：Noto/思源、抖音美好体、得意黑、Monu Titl、
  阿里巴巴普惠体、阿里妈妈、站酷；`font-pick` 候选带 `license_id/license_url/
  license_review_required`，需核对的字体不再静默通过。
- 新增远程源 `workflow/asset_remote.py`：Pexels/Pixabay 单条检索/下载（
  `PEXELS_API_KEY` / `PIXABAY_API_KEY`），sfx-kit CC0 音效按分类导入；
  12 小时缓存、限流、无 Key 明确报错。
- Mixkit 下载、剪映云端 BGM 下载自动写 sidecar；`extract_still` 的静帧改为
  `project-input`（权利随源片）。
- 流水线新增 `asset-audit`（draft 后）：写 `work/asset-manifest.json`，生成
  `output/asset-licenses.csv` 与 `output/CREDITS.md`；`verify` 新增
  `asset-license` 三态，`preflight` 提前报 `asset:` 坏引用，`review-outputs`
  视频门纳入。
- `suggest` 按字幕做可解释的元数据召回（场景同义词 + tags/use_for + 时长 +
  许可），只出建议，不改 config。
- 新增 [素材库文档](docs/asset-library.md)、`assets/library/README.md`、
  `fonts/licenses/README.md`；测试 297 项通过。

## 1.20.3 — 2026-10-21

### 审查可读性

- `review-outputs` 文字门新增 `caption-asr-coverage`：字幕与 ASR 转写做字符级相似度；
  <0.35 红项，0.35–0.60 记为 unchecked，>0.60 通过。新片实测 0.86。
- `koubo preflight` / `koubo cleanup` 增加独立入口。
- 文档补字幕↔ASR 审查与 preflight/cleanup 命令。
- 248 项测试。

## 1.20.2 — 2026-10-21

### 素材与清理

- Mixkit：页面/下载 2 次重试 + 1 小时页面缓存；`review-outputs` 增加 Mixkit 路径/许可检查。
- `extract_still --scan` 增加人脸权重；优先选有正脸、清晰、亮度合格的静帧。
- 新增 `cleanup_workspace.py`：默认 dry-run，`--apply-cache` 只删可再生的
  `work/auto-edit-pro` 与 `__pycache__`，不动模型/项目/成片。
- 实测清理 `work/auto-edit-pro` 约 698M；清单写 `work/cleanup-inventory.md`。
- 文档补 Mixkit 重试/许可与清理清单。
- 247 项测试。

## 1.20.1 — 2026-10-21

### 健壮性与收口

- `draft-font` 不再假 pass：字段已写入但 JianYing 11.6 加密，改为 `unchecked`。
- `run_all` 所有异常都写失败现场包，不再只捕获 `SystemExit`。
- 新增 `preflight`：卡片/插图/B-roll/转场/BGM 长度在 frames 前报错。
- `claims.allow`：既有品牌 CTA 可人工列入白名单，但结果是 `unchecked`，不是通过。
- 删除一次性 `render_caption_overlays.py`。
- README/架构/模块文档补 `beats`、`preflight`、`review-outputs`，测试数改 247。
- 新增 grounding allowlist 测试。

## 1.20.0 — 2026-10-21

### 插画/视觉与音频收口

- 插画分三层：真实静帧（still）/ SVG 概念图（vector）/ 可选 AI 位图；
  80px 小图窗不再塞 SVG。
- 新增 `extract_still.py`：从 `clean-cut.mp4` 抽真实静帧，写 `assets/stills/manifest.json`。
- `illustration_focus` 支持图窗焦点裁切；4105 CTA、接送两条信息条改用真实静帧。
- 4105 叠卡延长到 12.63–24.30，三行分别 12.95/16.75/19.45；
  `captions.skip [5,6,7]`，叠卡期间不放底部字幕。
- 混音从“BGM 压人声”改为“人声优先”：voice_volume 2.2、BGM 0.12/0.10、
  目标 -13 LUFS；4105 实测 -13.0 LUFS / -2.0 dBTP。
- 新增 `draft-font` 质检；JianYing 11.6 加密草稿仍无法稳定注入字体，
  成片字体正常，草稿保留默认字体（限制已记录）。
- 新增 [工作流与模块地图](docs/modules.md)。
- 测试 239 项通过。

## 1.19.0 — 2026-10-20

### 按参考片自动选字体

- 新增 `font_pick.py` / `koubo font-pick`：读 `reference-profile.json` 的风格、结构、
  受众与字幕文案，从**本机 CJK 字体 + emfont 在线库**里选一款字幕字体。
- 本机字体按渲染顺序扫描（工程 `fonts/` → 安装目录 → `KOUBO_FONT_DIRS` → 系统），
  只收带汉字的字体，同族保留最粗字重；候选带授权文本。
- emfont 复用 [emfont-mcp](https://github.com/emfont/emfont-mcp) 背后的
  `/list` `/info` `/g` HTTP 接口，不引入 Node/MCP；目录/详情有缓存，
  接口不可用时 `auto` 回退本机字体并记入「未检查」。
- AI 只从候选闭集里选，校验 id / confidence / usage / alternates；无 Key、
  调用失败或输出不合格时回退本地风格打分，`mode=ai|fallback` 写清楚。
- `--apply` 写 `config.captions.font`；项目有 `work/style-lock.json` 时默认拒绝，
  `--force` 才写并标记 `style_lock_conflict`（`koubo style check` 会红）。
- emfont 字体按工程字幕/口播/卡片文字生成子集 TTF，存 `fonts/emfont-<id>.ttf`；
  应用前用 PIL 检查字幕缺字，缺字就换备选。
- `koubo reference ... --pick-font`：拆完顺手出字体建议（不写 config）。
- 新增 `workflow/emfont.py`、`workflow/font_picker.py`、`docs/font-picker.md`、
  2 个测试文件；测试总数 **239**。

## 1.18.0 — 2026-10-20

### 抖音参考片入库与拆解

- 新增 `reference_intake.py` / `koubo reference`：抖音分享链接或本地视频 →
  原片、节奏、三联图、接触表、口播转写、全片结构与 `REPORT.md`。
- 抖音来源走分享页 SSR：首次请求拿 `ttwid`，带 Cookie 自动重试一次；
  失败回退 `yt-dlp`（可选），再失败明确报错。不引入 MediaCrawler
  （NON-COMMERCIAL LEARNING LICENSE + 扫码登录），不登录、不批量。
- 切镜复用 `workflow.pacing` 的自适应切点，并用固定阈值补漏；长镜头拆成
  ≤5s beat，镜头过多时合并最短邻居，按镜头边界分 ≤15s 段。
- 每镜抽首/中/尾三联图与中点关键帧，Pillow 拼 `contact-sheet.jpg`。
- 新增 `workflow/reference_vision.py`：DeepSeek 视觉拆解，结论必须引用三联图证据；
  枚举 / 镜头 id / 置信度由代码校验，失败只影响该批并记 `unchecked`。
- 报告三态：没装 faster-whisper、没有 Key、某批拆解失败、字体量不了、
  音乐没识别、字幕 `margin_v` 未重算，都逐条写进「未检查」。
- `new_project.py` / `auto_film.py` 的 `--reference` 接受本地文件、抖音链接或
  `koubo reference` 产出目录；传目录直接复用 `teardown.json`，不重复抽帧。
- 修复 `analyze_reference.scene_cuts` 的切点时间与分数错位一刀的 bug。
- 满屏色块不再当成信息卡写进 `config.card`（面积 >55% 时剔除并写明）。
- 新增 4 个测试文件（来源解析、切镜/接触表、视觉校验、档案汇总与端到端）；
  测试总数 **213**。

## 1.17.1 — 2026-10-20

### d08 参考版：叠卡

- 按 style-match 的 top1 `TH-DY-08` 做一版 4105：
  - 玻璃卡后方加两层错位暗玻璃，形成 d08 的“叠卡”深度；
  - 保留云端配乐、editorial 插图、无片头标题。
- 草稿：**`4105-全功能版-d08参考版`**
- 草稿审计 19/0/0；QC **36/0/6**（`bgm-cloud` pass）
- `KB-TH-01` → v1.2.3
- 176 项测试通过。

### 边界

这是 d08 的 **叠卡参考**，不是三张独立内容卡的完整重排；真正的三卡结构需要另做卡片布局。

## 1.17.0 — 2026-10-20

### 按内容匹配参考风格

- `style_match.py`：读字幕/镜头表/已有版式，给 talking-head-motion 的 30 款风格打分。
- 输出 top 5：`id/name/readiness/grammar/engine/score/fit/risk/action`。
- 内容信号：步骤/清单、细节、数字、对比、情绪、钩子、品牌词；
- 画面信号：镜头密度、已有 card skin、已有插图数；
- readiness 与引擎能力参与排序；已有玻璃卡时 d08 加权。
- 结果只是 **adaptation brief**，不是自动 1:1 复刻；外部 catalog/recipes 只读，不复制素材。
- 4105 实测 top：d08 / d14 / d06 / d19 / d02；接送 top：d02 / d19 / d01 / d11 / d22。
- 新增 style_match 测试；测试总数 **176**。

## 1.16.1 — 2026-10-20

### 云端音乐实测 + URL 刷新

- `pick` 先试 CSV/草稿 URL；过期/403/SSL 时调用剪映 item 接口刷新一次。
- 下载后自动去掉开头静音，再循环/裁到片长，修复 BGM 开头空导致
  `long-silence` 红项。
- 用 `7378223391197399051`《感人温暖叙事 Where We Belong》重出 4105：
  - 草稿 **`4105-全功能版-云端配乐版`**
  - 草稿审计 19/0/0
  - QC **36/0/6**（`bgm-cloud` pass；6 = 无旁白 4 + gold-slot 1 + visual-review 1）
- 参考项目名单补 `jianying-editor-skill`（MIT）；616 行 CSV 只进本机缓存。
- 175 项测试通过。

## 1.16.0 — 2026-10-20

### 剪映云端音乐库

- `music_library.py`：扫描剪映草稿/历史快照里的 `type=music` + 数字 `music_id`，
  缓存 `~/.cache/koubo/music-library.json`。
- 支持导入外部 `music_id,title,duration_s,categories,url` CSV；本次导入 616 行，
  去重 615 首（缓存，不进仓库）。
- `koubo music scan / import / search / pick`。
- `pick` 下载到 `work/cloud-music/`，循环/裁成 `work/bgm.wav`，写
  `work/music-selection.json`，更新 `audio.bgm.source=jianying-cloud/music_id/title`。
- `run_all` 的 `music` 步优先使用云端曲库；`verify` 新增 `bgm-cloud`。
- 没有 CDN URL 时明确报错，不伪造“云端音乐已加载”。
- **配音音色**：`audio.narration_voice` 可指定 edge-tts 音色，缓存键包含音色。
- 新增 music_library / 音色缓存测试；测试总数 **175**。

### 实测

- 本机扫描 1746 个草稿/快照文件，云端音乐 ID **0 条**（现有 BGM 都是本地 `bgm.wav`）。
- 从参考 skill CSV 导入 615 首后，`search 温暖` / `search 企业` 能返回曲目。
- 未改动 4105/接送的现有 BGM；选曲需要用户确认。

## 1.15.1 — 2026-10-20

### 6 张插图全部接入

- 4105 玻璃卡三行分别接 `food-tray` / `quiet-room` / `tea-set` 小图窗；
  末尾 CTA 接 `doorway`。
- 接送「有人扶稳」接 `car-seat`，「送到床边」接 `crib`。
- 共 **6 张自有 SVG 插图**实际进入 4105/接送成片；`care-hands` 保留为未用草图。
- `render_illustrations` 现在也收集 `card.rows[].illustration`。
- 4105 新草稿：**`4105-全功能版-插画定稿`**；草稿 19/0/0，QC 35/0/6。
- 接送：`接送_品牌版_v2`；草稿 18/0/2，QC 33/0/8。
- 172 项测试通过。

## 1.15.0 — 2026-10-20

### SVG / Canvas 绘图进入工作流

- **SVG 插图源**：`assets/illustrations/*.svg`，800×1000，暖纸/金线/纸纹，无文字。
- `scripts/render_illustrations.py`：按 config 引用自动把 SVG 渲染到
  `PROJECT/assets/illustrations/*.png`，按 SVG SHA 缓存，写 `work/illustrations.json`。
- `run_all` 的 `assets` 步自动执行；`make_assets` 支持插图卡左侧图窗。
- 项目已接入：
  - 4105 CTA → `doorway.png`
  - 接送「有人扶稳」→ `car-seat.png`
  - 接送「送到床边」→ `crib.png`
- 资产库还包含 `food-tray`、`quiet-room`、`tea-set`、`care-hands` 源文件。
- **Canvas/HTML 动效**：`scripts/render_motion.py` 按 `window.renderAt(t)` 逐帧截图，
  输出 ProRes 4444 + alpha；示例 `assets/motion/steam.html`。
- `koubo svg / illustrations / motion` 命令；文档 [SVG/Canvas](docs/code-illustration.md)、
  [动效](docs/motion.md)。
- 新增 `render_illustrations` 测试；测试总数 **172**。
- 4105 插画终版：草稿 19/0/0，QC 35/0/6；接送 v2：草稿 18/0/2，QC 33/0/8。

### 边界

- SVG 是代码绘制，不是 AI 位图；照片级/写实人物仍不能用它替代。
- 动效只适合 1–2 个 overlay hero moment；尚未自动写入 draft 轨，需实测剪映对 ProRes alpha 的导入。
- 画面里的文字仍由 Pillow/剪映排，SVG 不画文字。

## 1.14.0 — 2026-10-20

### 插图重做：editorial 细线体系

参考 talking-head-motion 的固定风格方法，重做我们自己的插图，不复制其素材/配方。

- **信息条/CTA**：暖纸底、发丝边、顶部金色标记、`LABEL · 01`、Songti 标题、
  常规字重正文、细线图标 + 发丝圆环。
- **玻璃卡图标**：🍱/🌿/🏠 emoji 换成 bowl/leaf/home 细线图标；卡标题改用 Songti。
- **卡片行距**：主标题上移、副标题下移，解决“每一份 准时送到”贴字。
- 4105 重出 **`4105-全功能版-插画版`**；接送重出 **`接送_品牌版_v2`**。
- `KB-TH-01` → **v1.2.2**；`KB-TH-02` → **v1.0.1**。
- 4105：草稿审计 19/0/0；QC 35/0/6。
- 接送：草稿审计 18/0/2；QC 33/0/8；caption-role 通过。
- 171 项测试通过。

### 边界

插图为本项目几何绘制，不是 talking-head-motion 的 30 款配方复刻；参考视频/字体/素材未搬。

## 1.13.0 — 2026-10-19

### 接送素材包 · 品牌版

- 基于 `接送-推广版` 的 30s / 23 镜头结构，生成 **`接送-品牌版`**：
  - 字幕描边 9→8、阴影 6→4；
  - 新增暖食滤镜、口号扫描光条、发光字落位关键帧；
  - 保留原旁白、6 条字幕、2 条信息条、金色口号。
- 新增固定风格 **`KB-TH-02` 接送纪实 v1.0.0**，style-lock 已绑定。
- 草稿：**`接送_品牌版_v1`**；草稿审计 18/0/2；QC 33/0/8。
- 修复 B-roll resolver 与 visual-contract 的初始化顺序（`broll_plans` 未定义）。
- 文档 [参考项目名单](docs/reference-projects.md)、B-roll 文档/拍摄清单。
- 171 项测试通过。

## 1.12.0 — 2026-10-19

### 新增

- **B-roll 槽位**：真实细节镜头按 `cue/keyword` 插到剪映 `B-roll` 轨，
  主轨之上、包装层之下；支持 `source/in/dur/volume`，默认静音。
- `broll` resolver 校验：cue 存在、keyword 真在字幕里、时窗在字幕范围内、素材存在。
- B-roll 进入 `visual-contract`（`kind=broll`，`requires-capcut-export`）。
- 文档：[B-roll](docs/broll.md)、[4105 拍摄清单](docs/broll-shotlist-4105.md)、
  [参考项目名单](docs/reference-projects.md)。
- 新增 broll 测试；测试总数 **171**。

### 说明

B-roll 只进剪映草稿，ffmpeg mp4 预览暂不包含；最终以剪映导出为准。
没有真实素材时不启用、不伪造画面。

## 1.11.0 — 2026-10-19

### P0：排版/声音/卡片落位

- 字幕描边 **10 → 8**、阴影 **6 → 4**，减少“综艺花字”感，保留可读性。
- 卡片增加 **包装层落位关键帧**（scale 1.03 → 1.0），
  `verify` 新增 `overlay-fx`。
- 卡片三行出现时增加 **row 软音效**（12.95/13.85/14.75s），
  替代全片只有 whoosh 的单层声音。
- 保留：末尾预约 CTA、扫描光条、推近/擦除转场、镜头 3/6 推拉。
- `KB-TH-01` → **v1.2.0**；style-lock 重新绑定。
- 草稿审计 **19/0/0**；QC **35/0/6**（6 = 无旁白 4 + gold-slot 1 + visual-review 1）。
- 新增 overlay_fx 测试；测试总数 **169**。

### 说明

这一版是 CapCut 原生 P0，不是换引擎。B-roll/实拍细节仍缺；没有新素材，画面丰富度到此为止。

## 1.10.1 — 2026-10-19

### 修正

- **关闭开头品牌字“多萌十月”**：它在剪映里与第一条字幕重叠。品牌信息保留在末尾 CTA。
- 草稿改名为 **`4105-全功能版-无片头标题`**，旧 `-高级` 保留（已被剪映打开，不覆盖）。
- 视觉合同 **16 beat**：2 个可看（卡/预约 CTA），14 个需剪映导出。
- QC **34 过 / 0 红 / 6 没查**：6 = 无旁白 4 + gold-slot 未启用 1 + visual-review 1。
- 草稿审计仍 **19/0/0**。
- `KB-TH-01` → **v1.1.2**；style-lock 重新绑定。

## 1.10.0 — 2026-10-19

### 新增 / 调优

- 4105 新增 **末尾独立 CTA 插图**“预约参观 / 多萌十月”，不是复述字幕；`caption-role` 通过。
- 卡片增加剪映原生 **扫描光条** 效果；转场从全叠化改为 **推近 / 叠化 / 擦除**。
- 镜头 3/6 增加缓慢推拉关键帧，和镜头 1/8 形成前后呼吸。
- 视觉合同 **17 beat**：3 个可看（卡/品牌字/CTA），14 个需剪映导出（3 贴纸 + 7 原生 + 4 高级）。
- `KB-TH-01` → **v1.1.1**；style-lock 重新绑定。
- 草稿审计 **19/0/0**；QC **35/0/5**（5 = 4 项无旁白 + visual-review）。
- 167 项测试通过。

### 边界

- 扫描光条、转场、关键帧只进剪映草稿；mp4 预览不含。
- CTA 文案“预约参观 / 多萌十月”来自现有品牌信息，没有新增未经确认的服务承诺。

## 1.9.1 — 2026-10-19

### 修正

- **删除 4105 的 3 张复述字幕插图**（`放心 / 我们一直都在 / 恢复状态 / 让宝宝安心成长 / 月子中心`）。
  没有 owner 确认的独立标签可替换，选择删除而不是编造事实。
- `caption-role` 从 5 处 warning 变为 **pass**。
- 视觉合同从 16 beat 降到 **13 beat**（2 可看 + 11 需剪映导出）。
- `KB-TH-01` 升到 **v1.0.1**，readiness 更新；style-lock 重新绑定。
- 当前 QC **31 过 / 0 红 / 9 没查**：9 = 插图未启用 4 + 无旁白 4 + visual-review 1。
- 草稿审计仍 **19/0/0**。

## 1.9.0 — 2026-10-19

吸收 talking-head-motion 的固定风格与“单处底部字幕”约束。

### 新增

- **固定风格 `KB-TH-01` 暖食玻璃卡 v1.0.0**：`references/styles/catalog.json` + recipe；
  只含风格参数，不含文案/时间/素材；`readiness` 明确写到视觉审查仍 pending。
- **`style-lock.json`**：`koubo style bind/check`；完整配方快照 + 哈希 + 选择来源；
  `verify` 新增 `style-lock`，配置风格参数漂移但没升版本会红。
- **`caption-role` 字幕角色检查**：卡片/插图/品牌字逐条与当前底部字幕比对；
  完全重复/同义复述记为 warning；`captions.duplicate_policy=warn|fail` 控制是否红项。
- 4105 实际发现 **5 处插图复述底部字幕**；当前策略 warn，QC 34/0/6；没有静默通过。
- 新增 style-lock / caption-role 测试；测试总数 167。

### 已知边界

- `caption-role` 是文本相似度 + 人工判断，不是语义理解；品牌名/结构标签是否算独立信息仍需人看。
- 当前只有一款真实风格；不复制 30 款参考库。
- style-lock 只保证风格参数不漂移，不保证审美通过。

## 1.8.0 — 2026-10-19

### 新增

- **`shot_fx` 高级片段操作（只进草稿）**：
  - 关键帧：位置/缩放/旋转/透明度/音量，时间相对镜头起点；
  - 蒙版：linear/mirror/circle/rectangle/heart/star；
  - 混合模式、背景模糊 1–4、透明度、逐段滤镜；
  - `duplicate=true` 复制上层，把蒙版/混合模式作用在副本，原主轨保留。
- `workflow/advanced_fx.py`：先校验 shot/属性/时间窗，再执行；关键帧/蒙版/混合模式/滤镜失败会直接报错，不再静默。
- `draft-spec.advanced` 登记高级操作；`verify` 新增 `advanced-fx`。
- 视觉合同把 advanced 操作标为 `requires-capcut-export`，审查包 16 beat / 11 需剪映导出。
- 全功能版新增镜头 1/8 推拉关键帧；草稿审计 19/0/0，QC 33/0/5。
- 新增 advanced_fx 测试；测试总数 163。

### 已知边界

- 高级操作只进剪映草稿；mp4 预览不含关键帧/蒙版/混合模式/逐段滤镜。
- `duplicate` 副本默认静音，避免声音叠两遍；混合模式需要有下层内容才有意义。
- 逐段滤镜是时间窗滤镜轨，不是严格绑定到某个 segment 的局部滤镜。

## 1.7.0 — 2026-10-19

### 新增

- **`scripts/analyze_pacing.py` + `workflow/pacing.py`**：自适应 scene score（中位数 + MAD，
  非极大抑制）、镜头数/切点密度/平均/中位/最短/最长镜长、VFR 诊断、容器 vs 视频流时长、
  LUFS/真峰。给 `references/styles/` 的量化锚点提供可复现来源。
- Vlog 的 `auto_edit.scene_cuts` 改用自适应切点，不再固定 `scene>0.35`。
- 文档 `docs/pacing.md`；风格模板增加分析命令。
- 新增 pacing 测试；测试总数 161。

### 已知限制

- 同背景跳切（口播换句、人物不动）scene score 很低，分析器可能识别不到；需要 SRT/ASR 停顿或人工确认。

## 1.6.0 — 2026-10-19

### 新增

- **`koubo package` / `package_video.py`：package-only 模式**。输入已经剪好的成片 + SRT，
  不调用 `auto_edit` / `merge_cut`，不重排镜头、不改原声；只做字幕/包装/BGM/草稿/质检。
- `--prepare-only`：只建工程/config 与 SRT，方便先配包装再跑。
- `--captions generated|burned-in|none`：沿用字幕模式，源片已有字幕不重复叠。
- 默认开启暖调 BGM（0.30）填原片静音；原声 `speech_mode=source` 保留。
- 复用了 visual-contract / packaging-review / draft-audit；启用包装后自动生成。
- 新增 package-only 测试；测试总数 159。

### 说明

- package-only 的主轨是**一条原成片**，不拆镜头；要逐镜头剪走 `auto` 或手动 `merge`。
- 卡片/插图/贴纸默认关闭，需在 config 里配置；不会自动编造品牌文案。

## 1.5.0 — 2026-10-19

吸收 auto-edit-pro 的包装层方法：视觉合同、72% 静帧/完整 beat 审查、字幕模式与证据边界。

### 新增

- **`work/visual-contract.json`**：每个卡片/插图/贴纸/原生资源写语义结构、
  可见区域、稳定阅读窗口、动效机制、`claim_status` 和证据边界；`sourced` 必须有依据。
- **`work/packaging-review.json` + 视觉审查包**：每个可看 beat 抽 72% 静帧、截完整 beat 片段、
  生成联系表；原生特效/滤镜/转场和草稿专属贴纸标 `requires-capcut-export`，
  不拿 mp4 底层画面冒充证据。
- **`verify.py` 新增 `visual-contract` / `visual-review`**：合同违规红项；审查包 pending 记 unchecked，
  只有人工逐 beat 观看并改 pass 才通过。
- **`captions.mode`**：`generated` / `burned-in` / `none`；`koubo auto --captions` 可指定。
  `burned-in/none` 时不重复生成画面字幕，草稿也不建字幕轨。
- `koubo visual-review PROJECT` 生成视觉审查包。
- 草稿规格/审计、视觉合同、能力矩阵、证据登记、经验日志形成闭环。
- 新增视觉合同正例/反例、burned-in 字幕测试；测试总数 158。

### 变更

- 质检从 35 项扩到 37 项。
- `4105-全功能版-定稿`：草稿审计 19/0/0；QC 32/0/5（visual-review 待人工观看）。

## 1.4.0 — 2026-10-19

### 新增

- **`work/draft-spec.json`**：草稿决策规格，统一记录主轨/包装/贴纸/人声/音效/BGM/字幕/原生资源/QA；
  每个镜头带 `role / rule_id / reason`，时间统一用秒。
- **`workflow/draft_audit.py` + `work/draft-qc.json`**：执行后和规格对账；检查主轨段数与计划镜头数、
  时长/结尾/间隙、人声/音效/BGM、字幕条数/时间重叠/行距、贴纸/特效/滤镜/转场数量、素材路径、安装状态。
- **`verify.py` 新增 `draft-audit` 红项**：草稿审计失败会进入三态质检，不再只检查 mp4 元数据。
- **能力矩阵 `references/operations.md`**：自动 / 只进草稿 / 人工 / 不可读四类，明确导出、关键帧、
  蒙版、跟踪、抠像、降噪、原生贴纸库等必须人工或暂不支持。
- **证据登记 `references/evidence-registry.md`**：L1–L4；`暖食/光晕/叠化/0.22 行距` 等先标 L3/L4，
  不再把“API 接受”当成“效果正确”。
- **风格模板 `references/styles/`、经验日志 `docs/lessons.md`、`docs/draft-spec.md`**。
- 草稿审计正例 + 反例测试（缺人声、0.02 行距必须报红）；测试总数 154。

### 变更

- 质检从 34 项扩到 35 项。
- `make_jianying_draft` 在写草稿前生成 spec，写完后自动审计；旧工程没有 spec 时 `draft-audit` 记 `unchecked`，不伪造通过。

## 1.3.0 — 2026-10-19

这一版按反馈把草稿的「可看性」拆开修：字幕行距、插图字距、音效、贴纸、特效、转场、滤镜。

### 新增

- **草稿贴纸层**：`stickers` 配置生成全画布透明 PNG，由 `make_jianying_draft` 加到独立「贴纸」轨；
  只进草稿，不烘进 mp4。
- **剪映原生特效**：`jianying_fx.effects` 支持 `光晕` 等资源，报告里逐项对账。
- **更多原生转场**：全功能版 4 处「叠化」，挂在主轨切点。
- **滤镜更换**：`日系奶油` → `暖食`，更贴合月子餐/暖调口播。
- `jianying.line_spacing` 可配置，默认 0.22。

### 修复

- 草稿字幕行距：`import-srt` 默认 `line_spacing=0.02`，双行字幕在剪映里会叠字；
  现在装配完直接写 `line_spacing=0.22`（项目内和草稿箱两份都写）。
- 插图字距：editorial 插图的标题/正文基线间距从 1.28× 提到 1.58×，不再挤在一起。
- 自动音效：去掉 `impact-bass-2` / `hook` 低频鼓点，默认只用轻 whoosh / ping / chime，
  音量上限 0.55；不会再在每次切点砸一记低鼓。
- `pip.enabled=false` 时卡片不再偷偷画 PiP（上一版 1.2.4 已修，这里保留回归测试）。
- 新增 2 项测试；测试总数 152。

## 1.2.4 — 2026-10-19

### 修复

- `pip.enabled = false` 时卡片里仍会绘制画中画：`compose_card` 之前没有判断开关，
  只要 `pip.at` 落在卡段内就会把 PiP 叠上去，甚至压住卡片标题。现在开关为 false
  或 `dur <= 0` 时完全不画。
- 全功能版实剪：卡片 / 发光字 / 3 条插图 / 日系奶油滤镜 / 两处叠化转场 / BGM / 音效 /
  逐镜头主轨，质检 30 过 / 0 红 / 4 没查。

## 1.2.3 — 2026-10-19

### 变更

- **工作流侧重点改为剪映草稿**：剪映草稿是主交付，mp4 降为预览 / 快速发布副本。
- 草稿主轨从「通常一整段」改为**逐镜头帧对齐分段**：粗剪 plan 42.761s 渲出来 42.900s
  时不再退回单段，而是按 30fps 对齐到 8 段，逐镜头可 trim / 排序 / 加转场 / 滤镜 / 关键帧。
- 新增 [docs/draft-first.md](docs/draft-first.md)：草稿里能改什么、哪些仍烘焙在 `graded.mp4`、
  为什么暂不直接挂原始素材。
- 新增主轨帧对齐测试；测试总数 150。

## 1.2.2 — 2026-10-19

### 修复

- 剪映草稿人声轨：从 AAC 源抽出的 WAV 常比视频短 20–40ms，`capcut add-audio` 会拒绝
  「请求时长 > 源时长」；旧代码用 `check=False` 把这个错误静默吞掉，结果是草稿里
  只有 BGM / 音效、没有人声，但日志仍打印“人声 + 音效 + BGM”。
- 现在人声 / 音效 / 旁白 / BGM 一律按源文件实际时长夹取，并强制检查 `add-audio`；
  失败会直接报错，不再产出“看起来有、实际没有”的草稿。
- 新增人声上轨时长回归测试；测试总数 149。

## 1.2.1 — 2026-10-19

### 修复

- 全自动口播切点增加 `lead` / `tail`，避免静音检测把第一个字的前 0.2–0.7s 判成静音，
  导致成片从「人问我」开始而不是「很多人问我」。
- 自动口播把短停顿并成完整句，减少「华/丽」「送/到」「打/咬」这类跨镜头断词。
- 新增切点回归测试；测试总数 148。

## 1.2.0 — 2026-10-19

**在 DeepSeek / Agent 窗口里直接用，不填 API Key**：新增宿主导演模式。

### 新增

- `koubo auto --prepare`：生成候选镜头、ASR 转录、Vlog 代表帧与 `work/host-director-request.json` / `host-director-prompt.md`。
- `koubo auto --resume`：读取 `work/host-director-decision.json` 继续出片；决策仍走与云端模型相同的校验。
- 当前窗口的 DeepSeek / Agent 可以直接读请求、写 decision，用会话自身的推理完成选段/排序/旁白，不需要 `DEEPSEEK_API_KEY`。
- `--decision PATH` 可指定宿主 decision 文件位置。
- 响度二次校准增加动态 loudnorm / 压缩 / volume+limiter 回退，旁白 + BGM 的短素材不再因真峰限制卡死。
- 新增宿主导演校验测试；测试总数 147。

### 边界

- 宿主模式需要 Agent 能读本地文件；Vlog 需要能看图（`work/host-frames/`）。
- 宿主写出的 decision 仍受覆盖率、关键词、旁白长度、镜头锚点等校验；不合格会拒绝继续。
- 这不是“脚本借用聊天窗口登录”：脚本本身不会调用 DeepSeek；推理由当前窗口的模型完成。

## 1.1.0 — 2026-10-17

**全自动成片**：新增 `koubo auto`，一条命令从原始素材出 mp4 + 剪映草稿。

### 新增

- `scripts/auto_film.py`（`koubo auto`）：建工程 → 候选镜头 → 导演决策 → 粗剪 → 字幕 → 原声/旁白 → BGM/音效 → 渲染 → 草稿 → 质检 → 自动修复。
- `workflow/auto_director.py`：口播选段/排序/关键词高亮/音乐情绪；Vlog 复用视觉分析与故事方案。模型输出全部过校验，失败回退本地规则。
- `workflow/auto_voice.py`：无声素材自动旁白（edge-tts），逐句时窗、旁白字幕与 `voice-cues.json`；装不下跳过而不是截断。
- `run_all.py --auto`：跳过人工听审门禁，`pipeline.json` 记为 `automated`；需要复核仍可单独跑 `export_voice_review.py`。
- 自动质检修复循环：BGM 填静音、字幕标点/重叠、插图/卡片关闭、响度目标调整、草稿/渲染重试等。
- 空画面字幕支持：只有旁白字幕的 Vlog 也能生成合法空 ASS，草稿跳过空的字幕轨。
- 响度二次校准回退：`normalize_final_audio` 在带 offset 的线性校准不达标时，自动尝试无 offset 与确定性 volume+limiter。
- 安装器默认安装 `faster-whisper`（`--no-whisper` / `--minimal` 可跳过），为全自动口播路径准备 ASR。
- 新测试：导演校验与回退、自动旁白、自动修复、空字幕；测试总数 145。

### 变更

- `faster-whisper` 从“可选”变为推荐能力；模型仍首次运行时下载，默认 `small`，可用 `--asr-model large-v3`。
- README 增加全自动入口与能力边界；新增 [docs/auto.md](docs/auto.md)。

### 已知限制

- 口播自动选段依赖 ASR 质量；Vlog 的旁白与故事线依赖 DeepSeek API，缺 Key 时回退本地保序 + BGM。
- 自动模式默认不做信息卡/画中画/插图（这些需要内容支撑）；参考片只取字幕几何与配色。
- 质检仍是三态：自动修复只覆盖常见红项，`unchecked` 项仍会留在报告里。

## 1.0.0 — 2026-10-17

首个公开发布版本，项目由 `talking-head-style-pack` 更名为 **口播工坊 / Koubo Studio**。

### 新增

- 一键安装器 `install.sh`：安装目录、venv、字体、capcut-cli、Agent skill 软链接与环境自检。
- `koubo` CLI：`new` / `run` / `doctor` / `auto-edit` / `draft` / `verify` 等脚本别名。
- `scripts/doctor.py`：python、ffmpeg、字体、剪映草稿箱、可选模型逐项自检。
- `KOUBO_*` 环境变量；旧 `THSP_*` 继续兼容。
- 安装目录 `fonts/` 作为字体查找路径，一键安装的字体不必写进系统字体目录。
- 公开文档：安装、使用、架构、capcut-cli 笔记与贡献指南。

### 变更

- 项目名、Skill 名、Agent 元数据统一为 Koubo Studio。
- `.gitignore` 排除本地剪辑工程、素材、成片、剪映草稿与内部草稿。
- 示例与文档脱敏；移除对本地样片工程的依赖。
- `check_measured.py` 的基准配置改为仓库内 `examples/baseline/config.json`。

### 保留

- 参考片量化、自动粗剪、字幕/包装、旁白/BGM/音效、剪映草稿、三态质检等既有能力。
- 128 项回归测试。

### 已知限制

- 仍不是语义理解的全自动剪辑，镜头、文案、旁白与最终听审需要人。
- 剪映原生特效只进草稿，不进 mp4。
- 剪映草稿箱与 `say` 旁白以 macOS 为主；Linux 部分支持，Windows 需自行验证。
