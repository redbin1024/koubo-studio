#!/usr/bin/env bash
# 口播工坊 Koubo Studio 一键安装器
#
# 推荐用法（公开仓库）：
#   curl -fsSL https://raw.githubusercontent.com/redbin1024/koubo-studio/main/install.sh | bash
#
# 从本地 checkout 安装：
#   bash install.sh
#
# 全部装上（含离线语音模型、Node 与 capcut-cli）：
#   bash install.sh --full
#
# 只装 Python 核心，不动系统依赖：
#   bash install.sh --minimal
set -euo pipefail

APP="口播工坊 Koubo Studio"
NAME="koubo-studio"
REPO="${KOUBO_REPO:-redbin1024/koubo-studio}"
REF="${KOUBO_REF:-main}"
MODE="recommended"          # minimal | recommended | full
INSTALL_DIR=""
LOCAL_SOURCE=0
DRY_RUN=0
FORCE=0
UNINSTALL=0
WITH_SYSTEM=1
WITH_FONT=1
WITH_NARRATION=1
WITH_WHISPER=0
WITH_CAPCUT=1
WITH_SKILL_LINKS=1
WITH_VENV=1

if [ -t 1 ]; then
  C_RESET=$'\033[0m'; C_BLUE=$'\033[38;5;39m'; C_GREEN=$'\033[38;5;42m'
  C_YELLOW=$'\033[38;5;220m'; C_RED=$'\033[38;5;203m'; C_DIM=$'\033[2m'
else
  C_RESET=""; C_BLUE=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_DIM=""
fi

info() { printf '%s▸%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok()   { printf '%s✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s⚠%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
die()  { printf '%s✗%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }
dim()  { printf '%s  %s%s\n' "$C_DIM" "$*" "$C_RESET"; }

run() {
  if [ "$DRY_RUN" = 1 ]; then
    printf '  %s[dry-run] %s%s\n' "$C_DIM" "$*" "$C_RESET"
  else
    "$@"
  fi
}

usage() {
  cat <<'EOF'
口播工坊 Koubo Studio 一键安装

用法：
  bash install.sh [选项]

选项：
  --dir PATH           安装目录（默认 ~/.agents/skills/koubo-studio）
  --repo OWNER/NAME    仓库（默认 redbin1024/koubo-studio）
  --ref REF            分支或标签（默认 main）
  --minimal            只装 Python 核心；不装系统依赖、字体、capcut、edge-tts
  --full               全部装齐：系统依赖、字体、edge-tts、faster-whisper、capcut-cli
  --no-system          不运行 Homebrew / apt 等系统包安装
  --no-font            不下载 / 安装中文字体
  --no-narration       不装 edge-tts
  --with-whisper       安装 faster-whisper（离线语音转写，体积较大）
  --no-capcut          不安装 capcut-cli（仍可出 mp4，出不了剪映草稿）
  --no-skill-links     不创建 Codex / Claude / Agents 的 skill 软链接
  --no-venv            不创建 .venv（使用当前 Python 环境）
  --force              覆盖同名软链接；更新时允许强拉
  --dry-run            只打印计划，不改动系统
  --uninstall          卸载：删除软链接；安装目录默认保留，加 --force 一并删除
  -y, --yes            不询问（非交互模式下自动成立）
  -h, --help           显示本帮助

环境变量：
  KOUBO_HOME           安装目录（等价于 --dir）
  KOUBO_REPO           仓库（等价于 --repo）
  KOUBO_REF            分支（等价于 --ref）
  KOUBO_PYTHON         指定 Python 3.10+ 解释器
  KOUBO_NO_SYSTEM=1    等价于 --no-system
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) INSTALL_DIR="${2:-}"; shift 2 ;;
    --dir=*) INSTALL_DIR="${1#*=}"; shift ;;
    --repo) REPO="${2:-}"; shift 2 ;;
    --repo=*) REPO="${1#*=}"; shift ;;
    --ref) REF="${2:-}"; shift 2 ;;
    --ref=*) REF="${1#*=}"; shift ;;
    --minimal) MODE="minimal"; WITH_SYSTEM=0; WITH_FONT=0; WITH_NARRATION=0
               WITH_CAPCUT=0; WITH_WHISPER=0; shift ;;
    --full) MODE="full"; WITH_SYSTEM=1; WITH_FONT=1; WITH_NARRATION=1
            WITH_CAPCUT=1; WITH_WHISPER=1; shift ;;
    --no-system) WITH_SYSTEM=0; shift ;;
    --no-font) WITH_FONT=0; shift ;;
    --no-narration) WITH_NARRATION=0; shift ;;
    --with-whisper) WITH_WHISPER=1; shift ;;
    --no-capcut) WITH_CAPCUT=0; shift ;;
    --no-skill-links) WITH_SKILL_LINKS=0; shift ;;
    --no-venv) WITH_VENV=0; shift ;;
    --force) FORCE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -y|--yes) shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数：$1（--help 看用法）" ;;
  esac
