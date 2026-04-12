#!/usr/bin/env bash
# =============================================================================
# stop.sh — 一键停止所有服务
# 可选参数（不传则停止所有）：
#   --minio     只停止 MinIO
#   --backend   只停止 FastAPI
#   --frontend  只停止 Vite
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PID_DIR="$PROJECT_ROOT/.pids"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_success() { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }

# ─── 参数解析 ─────────────────────────────────────────────────────────────────
STOP_MINIO=false
STOP_BACKEND=false
STOP_FRONTEND=false
STOP_ALL=true

for arg in "$@"; do
    case "$arg" in
        --minio)    STOP_MINIO=true;    STOP_ALL=false ;;
        --backend)  STOP_BACKEND=true;  STOP_ALL=false ;;
        --frontend) STOP_FRONTEND=true; STOP_ALL=false ;;
        *) log_warn "未知参数: $arg" ;;
    esac
done

if [[ "$STOP_ALL" == "true" ]]; then
    STOP_MINIO=true
    STOP_BACKEND=true
    STOP_FRONTEND=true
fi

# ─── 停止单个服务 ─────────────────────────────────────────────────────────────
stop_service() {
    local name="$1"
    local pid_file="$PID_DIR/${2}.pid"
    local fallback_pattern="${3:-}"

    if [[ -f "$pid_file" ]]; then
        local pid
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            sleep 1
            # 若未退出，强制 kill
            if kill -0 "$pid" 2>/dev/null; then
                kill -9 "$pid" 2>/dev/null || true
            fi
            log_success "$name 已停止 (PID: $pid)"
        else
            log_warn "$name 进程不存在 (PID: $pid)"
        fi
        rm -f "$pid_file"
    elif [[ -n "$fallback_pattern" ]]; then
        # PID 文件不存在，按进程名兜底
        local pids
        pids=$(pgrep -f "$fallback_pattern" 2>/dev/null || true)
        if [[ -n "$pids" ]]; then
            echo "$pids" | xargs kill 2>/dev/null || true
            log_success "$name 已停止 (按进程名匹配)"
        else
            log_warn "$name 未在运行"
        fi
    else
        log_warn "$name PID 文件不存在，服务可能已停止"
    fi
}

# ─── 主流程 ───────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo "=========================================="
    echo "  Graph Compare Platform — 停止服务"
    echo "=========================================="
    echo ""

    [[ "$STOP_FRONTEND" == "true" ]] && stop_service "Vite 前端"   "frontend" "vite"
    [[ "$STOP_BACKEND"  == "true" ]] && stop_service "FastAPI 后端" "backend"  "uvicorn"
    [[ "$STOP_MINIO"    == "true" ]] && stop_service "MinIO"        "minio"    "minio server"

    echo ""
    log_success "完成"
    echo "=========================================="
    echo ""
}

main "$@"
