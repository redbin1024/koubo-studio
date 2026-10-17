# 贡献指南

欢迎提交 issue 和 PR。这个仓库最看重的不是功能数量，而是**可验证**：每个结论都要有命令、数据或失败用例支撑。

## 开发环境

```bash
git clone https://github.com/redbin1024/koubo-studio.git
cd koubo-studio
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests
```

测试会调用 `ffmpeg` 生成短素材，请确保 `ffmpeg` / `ffprobe` 在 PATH 里。

## 提交前

```bash
python -m compileall -q scripts tests
python -m unittest discover -s tests
koubo doctor
```

如果改了实测常量，同步 `references/measured.json`；如果新增跨文件规矩，先在 `references/registry.md` 登记正本。

## 代码约定

- **引用不复制。** 同一个数值/名单只保留一个正本，别处写「见正本 X」。
- **异源要硬失败。** 同一件事出现两个来源时直接报错，不要静默择一。
- **缺席 ≠ 通过。** 判不了的质检项必须以 `unchecked` 出现，并写清原因。
- **不静默降级。** 字体找不到、语音缺失、字幕冲突都要报出来，不能偷偷换一个。
- 新增脚本优先放进 `scripts/`，可复用逻辑放进 `scripts/workflow/`；旧导入路径保留兼容层。

## 隐私

**不要提交真实客户素材、成片、剪映草稿、带个人信息的截图或路径。** 示例请脱敏；本地工程目录已被 `.gitignore` 排除。提交前建议：

```bash
git diff --cached | grep -nE '/Users/|/home/|客户|真名' || true
```

## 提交信息

用一句话说清「改了什么、为什么」。涉及事故修复时，把复现方式写进 PR 描述；值得留档的踩坑请补到 `references/lessons.md`。
