# Graph Compare Platform

图片对比平台 — 以任务为单位，对两组图片进行一一配对差异分析。

## 服务端口

| 服务 | 端口 |
|------|------|
| 前端 Dev Server | http://localhost:13010 |
| 后端 FastAPI | http://localhost:13011 |
| API 文档（Swagger） | http://localhost:13011/docs |
| MinIO API | http://localhost:13012 |
| MinIO 控制台 | http://localhost:13013 |

## 快速开始

### 前置要求

- macOS 或 Linux（Apple Silicon / Intel / x86_64 / arm64）
- Node.js >= 18
- 网络可访问（首次下载 MinIO 二进制和 Python 依赖）

### 首次安装

```bash
bash scripts/install.sh
```

安装内容：
- 自动检测系统架构，下载对应 MinIO 二进制到 `bin/`
- 安装 `uv`（Python 包管理工具）
- 执行 `uv sync --python 3.12` 创建后端虚拟环境并安装所有依赖
- 执行 `npm install` 安装前端依赖
- 生成 `backend/.env` 环境变量配置文件

### 启动服务

```bash
bash scripts/start.sh
```

可选参数：
```bash
bash scripts/start.sh --no-frontend   # 只启动 MinIO + 后端
bash scripts/start.sh --no-minio      # 跳过 MinIO（已在运行）
```

### 重启服务（最常用：改完后端代码后重启）

```bash
bash scripts/restart.sh              # 只重启后端（默认，最常用）
bash scripts/restart.sh --backend    # 同上
bash scripts/restart.sh --frontend   # 只重启前端
bash scripts/restart.sh --minio      # 只重启 MinIO
bash scripts/restart.sh --all        # 重启全部服务
```

### 停止服务

```bash
bash scripts/stop.sh
```

可选参数：
```bash
bash scripts/stop.sh --frontend   # 只停止前端
bash scripts/stop.sh --backend    # 只停止后端
bash scripts/stop.sh --minio      # 只停止 MinIO
```

### 手动启动（调试用）

```bash
# 1. MinIO
MINIO_ROOT_USER=admin MINIO_ROOT_PASSWORD=password123 \
  ./bin/minio server ./minio-data --address ":13012" --console-address ":13013"

# 2. 后端
cd backend && uv run uvicorn main:app --host 0.0.0.0 --port 13011 --reload

# 3. 前端
cd frontend && npm run dev
```

### 查看日志

```bash
tail -f logs/minio.log
tail -f logs/backend.log
tail -f logs/frontend.log
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript + Vite + Tailwind CSS + shadcn/ui |
| 后端 | Python 3.12 + FastAPI + uv |
| 数据库 | SQLite + SQLAlchemy |
| 对象存储 | MinIO（本地部署，S3 兼容） |
| 图像处理 | OpenCV + scikit-image（SSIM）+ Pillow |

## 目录结构

```
Graph_Compare_Platform/
├── scripts/        # 启动脚本
├── bin/            # MinIO 二进制（.gitignore）
├── minio-data/     # MinIO 数据目录（.gitignore）
├── logs/           # 日志（.gitignore）
├── backend/        # FastAPI 后端
│   ├── main.py
│   ├── models.py
│   ├── schemas.py
│   ├── database.py
│   ├── routers/
│   └── services/
├── frontend/       # React 前端
└── .gitignore
```
