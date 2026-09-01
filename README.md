# Biscuit Studio 🐶

> 小饼干英语视频工坊：从英语知识点到 30 秒竖屏教学视频的一站式 AI 创作工具。

![Biscuit Studio character](frontend/src/assets/biscuit-reference.png)

## 在线预览

- Web Demo: https://054495fe0ee4.aime-app.bytedance.net

> 当前预览环境使用 Aime SSO。面向公网的无登录部署版本正在整理中。

## 功能亮点

- **AI 编剧**：根据英语知识点和场景生成标题、口播脚本、分镜、字幕稿与视频提示词。
- **知识审校**：检查语法、搭配、例外、词源和文化背景，避免为了趣味牺牲准确性。
- **固定角色**：使用“小饼干”参考图与角色约束，提升多条视频中的形象一致性。
- **Seedance 视频生成**：调用视频模型生成 30 秒、9:16 的无字教学视频。
- **自动字幕**：提取音轨，将审校后的字幕稿与真实口播打轴，生成 SRT。
- **字幕烧录**：通过 FFmpeg 生成中文字幕，并突出显示英文关键词。
- **批量生产**：支持按“知识点 | 场景”批量创建任务。
- **本地历史**：浏览器保存最近 7 天、最多 30 条任务记录。

## 工作流程

```text
输入英语知识点
      ↓
语言模型生成脚本、分镜和字幕稿
      ↓
Seedance 生成无字幕原片
      ↓
提取音轨并进行字幕打轴
      ↓
FFmpeg 烧录重点高亮字幕
      ↓
下载无字幕原片与带字幕成片
```

## 项目结构

```text
biscuit-studio/
├── frontend/   # React 19 + EdenX 前端
└── backend/    # FastAPI + FFmpeg 后端
```

## 技术栈

### Frontend

- React 19
- TypeScript
- EdenX
- Tailwind CSS
- Lucide React
- pnpm

### Backend

- Python 3.8+
- FastAPI
- Uvicorn
- HTTPX
- FFmpeg / imageio-ffmpeg
- 火山方舟 Responses API
- Seedance 视频生成 API
- 豆包语音字幕服务

## 本地启动

### 1. 启动后端

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

字幕生成需要在后端环境中配置：

```dotenv
SUBTITLE_APP_ID=
SUBTITLE_ACCESS_TOKEN=
```

也可以在本地创建 `backend/subtitle_secrets.py`，但不要提交该文件：

```python
SUBTITLE_APP_ID = ""
SUBTITLE_ACCESS_TOKEN = ""
```

### 2. 启动前端

```bash
cd frontend
pnpm install
cp .env.example .env.local
pnpm dev
```

设置后端地址：

```dotenv
REACT_APP_API_BASE_URL=http://localhost:8000
```

浏览器中还需要填写个人的火山方舟 API Key，以及语言模型、Seedance 推理接入点 ID。API Key 仅保存在当前浏览器会话中。

## 生产构建

```bash
cd frontend
pnpm build
```

构建产物位于 `frontend/dist/`。

## 安全说明

请勿向仓库提交以下内容：

- 火山方舟 API Key
- 字幕服务 Access Token / Secret Key
- 腾讯云 SecretId / SecretKey
- `.env`、`subtitle_secrets.py`
- SSH 私钥和服务器密码
- 用户生成的视频与本地历史数据

仓库仅保留不含真实凭证的 `.env.example`。

## 当前限制

- 当前在线预览仍依赖 Aime SSO 环境。
- 带字幕视频暂未持久化到对象存储，页面刷新后临时 Blob 地址会失效。
- 浏览器历史无法跨设备同步。
- 第一版固定生成 30 秒竖屏视频。

## Roadmap

- [ ] 腾讯云服务器公开部署
- [ ] COS 保存原片、成片和 SRT，并在 7 天后自动清理
- [ ] 移除预览环境 SSO，支持公网无登录使用
- [ ] 后台异步任务和失败重试
- [ ] 更丰富的字幕模板和知识类型

## 免责声明

本项目生成的英语教学内容应在发布前进行人工复核。第三方模型与云服务的使用须遵守相应平台规则。
