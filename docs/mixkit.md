# Mixkit 免费素材

[Mixkit](https://mixkit.co/) 是 Envato 的免费素材站：stock video、music、sound effects。
本项目只抓公开页面/公开下载地址，不登录、不绕过付费墙、不转售素材。

## 搜索

```bash
koubo mixkit search video coffee --limit 8
koubo mixkit search music warm --limit 8
koubo mixkit search sfx horn --limit 8
```

来源页：

```text
https://mixkit.co/free-stock-video/discover/<keyword>/
https://mixkit.co/free-stock-music/discover/<keyword>/
https://mixkit.co/free-sound-effects/discover/<keyword>/
```

## 下载

```bash
# 默认放 assets/mixkit/<kind>/，写 work/mixkit.json
koubo mixkit download PROJECT video --id 41859 --quality 1080
koubo mixkit download PROJECT music --id 443
koubo mixkit download PROJECT sfx --id 1565

# active_storage 的 video 用搜索页给出的 --url（固定文件名的 ID 才能只给 --id）
koubo mixkit download PROJECT video --url 'https://assets.mixkit.co/active_storage/...mp4'
```

## 直接进工程

```bash
# 作为 B-roll，写 config.broll
koubo mixkit broll PROJECT --id 41859 --cue 7 --keyword 放心 --dur 1.8

# 作为 BGM：转 work/bgm.wav，写 config.audio.bgm.source=mixkit
koubo mixkit bgm PROJECT --id 443
```

`run_all` 的 `music` 步看到 `audio.bgm.source=mixkit` 会沿用已生成的
`work/bgm.wav`，不会用本地合成覆盖。

## 记录与审查

`work/mixkit.json` 记录：

- `kind / id / title / url`
- 本地文件
- 许可链接
- 搜索来源页

`review-outputs` 的插画/视频门会检查素材文件存在与尺寸；Mixkit 素材的
**审美、是否适合品牌、许可是否覆盖你的用途**仍要人工确认。

## 许可边界

- Mixkit 免费许可允许个人/商业项目使用，但**不能单独转售、再分发素材本身**；
- 不能把 Mixkit 素材当成自己的素材库发布；
- 具体条款以 [Mixkit License](https://mixkit.co/license/) 为准；
- 人物/品牌/地点出现的素材，商用前仍需自行确认肖像/商标风险。

## 限制

- 没有官方公开 API；页面结构变化会导致解析失败，失败会明确报错，不静默降级；
- 不是所有关键词都有结果；没有结果时换关键词或查分类页；
- `--id` 只对固定文件名 URL 有效；active_storage ID 用 `--url`。
