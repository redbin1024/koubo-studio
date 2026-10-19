# B-roll：真实细节镜头

这一版支持把**真实 B-roll** 作为剪映草稿的一条 `B-roll` 轨插入，覆盖对应字幕时窗。

> B-roll 只进剪映草稿；ffmpeg mp4 预览暂时不包含。最终以剪映导出为准。

## 配置

```jsonc
"broll": {
  "enabled": true,
  "items": [
    {
      "cue": 7,                 // 触发字幕序号
      "keyword": "放心",        // 必须出现在该条字幕里
      "source": "broll/tea.mp4",// 相对 input/；也可绝对路径
      "in": 0.5,                // 从素材第 0.5s 开始
      "dur": 1.8,               // 覆盖 1.8s
      "volume": 0.0             // 原声静音，避免和口播打架
    }
  ]
}
```

## 规则

- 时长必须在触发字幕的起止范围内；
- `keyword` 必须真的在该条字幕里，不能“先有画面再找句话”；
- 素材必须是真实拍摄/授权的细节镜头，不能生成假截图冒充证据；
- 默认静音；如果要用现场声，单独确认后把 `volume` 调高；
- 横屏素材会按 9:16 中心裁切，重要对象不要放边缘；
- 人物/客户正脸需授权；不要拍到其他品牌 Logo。

## 执行

素材放进 `PROJECT/input/broll/`，配置 `broll` 后：

```bash
koubo draft PROJECT --name PROJECT-Broll
```

`make_jianying_draft` 会：

1. 校验 cue/keyword/时窗/素材存在；
2. 在主轨之上新建 `B-roll` 轨；
3. 裁成 9:16、静音；
4. 写入 `visual-contract` 的 `broll` beat（`requires-capcut-export`）。

## 当前 4105

见 [4105 B-roll 拍摄清单](broll-shotlist-4105.md)。素材未提供前，`broll.enabled=false`，不伪造画面。
