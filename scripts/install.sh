#!/usr/bin/env bash
# =============================================================================
# install.sh — 首次初始化脚本（带进度显示）
# 支持：macOS (Apple Silicon / Intel) + Linux (x86_64 / arm64)
# 功能：
#   1. 检测并安装 uv（Python 包管理工具）
#   2. 按系统/架构下载 MinIO 二进制到 bin/（国内镜像：dl.minio.org.cn）
#   3. 下载 MinIO 客户端 mc 到 bin/（国内镜像：dl.minio.org.cn）
#   4. uv sync --python 3.12 创建后端虚拟环境并安装依赖（腾讯云 PyPI 镜像）
#   5. 检测并安装 Node.js LTS（通过 nvm，腾讯云镜像）
#   6. npm install 安装前端依赖（腾讯云 npm 镜像）
#   7. 生成 backend/.env（若不存在）
#
# 镜像策略（均为国内加速，失败时自动 fallback 到官方源）：
#   MinIO 服务端 / mc：dl.minio.org.cn（MinIO 官方中国加速节点）
#   Python 包（PyPI） ：mirrors.tencent.com/pypi/simple/（腾讯云）
#   npm 包            ：mirrors.tencent.com/npm/（腾讯云）
#   uv 安装器         ：gitee.com 镜像
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# ─── 颜色 & 符号 ─────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

TICK="${GREEN}✔${NC}"
CROSS="${RED}✘${NC}"
ARROW="${CYAN}▶${NC}"
DASH="${DIM}─${NC}"

log_step()    { echo -e "\n${BOLD}${BLUE}[$1/$TOTAL_STEPS]${NC} ${BOLD}$2${NC}"; }
log_info()    { echo -e "  ${ARROW} $*"; }
log_success() { echo -e "  ${TICK}  $*"; }
log_warn()    { echo -e "  ${YELLOW}⚠${NC}  $*"; }
log_error()   { echo -e "  ${CROSS}  ${RED}$*${NC}"; }
log_detail()  { echo -e "  ${DIM}   $*${NC}"; }

TOTAL_STEPS=7

# ─── 进度条 ───────────────────────────────────────────────────────────────────
# 用法：show_progress <当前值> <总值> <标签>
show_progress() {
    local current=$1 total=$2 label="${3:-}"
    local width=40
    local filled=$(( current * width / total ))
    local empty=$(( width - filled ))
    local pct=$(( current * 100 / total ))
    local bar=""
    for ((i=0; i<filled; i++)); do bar+="█"; done
    for ((i=0; i<empty;  i++)); do bar+="░"; done
    # \r 回到行首覆盖刷新（不换行）
    printf "\r  ${CYAN}[%s]${NC} %3d%%  %s " "$bar" "$pct" "$label"
}

# curl 下载并实时显示进度条
# 用法：download_with_progress <url> <目标文件> <显示名>
download_with_progress() {
    local url="$1" dest="$2" label="${3:-downloading}"
    local tmp="${dest}.tmp"

    # 先获取文件大小（HEAD 请求）
    local total_bytes=0
    total_bytes=$(curl -sI --connect-timeout 10 "$url" 2>/dev/null \
        | grep -i "content-length" | tail -1 | tr -d '[:space:]' \
        | cut -d: -f2 || echo "0")
    total_bytes="${total_bytes:-0}"

    if [[ "$total_bytes" -gt 0 ]]; then
        # 已知文件大小 → 实时进度条
        curl -fL --connect-timeout 15 --retry 2 \
            -o "$tmp" "$url" \
            --progress-bar 2>&1 | _draw_curl_progress "$label" "$total_bytes" &
        local curl_pid=$!
        # 用 curl 内置 --progress-bar 输出，不需要额外 polling
        wait "$curl_pid" 2>/dev/null || true
        # 如果上面的 pipe 方式在不同系统表现不一，改用简单方式
        # 直接用 curl --progress-bar（终端会显示进度），再清行
        rm -f "$tmp"
        echo ""  # 进度条后换行
        curl -fL --connect-timeout 15 --retry 2 \
            --progress-bar \
            -o "$dest" "$url"
    else
        # 未知大小 → spinner
        (
            local spin=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
            local i=0
            while kill -0 $$ 2>/dev/null; do
                printf "\r  ${CYAN}%s${NC}  下载中... %s" "${spin[$((i % ${#spin[@]}))]}" "$label"
                sleep 0.1
                (( i++ ))
            done
        ) &
        local spin_pid=$!
        curl -fsSL --connect-timeout 15 --retry 2 -o "$dest" "$url"
        kill "$spin_pid" 2>/dev/null || true
        wait "$spin_pid" 2>/dev/null || true
        echo ""
    fi
}

