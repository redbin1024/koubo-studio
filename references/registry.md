# 正本登记表

**一条规矩只允许有一个正本。** 别处出现同一件事时写「见正本 X」，不要抄数值、不要抄名单 ——
抄一份就是给自己埋一个会漂的副本。

这张表是**唯一的登记处**：新立一条跨文件的规矩，就在这儿加一行；改正本时照着「同步」一列
把副本一起改掉。

## 规矩 → 正本 → 副本

| 规矩 / 常量 | **正本**（改这里） | 副本（改完要同步，或只写指针） |
|---|---|---|
| **两条房规**（去标点 / 不做封面片尾卡常驻标题） | `scripts/_common.py` 的 `HOUSE_RULES` | `SKILL.md` 房规一节 · `references/config-schema.md` 的 `constraints` 块（两个都是**说明**，不是定义） |
| **标点字符表** | `scripts/_common.py` 的 `PUNCT_CHARS` | `scripts/verify.py` **直接 import**（曾经各写一份，已漂移：20 vs 43 字符） |
| **字幕行高 / 字身下沿系数** | `scripts/caption_layer.py` 的 `LINE_PITCH` / `DESCENT_EM` | `references/lessons.md` #22（讲来历，不写数值承诺） |
| **交付响度基准** | `scripts/_common.py` 的 `audio.loudness` 默认值 | `references/config-schema.md` 的 `audio.loudness` 注释 |
| **默认画布** | `scripts/_common.py` 的 `canvas` 默认值 | `scripts/new_project.py` 的 `--aspect` 分支 · `references/config-schema.md` |
| **中文字体候选**（兜底名单） | `scripts/_common.py` 的 `CJK_FONT_CANDIDATES` | 无。字体该走 `captions.font` + `list_fonts.py`，别抄这份名单 |
| **实测常量的值与出处** | `references/measured.json` | `scripts/check_measured.py` 校验、`scripts/recalibrate.py` 重量；`SKILL.md` 只写用法不写数值 |
| **语速折算口径** | `references/speech-rate.md`（方法）+ `references/speech-rate.json`（数值） | `SKILL.md` 写旁白一节（只写公式，不写数值） |
| **参考片拆解字段的含义** | `references/reference-teardown.md` | `analyze_reference.py` 输出里的 `note` 字段（各说各的那一条） |
| **音效 cue 表** | `scripts/make_sfx.py` 的 `CUES` | `references/style-recipes.md` 的 cue 表（**这是副本**，改 `CUES` 要同步） |
| **本轮成片凭据的输入集合** | `scripts/workflow/delivery.py` 的 `_fingerprint` | `render.py` 写入、`verify.py` 读取同一实现；`docs/architecture.md` 的「交付凭据」只说明行为 |
| **草稿属于哪次渲染** | `scripts/workflow/delivery.py` 的 `receipt_digest` / `draft_matches_receipt` | `make_jianying_draft.py` 写入报告、`verify.py` 校验同一摘要 |
| **字幕同帧重叠判定** | `scripts/workflow/caption_timing.py` 的 `overlap_status` | `make_captions.py`、`speech_policy.py` 预检，`verify.py` 复查同一实现 |
| **旁白镜头锚点判定** | `scripts/workflow/speech_policy.py` 的 `_check_shot_anchors` | `story_audio.py` 与 `rebuild_sample.py` 写逐句证据；`export_voice_review.py` 给人工审查映射 |
| **逐句人工验收及失效规则** | `scripts/workflow/voice_review.py` | `export_voice_review.py` 写样张与摘要，`review_voice.py` 登记；`run_all.py` 使用同一状态计算，README/SKILL 只写用法 |
| **成片时长来源** | `scripts/_common.py` 的 `resolve_duration`（实际粗剪优先） | `auto_edit.py`/`merge_cut.py` 写回实测片长；包装、渲染、旁白和 QC 使用实际粗剪；`duration` 不作为隐式裁剪目标 |
| **最终混音响度测量与校准** | `scripts/workflow/loudness.py` | `render.py` 在限峰后复测并按实测值校准；`verify.py` 使用同一测量器，保留数值对象 |
| **逐条字幕样式与动效计划** | `scripts/workflow/caption_plan.py` 产出的 `work/style-plan.json` | `caption_layer.py`（mp4）与 `make_jianying_draft.py`（草稿）**都只读这一份**；`jy_hybrid.py` 从 `caption_plan` import 动画名单，不再自带副本 |
| **字幕轻量标记语法** | `scripts/_common.py` 的 `MARK_OPEN`/`MARK_CLOSE`（强调色）+ `CUE_DIRECTIVE_RE`（逐条指令） | `caption_plan.parse_cue_directives` 负责解析与报错；`verify.py` 的标点扫描、`caption_plain`、`make_captions` 必须先脱指令再比对 |
| **解说槽的位置** | `scripts/workflow/narration.py` 的 `shot_spans` / `narration_spans`（按帧对齐） | `tts.py` 装槽、`caption_plan` 的图形段、`speech_policy` 的落位判定、`verify.py` 的 `narration-slot-*` 全走这一份 |
| **解说只能落在解说槽里** | `scripts/workflow/speech_policy.py` 的 `_in_silence_slots`（`narration_slot_status` 是对外三态入口） | `narration.py` 的 `slot_source_status` 复查槽本身是不是原素材真静音；`storyboard.py` / `story_audio.py` 用同一判据放行旁白 |
| **插图由什么触发、能不能压字幕** | `scripts/workflow/caption_plan.py` 的 `resolve_inserts` | `make_assets.py` 按解出来的条目画图，`verify.py` 的 `insert-grounded` / `caption-band-clearance` 复查同一份计划 |
| **哪些静音不算「空场」** | `scripts/verify.py` 的 `_long_silence_excuses` | 已声明的解说槽与旁白时窗；排除几段、为什么排除写进 `long-silence` 的 detail |
| **剪映资源怎么选、怎么落盘** | `scripts/make_jianying_draft.py` 的 `resolve_fx` / `apply_fx` | `verify.py` 的 `jianying-fx` 对账草稿报告；`config-schema.md` 的 `jianying_fx` 块只写字段，不复述规则 |
| **BGM 从哪来** | `scripts/make_bgm.py`（本地合成，零素材） | `run_all.py` 的 `music` 步按片长决定要不要重算；`verify.py` 的 `bgm-present` 查存在与长度 |

