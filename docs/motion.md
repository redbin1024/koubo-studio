# Canvas / HTML 动效

```bash
python scripts/render_motion.py assets/motion/steam.html \
  --out work/motion/steam.mov --duration 2 --fps 30
ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,pix_fmt,width,height -of default=nw=1 work/motion/steam.mov
```

输出为 ProRes 4444 + alpha。适合：

- 水汽/热气、线条生长、轻粒子；
- 卡片入场/退场的一个 signature 动作；
- 透明 overlay，叠加在剪映/PR/FCP 上。

不适合：

- 整条口播的逐帧渲染；
- 需要用户在剪映里改文字/图层的场景；
- 没有 `renderAt(t)` 的实时随机动画（不可 seek、不可复现）。

约定：

1. 页面透明背景，固定画布；
2. `window.renderAt(t)` 只依赖 t，不用 `Date.now()`/随机；
3. 动效内容不承载事实证据；
4. 渲染后必须看实际编码帧，不能只看 HTML；
5. 作为 overlay 时保留源 HTML，方便改。