# curl --progress-bar 已经是最佳内置方案，封装辅助函数清理输出
_curl_download() {
    local url="$1" dest="$2" label="${3:-}"
    [[ -n "$label" ]] && echo -e "  ${ARROW} 下载: ${BOLD}$label${NC}"
    curl -fL --connect-timeout 15 --retry 2 \
        --progress-bar \
        -o "$dest" "$url"
    # curl --progress-bar 输出到 stderr，最后一行停在进度行，补一个换行
    echo ""
}

# ─── 检测系统和架构 ───────────────────────────────────────────────────────────
detect_platform() {
    local os arch
    os="$(uname -s | tr '[:upper:]' '[:lower:]')"
    arch="$(uname -m)"

    case "$os" in
        darwin) os="darwin" ;;
        linux)  os="linux"  ;;
        *)
            log_error "不支持的操作系统: $os"
            exit 1
            ;;
    esac

    case "$arch" in
        x86_64)         arch="amd64" ;;
        aarch64|arm64)  arch="arm64" ;;
        *)
            log_error "不支持的 CPU 架构: $arch"
            exit 1
            ;;
    esac

    echo "${os}-${arch}"
}

# ─── 步骤 1：安装 uv ──────────────────────────────────────────────────────────
# ─── uv 安装方式（三级 fallback）──────────────────────────────────────────────
# 方案1（首选）：pip install uv，使用腾讯云 PyPI 镜像，国内最稳定
# 方案2：GitHub releases 官方 installer（302 可达，部分服务器可用）
# 方案3（最后）：astral.sh 官方（需翻墙或走代理）
UV_INSTALLER_GITHUB="https://github.com/astral-sh/uv/releases/latest/download/uv-installer.sh"
UV_INSTALLER_OFFICIAL="https://astral.sh/uv/install.sh"
TENCENT_PYPI_SIMPLE="https://mirrors.tencent.com/pypi/simple/"

install_uv() {
    log_step 1 "安装 uv（Python 包管理工具）"

    if command -v uv &>/dev/null; then
        log_success "uv 已安装，跳过  →  $(uv --version)"
        return
    fi

    # ── 方案1：pip install uv（腾讯云 PyPI，国内最稳定）──────────────────────
    log_info "尝试方案1：pip install uv（腾讯云 PyPI 镜像）..."
    if command -v pip3 &>/dev/null || command -v pip &>/dev/null; then
        local pip_cmd="pip3"
        command -v pip3 &>/dev/null || pip_cmd="pip"
        if "$pip_cmd" install uv -i "$TENCENT_PYPI_SIMPLE" --quiet 2>/dev/null; then
            export PATH="$HOME/.local/bin:$PATH"
            if command -v uv &>/dev/null; then
                log_success "uv 安装成功（pip + 腾讯云 PyPI）  →  $(uv --version)"
                return
            fi
        fi
        log_warn "方案1 失败，尝试方案2..."
    else
        log_warn "pip 未找到，跳过方案1，尝试方案2..."
    fi

    # ── 方案2：GitHub releases 官方 installer ──────────────────────────────────
    log_info "尝试方案2：GitHub releases installer..."
    local installer="/tmp/uv-installer-$$.sh"
    if _curl_download "$UV_INSTALLER_GITHUB" "$installer" "uv-installer.sh（GitHub releases）" 2>/dev/null; then
        sh "$installer" 2>&1 | while IFS= read -r line; do log_detail "$line"; done
        rm -f "$installer"
        export PATH="$HOME/.local/bin:$PATH"
        if command -v uv &>/dev/null; then
            log_success "uv 安装成功（GitHub releases）  →  $(uv --version)"
            return
        fi
    fi
    log_warn "方案2 失败，尝试方案3（官方，可能需要网络代理）..."

    # ── 方案3：astral.sh 官方 ──────────────────────────────────────────────────
    log_info "尝试方案3：astral.sh 官方安装器..."
    if _curl_download "$UV_INSTALLER_OFFICIAL" "$installer" "uv-installer.sh（官方）"; then
        sh "$installer" 2>&1 | while IFS= read -r line; do log_detail "$line"; done
        rm -f "$installer"
        export PATH="$HOME/.local/bin:$PATH"
        if command -v uv &>/dev/null; then
            log_success "uv 安装成功（官方源）  →  $(uv --version)"
            return
        fi
    fi
    rm -f "$installer"

    log_error "三种方式均失败，请手动安装 uv：https://docs.astral.sh/uv/getting-started/installation/"
    log_error "或执行：pip install uv -i https://mirrors.tencent.com/pypi/simple/"
    exit 1
}

