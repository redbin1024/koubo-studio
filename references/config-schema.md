# config.json 字段表

所有字段都有默认值（见 `scripts/_common.py` 的 `apply_defaults`），只写要改的即可。
坐标一律**归一化到 0–1**，换画布尺寸不用改。

```jsonc
{
  "name": "project-name",
  "duration": 37.095,                     // 实际粗剪片长的记录；由选段结果产生，不是裁剪目标

  "canvas": { "width": 1080, "height": 1920, "fps": 30 },

  "input": {
    "video": "in.mp4",                    // 相对 input/；绝对路径也接受（避免复制大素材）
    "subtitle": "captions.srt",           // 画面提示文字；旁白逐字稿是另一条轨，见 audio.voice_subtitle
    "clips": ["1.mp4", "2.mp4"],          // 只在 merge_cut 阶段用；为空就跳过粗剪
    "audio": "talk_ext.wav",              // 外录（双轨收音）；配 video。留空 = 单轨
    "audio_map": { "1.mp4": "1.flac" },   // 多条素材逐条配外录；留空 = 单轨
    "align": { "enabled": true, "threshold": 0.35 },  // 对轨；置信度低于阈值不自动换轨
  },

  "captions": {
    "mode": "generated",                  // generated / burned-in / none
                                          // burned-in = 源片已有烧录字幕，不再生成一层
    "strip_punctuation": true,            // 房规：去标点
    "duplicate_policy": "warn",          // warn：复述字幕记 unchecked；fail：直接红项
    "burn": "layer",                      // layer = Pillow 逐帧画（默认）；ass = 交回 libass
    "jianying_font": {                    // 剪映草稿专用字体（cloud resource）
      "name": "SourceHanSansCN-Bold",     // 必须在 `capcut enums --fonts --jianying` 里
      "resource_id": "7265596643066516029",
      "path": ""
    },
    "font": "Noto Sans CJK SC Black",     // 族名，中英文都认（"阿里妈妈数黑体" 同一个字体）。
                                          // 顺序：工程 fonts/ → 安装目录 fonts/ → KOUBO_FONT_DIRS → 系统目录，
                                          // 第一个命中的目录定案；写错了报错并列出可用族名，
                                          // 不静默换字体。看有哪些可写：scripts/list_fonts.py
    "size": 90, "outline": 10, "shadow": 6, "spacing": 1.5,  // size 是字号上限，超宽会实测缩
    "margin_lr": 66, "margin_v": 190, "max_width": 948,      // max_width = 画布宽 − 2×margin_lr
    "fade_in_ms": 110, "fade_out_ms": 130,
    "anim_ms": 320,                       // pop/rise/wipe 这类入场位移的时长（淡入淡出仍走上面两个）
    "layout": "bottom",                   // bottom 底部 / center 居中 / top 上三分之一 / side 靠左腰部
    "theme": "screen-clean",              // 可选：字体+配色预设（正本 CAPTION_THEMES）。
                                          // **盖过** font 与两个强调色（否则永远不生效），
                                          // 其余键仍看 config；换回默认观感就删掉这一行
    "styles": {                           // 可选：自定义逐条样式，SRT 里用 {@名字} 调用
      "hero": { "size": 132, "layout": "center", "anim": "pop" }
    },
    "big": { "size": 132, "outline": 14, "shadow": 8, "tracking": 2.0 },  // 内置 {@big} 大字卡
    "hook": { "enabled": true, "scale": 330, "accel": 2.6, "ms": 600 },
    "skip": [7, 8, 9],                    // 这几条 SRT 不烧（卡段那几句）
    "palette": {
      "white": "#FFFFFF",
      "accent": "#F5E14A",                // [[词]] 用这个色
      "contrast": "#FF6284",              // ((词)) 用这个色
      "gold": "#F2D26A",                  // 卡片标题、结尾发光字
      "outline": "#000000"
    }
  },

  "card": {
    "enabled": true,
    "start": 10.50, "end": 20.98,         // 卡段起止（从 analyze_reference 的 card.start/end 抄）
    "title": "这些细节", "title_at": 10.62,
    "box": [0.114, 0.150, 0.878, 0.855],  // 归一化 x0,y0,x1,y1（含亮描边外沿）
    "fill": "#A2A0A1", "edge": "#FAFAFA",
    "radius": 36, "edge_width": 15, "wipe": 0.22,
    "theme": {                            // 卡面主题；不写 = flat（参考片量出来的浅灰卡）
      "skin": "glass",                    // flat / glass
      "accent": "#E8C56A",                // 序号、标题、短线、落款的金色
      "footnote": "每一趟都当家人"        // 卡底部小字落款，空着只留金色短条
    },
    "box_dur": 0.30,                      // 卡框自己的入场时长；缺省 = wipe
    "row_enter": "wipe",                  // 行入场的缺省动作，行上没写 enter 时用它
    "rows": [
      { "num": "1", "main": "精致的营养餐", "sub": "每一份  准时送到",
        "icon": "🍱", "at": 10.90,         // at = 该行入场的时间点
        "enter": "wipe" }                  // 该行怎么进：wipe / wipe-right / rise / pop
    ]
  },

  "pip": {
    "enabled": true,
    "box": [0.5, 0.49, 1.0, 1.0],         // 贴 1.0 的边 = 出血
    "radius": 56, "at": 10.52, "dur": 0.34,
    "crop_height": 1150,                  // 从源画面上裁多高（1920 基准）
    "center": [0.555, 0.432]              // 裁切中心（归一化）；脚本不猜，按构图填
  },

  "gold": { "enabled": true, "text": "示例品牌", "in": 32.36, "out": 33.51, "size": 120 },

  "jianying_fx": {
    "enabled": true,
    "namespace": "jianying",              // 剪映资源库（capcut = CapCut 命名空间）
    "effects":     [{ "name": "漏光噪点", "at": 0.0, "dur": 2.2, "intensity": 0.45 }],
                                          // 也可给 resource_id（enums 里的数字 id）
    "filters":     [{ "name": "日系奶油", "intensity": 0.32 }],
                                          // dur 不写 = 覆盖全片；别用 CLI 的 --full（它会算成 2× 片长）
    "transitions": [{ "at": 21.80, "name": "叠化", "dur": 0.36 }],
                                          // at 必须是主轨切点（±0.25s），转场挂在切点前那一段
    "sfx":         [{ "name": "回音", "at": 8.0, "dur": 0.8, "volume": 0.5 }]
                                          // 剪映「音效效果」（处理器），不是音效素材
  },

  "shot_fx": {                            // 只进草稿的高级片段操作
    "enabled": true,
    "items": [
      { "shot": 1,                        // 主轨 1-based 序号
        "duplicate": false,               // true 时复制上层，把 mask/mix 作用在副本
        "opacity": 1.0, "bg_blur": null,  // bg_blur: 1-4
        "mask": { "type": "circle", "center_x": 0, "center_y": 0,
                  "size": 0.6, "rotation": 0, "feather": 0.1, "invert": false },
        "mix_mode": "normal",             // normal/multiply/screen/...
        "keyframes": [                    // time 相对镜头起点
          { "property": "scale", "time": 0.0, "value": "1.0" },
          { "property": "scale", "time": 1.5, "value": "1.04", "easing": "ease-out" }
        ],
        "filters": [{ "name": "暖食", "intensity": 0.15 }]
      }
    ]
  },

  "broll": {                              // 真实 B-roll；只进草稿
    "enabled": true,
    "items": [
      { "cue": 7, "keyword": "放心",      // keyword 必须在该条字幕里
        "source": "broll/tea.mp4",        // 相对 input/
        "in": 0.5, "dur": 1.8, "volume": 0.0 }
    ]
  },

  "stickers": {                           // 只进草稿的贴纸/图形层（全画布透明 PNG）
    "enabled": true,
    "items": [
      { "icon": "heart", "at": 19.6, "dur": 2.2,
        "x": 0.82, "y": 0.22, "size": 0.085, "color": "#B9824A" }
                                          // icon: check/clock/bowl/leaf/heart/home/star/shield
    ]
  },

  "inserts": {
    "enabled": true,
    "layout": "band",                     // band 字幕带上方的横条卡 / panel 整屏图形段（压暗底画）
    "box": [0.10, 0.53, 0.90, 0.72],      // 归一化框；下沿不得越过字幕带（verify 硬查）
    "radius": 28, "hold": 2.6,            // hold = 单条默认停留秒数
    "theme": {                            // skin 不写 = flat（实心图标块 + 粗边，参考片量出来的样子）
      "skin": "editorial",                // editorial = 发丝描边 + 淡色圆底图标 + 字距标题（压在真人口播上更像设计过的图形，不像系统通知）
      "bg": "#FFFDF9", "fg": "#2A211A", "accent": "#C08A4E",
      "title_font": "Songti SC", "body_font": "Noto Sans CJK SC Medium",
      "label": "CARE NOTE" },
    "items": [
      { "kind": "icon-label",             // icon-label / list / stat / quote（全部由脚本现画）
        "trigger": { "cue": 6, "keyword": "准时" },   // 或 { "slot": 1 } 挂在解说槽上
        "icon": "clock",                  // check/clock/bowl/leaf/heart/home/star/shield
        "illustration": "stills/clean-9.2.jpg", // 可选：左侧图窗，支持 PNG/SVG/真实静帧
        "illustration_focus": [0.56, 0.4],      // 焦点裁切（x,y 0–1）；不写=居中
        "title": "准时送达", "text": "精致的营养餐", "hold": 2.4 }
    ]
  },

  "sfx": {
    "events": [
      { "t": 0.00,  "cue": "hook" },                  // 走 make_sfx.py 的 CUES 预设
      { "t": 10.90, "clip": "riser", "peak_db": -22 } // 或直接指定素材与电平
    ]
  },

  "grade": {
    "enabled": true,
    "eq": "eq=contrast=1.06:saturation=1.10:brightness=0.012",
    "blur": "gblur=sigma=26",             // 卡段模糊底用的模糊核
    "darken": 0.28
  },

  "audio": {
    "speech_mode": "narration",           // narration 配音 / source 原声 / mixed 原声+解说 /
                                          // none 明确无语音
                                          // 不写 = 按 mode 推：vlog→narration，talking-head→source
                                          // mixed 两条腿都要过检：原声证据 + 逐句解说，
                                          // 且解说只能落在 narration-slot（见「解说旁白」一节）
    "voice_cues": "voice-cues.json",      // 可选：work/ 下的逐句时窗；声明了就逐句查
                                          // 「这句真出声了吗 + 有没有对应字幕」，不声明只查整轨
                                          // 新生成的每句还写 shot_index/shot_ref，核对当前镜头表
    "voice_subtitle": "voice-captions.srt",  // 旁白逐字稿写到 input/ 下的哪个文件；
                                          // 不写 = 沿用 input.subtitle（老工程行为不变）
    "narration_voice": "zh-CN-XiaoxiaoNeural",  // edge-tts 音色；换音色会换缓存键
    "voice_volume": 1.0, "sfx_volume": 0.80,
    "narration_volume": 1.0,              // work/voice.wav 的音量（文件不存在就整条忽略）
    "bgm_volume": 0.55,                   // work/bgm.wav 的音量；0.25 很含蓄，0.55 清楚听得见
    "bgm": { "enabled": true, "mood": "warm", "bpm": 88 },
                                          // 默认本地合成 BGM（make_bgm.py，零素材）。
                                          // 云端曲库用 `koubo music pick` 写：
                                          // { "source":"jianying-cloud", "music_id":"...",
                                          //   "title":"..." }；run_all 会下载/循环成 work/bgm.wav。
                                          // 没有 CDN URL 时明确报错，不伪造。enabled=false 时整步跳过。
    "duck": { "threshold": 0.08, "ratio": 3, "attack": 25, "release": 500 },
                                          // 旁白对现场声/BGM 的侧链闪避；不铺旁白就无效果
    "loudness": { "I": -14, "TP": -2.6, "LRA": 11 }
  },

  "segments": { "fade_out": 0.40 },       // 收尾淡黑时长

  "jianying": {                           // 剪映草稿（run_all 中在质检前生成，每轮必出）
    "name": "示例_风格包装_v1",           // 草稿名；同名会被覆盖，要留手改版就换名
    "install": true,                      // 复制 + 登记进剪映草稿箱；false = 只留在 draft-store/
    "ratio": "9:16",                      // 缺省按 canvas 推（高 ≥ 宽 → 9:16）
    "line_spacing": 0.22,                 // import-srt 默认 0.02，双行字幕会叠；0.22 是安全值
    "force_install": false                // true = 连剪映改过的同名草稿也覆盖（默认保护手改版）
  },

  "constraints": {                        // 房规；默认 false/false/false/true
    "strip_punctuation": true,
    "opening_cover": false,               // 不要开头封面
    "end_card": false,                    // 不要片尾卡
    "sticky_title": false                 // 不要常驻标题
  }
}
```

