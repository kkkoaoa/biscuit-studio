# Frontend

Biscuit Studio 前端，负责选题输入、脚本预览、Seedance 任务管理、字幕状态和视频结果展示。

## 开发

```bash
pnpm install
cp .env.example .env.local
pnpm dev
```

## 构建

```bash
pnpm build
```

主要环境变量：

```dotenv
REACT_APP_API_BASE_URL=http://localhost:8000
```