# ─── 步骤 2：下载 MinIO 二进制 ────────────────────────────────────────────────
MINIO_MIRROR_CN="https://dl.minio.org.cn/server/minio/release"
MINIO_MIRROR_OFFICIAL="https://dl.min.io/server/minio/release"

download_minio() {
    local platform="$1"
    local bin_dir="$PROJECT_ROOT/bin"
    local minio_bin="$bin_dir/minio"
    mkdir -p "$bin_dir"

    log_step 2 "下载 MinIO 服务端 ($platform)"

    if [[ -x "$minio_bin" ]]; then
        log_success "MinIO 已存在，跳过下载  →  $minio_bin"
        return
    fi

    local url_cn="${MINIO_MIRROR_CN}/${platform}/minio"
    local url_official="${MINIO_MIRROR_OFFICIAL}/${platform}/minio"
    local tmp="${minio_bin}.tmp"

    log_info "镜像：dl.minio.org.cn（国内）"
    if _curl_download "$url_cn" "$tmp" "minio（dl.minio.org.cn）"; then
        mv "$tmp" "$minio_bin"
        chmod +x "$minio_bin"
        log_success "MinIO 下载完成（国内镜像）"
    else
        log_warn "国内镜像失败，回退到官方源..."
        rm -f "$tmp"
        if _curl_download "$url_official" "$tmp" "minio（官方）"; then
            mv "$tmp" "$minio_bin"
            chmod +x "$minio_bin"
            log_success "MinIO 下载完成（官方源）"
        else
            log_error "MinIO 下载失败，请手动下载：$url_official"
            exit 1
        fi
    fi

    log_detail "版本: $($minio_bin --version 2>/dev/null | head -1)"
}

# ─── 步骤 3：下载 mc（MinIO 客户端）─────────────────────────────────────────
MC_MIRROR_CN="https://dl.minio.org.cn/client/mc/release"
MC_MIRROR_OFFICIAL="https://dl.min.io/client/mc/release"

download_mc() {
    local platform="$1"
    local bin_dir="$PROJECT_ROOT/bin"
    local mc_bin="$bin_dir/mc"

    log_step 3 "下载 mc (MinIO 客户端 $platform)"

    if [[ -x "$mc_bin" ]]; then
        log_success "mc 已存在，跳过下载  →  $mc_bin"
        return
    fi

    local url_cn="${MC_MIRROR_CN}/${platform}/mc"
    local url_official="${MC_MIRROR_OFFICIAL}/${platform}/mc"
    local tmp="${mc_bin}.tmp"

    log_info "镜像：dl.minio.org.cn（国内）"
    if _curl_download "$url_cn" "$tmp" "mc（dl.minio.org.cn）"; then
        mv "$tmp" "$mc_bin"
        chmod +x "$mc_bin"
        log_success "mc 下载完成（国内镜像）"
    else
        log_warn "国内镜像失败，回退到官方源..."
        rm -f "$tmp"
        if _curl_download "$url_official" "$tmp" "mc（官方）"; then
            mv "$tmp" "$mc_bin"
            chmod +x "$mc_bin"
            log_success "mc 下载完成（官方源）"
        else
            log_warn "mc 下载失败（非必需），可手动下载：$url_official"
            rm -f "$tmp"
        fi
    fi
}

# ─── 步骤 4：后端 Python 依赖 ─────────────────────────────────────────────────
TENCENT_PYPI="https://mirrors.tencent.com/pypi/simple/"

