# 素材库

程序可检索、可稳定调用、授权边界清晰的素材目录。正本是 `registry.jsonl`；
`licenses.csv` / `CREDITS.md` 由它生成，不要手改。

```text
assets/library/
├── registry.jsonl          每条素材一行 JSON（ID/kind/标签/许可/来源/哈希）
├── licenses.csv            人可读授权台账（生成）
├── CREDITS.md              署名清单（生成）
├── audio/bgm/              BGM
├── audio/sfx/              音效（whoosh/click/pop/impact/riser…）
├── video/broll/            B-roll 空镜
├── video/overlays/         转场、光效、纹理
├── graphics/stickers/      贴纸
├── graphics/fonts/         字体二进制（许可记录在 ../../fonts/licenses/）
├── graphics/illustrations/ 插图
├── graphics/stills/        静帧
├── templates/jianying/     剪映草稿模板
└── templates/captions/     花字/字幕条模板
```

## 常用命令

```bash
koubo assets init                       # 建目录 + 登记随包音效/插图/动效
koubo assets scan                       # 扫目录；新文件登记为授权未填
koubo assets add ~/Downloads/night.mp4 --kind broll \
  --license CC0-1.0 --source-url https://example.com/n --tags city,night
koubo assets search 城市夜景 --kind broll
koubo assets verify --strict            # 文件/哈希/许可三态
koubo assets audit PROJECT              # 工程实际用量 → output/asset-licenses.csv
koubo assets suggest PROJECT --cue 7    # 按字幕召回，只出建议
```

完整字段、许可判据、远程源边界见 [素材库文档](../../docs/asset-library.md)。

## 规则

1. **入库必须给授权**。`scan` 扫到的新文件是 `unknown`，`verify` 会记 `unchecked`；
   用 `koubo assets set-license ID --license ...` 补齐后才能进交付。
2. **ID 是调用契约**。配置里写 `asset:sfx/whoosh-short`，不要写死文件路径；
   换文件名/换目录不影响调用。
3. **文件旁边有 sidecar**。`<file>.asset.json` 记录来源/许可/标签；工程内素材
   （`input/broll/`、`work/cloud-music/`、`assets/mixkit/`）靠 sidecar 随工程走。
4. **许可会变**。记录 `license_checked_at`；超过 365 天 `verify` 会提示重新核对。
5. **不替用户做法律判断**。`pass` 只表示已知授权边界内没有障碍；肖像/商标/平台
   规则仍需人工签收。
6. **媒体文件默认不进 git**（仓库 `.gitignore` 忽略 `*.mp4` / `*.wav` 等大文件）。
   `registry.jsonl` 可以单独提交；换机器时把媒体放回相同相对路径即可。
