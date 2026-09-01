# Backend

Biscuit Studio 后端，负责语言模型调用、Seedance 任务代理、音频提取、字幕打轴和 FFmpeg 字幕烧录。

## 开发

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## 私密配置

```dotenv
SUBTITLE_APP_ID=
SUBTITLE_ACCESS_TOKEN=
```

不要提交真实密钥、`.env` 或 `subtitle_secrets.py`。