setup_backend() {
    local backend_dir="$PROJECT_ROOT/backend"

    log_step 4 "安装 Python 后端依赖（Python 3.12 + uv + 腾讯云 PyPI 镜像）"

    if [[ ! -f "$backend_dir/pyproject.toml" ]]; then
        log_warn "backend/pyproject.toml 不存在，跳过后端依赖安装"
        return
    fi

    export PATH="$HOME/.local/bin:$PATH"
    cd "$backend_dir"

    log_info "执行: uv sync --python 3.12"
    log_info "PyPI 镜像: $TENCENT_PYPI"
    echo ""

    # uv sync 本身会输出安装进度（彩色包列表），直接透传显示
    UV_INDEX_URL="$TENCENT_PYPI" uv sync --python 3.12 2>&1 | while IFS= read -r line; do
        echo "    $line"
    done

    echo ""
    log_success "后端依赖安装完成（.venv 已创建，Python 3.12）"
    cd "$PROJECT_ROOT"
}

# ─── 步骤 5：Node.js 安装（若未安装）────────────────────────────────────────
# 使用 nvm（Node Version Manager）安装 Node.js LTS
# nvm 安装器：国内用腾讯镜像，失败 fallback 官方
NVM_DIR_DEFAULT="$HOME/.nvm"
NODE_VERSION="20"       # nvm 安装目标版本（LTS）
# Vite 7 / @vitejs/plugin-react 5 要求 node ^20.19.0 || >=22.12.0
# 用"20.19.0"作为 20.x 分支的最低精确版本
NODE_MIN_VERSION="20.19.0"
NEED_LEGACY_DEPS=false # 全局标志：node 版本不足时 npm install 改用 --legacy-peer-deps

# 版本比较：semver_gte <a> <b>  ← 若 a >= b 返回 0（true）
semver_gte() {
    local a="$1" b="$2"
    # 按 . 分割，逐段比较
    local IFS=.
    local pa=($a) pb=($b)
    local i
    for i in 0 1 2; do
        local va="${pa[$i]:-0}" vb="${pb[$i]:-0}"
        if (( va > vb )); then return 0; fi
        if (( va < vb )); then return 1; fi
    done
    return 0  # 完全相等也算 >=
}

install_node() {
    log_step 5 "检测并安装 Node.js"

    if command -v node &>/dev/null; then
        local cur_ver
        cur_ver=$(node -v 2>/dev/null | sed 's/^v//')  # e.g. 20.18.1

        if semver_gte "$cur_ver" "$NODE_MIN_VERSION"; then
            log_success "Node.js 已安装且满足要求（>= v${NODE_MIN_VERSION}）  →  v$cur_ver"
            return
        fi

        # ── 版本不满足，询问用户 ──────────────────────────────────────────────
        echo ""
        log_warn "当前 Node.js 版本 v$cur_ver 低于最低要求 v${NODE_MIN_VERSION}"
        log_warn "项目依赖（Vite 7 / @vitejs/plugin-react 5）要求 Node.js ^20.19.0 || >=22.12.0"
        echo ""
        echo -e "  请选择处理方式："
        echo -e "  ${BOLD}[1]${NC} 升级 Node.js 到 v20.19 LTS（推荐，通过 nvm 安装）"
        echo -e "  ${BOLD}[2]${NC} 保持当前版本 v$cur_ver，尝试以兼容模式安装依赖（--legacy-peer-deps）"
        echo ""
        local choice
        read -rp "  请输入选择 [1/2]（默认1）: " choice
        choice="${choice:-1}"

        if [[ "$choice" == "2" ]]; then
            log_warn "保持 Node.js v$cur_ver，将使用 --legacy-peer-deps 安装兼容依赖"
            log_warn "部分功能可能受限，建议后续升级到 v${NODE_MIN_VERSION}+"
            NEED_LEGACY_DEPS=true
            return
        fi

        log_info "用户选择升级，继续安装 Node.js 20.19 LTS..."
    fi

    # ── 通过 nvm 安装目标版本 ──────────────────────────────────────────────────
    log_info "未检测到满足条件的 Node.js，尝试通过 nvm 安装 Node.js ${NODE_VERSION} LTS..."

    if [[ ! -s "$NVM_DIR_DEFAULT/nvm.sh" ]]; then
        log_info "正在安装 nvm..."
        local nvm_install_cn="https://gitee.com/mirrors/nvm/raw/master/install.sh"
        local nvm_install_official="https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh"
        local nvm_tmp="/tmp/nvm-installer-$$.sh"

        if curl -fsSL --connect-timeout 15 "$nvm_install_cn" -o "$nvm_tmp" 2>/dev/null; then
            log_info "使用 gitee 镜像安装 nvm..."
        else
            log_warn "gitee 镜像失败，回退到官方源..."
            if ! curl -fsSL --connect-timeout 15 "$nvm_install_official" -o "$nvm_tmp"; then
                log_error "nvm 下载失败，请手动安装 Node.js >= ${NODE_MIN_MAJOR}：https://nodejs.org"
                NEED_LEGACY_DEPS=true   # 已有旧版 node，降级尝试
                return
            fi
        fi
        PROFILE=/dev/null bash "$nvm_tmp" 2>&1 | while IFS= read -r line; do log_detail "$line"; done
        rm -f "$nvm_tmp"
    fi

    export NVM_DIR="${NVM_DIR:-$NVM_DIR_DEFAULT}"
    # shellcheck source=/dev/null
    [[ -s "$NVM_DIR/nvm.sh" ]] && source "$NVM_DIR/nvm.sh"

    if ! command -v nvm &>/dev/null 2>&1; then
        log_error "nvm 加载失败，请手动安装 Node.js >= ${NODE_MIN_MAJOR}：https://nodejs.org"
        log_warn "安装完成后重新运行 bash scripts/install.sh"
        return 1
    fi

    log_info "正在安装 Node.js ${NODE_VERSION} LTS（通过 nvm + 腾讯云镜像）..."
    NVM_NODEJS_ORG_MIRROR="https://mirrors.tencent.com/nodejs-release" \
        nvm install "$NODE_VERSION" 2>&1 | while IFS= read -r line; do log_detail "$line"; done

    nvm use "$NODE_VERSION" &>/dev/null
    nvm alias default "$NODE_VERSION" &>/dev/null

    if command -v node &>/dev/null; then
        log_success "Node.js 安装成功  →  $(node -v)"
        log_warn "提示：nvm 仅在当前 session 生效，如需永久生效请在 ~/.zshrc 或 ~/.bashrc 中添加："
        log_warn "  export NVM_DIR=\"\$HOME/.nvm\""
        log_warn "  [ -s \"\$NVM_DIR/nvm.sh\" ] && source \"\$NVM_DIR/nvm.sh\""
    else
        log_error "Node.js 安装失败，请手动安装：https://nodejs.org"
        NEED_LEGACY_DEPS=true
    fi
}