done

[ -n "${KOUBO_NO_SYSTEM:-}" ] && WITH_SYSTEM=0

expand_path() {
  local p="$1"
  case "$p" in
    "~") p="$HOME" ;;
    "~/"*) p="$HOME/${p#\~/}" ;;
  esac
  case "$p" in
    /*) ;;
    *) p="$(pwd)/$p" ;;
  esac
  printf '%s\n' "$p"
}

# 安装脚本从 checkout 直接跑时，默认装回这个 checkout；从 curl 管道跑时装到 skills 目录。
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
if [ -n "$SCRIPT_PATH" ] && [ -f "$SCRIPT_PATH" ]; then
  SCRIPT_DIR="$(cd -P "$(dirname "$SCRIPT_PATH")" && pwd)"
  if [ -f "$SCRIPT_DIR/SKILL.md" ] && [ -f "$SCRIPT_DIR/scripts/run_all.py" ]; then
    LOCAL_SOURCE=1
  fi
else
  SCRIPT_DIR=""
fi

if [ -z "$INSTALL_DIR" ]; then
  if [ -n "${KOUBO_HOME:-}" ]; then
    INSTALL_DIR="$KOUBO_HOME"
  elif [ "$LOCAL_SOURCE" = 1 ]; then
    INSTALL_DIR="$SCRIPT_DIR"
  else
    INSTALL_DIR="$HOME/.agents/skills/$NAME"
  fi
fi
INSTALL_DIR="$(expand_path "$INSTALL_DIR")"
CANONICAL_DIR="$HOME/.agents/skills/$NAME"

# ---------------------------------------------------------------- 卸载

remove_link() {
  local target="$1" expected="$2"
  if [ -L "$target" ]; then
    local current
    current="$(readlink "$target" || true)"
    case "$current" in
      "$expected"|"$expected"/*)
        run rm -f "$target"
        [ "$DRY_RUN" = 1 ] || ok "移除 $target"
        ;;
      *) dim "保留 ${target}（指向 ${current}）" ;;
    esac
  fi
}

if [ "$UNINSTALL" = 1 ]; then
  info "卸载 $APP"
  if [ "$FORCE" = 1 ] && ! { [ "$LOCAL_SOURCE" = 1 ] && [ "$INSTALL_DIR" = "$SCRIPT_DIR" ]; }; then
    case "$INSTALL_DIR" in
      "$HOME"/*) ;;
      *) die "拒绝删除 HOME 之外的目录：$INSTALL_DIR" ;;
    esac
    [ "$INSTALL_DIR" != "$HOME" ] || die "拒绝删除 HOME"
  fi
  remove_link "$HOME/.local/bin/koubo" "$INSTALL_DIR/bin/koubo"
  remove_link "$CANONICAL_DIR" "$INSTALL_DIR"
  remove_link "$HOME/.codex/skills/$NAME" "$INSTALL_DIR"
  remove_link "$HOME/.claude/skills/$NAME" "$INSTALL_DIR"
  if [ "$LOCAL_SOURCE" = 1 ] && [ "$INSTALL_DIR" = "$SCRIPT_DIR" ]; then
    dim "安装目录就是当前 checkout，保留源码和 .venv"
  elif [ "$FORCE" = 1 ]; then
    run rm -rf "$INSTALL_DIR"
    [ "$DRY_RUN" = 1 ] || ok "已删除 $INSTALL_DIR"
  else
    dim "安装目录保留：${INSTALL_DIR}（加 --force 一并删除）"
  fi
  exit 0
fi

if [ "$DRY_RUN" = 1 ]; then
  cat <<EOF
$APP 安装计划（dry-run）

  仓库      https://github.com/$REPO
  分支      $REF
  安装目录  $INSTALL_DIR
  模式      $MODE
  系统依赖  $([ "$WITH_SYSTEM" = 1 ] && echo 安装 || echo 跳过)
  中文字体  $([ "$WITH_FONT" = 1 ] && echo 安装 || echo 跳过)
  edge-tts  $([ "$WITH_NARRATION" = 1 ] && echo 安装 || echo 跳过)
  whisper   $([ "$WITH_WHISPER" = 1 ] && echo 安装 || echo 跳过)
  capcut    $([ "$WITH_CAPCUT" = 1 ] && echo 安装 || echo 跳过)
  skill 链接 $([ "$WITH_SKILL_LINKS" = 1 ] && echo 创建 || echo 跳过)

没有做任何改动。去掉 --dry-run 即可真正安装。
EOF
  exit 0
fi

# ---------------------------------------------------------------- 取代码

install_source() {
  if [ "$LOCAL_SOURCE" = 1 ]; then
    if [ "$INSTALL_DIR" = "$SCRIPT_DIR" ]; then
      ok "使用当前 checkout：$INSTALL_DIR"
      return
    fi
    if git -C "$SCRIPT_DIR" rev-parse --git-dir >/dev/null 2>&1; then
      info "从本地 checkout 复制已跟踪文件 → $INSTALL_DIR"
      mkdir -p "$INSTALL_DIR"
      git -C "$SCRIPT_DIR" archive HEAD | tar -x -C "$INSTALL_DIR"
      return
    fi
    die "本地安装到其他目录需要 $SCRIPT_DIR 是 git 仓库；直接 bash install.sh 即可原地安装"
  fi

  if [ -d "$INSTALL_DIR/.git" ]; then
    info "更新已有安装：$INSTALL_DIR"
    if [ "$FORCE" = 1 ]; then
      git -C "$INSTALL_DIR" fetch --depth 1 origin "$REF"
      git -C "$INSTALL_DIR" reset --hard "origin/$REF"
    else
      git -C "$INSTALL_DIR" pull --ff-only || warn "git pull 失败（可能有本地修改）；继续使用现有代码"
    fi
    return
  fi

  if [ -f "$INSTALL_DIR/SKILL.md" ]; then
    warn "目录里已有安装：${INSTALL_DIR}；保留现有文件，不自动覆盖"
    dim "要重装：先备份/删除该目录，再重跑安装器"
    return
  fi
  [ ! -e "$INSTALL_DIR" ] || die "目标已存在且不是安装目录：$INSTALL_DIR"
  mkdir -p "$(dirname "$INSTALL_DIR")"

  if command -v git >/dev/null 2>&1; then
    info "克隆 https://github.com/${REPO}（${REF}）"
    git clone --depth 1 --branch "$REF" "https://github.com/$REPO.git" "$INSTALL_DIR"
  else
    info "没有 git，改用源码压缩包"
    local tmp repo_name
    tmp="$(mktemp -d)"
    repo_name="${REPO##*/}"
    curl -fsSL --retry 3 --connect-timeout 15 \
      "https://github.com/$REPO/archive/refs/heads/$REF.tar.gz" -o "$tmp/src.tar.gz"
    tar -xzf "$tmp/src.tar.gz" -C "$tmp"
    mv "$tmp/$repo_name-$REF" "$INSTALL_DIR"
    rm -rf "$tmp"
  fi
}