## 几处容易搞错的地方

- **字幕是一条「逐条样式计划」**（`work/style-plan.json`，正本 `workflow/caption_plan.py`），
  mp4 与剪映草稿读的是**同一份**。SRT 里可以写一行轻量指令：
  `{@hero layout=center anim=pop}正文` —— `@` 后面是 `captions.styles` 里的名字
  （内置 `default` 与 `big`），也可以只覆盖 `layout=` / `anim=`。指令写错**直接报错**，
  不会当正文画到屏幕上。`anim` 可取 `fade`（默认）/ `hook`（首句默认）/ `pop` / `rise` /
  `wipe` / `karaoke`（逐字上色，按 cue 时长均分推进，不假装逐词对时）。
  草稿那侧只能对齐入场动画：`import-srt` 不收逐段字号与位置，对不齐的部分
  `verify.py` 的 `style-plan-consistent` 记 `unchecked` 并写明原因，不假装通过。
- **`{@big}` 不许压在 0s**：那等于换个名字的开头封面，房规禁的就是这个。
- **插图必须由字幕或解说触发，不做无据装饰**。`trigger.cue + keyword` 要求该关键词
  真的出现在那条字幕里；`trigger.slot` 要求 `work/narration-lines.json` 里确实有
  对应那一槽的解说。插图框的下沿不许越过字幕带上沿（`caption-band-clearance`），
  触发词对不上的记 `insert-grounded` 红。