# ─── 步骤 6：前端 npm 依赖 ────────────────────────────────────────────────────
TENCENT_NPM="https://mirrors.tencent.com/npm/"

setup_frontend() {
    local frontend_dir="$PROJECT_ROOT/frontend"

    log_step 6 "安装前端依赖（npm + 腾讯云 npm 镜像）"

    if [[ ! -d "$frontend_dir" ]]; then
        log_warn "frontend/ 目录不存在，跳过前端依赖安装"
        return
    fi

    # 若 nvm 已在本步骤初始化，确保 node 可用
    if ! command -v node &>/dev/null; then
        export NVM_DIR="${NVM_DIR:-$NVM_DIR_DEFAULT}"
        # shellcheck source=/dev/null
        [[ -s "$NVM_DIR/nvm.sh" ]] && source "$NVM_DIR/nvm.sh" 2>/dev/null || true
    fi

    if ! command -v node &>/dev/null; then
        log_warn "未检测到 Node.js，跳过前端依赖安装（步骤5 安装失败？）"
        return
    fi

    local node_ver
    node_ver=$(node -v 2>/dev/null)
    log_info "Node.js 版本: $node_ver"
    log_info "npm 镜像: $TENCENT_NPM"

    # ── 修复 npm cache 权限（常见于 sudo 操作后遗留的 root 文件）──────────────
    local npm_cache
    npm_cache=$(npm config get cache 2>/dev/null || echo "$HOME/.npm")
    if [[ -d "$npm_cache" ]] && find "$npm_cache" -maxdepth 0 -not -user "$(id -u)" 2>/dev/null | grep -q .; then
        log_warn "检测到 npm 缓存目录存在权限问题，正在修复..."
        sudo chown -R "$(id -u):$(id -g)" "$npm_cache" 2>/dev/null && \
            log_success "npm 缓存权限已修复" || \
            log_warn "权限修复失败（无 sudo 权限），如 npm 安装失败请手动执行：sudo chown -R $(id -u):$(id -g) $npm_cache"
    fi

    # 根据 NEED_LEGACY_DEPS 标志决定是否加 --legacy-peer-deps
    local npm_extra_flags=""
    if [[ "$NEED_LEGACY_DEPS" == "true" ]]; then
        npm_extra_flags="--legacy-peer-deps"
        log_warn "当前 Node.js 版本较低，使用 --legacy-peer-deps 安装兼容依赖"
        log_warn "如遇功能异常，建议升级至 Node.js v${NODE_MIN_VERSION}+ 后重新执行 bash scripts/install.sh"
    fi
    echo ""

    cd "$frontend_dir"
    # npm install 输出透传（会显示包数量/进度）
    # shellcheck disable=SC2086
    if ! npm install --registry "$TENCENT_NPM" $npm_extra_flags 2>&1 | while IFS= read -r line; do
            echo "    $line"
        done
    then
        log_warn "腾讯云镜像失败，回退到官方源..."
        echo ""
        # shellcheck disable=SC2086
        npm install $npm_extra_flags 2>&1 | while IFS= read -r line; do
            echo "    $line"
        done
    fi

    echo ""
    log_success "前端依赖安装完成"
    cd "$PROJECT_ROOT"
}

