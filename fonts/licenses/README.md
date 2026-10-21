# 字体许可记录

`captions.font` 用到的每一款字体，都应该在这里留一条 **license 记录**。字体二进制
（`.otf` / `.ttf` / `.ttc`）默认不进仓库，但许可记录要进仓库：

```text
fonts/licenses/<font-slug>.json
```

记录字段：

| 字段 | 说明 |
| --- | --- |
| `family_aliases` | 字体族名/中文名的别名，`font_license_for()` 按包含匹配 |
| `file_globs` | 文件名兜底匹配（小写、fnmatch） |
| `license` | `workflow/asset_licenses.py` 里的许可 key，如 `OFL-1.1` |
| `license_url` | 官方许可页/仓库 LICENSE 的直链 |
| `copyright` | 版权声明；再分发字体文件时必须一起附上 |
| `commercial` | 是否允许商用（`true` / `false` / `null` 不明） |
| `attribution` | 成片是否需要署名：`none` / `optional` / `required` |
| `redistribute` | 是否允许再分发字体文件本身 |
| `notice_required` | 再分发时是否必须附许可文本/NOTICE |
| `review_required` | 商用前是否必须人工再核对一次 |
| `checked_at` | 这次核对的日期（超过 365 天，`assets verify` 会提示重新核对） |
| `source_url` | 字体来源页 |

判据与三态见 [素材库文档](../../docs/asset-library.md)。

## 当前记录

| 字体 | 许可 | 成片署名 | 商用前核对 |
| --- | --- | --- | --- |
| Noto Sans CJK / 思源黑体 | OFL-1.1 | 不需要 | 否 |
| 抖音美好体 DouyinSans | OFL-1.1 | 不需要 | 否 |
| 得意黑 Smiley Sans | OFL-1.1 | 不需要 | 否 |
| 典迹题幕 Monu Titl | OFL-1.1（以发布页为准） | 不需要 | **是** |
| 阿里巴巴普惠体 | 官方免费商用 | 不需要 | **是** |
| 阿里妈妈字体 | 官方免费商用 | 不需要 | **是** |
| 站酷字体 | 官方免费商用 | 不需要 | **是** |

> “官方免费商用”不是 OFL。记录里的 `review_required: true` 表示脚本不会把它报成
> `pass`，而是 `unchecked`，直到有人核对了官方条款并把 `review_required` 改为
> `false`（并在 `checked_at` 写核对日期）。