- **包装元素的寿命必须落在片长之内**（「坑位包络」）。`card.start/end`、`gold.in/out`、
  每条字幕与每条插图的起止，都要被 `duration` 包住 —— 跑出去的表现是**元素在片尾被
  硬切掉**或**还没到就消失**，而这两种都不会报错，只是看起来不对。
  `verify.py` 的 `card-slot` / `gold-slot` / `caption-slot` / `insert-slot` 几项专门查这个
  （元素没启用时记 `unchecked`，不是「通过」）。
- **入场动画负责「进」，出场靠被下一个元素顶掉或结构切走**，不要自己渐隐到空。
  卡段就是这样：条目入场后一直定格到 `card.end`，然后跟着卡段结构一起切回满屏真人。
  自己加一个整体渐隐，观众看到的是「东西无缘无故没了」。
- **`card.box` 是含描边的外沿**，不是填充色区域。analyze 输出的就是这个口径。
- **`card.rows[].at` 是自己写的**，不要照抄字幕时间轴。条目擦出的节奏常比字幕早 0.1–0.3s。
- **`card.rows[].enter` 别三行都填一样**。参考片三行都是同一种从左擦出，单看没问题，
  连起来看就是一块板子刷三遍、很死板。常用组合：`wipe`（左进，签名动作）→
  `wipe-right`（右进，镜像成来回）→ `pop`（0.88 放大到 1.0，收尾强调）。
  `rise`（从下 52px 淡入上浮）适合当中间那行的过渡。四种动作落位后都会带一次
  1.4% 的落定微弹，所以条目是「落」下去而不是「贴」上去。