# ---------------------------------------------------------------- Python

find_python() {
  local c
  for c in "${KOUBO_PYTHON:-}" python3.13 python3.12 python3.11 python3.10 python3; do
    [ -n "$c" ] || continue
    command -v "$c" >/dev/null 2>&1 || continue
    if "$c" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
        >/dev/null 2>&1; then
      printf '%s\n' "$c"
      return 0
    fi
  done
  return 1
}

ensure_python() {
  local py version
  if py="$(find_python)"; then
    PYTHON_BIN="$py"
    version="$("$py" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
    ok "Python：${version}（${py}）"
    return
  fi
  if [ "$WITH_SYSTEM" = 1 ] && command -v brew >/dev/null 2>&1; then
    info "没有 Python 3.10+，尝试 brew install python@3.12"
    brew install python@3.12
    local prefix
    prefix="$(brew --prefix python@3.12 2>/dev/null || true)"
    if [ -n "$prefix" ] && [ -x "$prefix/bin/python3.12" ]; then
      PYTHON_BIN="$prefix/bin/python3.12"
      ok "Python：$PYTHON_BIN"
      return
    fi
  fi
  die "找不到 Python 3.10+。macOS: brew install python@3.12；Ubuntu: sudo apt install python3.12 python3.12-venv"
}

