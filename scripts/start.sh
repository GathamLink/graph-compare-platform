#!/usr/bin/env bash
# =============================================================================
# start.sh — 一键启动所有服务
# 服务：MinIO + FastAPI 后端 + Vite 前端
# 可选参数：
#   --no-minio     跳过启动 MinIO
#   --no-backend   跳过启动 FastAPI
#   --no-frontend  跳过启动 Vite
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 端口配置
PORT_MINIO_API=13012
PORT_MINIO_CONSOLE=13013
PORT_BACKEND=13011
PORT_FRONTEND=13010

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_success() { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*"; }

# ─── 参数解析 ─────────────────────────────────────────────────────────────────
START_MINIO=true
START_BACKEND=true
START_FRONTEND=true

for arg in "$@"; do
    case "$arg" in
        --no-minio)    START_MINIO=false ;;
        --no-backend)  START_BACKEND=false ;;
        --no-frontend) START_FRONTEND=false ;;
        *) log_warn "未知参数: $arg" ;;
    esac
done

# ─── 目录准备 ─────────────────────────────────────────────────────────────────
mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/.pids" "$PROJECT_ROOT/minio-data"

PID_DIR="$PROJECT_ROOT/.pids"
LOG_DIR="$PROJECT_ROOT/logs"

# ─── 端口检测 ─────────────────────────────────────────────────────────────────
check_port() {
    local port="$1"
    local name="$2"
    if lsof -iTCP:"$port" -sTCP:LISTEN -n -P &>/dev/null 2>&1; then
        log_error "端口 $port 已被占用 ($name)，请先停止占用该端口的进程："
        lsof -iTCP:"$port" -sTCP:LISTEN -n -P 2>/dev/null | head -5
        return 1
    fi
    return 0
}

# ─── 等待服务启动 ─────────────────────────────────────────────────────────────
wait_for_port() {
    local port="$1"
    local name="$2"
    local max_wait="${3:-30}"
    local count=0
    log_info "等待 $name 就绪 (端口 $port)..."
    while ! lsof -iTCP:"$port" -sTCP:LISTEN -n -P &>/dev/null 2>&1; do
        sleep 1
        count=$((count + 1))
        if [[ $count -ge $max_wait ]]; then
            log_error "$name 启动超时 (${max_wait}s)，请查看日志: $LOG_DIR/"
            return 1
        fi
    done
    log_success "$name 已就绪"
}

# ─── 启动 MinIO ───────────────────────────────────────────────────────────────
start_minio() {
    local minio_bin="$PROJECT_ROOT/bin/minio"
    if [[ ! -x "$minio_bin" ]]; then
        log_error "MinIO 二进制不存在：$minio_bin，请先运行 bash scripts/install.sh"
        exit 1
    fi

    check_port "$PORT_MINIO_API" "MinIO API" || exit 1
    check_port "$PORT_MINIO_CONSOLE" "MinIO Console" || exit 1

    log_info "启动 MinIO..."
    MINIO_ROOT_USER=admin MINIO_ROOT_PASSWORD=password123 \
        "$minio_bin" server "$PROJECT_ROOT/minio-data" \
        --address ":${PORT_MINIO_API}" \
        --console-address ":${PORT_MINIO_CONSOLE}" \
        > "$LOG_DIR/minio.log" 2>&1 &
    echo $! > "$PID_DIR/minio.pid"

    wait_for_port "$PORT_MINIO_API" "MinIO" 30

    # 初始化 Bucket (通过 mc 或 curl)
    _init_bucket
}

_init_bucket() {
    local mc_bin="$PROJECT_ROOT/bin/mc"
    local bucket="graph-compare"

    if [[ -x "$mc_bin" ]]; then
        # 用 mc 初始化
        "$mc_bin" alias set local http://localhost:${PORT_MINIO_API} admin password123 --quiet 2>/dev/null || true
        "$mc_bin" mb --ignore-existing local/${bucket} 2>/dev/null || true
        "$mc_bin" anonymous set download local/${bucket} 2>/dev/null || true
        log_success "MinIO Bucket '$bucket' 已就绪 (公开读)"
    else
        log_info "mc 不可用，Bucket 将由后端首次请求时自动创建"
    fi
}

