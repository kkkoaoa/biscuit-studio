# Biscuit Studio 🐶

> 小饼干英语视频工坊：从英语知识点到 30 秒竖屏教学视频的一站式 AI 创作工具。
> 已上线，网址可见：http://1.13.175.246/

![Biscuit Studio](docs/biscuit-studio-overview.png)

## 功能

- 根据英语知识点生成教学脚本、分镜、字幕稿和视频 Prompt
- 对语法、搭配、例外、词源和英语文化背景进行自检
- 调用 Seedance 生成固定角色的 9:16 无字幕视频
- 将审校后的字幕稿与真实口播自动打轴
- 使用 FFmpeg 烧录中文字幕并高亮英文关键词
- 支持批量选题、任务队列和失败重试
- 浏览器本地保存 7 天、最多 30 条历史记录

## 技术栈

- Frontend：Vite、React 19、TypeScript、Lucide React
- Backend：FastAPI、HTTPX、Uvicorn
- Media：FFmpeg、Noto Sans CJK
- AI：火山方舟 Responses API、Seedance、豆包语音字幕服务
- Deployment：Docker Compose、Nginx

## 快速启动

普通电脑或云服务器只需安装 Git、Docker 和 Docker Compose。

```bash
git clone https://github.com/kkkoaoa/biscuit-studio.git
cd biscuit-studio
git checkout aime/1788264454-open-source-release
cp .env.example .env
```

在 `.env` 中填写字幕服务凭证：

```dotenv
SUBTITLE_APP_ID=
SUBTITLE_ACCESS_TOKEN=
CORS_ORIGINS=http://localhost,http://127.0.0.1
```

启动：

```bash
docker compose up -d --build
```

浏览器打开：

```text
http://localhost
```

在网页中填写自己的：

- 火山方舟 API Key
- 语言模型推理接入点 ID
- Seedance 推理接入点 ID

API Key 只保存在当前浏览器会话，不会写入仓库。

停止服务：

```bash
docker compose down
```

查看日志：

```bash
docker compose logs -f
```

## 不使用 Docker

### 后端

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

本机需要安装 FFmpeg，并确保存在支持中文的 Noto CJK 字体。

### 前端

```bash
cd frontend
corepack enable
pnpm install
cp .env.example .env.local
pnpm dev
```

前端开发环境在 `.env.local` 中配置：

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

访问 `http://localhost:5173`。

## 项目结构

```text
biscuit-studio/
├── frontend/
│   ├── src/                 # React 页面、样式与资源
│   ├── Dockerfile           # Vite 构建 + Nginx 运行
│   └── nginx.conf           # 静态站点与 /api 反向代理
├── backend/
│   ├── main.py              # FastAPI API
│   ├── prompts/             # 小饼干英语编剧规范
│   ├── fonts/               # 中文字幕字体
│   └── Dockerfile           # Python + FFmpeg 运行环境
├── docker-compose.yml
└── .env.example
```

## 主要流程

```text
输入知识点与场景
      ↓
大模型生成脚本、分镜、字幕稿
      ↓
Seedance 生成无字幕原片
      ↓
提取音轨并按审校稿进行字幕打轴
      ↓
FFmpeg 烧录中文字幕与英文重点词
      ↓
下载无字幕原片和带字幕成片
```

## 配置与安全

不要提交以下内容：

- 火山方舟 API Key
- 字幕服务 Access Token / Secret Key
- 腾讯云 SecretId / SecretKey
- `.env`、`subtitle_secrets.py`
- SSH 私钥和服务器密码

仓库的 `.gitignore` 和 `.dockerignore` 已排除这些文件。公开仓库只保留空白配置示例。

## 当前限制

- 字幕服务凭证由部署者统一配置在后端。
- 带字幕视频当前以临时文件返回；刷新后 Blob 地址会失效。
- 历史记录保存在当前浏览器，无法跨设备同步。
- 第一版固定生成 30 秒竖屏视频。

## Roadmap

- [ ] 接入 COS，对原片、成片和 SRT 保存 7 天
- [ ] 增加后台异步任务，关闭网页后继续生成
- [ ] 增加更多字幕模板和知识类型
- [ ] 增加可选的用户额度与并发限制

## 内容说明

AI 生成的英语教学内容应在正式发布前进行人工复核。第三方模型与云服务的使用须遵守相应平台规则。