- **卡框自己也别只是横着推**。`card-base` 的入场是擦出 + 上浮 72px + 0.955→1.0 缩放，
  比纯擦出多一层「落位」感；`card.box_dur` 是框自己的时长（0.22s 的纯横推太快，
  观众只会看到一块灰板子突然在那儿），`card.wipe` 是每行条目的入场时长。
- **`pip.center` 是构图决定**，不是量出来的。想让画中画里的人靠左就调小。
- **`card.enabled: false` 时整段卡片逻辑跳过**，`pip` 也不会画（画中画只在卡段里出现）。
- **`card.theme.skin = "glass"` 是另一套卡面**，几何（卡盒、画中画）不动，换的是脸：
  深色竖向渐变底 + 发丝描边 + 外投影 + 金色点缀，文字去黑描边改柔投影，图标套一层
  白色 7% 的圆角托底。"flat"（不写 theme）是照参考片量出来的浅灰底 + 粗白边 + 黑描边字
  ——想要「像参考片」就留 flat，想要「精致」就上 glass；浅灰底配金色是最显廉价的一种搭法。
  glass 下 `fill` / `edge` / `edge_width` 不生效，`GLASS_THEME`（`scripts/make_assets.py`）
  里每一项都能被 `card.theme` 覆盖；行距和标题位置在 `_common.py` 的
  `CARD_ROW_PITCH_GLASS` / `CARD_TITLE_OFF_GLASS`（素材与合成共用，改一处两边一起动）。
