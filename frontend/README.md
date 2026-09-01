# Biscuit Studio 前端

Biscuit Studio 的标准 Vite + React 19 前端，负责选题输入、脚本预览、Seedance 任务管理、字幕状态和视频结果展示。

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
VITE_API_BASE_URL=http://localhost:8000
```
