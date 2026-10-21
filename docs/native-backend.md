# 原生草稿适配层（jianying-tool 桥）

> 一句话：**让本项目能读懂剪映自己保存过的那份草稿，并在需要时调用剪映原生导出。**
> 它只补 I/O，不参与「剪什么、怎么剪」的决策。

## 为什么需要它

本项目的草稿层默认只认 `draft_content.json`——这是 capcut-cli 和 pyJianYingDraft
都能稳定读写的明文文件。但剪映在 macOS 上把**活动时间线**写进 `draft_info.json`，
而且**保存后是密文**（实测剪映 11.6.0，`draft_info.json` 以 base64 密文开头）。
于是出现两个问题：

1. 用户在剪映里改过草稿并保存后，本项目读不回真实内容，`install_draft` 也会
   因为「这份被剪映改过」而拒绝覆盖（这是对的，但代价是不能续编）。
2. 我们自己的收尾步骤（字体、行距）曾经只写 `draft_content.json`，
   剪映下次打开读的却是 `draft_info.json`，两边可能各说各话。

[jianying-tool](https://pypi.org/project/jianying-tool/) 能用本机剪映自带的
`libvideoeditor.dylib` / `videoeditor.dll` 解/加密原生草稿。本项目把它做成
**可选的子进程桥**：装了就多一层能力，没装也照常出片。

## 它是怎么接的

```text
剪映 / jianying-tool 改过的 draft_info.json（可能是密文）
        │
        ├── workflow/draft_native.py
        │     ├─ probe()       找可用的 3.10+ 解释器
        │     ├─ read_draft()  明文直读；密文走桥解密
        │     ├─ sync_twin()   较新的一份 → 另一份（可指定方向，带备份）
        │     ├─ doctor()      桥在就用 jianying-tool 深度诊断，否则基础结构检查
        │     └─ export()      调剪映自己的导出对话框
        │
        ├── workflow/draft_audit.py   改审「活动文件」，不再只审 draft_content.json
        ├── verify.py                 新增 draft-file / draft-doctor 两项
        ├── doctor.py                 报告桥是否可用
        └── make_jianying_draft.py    字体/行距写两份；收尾时双向对齐
```

桥脚本是 [scripts/jytool_bridge.py](../scripts/jytool_bridge.py)，用独立解释器运行，
只输出 JSON。这样主环境是 Python 3.9 也能用（jianying-tool 要求 3.10+）。

## 安装

```bash
# 在 repo 根目录；需要 uv（brew install uv / pip install uv）
python scripts/draft_native.py setup

# 装到 vendor/jytool-venv（已 gitignore），不动 .venv、不动系统 Python
python scripts/draft_native.py info
```

也可以自己指定解释器：

```bash
export KOUBO_JYTOOL_PYTHON=/path/to/python3.12
# 该解释器需要能 import jianying_tool
pip install "jianying-tool==0.5.0"
```

`koubo doctor` 会把 `jianying-tool` 标成 `ok` / `warn`（可选依赖，缺了不算失败）。

## 命令

```bash
# 环境 + 一份草稿的概况
python scripts/draft_native.py info
python scripts/draft_native.py info "my-video/draft-store/片名"

# 深度诊断（jianying-tool doctor）
python scripts/draft_native.py doctor "my-video/draft-store/片名" --json

# 对齐两份文件：默认较新的一份为准；也可显式指定方向
python scripts/draft_native.py sync "my-video/draft-store/片名"
python scripts/draft_native.py sync "my-video/draft-store/片名" --from active

# 驱动剪映导出（GUI；先关掉剪映里的这个草稿，或让它自己打开）
python scripts/draft_native.py export \
    --draft "片名" --title "片名_导出" --output-dir output \
    --resolution 1080P --framerate 30 --close
```

`koubo native` 是同一入口的别名。

### 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 成功 / 诊断无红项 / 已是同步状态 |
| 1 | 有错误、草稿不可读、同步被方向保护拦下 |
| 2 | 缺 jianying-tool 桥（`doctor` 遇到加密草稿；`export` 一律需要它） |

## 三条保护

1. **不猜方向。** `sync` 默认以**较新的那份**为准：剪映保存后活动文件更新，就活动 → 副本；
   本项目只改明文副本时，就副本 → 活动。两份时间几乎相同（≤1s）时拒绝猜，要求
   `--from active|twin` 指定；`--force` 表示「以活动文件为准」。构建收尾的 `ensure_twin`
   同样走这套规则，但只处理明文，加密文件不盲改。
2. **写前备份。** 被覆盖的文件先复制到草稿内 `.koubo-backups/<时间戳>/`。
3. **加密文件不盲改。** `write_all` 跳过密文；要改加密草稿，走 jianying-tool 的
   命令或剪映本身。本项目只负责把明文副本对齐。

## 实测记录（2026-10，剪映 11.6.0 macOS）

- `jianying probe` 找到 `/Applications/VideoFusion-macOS.app`，`codec_dir` 指向
  `Contents/Frameworks`。
- 对剪映保存过的 `draft_info.json`（16 个顶层键）解密成功；`set-text` 改字后
  文件从 48KB 变 90KB（重新加密），内容确认生效。
- 对本项目产出的 9 键草稿 `inspect`/`doctor` 均通过——它能读我们的草稿。
- 它在 macOS 上只写活动文件；`draft_content.json` 会留旧——这正是 `sync` 要解决的。
- 用真实旧草稿发现过一类静默分叉：活动文件 `line_spacing=0.02`、明文副本 `0.22`。
  `draft-audit` 改审活动文件后立刻红；`sync`（较新的一份为准）一次后两份一致并转绿。
- 对加密草稿走 `read_draft`：`draft-readable` 报 `jianying-native`，`draft-twin`
  由桥解出后比对，不会因为「读不了」把副本判成过期。

## 已知限制

- **只做 I/O，不做决策。** 它不会替你想镜头、字幕断行或质检标准。
- **导出是 GUI 自动化。** 依赖剪映版本、窗口状态和辅助功能权限；失败会明确报错，
  不会假装成功。导出前先确认剪映里打开的是哪份草稿。
- **不注册草稿箱。** jianying-tool 不写 `root_meta_info.json`；注册与 `lint` 仍由
  capcut-cli 负责（见 `install_draft`）。
- **版本要钉死。** `jianying-tool==0.5.0` 是实测版本；升级后先跑
  `python scripts/draft_native.py doctor` 和本仓库测试。
- **许可证。** jianying-tool 是 Apache-2.0；本项目 MIT。若把它的代码 vendor 进仓库，
  要保留 LICENSE/NOTICE。当前实现是**运行期依赖**，没有复制源码。