# ─── 步骤 7：生成配置文件 & 目录 ─────────────────────────────────────────────
setup_env_and_dirs() {
    log_step 7 "生成配置文件 & 目录"

    # .env
    local env_file="$PROJECT_ROOT/backend/.env"
    if [[ -f "$env_file" ]]; then
        log_success ".env 已存在，跳过生成  →  $env_file"
    else
        cat > "$env_file" <<'EOF'
# 服务端口
BACKEND_PORT=13011

# MinIO 配置
MINIO_ENDPOINT=localhost:13012
MINIO_ACCESS_KEY=admin
MINIO_SECRET_KEY=password123
MINIO_BUCKET=graph-compare

# 数据库
DATABASE_URL=sqlite:///./graph_compare.db

# 跨域（允许前端 13010 端口）
CORS_ORIGINS=http://localhost:13010
EOF
        log_success ".env 已生成  →  $env_file"
    fi

    # 运行时目录
    for d in minio-data logs .pids; do
        mkdir -p "$PROJECT_ROOT/$d"
    done
    log_success "运行时目录已就绪  →  minio-data/ logs/ .pids/"
}

# ─── 主流程 ───────────────────────────────────────────────────────────────────
main() {
    clear
    echo ""
    echo -e "${BOLD}${BLUE}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${BLUE}║   Graph Compare Platform — 初始化安装   ║${NC}"
    echo -e "${BOLD}${BLUE}╚══════════════════════════════════════════╝${NC}"

    PLATFORM=$(detect_platform)
    echo ""
    echo -e "  ${DIM}平台：${NC}${BOLD}$PLATFORM${NC}"
    echo -e "  ${DIM}项目：${NC}${BOLD}$PROJECT_ROOT${NC}"
    echo -e "  ${DIM}步骤：${NC}${BOLD}$TOTAL_STEPS 个${NC}"
    echo ""
    echo -e "  ${DIM}$(printf '─%.0s' {1..42})${NC}"

    # 记录开始时间
    local start_time=$SECONDS

    install_uv
    download_minio "$PLATFORM"
    download_mc "$PLATFORM"
    setup_backend
    install_node
    setup_frontend
    setup_env_and_dirs

    local elapsed=$(( SECONDS - start_time ))
    local mins=$(( elapsed / 60 ))
    local secs=$(( elapsed % 60 ))

    echo ""
    echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${GREEN}║            🎉 安装完成！                 ║${NC}"
    echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${DIM}耗时：${NC}${BOLD}${mins}m${secs}s${NC}"
    echo ""
    echo -e "  ${BOLD}下一步：${NC}"
    echo -e "  ${ARROW}  启动所有服务   ${BOLD}bash scripts/start.sh${NC}"
    echo -e "  ${ARROW}  停止所有服务   ${BOLD}bash scripts/stop.sh${NC}"
    echo ""
    echo -e "  ${BOLD}服务地址：${NC}"
    echo -e "  ${TICK}  前端          ${CYAN}http://localhost:13010${NC}"
    echo -e "  ${TICK}  后端 API      ${CYAN}http://localhost:13011${NC}"
    echo -e "  ${TICK}  API 文档      ${CYAN}http://localhost:13011/docs${NC}"
    echo -e "  ${TICK}  MinIO         ${CYAN}http://localhost:13012${NC}"
    echo -e "  ${TICK}  MinIO 控制台  ${CYAN}http://localhost:13013${NC}"
    echo ""
}

main "$@"