- **`card.theme.footnote` 要按画中画左边界裁长度**。落款画在卡底左端，而画中画压着卡的
  右下角，太长会被盖住半句——先算 x（卡左 + 卡宽 × 0.093 + 48 + 24）到画中画左边界还剩多少，
  再定字数（1080 宽、30px 字号时大约 8 个汉字）。
- `sfx.events` 里混用 `cue` 与 `clip` 是允许的；`peak_db` 缺省时用 CUES 里的预设值。
- **`jianying` 不用手填也能跑**：缺省用 `name`（= config.name）、`install: true`、
  `ratio` 按 canvas 推、`force_install: false`。草稿里的轨道结构见 SKILL.md「剪映草稿」一节。
- **草稿是质检项，不是可选项**：`verify.py` 会检查 `draft-store/<jianying.name>/` 在不在、
  有没有登记进剪映草稿箱（`jianying-draft` / `jianying-installed`）。`--skip draft` 会让质检报红。

## 解说旁白（`speech_mode: "mixed"`）

给口播再叠一条解说，现场人声不动。规矩只有一条，但它是硬的：

**解说只能落在现场人声的空隙里。** 空隙不是事后补的静音，而是粗剪时从**原素材真实静音**
里留出来的镜头：

```bash
# 留最长的 3 段真实静音当解说槽（0 = 不留，行为与以前一致）
python3 scripts/auto_edit.py my-video --mode talking-head --clips talk.mp4 --narration-slots 3
# 写文案（每句指向一个槽）
$EDITOR my-video/work/narration-lines.json     # {"lines": [{"slot": 1, "text": "…"}]}
# 试装（真的合成、不落产物）→ 生成 voice.wav + 逐句时窗 + 旁白字幕
../.venv/bin/python scripts/tts.py my-video --probe
../.venv/bin/python scripts/tts.py my-video
python3 scripts/run_all.py my-video            # narrate → voice → … 全链
```

- **槽的数量与长度由素材决定**：本机实测一条 60s 口播只有 15 段 ≥0.6s 的静音、合计 17.2s。
  留 3 个槽大约多 6s 片长，能放 3 句短解说 —— 想要长解说就要留更多静音（片更长），
  脚本不会替你压缩素材。
- **装不下就报错，不截断**：`tts.py` 会按 `−5% → +30%` 逐档升速试装，都不行就直接报错，
  让你改文案或换更长的槽。
- **质检怎么查**：`narration-slot-fit`（每句是否落在槽里，允许向相邻说话段外溢 0.5s、
  那一段现场声会被侧链压低）、`narration-slot-real`（槽本身在原素材里是不是真静音，
  防「把说话声标成槽」）、`voice-caption-cross-overlap`（画面字幕与旁白字幕**合起来**
  会不会同帧打架）、`long-silence`（已声明的槽与旁白时窗不算空场，排除几段写在 detail 里）。
- `voice_cues` / `voice_subtitle` 与 `narration` 模式共用同一套逐句检查；改稿或改镜头表后
  旁白会**自动重配**（判据是重新解一遍位置再和现有配音当时的解比对）。
