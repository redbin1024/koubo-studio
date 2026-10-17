# 字体目录

把 `.otf` / `.ttf` / `.ttc` 丢进这里，`config.json` 的 `captions.font` 写**族名**即可，
不用装进系统字体。查找顺序是：

1. 工程自己的 `fonts/`
2. 本安装目录的 `fonts/`（`install.sh` 会把 Noto Sans CJK SC Black 下载到这里）
3. `KOUBO_FONT_DIRS`（冒号分隔）
4. 系统字体目录

换字体后字号由 `caption_layer` 实测自动收缩，不用手算。列出可用族名：

```bash
koubo fonts my-video          # 工程 fonts/
koubo fonts my-video --all    # 连系统字体一起列
```

字体二进制默认被 `.gitignore` 排除，不要把大字体提交进仓库。