# ─── 启动后端 ─────────────────────────────────────────────────────────────────
start_backend() {
    local backend_dir="$PROJECT_ROOT/backend"
    export PATH="$HOME/.local/bin:$PATH"

    if ! command -v uv &>/dev/null; then
        log_error "未找到 uv，请先运行 bash scripts/install.sh"
        exit 1
    fi

    if [[ ! -d "$backend_dir/.venv" ]]; then
        log_warn "后端虚拟环境不存在，正在执行 uv sync --python 3.12..."
        cd "$backend_dir"
        uv sync --python 3.12
        cd "$PROJECT_ROOT"
    fi

    check_port "$PORT_BACKEND" "FastAPI 后端" || exit 1

    # 按日期命名日志文件（追加写入，不覆盖历史日志）
    local today
    today=$(date +%Y-%m-%d)
    local backend_log="$LOG_DIR/backend.${today}.log"
    # 同时维护一个 backend.log 软链，方便 tail -f logs/backend.log 使用
    ln -sf "backend.${today}.log" "$LOG_DIR/backend.log"

    log_info "启动 FastAPI 后端 (端口 $PORT_BACKEND)..."
    log_info "日志文件: $backend_log"
    cd "$backend_dir"
    uv run uvicorn main:app \
        --host 0.0.0.0 \
        --port "$PORT_BACKEND" \
        --reload \
        >> "$backend_log" 2>&1 &
    echo $! > "$PID_DIR/backend.pid"
    cd "$PROJECT_ROOT"

    wait_for_port "$PORT_BACKEND" "FastAPI" 30
}

# ─── 启动前端 ─────────────────────────────────────────────────────────────────
start_frontend() {
    local frontend_dir="$PROJECT_ROOT/frontend"
    if [[ ! -d "$frontend_dir" ]]; then
        log_warn "frontend/ 目录不存在，跳过前端启动"
        return
    fi

    if ! command -v node &>/dev/null; then
        log_warn "未检测到 Node.js，跳过前端启动"
        return
    fi

    if [[ ! -d "$frontend_dir/node_modules" ]]; then
        log_warn "前端依赖未安装，正在执行 npm install..."
        cd "$frontend_dir"
        npm install
        cd "$PROJECT_ROOT"
    fi

    check_port "$PORT_FRONTEND" "Vite 前端" || exit 1

    log_info "启动 Vite 前端 (端口 $PORT_FRONTEND)..."
    cd "$frontend_dir"
    npm run dev > "$LOG_DIR/frontend.log" 2>&1 &
    echo $! > "$PID_DIR/frontend.pid"
    cd "$PROJECT_ROOT"

    wait_for_port "$PORT_FRONTEND" "Vite" 30
}

# ─── 主流程 ───────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo "=========================================="
    echo "  Graph Compare Platform — 启动服务"
    echo "=========================================="
    echo ""

    [[ "$START_MINIO"    == "true" ]] && start_minio
    [[ "$START_BACKEND"  == "true" ]] && start_backend
    [[ "$START_FRONTEND" == "true" ]] && start_frontend

    echo ""
    echo "=========================================="
    log_success "所有服务已启动！"
    echo ""
    [[ "$START_FRONTEND" == "true" ]] && echo "  前端       http://localhost:${PORT_FRONTEND}"
    [[ "$START_BACKEND"  == "true" ]] && echo "  API 文档   http://localhost:${PORT_BACKEND}/docs"
    [[ "$START_MINIO"    == "true" ]] && echo "  MinIO 控制台 http://localhost:${PORT_MINIO_CONSOLE}"
    echo ""
    echo "  日志目录: $LOG_DIR/"
    echo "  停止服务: bash scripts/stop.sh"
    echo "=========================================="
    echo ""
}

main "$@"
