# SVG / Canvas 插图与动画

不依赖图像 API：DeepSeek 写 SVG/Canvas 代码，本机 Chromium 渲染成 PNG/视频。
适合 **editorial 线稿、场景插画、动效**；不适合照片级写实或真人证据。

## 静态插图：SVG → PNG → 卡片

源文件：`assets/illustrations/*.svg`（800×1000，透明/暖纸底，无文字）。

```bash
# 单张渲染
python scripts/render_svg.py assets/illustrations/car-seat.svg /tmp/car-seat.png

# 项目里引用（相对 assets/）
"inserts": {
  "items": [
    {"title": "有人扶稳", "text": "上车这一下 手不松开",
     "illustration": "illustrations/car-seat.png"}
  ]
}
```

`run_all` 的 `assets` 步会：

1. 读 config 里引用的 `illustrations/*.png`；
2. 找到同名 `.svg`，按 SVG 哈希缓存渲染；
3. 写 `work/illustrations.json`（源/产物 SHA）；
4. `make_assets` 把图放进卡片左侧圆角图窗，右侧仍排 Songti 标题 + 正文。

已接入过 6 张，但 2026-10-20 设计复盘后：

- 4105 卡片行的小图窗已撤（80px 下 SVG 细节看不清）；
- 4105 CTA、接送两条信息条改用**真实成片静帧**（`assets/stills/`）；
- SVG 仍保留为素材库/概念图，不强行塞进小图窗。

当前库里：

| 文件 | 用途 |
| --- | --- |
| `food-tray.svg` | 营养餐托盘 |
| `quiet-room.svg` | 安静房间/窗光 |
| `tea-set.svg` | 茶具/水汽 |
| `car-seat.svg` | 上车/座椅/毛毯 |
| `crib.svg` | 婴儿床/毯子 |
| `doorway.svg` | 门廊/预约参观 |
| `care-hands.svg` | 照护手部草图（未用于成片） |

## 动效：Canvas → ProRes 4444 overlay

源文件：`assets/motion/*.html`，页面必须暴露 `window.renderAt(t)`，按秒确定帧。

```bash
python scripts/render_motion.py assets/motion/steam.html \
  --out work/motion/steam.mov --duration 2 --fps 30
```

- 逐帧截图，透明背景；
- `prores_ks -profile:v 4444 -pix_fmt yuva444p10le`；
- 输出可做剪映/PR/FCP 的透明 overlay。

**边界**：动效只做 1–2 个 hero moment，不把整片交给 Canvas；overlay 内部文字不可在剪映里逐字改。
当前动效渲染是独立命令，尚未自动写入 draft 轨；等剪映对 ProRes alpha 的导入实测后再接。

## 三层素材（v2）

- **still**：真实成片静帧，优先用于护理/环境/证据；`extract_still.py` 从
  `input/clean-cut.mp4` 抽帧，写 `assets/stills/manifest.json`。
- **vector**：代码绘制 SVG；`assets/illustrations/manifest.json` 记录 tier/focus/
  license；只用于概念/章节，不塞 80px 小图窗。
- **ai**：可选，当前没有 provider；接入后必须人工审片、标识来源。
- 图窗裁切支持 `illustration_focus: [x,y]`，不再永远居中。

```bash
python scripts/extract_still.py 接送-品牌版 --time 9.2 \
  --out stills/clean-9.2.jpg --focus 0.56,0.4
```

## 设计 token

- 纸色 `#FBF4E7` / `#F7EEDF`
- 金 `#D8B36A` / `#B9824A`
- 鼠尾草 `#8FA36B`
- 墨 `#2A211A`
- 发丝线 `2–4px`，圆角 `18–28px`，纸纹 `feTurbulence`
- 画面不放文字/Logo；文字由 Pillow/剪映排