# ---------------------------------------------------------------- 系统依赖与字体

have_font() {
  local f
  for f in "$HOME/Library/Fonts/NotoSansCJKsc-Black.otf" \
           "/Library/Fonts/NotoSansCJKsc-Black.otf" \
           "$INSTALL_DIR/fonts/NotoSansCJKsc-Black.otf"; do
    [ -f "$f" ] && return 0
  done
  return 1
}

install_font() {
  [ "$WITH_FONT" = 1 ] || return 0
  if have_font; then
    ok "中文字体已存在"
    return 0
  fi
  local dest_dir dest
  dest_dir="$INSTALL_DIR/fonts"
  dest="$dest_dir/NotoSansCJKsc-Black.otf"
  mkdir -p "$dest_dir"
  info "下载 Noto Sans CJK SC Black（约 17MB，装进安装目录，不动系统字体）"
  if curl -fL --retry 3 --connect-timeout 15 \
      "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Black.otf" \
      -o "$dest.part" 2>/dev/null; then
    mv "$dest.part" "$dest"
    ok "字体：$dest"
    return 0
  fi
  rm -f "$dest.part"
  warn "字体下载失败"
  if command -v brew >/dev/null 2>&1; then
    info "改用 brew install --cask font-noto-sans-cjk-sc"
    brew install --cask font-noto-sans-cjk-sc || warn "字体 cask 安装失败"
  else
    warn "请手动安装 Noto Sans CJK SC，或把字体放进 $dest_dir/"
  fi
}

