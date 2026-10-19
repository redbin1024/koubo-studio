# Changelog

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
