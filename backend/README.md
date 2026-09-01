# Backend

Biscuit Studio 的公开 FastAPI 后端，负责语言模型调用、Seedance 任务代理、音频提取、字幕打轴和 FFmpeg 字幕烧录。API 无需登录即可直接访问；调用第三方模型时，API Key 由请求体传入。

## 本地开发

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
set -a && source .env && set +a
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

服务启动后可访问：

- API 状态：`http://localhost:8000/api`
- 健康检查：`http://localhost:8000/api/v1/ping`
- OpenAPI 文档：`http://localhost:8000/api/docs`

## 环境变量

| 变量 | 必需 | 说明 |
| --- | --- | --- |
| `CORS_ORIGINS` | 否 | 逗号分隔的允许来源。默认允许 `localhost` 和 `127.0.0.1` 的 3000、5173 端口。生产环境应设置为实际站点来源。 |
| `SUBTITLE_APP_ID` | 字幕功能需要 | 字幕服务 App ID。 |
| `SUBTITLE_ACCESS_TOKEN` | 字幕功能需要 | 字幕服务访问令牌。 |

不要提交真实密钥、`.env` 或 `subtitle_secrets.py`。服务会在后端使用字幕凭据，不会在健康检查或响应中返回凭据内容。

## Docker

在仓库根目录执行：

```bash
cp backend/.env.example backend/.env
# 按需编辑 backend/.env，然后：
docker compose up --build
```

前端默认发布到 `http://localhost`，后端也可通过 `http://localhost:8000` 直接访问。根目录 Compose 配置需要 `frontend/Dockerfile`；该文件由前端容器化任务提供。

也可只构建并运行后端：

```bash
docker build -t biscuit-studio-backend ./backend
docker run --rm -p 8000:8000 --env-file backend/.env biscuit-studio-backend
```