install_system_deps() {
  [ "$WITH_SYSTEM" = 1 ] || return 0
  if [ "$(uname -s)" = "Darwin" ]; then
    if ! command -v brew >/dev/null 2>&1; then
      warn "没有 Homebrew；跳过系统依赖。需要时手动安装：https://brew.sh"
      return 0
    fi
    local ff=""
    if command -v ffmpeg >/dev/null 2>&1; then
      ff="$(command -v ffmpeg)"
    elif [ -x /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg ]; then
      ff="/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
    elif [ -x /usr/local/opt/ffmpeg-full/bin/ffmpeg ]; then
      ff="/usr/local/opt/ffmpeg-full/bin/ffmpeg"
    fi
    if [ -z "$ff" ]; then
      info "安装 ffmpeg-full（带 libass）"
      brew install ffmpeg-full || warn "ffmpeg-full 安装失败；普通 ffmpeg 也能渲染默认字幕层"
    elif ! "$ff" -hide_banner -filters 2>/dev/null | grep -q ' subtitles '; then
      warn "现有 ffmpeg 没有 libass；默认 captions.burn=layer 不受影响"
    fi
    if [ "$WITH_CAPCUT" = 1 ] && ! command -v node >/dev/null 2>&1; then
      if [ "$MODE" = "full" ]; then
        info "安装 Node（capcut-cli 需要 ≥18）"
        brew install node || warn "Node 安装失败"
      else
        warn "没有 Node；跳过 capcut-cli（可用 --full 安装 Node 后再跑一次）"
      fi
    fi
  else
    if ! command -v ffmpeg >/dev/null 2>&1; then
      warn "没有 ffmpeg。Debian/Ubuntu: sudo apt install ffmpeg fonts-noto-cjk"
    fi
    if ! command -v ffprobe >/dev/null 2>&1; then
      warn "没有 ffprobe；同上，随 ffmpeg 一起装"
    fi
  fi
}

install_capcut() {
  [ "$WITH_CAPCUT" = 1 ] || return 0
  if command -v capcut >/dev/null 2>&1 || [ -x "$INSTALL_DIR/vendor/npm/node_modules/.bin/capcut" ]; then
    ok "capcut-cli 已可用"
    return 0
  fi
  if ! command -v npm >/dev/null 2>&1; then
    warn "没有 npm；跳过 capcut-cli。草稿步骤会失败，mp4 仍可渲染"
    return 0
  fi
  local major
  major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
  if [ "${major:-0}" -lt 18 ]; then
    warn "Node $major < 18；跳过 capcut-cli"
    return 0
  fi
  info "安装 capcut-cli 到安装目录（不污染全局 npm）"
  mkdir -p "$INSTALL_DIR/vendor/npm" "$INSTALL_DIR/.cache/npm"
  if npm install --prefix "$INSTALL_DIR/vendor/npm" \
        --cache "$INSTALL_DIR/.cache/npm" \
        --no-audit --no-fund --loglevel=error capcut-cli; then
    ok "capcut：$INSTALL_DIR/vendor/npm/node_modules/.bin/capcut"
    return 0
  fi
  warn "capcut-cli 安装失败。可手动：npm install -g capcut-cli"
  return 0
}

# ---------------------------------------------------------------- venv 与依赖

install_python_deps() {
  local py="$1" req
  if [ "$WITH_VENV" = 1 ]; then
    if [ -x "$INSTALL_DIR/.venv/bin/python" ]; then
      ok "复用已有 venv：$INSTALL_DIR/.venv"
    else
      info "创建 venv：$INSTALL_DIR/.venv"
      "$py" -m venv "$INSTALL_DIR/.venv"
    fi
    py="$INSTALL_DIR/.venv/bin/python"
  else
    warn "跳过 venv，依赖装进当前 Python 环境：$py"
  fi
  PY="$py"
  "$py" -m pip install -q --upgrade pip --disable-pip-version-check || warn "pip 升级失败，继续"
  req="$INSTALL_DIR/requirements.txt"
  [ -f "$req" ] || die "缺 $req"
  info "安装核心依赖：numpy / Pillow"
  "$py" -m pip install -q --disable-pip-version-check -r "$req"
  if [ "$WITH_NARRATION" = 1 ]; then
    if "$py" -m pip install -q --disable-pip-version-check \
          -r "$INSTALL_DIR/requirements-narration.txt"; then
      ok "解说旁白依赖：edge-tts"
    else
      warn "edge-tts 安装失败；解说旁白不可用，其余功能不受影响"
    fi
  fi
  if [ "$WITH_WHISPER" = 1 ]; then
    info "安装离线语音转写：faster-whisper（体积较大）"
    "$py" -m pip install -q --disable-pip-version-check \
      -r "$INSTALL_DIR/requirements-transcribe.txt" \
      || warn "faster-whisper 安装失败；--auto-captions 不可用"
  fi
}

