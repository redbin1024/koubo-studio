# 剪映云端音乐库

目标：从**你以前用过的剪映草稿**里挖出云端音乐 ID，并支持搜索、选择、下载为本地 BGM。

## 1. 扫描历史草稿

```bash
python scripts/music_library.py scan
# 或
koubo music scan
```

扫描：

- `~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft/*/draft_content.json`
- 其他已知剪映草稿根
- `.capcut-cli-history/*.snap`、`.backup/**/*.bak` 历史快照

只收 `materials.audios[].type = "music"` 且 `music_id` 是数字的素材；本地
`extract_music`、TTS、音效不会混进来。

缓存：

```text
~/.cache/koubo/music-library.json
```

可用 `KOUBO_MUSIC_LIBRARY=/path` 覆盖。

**本机实测**：扫描 1746 个草稿/快照文件，云端音乐 ID **0 条**——因为现有草稿的 BGM
都是本地 `bgm.wav`，没有在剪映音乐库里选过曲。0 条是真实结果，不是脚本失败。

## 2. 导入外部目录（可选）

```bash
python scripts/music_library.py import /path/to/cloud_music_library.csv
```

CSV 列：`music_id,title,duration_s,categories,url`。  
本次从参考 skill 的 616 行 CSV 导入，去重后 **615 首**；这只是**缓存**，不进仓库。

## 3. 搜索

```bash
python scripts/music_library.py search 温暖 --limit 8
python scripts/music_library.py search 企业 --limit 5
```

按标题、分类、来源、ID 匹配；中文会扩展同义词（温暖→warm/治愈/舒缓 等）。

## 4. 选择并下载

```bash
python scripts/music_library.py pick 接送-品牌版 --id 7377847594314287123 --volume 0.22
```

`pick` 会：

1. 从曲库拿 `music_id` / `url`；
2. 下载到 `work/cloud-music/<id>.m4a`（缓存）；
3. 用 ffmpeg 循环/裁到片长，写 `work/bgm.wav`（48k/16bit/立体声）；
4. 写 `work/music-selection.json`（id/title/url/raw/bgm）；
5. 更新 config：`audio.bgm.source="jianying-cloud"`、`music_id`、`title`、`bgm_volume`。

之后 `run_all` 的 `music` 步会优先走云端曲库，不再本地合成 BGM；
`verify` 的 `bgm-cloud` 会核对 ID 与 `work/bgm.wav`。

## 5. 没有 URL 怎么办

曲库条目没有 `url` 时**不会伪造**。先在剪映里播放/缓存该曲，或使用带 `url` 的 CSV
重新导入；否则 `pick` 直接报错。

## 6. 版权

- `music_id` / URL 来自你自己的剪映草稿或你提供的目录；
- 下载文件只放本机 `work/cloud-music`，不进仓库、不随项目分发；
- 发布前按剪映/音乐平台授权和平台规则确认商用范围。

## 7. 配音

`audio.narration_voice` 可指定 edge-tts 音色（默认 `zh-CN-XiaoxiaoNeural`）：

```json
"audio": { "narration_voice": "zh-CN-XiaoxiaoNeural" }
```

音色不同会生成不同的 TTS 缓存键，不会复用旧音色的缓存。
