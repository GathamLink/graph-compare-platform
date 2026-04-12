#!/usr/bin/env bash
# =============================================================================
# restart.sh — 重启指定服务（默认只重启后端）
# 用法：
#   bash scripts/restart.sh              # 只重启后端（最常用）
#   bash scripts/restart.sh --backend    # 同上
#   bash scripts/restart.sh --frontend   # 只重启前端
#   bash scripts/restart.sh --minio      # 只重启 MinIO
#   bash scripts/restart.sh --all        # 重启全部服务
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_info()    { echo -e "  ${CYAN}▶${NC}  $*"; }
log_success() { echo -e "  ${GREEN}✔${NC}  $*"; }
log_warn()    { echo -e "  ${YELLOW}⚠${NC}  $*"; }
log_error()   { echo -e "  ${RED}✘${NC}  ${RED}$*${NC}"; }
log_step()    { echo -e "\n${BOLD}${BLUE}[$1]${NC} ${BOLD}$2${NC}"; }

# ─── 参数解析 ─────────────────────────────────────────────────────────────────
RESTART_BACKEND=false
RESTART_FRONTEND=false
RESTART_MINIO=false

# 无参数时默认只重启后端
if [[ $# -eq 0 ]]; then
    RESTART_BACKEND=true
else
    for arg in "$@"; do
        case "$arg" in
            --backend)  RESTART_BACKEND=true  ;;
            --frontend) RESTART_FRONTEND=true ;;
            --minio)    RESTART_MINIO=true    ;;
            --all)      RESTART_BACKEND=true; RESTART_FRONTEND=true; RESTART_MINIO=true ;;
            *)          log_warn "未知参数: $arg" ;;
        esac
    done
fi

# ─── 端口配置（与 start.sh 保持一致）─────────────────────────────────────────
PORT_MINIO_API=13012
PORT_MINIO_CONSOLE=13013
PORT_BACKEND=13011
PORT_FRONTEND=13010

PID_DIR="$PROJECT_ROOT/.pids"
LOG_DIR="$PROJECT_ROOT/logs"

mkdir -p "$PID_DIR" "$LOG_DIR"

# ─── 停止单个服务 ─────────────────────────────────────────────────────────────
stop_service() {
    local name="$1" pid_key="$2" pattern="${3:-}"
    local pid_file="$PID_DIR/${pid_key}.pid"

    if [[ -f "$pid_file" ]]; then
        local pid
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            # 等待最多 5s
            local i=0
            while kill -0 "$pid" 2>/dev/null && [[ $i -lt 5 ]]; do
                sleep 1; (( i++ ))
            done
            kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
            log_success "$name 已停止 (PID: $pid)"
        else
            log_warn "$name 进程不存在 (PID: $pid)，清理残留文件"
        fi
        rm -f "$pid_file"
    elif [[ -n "$pattern" ]]; then
        local pids
        pids=$(pgrep -f "$pattern" 2>/dev/null || true)
        if [[ -n "$pids" ]]; then
            echo "$pids" | xargs kill 2>/dev/null || true
            log_success "$name 已停止 (按进程名匹配)"
        else
            log_warn "$name 未在运行，跳过停止"
        fi
    else
        log_warn "$name PID 文件不存在，跳过"
    fi
}

# ─── 等待端口释放 ─────────────────────────────────────────────────────────────
wait_port_free() {
    local port="$1" name="$2"
    local i=0
    while lsof -iTCP:"$port" -sTCP:LISTEN -n -P &>/dev/null 2>&1; do
        sleep 0.5; (( i++ ))
        if [[ $i -ge 10 ]]; then
            log_warn "端口 $port ($name) 释放超时，继续尝试启动..."
            return
        fi
    done
}

# ─── 等待端口监听 ─────────────────────────────────────────────────────────────
wait_for_port() {
    local port="$1" name="$2" max="${3:-30}"
    local i=0
    while ! lsof -iTCP:"$port" -sTCP:LISTEN -n -P &>/dev/null 2>&1; do
        sleep 1; (( i++ ))
        if [[ $i -ge $max ]]; then
            log_error "$name 启动超时 (${max}s)，请查看日志: $LOG_DIR/"
            return 1
        fi
    done
    log_success "$name 已就绪 (端口 $port)"
}