# ---------------------------------------------------------------- 链接

link_path() {
  local source="$1" target="$2"
  if [ -L "$target" ]; then
    if [ "$(readlink "$target" 2>/dev/null || true)" = "$source" ]; then
      ok "链接已存在：$target"
      return 0
    fi
    if [ "$FORCE" = 1 ]; then
      rm -f "$target"
    else
      warn "跳过 ${target}（已指向别处；加 --force 覆盖）"
      return 0
    fi
  elif [ -e "$target" ]; then
    warn "跳过 ${target}（已存在且不是软链接）"
    return 0
  fi
  mkdir -p "$(dirname "$target")"
  ln -s "$source" "$target"
  ok "链接：$target → $source"
}

install_links() {
  chmod +x "$INSTALL_DIR/bin/koubo" 2>/dev/null || true
  chmod +x "$INSTALL_DIR/install.sh" 2>/dev/null || true
  mkdir -p "$HOME/.local/bin"
  link_path "$INSTALL_DIR/bin/koubo" "$HOME/.local/bin/koubo"
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) warn "~/.local/bin 不在 PATH；先执行：export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
  esac

  [ "$WITH_SKILL_LINKS" = 1 ] || return 0
  if [ "$INSTALL_DIR" != "$CANONICAL_DIR" ]; then
    link_path "$INSTALL_DIR" "$CANONICAL_DIR"
  fi
  if [ -d "$HOME/.codex" ] || command -v codex >/dev/null 2>&1; then
    link_path "$INSTALL_DIR" "$HOME/.codex/skills/$NAME"
  fi
  if [ -d "$HOME/.claude" ] || command -v claude >/dev/null 2>&1; then
    link_path "$INSTALL_DIR" "$HOME/.claude/skills/$NAME"
  fi
}

# ---------------------------------------------------------------- 主流程

printf '\n%s\n' "${C_BLUE}${APP}${C_RESET}  ${C_DIM}一键安装${C_RESET}"
printf '  %s\n\n' "${C_DIM}仓库 github.com/$REPO · 模式 $MODE${C_RESET}"

install_source
[ -f "$INSTALL_DIR/SKILL.md" ] || die "安装目录里没有 SKILL.md，代码不完整：$INSTALL_DIR"

ensure_python
install_system_deps
install_font
install_capcut
install_python_deps "$PYTHON_BIN"
install_links

# 代码里可能没有执行位（zip 下载常见），统一补上
chmod +x "$INSTALL_DIR"/scripts/*.py 2>/dev/null || true

info "运行环境自检"
set +e
"$PY" "$INSTALL_DIR/scripts/doctor.py"
DOCTOR_RC=$?
set -e
if [ "$DOCTOR_RC" -ne 0 ]; then
  warn "自检有失败项；按上面的 → 修好后再跑 koubo doctor"
fi

printf '\n%s\n' "${C_GREEN}${APP} 安装完成${C_RESET}"
printf '  安装目录  %s\n' "$INSTALL_DIR"
printf '  命令      koubo\n'
printf '  自检      koubo doctor\n\n'
printf '  下一步：\n'
printf '    koubo new my-video --video /path/to/口播.mp4 --reference /path/to/参考片.mp4\n'
printf '    # 编辑 my-video/input/captions.srt\n'
printf '    koubo run my-video\n\n'
printf '  Agent 里直接说：「用口播工坊把这条口播按参考片风格剪出来」。\n'
printf '  文档：https://github.com/%s\n\n' "$REPO"