## 已经漂移过一次的，记在这

| 事故 | 表现 | 现在怎么防 |
|---|---|---|
| **标点表两份** | `verify.py` 自己抄了 20 个字符，正本 `PUNCT_CHARS` 是 43 个 —— ASCII 的 `! " ' ( ) , - . : ; < > ? [ ] ~` 和一批中英引号**不在检查面里**，「检查通过」并不等于真的没标点 | `verify.py` 改成 `PUNCT = PUNCT_CHARS`（import）。扩表当场还抓出一个假阳性：`[[词]]` 的方括号被当标点 —— 所以检查前必须先脱标记语法 |
| **房规四处** | `SKILL.md` / `_common.py` / `verify.py` / `config-schema.md` 各写一遍 | `_common.HOUSE_RULES` 是唯一定义；其余三处只是引用它的说明文字 |
| **剪映动画名单两份** | `make_jianying_draft.py` 与 `jy_hybrid.py` 各抄了一份 `ANIM_PLAN` 与几个视觉常量，靠注释「要保持一致」维系 | 名单挪进 `workflow/caption_plan.py`，`jy_hybrid.py` 改成 import（`JY_*` 从 `make_jianying_draft` 引）——**注释不是机制** |
| **解说位置算两套** | 槽的位置本来按「镜头时长直接相加」算，而 `render_plan` 会逐段向上取整到整帧；段数一多累计偏差零点几秒，文件里一个位置、画面里另一个位置 | 统一走 `workflow/narration.shot_spans`（按帧对齐），并加了一条按帧取整的回归测试 |
| **「剪映转场一个都用不了」** | 这条结论是**只数 slug** 得出的（362 条里 0 条有 slug），实际 `findEnum` 还匹配 member，中文名就是 member | 实测 `transition … 上移 --jianying`、`add-sfx … 回音 --jianying` 都成功；SKILL 已改，判断资源可用性不能再只看 slug 数 |
| **`--full` 的时长** | `add-filter --full` 实测写出 2× 片长的滤镜段（81.47s / 40.93s），草稿时间轴对不上 | 滤镜一律显式给起止；`verify` 的 `style-plan-consistent`/时间轴校验会当场报出来 |

## 两条写法纪律（来自 gtrk 的公约，都是踩出来的）

1. **「引用不复制」** —— 零件参数归各自的文档，编排层只写「见 X」，不搬数值。
   *搬过来就会长出会漂移的副本*。典型反面：`make_jianying_draft.py` 结尾那句
   「参数手册在 AGENT.md」——只指路，不搬表。
2. **异源要硬失败，不要静默择一** —— 同一件事发现两个来源时（比如工程里存着一份 rubric，
   命令行又传了一份），不要挑一个用，直接报错让人来定。静默择一 = 没人知道用的是哪份。
   *本仓对应：`captions.font` 解析失败时**直接报错并列出可用族名**，不静默回落到默认字体。*

## 加一条新规矩时

1. 先问「这东西已经有正本了吗」—— 有就加指针，别新开一份；
2. 确实要新立，正本放**离使用点最近的那个模块**（常量放 `_common.py`，算法放各自脚本）；
3. 到这张表加一行，把「副本」一列写全；
4. 副本一律写成「见 X」，**不写数值**。