# ─── 启动后端 ─────────────────────────────────────────────────────────────────
start_backend() {
    local backend_dir="$PROJECT_ROOT/backend"
    export PATH="$HOME/.local/bin:$PATH"

    if ! command -v uv &>/dev/null; then
        log_error "未找到 uv，请先运行 bash scripts/install.sh"
        exit 1
    fi

    log_info "启动 FastAPI 后端 (端口 $PORT_BACKEND)..."
    cd "$backend_dir"
    uv run uvicorn main:app \
        --host 0.0.0.0 \
        --port "$PORT_BACKEND" \
        --reload \
        > "$LOG_DIR/backend.log" 2>&1 &
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
    log_info "启动 Vite 前端 (端口 $PORT_FRONTEND)..."
    cd "$frontend_dir"
    npm run dev > "$LOG_DIR/frontend.log" 2>&1 &
    echo $! > "$PID_DIR/frontend.pid"
    cd "$PROJECT_ROOT"
    wait_for_port "$PORT_FRONTEND" "Vite" 30
}

# ─── 启动 MinIO ───────────────────────────────────────────────────────────────
start_minio() {
    local minio_bin="$PROJECT_ROOT/bin/minio"
    if [[ ! -x "$minio_bin" ]]; then
        log_error "MinIO 二进制不存在，请先运行 bash scripts/install.sh"
        exit 1
    fi
    log_info "启动 MinIO (端口 $PORT_MINIO_API / $PORT_MINIO_CONSOLE)..."
    MINIO_ROOT_USER=admin MINIO_ROOT_PASSWORD=password123 \
        "$minio_bin" server "$PROJECT_ROOT/minio-data" \
        --address ":${PORT_MINIO_API}" \
        --console-address ":${PORT_MINIO_CONSOLE}" \
        > "$LOG_DIR/minio.log" 2>&1 &
    echo $! > "$PID_DIR/minio.pid"
    wait_for_port "$PORT_MINIO_API" "MinIO" 30
}

# ─── 主流程 ───────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo -e "${BOLD}${BLUE}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${BLUE}║   Graph Compare Platform — 重启服务     ║${NC}"
    echo -e "${BOLD}${BLUE}╚══════════════════════════════════════════╝${NC}"

    # ── 停止阶段 ──
    if [[ "$RESTART_BACKEND"  == "true" ]]; then
        log_step "1" "停止 FastAPI 后端"
        stop_service "FastAPI 后端" "backend" "uvicorn"
        wait_port_free "$PORT_BACKEND" "FastAPI"
    fi
    if [[ "$RESTART_FRONTEND" == "true" ]]; then
        log_step "-" "停止 Vite 前端"
        stop_service "Vite 前端" "frontend" "vite"
        wait_port_free "$PORT_FRONTEND" "Vite"
    fi
    if [[ "$RESTART_MINIO"    == "true" ]]; then
        log_step "-" "停止 MinIO"
        stop_service "MinIO" "minio" "minio server"
        wait_port_free "$PORT_MINIO_API" "MinIO"
    fi

    # ── 启动阶段 ──
    if [[ "$RESTART_MINIO"    == "true" ]]; then
        log_step "2" "启动 MinIO"
        start_minio
    fi
    if [[ "$RESTART_BACKEND"  == "true" ]]; then
        log_step "3" "启动 FastAPI 后端"
        start_backend
    fi
    if [[ "$RESTART_FRONTEND" == "true" ]]; then
        log_step "4" "启动 Vite 前端"
        start_frontend
    fi

    echo ""
    echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${GREEN}║             重启完成！                   ║${NC}"
    echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════╝${NC}"
    echo ""
    [[ "$RESTART_BACKEND"  == "true" ]] && echo -e "  ${GREEN}✔${NC}  后端 API     ${CYAN}http://localhost:${PORT_BACKEND}${NC}"
    [[ "$RESTART_BACKEND"  == "true" ]] && echo -e "  ${GREEN}✔${NC}  API 文档     ${CYAN}http://localhost:${PORT_BACKEND}/docs${NC}"
    [[ "$RESTART_FRONTEND" == "true" ]] && echo -e "  ${GREEN}✔${NC}  前端         ${CYAN}http://localhost:${PORT_FRONTEND}${NC}"
    [[ "$RESTART_MINIO"    == "true" ]] && echo -e "  ${GREEN}✔${NC}  MinIO        ${CYAN}http://localhost:${PORT_MINIO_API}${NC}"
    echo ""
    echo -e "  日志目录: ${CYAN}$LOG_DIR/${NC}"
    echo ""
}

main "$@"
