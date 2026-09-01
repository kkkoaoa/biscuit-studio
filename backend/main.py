import base64
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from functools import lru_cache
from typing import Any, Dict, List, Optional

import httpx
import imageio_ffmpeg
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

LOGGER = logging.getLogger(__name__)
JWT_HEADER = "x-jwt-token"
DEFAULT_JWT_SERVER = "cloud.bytedance.net"
DEFAULT_ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

try:
    from subtitle_secrets import SUBTITLE_ACCESS_TOKEN as FILE_SUBTITLE_ACCESS_TOKEN
    from subtitle_secrets import SUBTITLE_APP_ID as FILE_SUBTITLE_APP_ID
except ImportError:
    FILE_SUBTITLE_APP_ID = ""
    FILE_SUBTITLE_ACCESS_TOKEN = ""


def get_subtitle_credentials() -> Dict[str, str]:
    """Read server-side subtitle credentials without exposing them to the browser."""
    return {
        "app_id": os.environ.get("SUBTITLE_APP_ID", "").strip() or FILE_SUBTITLE_APP_ID.strip(),
        "access_token": os.environ.get("SUBTITLE_ACCESS_TOKEN", "").strip() or FILE_SUBTITLE_ACCESS_TOKEN.strip(),
    }


class UserResponse(BaseModel):
    username: str
    region: str
    name: str
    avatar_url: str
    terminated: bool


class CreateVideoRequest(BaseModel):
    api_key: str = Field(..., min_length=8)
    model: str = Field("ep-20260829130303-ddm7l", regex=r"^ep-")
    prompt: str = Field(..., min_length=10, max_length=12000)
    reference_image_url: Optional[str] = None
    duration: int = Field(30, ge=30, le=30)
    ratio: str = "9:16"
    resolution: str = "720p"
    generate_audio: bool = True
    watermark: bool = False
    seed: int = -1


class TaskStatusRequest(BaseModel):
    api_key: str = Field(..., min_length=8)
    task_id: str = Field(..., min_length=1)


class SubtitleSubmitRequest(BaseModel):
    video_url: str = Field(..., min_length=10, max_length=4000)
    expected_text: Optional[str] = Field(None, max_length=12000)


class SubtitleStatusRequest(BaseModel):
    task_id: str = Field(..., min_length=1, max_length=220)


class BurnSubtitlesRequest(BaseModel):
    video_url: str = Field(..., min_length=10, max_length=4000)
    utterances: List[Dict[str, Any]] = Field(..., min_items=1, max_items=200)


class ModelTestRequest(BaseModel):
    api_key: str = Field(..., min_length=8)
    model: str = Field(..., regex=r"^ep-")


class GenerateScriptRequest(BaseModel):
    api_key: str = Field(..., min_length=8)
    model: str = Field("ep-20260829134526-kk9fn", regex=r"^ep-")
    topic: str = Field(..., min_length=2, max_length=500)
    scene: str = Field("温暖明亮的生活场景", min_length=2, max_length=200)
    duration: int = Field(30, ge=30, le=30)


class ScriptResult(BaseModel):
    title: str
    script: str
    storyboard: str
    subtitles: str
    prompt: str


def get_jwt_userinfo_url() -> str:
    configured_url = os.environ.get("JWT_USERINFO_URL")
    if configured_url:
        return configured_url
    jwt_server = os.environ.get("JWT_SERVER", DEFAULT_JWT_SERVER).strip().rstrip("/")
    return "https://{}/auth/api/v1/userinfo".format(jwt_server)


async def fetch_user_info(token: str) -> Optional[UserResponse]:
    timeout_seconds = float(os.environ.get("JWT_USERINFO_TIMEOUT_SECONDS", "5"))
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, trust_env=False) as client:
            response = await client.get(get_jwt_userinfo_url(), headers={JWT_HEADER: token})
            response.raise_for_status()
            return UserResponse.parse_obj(response.json())
    except Exception as error:
        LOGGER.warning("Unable to resolve current user from JWT: %s", error)
        return None


async def auth_middleware(request: Request, call_next):
    public_paths = {"/api", "/api/v1/ping", "/reference/biscuit.png"}
    if request.method == "OPTIONS" or request.url.path in public_paths:
        return await call_next(request)
    token = request.headers.get(JWT_HEADER)
    if not token:
        return JSONResponse(status_code=403, content={"detail": "unauthorized: missing or invalid jwt token"})
    current_user = await fetch_user_info(token)
    if current_user is None:
        return JSONResponse(status_code=403, content={"detail": "unauthorized: missing or invalid jwt token"})
    request.state.current_user = current_user
    return await call_next(request)


def setup_permissions(app: FastAPI) -> None:
    app.middleware("http")(auth_middleware)


def ark_headers(api_key: str) -> Dict[str, str]:
    token = api_key.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return {
        "Authorization": "Bearer {}".format(token),
        "Content-Type": "application/json",
    }


def ark_error(response: httpx.Response) -> HTTPException:
    try:
        body = response.json()
        message = body.get("error", {}).get("message") or body.get("message") or response.text
    except Exception:
        message = response.text
    safe_message = (message or "火山方舟请求失败")[:1000]
    if "tokens per minute" in safe_message.lower() or "tpm" in safe_message.lower():
        return HTTPException(status_code=429, detail="语言模型 TPM 额度暂时已满，系统将自动等待后重试")
    # Do not leak Ark's 401 to the frontend SSO layer, which would trigger a
    # misleading login refresh and duplicate the generation request.
    client_status = 400 if 400 <= response.status_code < 500 else 502
    return HTTPException(status_code=client_status, detail="火山方舟：{}".format(safe_message))


def subtitle_headers() -> Dict[str, str]:
    credentials = get_subtitle_credentials()
    if not credentials["app_id"] or not credentials["access_token"]:
        raise HTTPException(status_code=503, detail="字幕服务尚未配置")
    return {
        "Authorization": "Bearer; {}".format(credentials["access_token"]),
    }


def subtitle_error(body: Dict[str, Any], fallback: str = "字幕服务请求失败") -> HTTPException:
    code = body.get("code")
    message = body.get("message") or fallback
    known = {
        1001: "字幕请求参数无效",
        1002: "字幕服务 Token 无效、过期或尚未授权该能力",
        1003: "字幕服务请求过于频繁",
        1004: "字幕服务额度不足",
        1010: "音频时长超出限制",
        1011: "音频文件过大",
        1012: "音频格式无效",
        1013: "音频静音或未识别出文本",
        1020: "字幕任务等待超时",
        1021: "字幕任务处理超时",
        1022: "字幕识别失败",
    }
    try:
        normalized_code = int(code)
    except (TypeError, ValueError):
        normalized_code = None
    safe_message = known.get(normalized_code, str(message))
    return HTTPException(status_code=400, detail="豆包语音：{}".format(safe_message[:1000]))


def clean_expected_subtitle_text(text: str) -> str:
    """Convert the reviewed subtitle draft into plain spoken text for alignment."""
    cleaned_lines: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*\d.、\s]+", "", line)
        line = re.sub(r"【重点】", "", line)
        line = re.sub(r"^【(?:画外男声|采访者|小饼干)】\s*[:：]?\s*", "", line)
        if line:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def format_srt_time(milliseconds: int) -> str:
    milliseconds = max(0, int(milliseconds))
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, millis = divmod(remainder, 1000)
    return "{:02d}:{:02d}:{:02d},{:03d}".format(hours, minutes, seconds, millis)


def utterances_to_srt(utterances: List[Dict[str, Any]]) -> str:
    blocks: List[str] = []
    for index, utterance in enumerate(utterances, start=1):
        text = str(utterance.get("text") or "").strip()
        if not text:
            continue
        start = format_srt_time(utterance.get("start_time") or 0)
        end = format_srt_time(utterance.get("end_time") or 0)
        blocks.append("{}\n{} --> {}\n{}".format(index, start, end, text))
    return "\n\n".join(blocks)


def format_ass_time(milliseconds: int) -> str:
    milliseconds = max(0, int(milliseconds))
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, millis = divmod(remainder, 1000)
    return "{}:{:02d}:{:02d}.{:02d}".format(hours, minutes, seconds, millis // 10)


def highlight_english_for_ass(text: str) -> str:
    safe = text.replace("{", "（").replace("}", "）").replace("\n", " ")
    pattern = r"[A-Za-z][A-Za-z0-9'’.-]*(?:\s+[A-Za-z][A-Za-z0-9'’.-]*)*"
    return re.sub(pattern, lambda match: r"{\c&H00A5FF&}" + match.group(0) + r"{\c&HFFFFFF&}", safe)


def utterances_to_ass(utterances: List[Dict[str, Any]]) -> str:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK SC,56,&H00FFFFFF,&H0000A5FF,&H00151515,&H90000000,-1,0,0,0,100,100,0,0,1,3,1,2,48,48,230,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines: List[str] = []
    for utterance in utterances:
        text = str(utterance.get("text") or "").strip()
        if not text:
            continue
        start = format_ass_time(utterance.get("start_time") or 0)
        end = format_ass_time(utterance.get("end_time") or 0)
        lines.append("Dialogue: 0,{},{},Default,,0,0,0,,{}".format(start, end, highlight_english_for_ass(text)))
    return header + "\n".join(lines) + "\n"


def extract_audio_from_video(video_bytes: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="biscuit-subtitle-") as temp_dir:
        video_path = os.path.join(temp_dir, "video.mp4")
        audio_path = os.path.join(temp_dir, "audio.mp3")
        with open(video_path, "wb") as video_file:
            video_file.write(video_bytes)
        command = [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", video_path,
            "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", audio_path,
        ]
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        if completed.returncode != 0 or not os.path.exists(audio_path):
            LOGGER.error("FFmpeg audio extraction failed: %s", completed.stderr[-1000:])
            raise HTTPException(status_code=502, detail="无法从生成的视频中提取音轨")
        with open(audio_path, "rb") as audio_file:
            return audio_file.read()


def extract_response_text(body: Dict[str, Any]) -> str:
    direct = body.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts: List[str] = []
    for item in body.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                parts.append(content["text"])
    return "\n".join(parts).strip()


def parse_json_object(text: str) -> Dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            raise HTTPException(status_code=502, detail="语言模型未返回可解析的脚本")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=502, detail="语言模型返回的脚本格式不正确") from error


@lru_cache(maxsize=1)
def get_script_prompt_template() -> str:
    prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "biscuit_script_prompt.txt")
    with open(prompt_path, "r", encoding="utf-8") as prompt_file:
        return prompt_file.read()


def build_script_instruction(payload: GenerateScriptRequest) -> str:
    return get_script_prompt_template().format(topic=payload.topic, scene=payload.scene)


@lru_cache(maxsize=1)
def get_biscuit_data_uri() -> str:
    image_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "biscuit-reference.png")
    with open(image_path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("ascii")
    return "data:image/png;base64,{}".format(encoded)


def build_content(payload: CreateVideoRequest) -> List[Dict[str, Any]]:
    content: List[Dict[str, Any]] = [{"type": "text", "text": payload.prompt}]
    if payload.reference_image_url:
        image_url = payload.reference_image_url
        if image_url == "builtin://biscuit":
            image_url = get_biscuit_data_uri()
        content.append({
            "type": "image_url",
            "image_url": {"url": image_url},
            "role": "reference_image",
        })
    return content


def register_routes(app: FastAPI) -> None:
    @app.get("/api")
    async def index_handler():
        return {"name": "Biscuit Studio API", "status": "ok"}

    @app.get("/api/v1/ping")
    async def ping_handler():
        credentials = get_subtitle_credentials()
        return {
            "status": "ok",
            "subtitles_configured": bool(credentials["app_id"] and credentials["access_token"]),
        }

    @app.get("/reference/biscuit.png")
    async def biscuit_reference_handler():
        image_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "biscuit-reference.png")
        try:
            with open(image_path, "rb") as image_file:
                image_bytes = image_file.read()
        except OSError as error:
            LOGGER.error("Unable to read reference image: %s", error)
            raise HTTPException(status_code=404, detail="reference image unavailable")
        return Response(
            content=image_bytes,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/api/v1/user", response_model=UserResponse)
    async def get_current_user(request: Request):
        user = request.state.current_user
        if user is None:
            raise HTTPException(status_code=403, detail="unauthorized")
        return user

    @app.post("/api/v1/models/test")
    async def test_language_model(payload: ModelTestRequest):
        body = {
            "model": payload.model,
            "input": "只回复：调用成功",
            "max_output_tokens": 16,
            "thinking": {"type": "disabled"},
        }
        started = time.monotonic()
        timeout = httpx.Timeout(20.0, connect=8.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.post(
                    "{}/responses".format(DEFAULT_ARK_BASE_URL),
                    headers=ark_headers(payload.api_key),
                    json=body,
                )
        except httpx.TimeoutException as error:
            raise HTTPException(status_code=504, detail="最小请求仍然超时") from error
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            raise ark_error(response)
        text = extract_response_text(response.json())
        return {"ok": True, "text": text, "elapsed_ms": elapsed_ms}

    @app.post("/api/v1/scripts/generate", response_model=ScriptResult)
    async def generate_script(payload: GenerateScriptRequest):
        body = {
            "model": payload.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": build_script_instruction(payload)}
                    ],
                }
            ],
            "max_output_tokens": 1000,
            "thinking": {"type": "disabled"},
        }
        timeout = httpx.Timeout(55.0, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.post(
                    "{}/responses".format(DEFAULT_ARK_BASE_URL),
                    headers=ark_headers(payload.api_key),
                    json=body,
                )
        except httpx.TimeoutException as error:
            raise HTTPException(status_code=504, detail="语言模型生成超时，请重新尝试") from error
        if response.status_code >= 400:
            raise ark_error(response)
        raw_text = extract_response_text(response.json())
        result = parse_json_object(raw_text)
        required = ("title", "script", "storyboard", "subtitles", "prompt")
        if any(not isinstance(result.get(key), str) or not result[key].strip() for key in required):
            raise HTTPException(status_code=502, detail="语言模型返回内容缺少脚本、分镜或字幕稿")
        return {key: result[key].strip() for key in required}

    @app.post("/api/v1/seedance/tasks")
    async def create_seedance_task(payload: CreateVideoRequest):
        body = {
            "model": payload.model,
            "content": build_content(payload),
            "generate_audio": payload.generate_audio,
            "resolution": payload.resolution,
            "ratio": payload.ratio,
            "duration": payload.duration,
            "seed": payload.seed,
            "watermark": payload.watermark,
        }
        timeout = httpx.Timeout(60.0, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(
                "{}/contents/generations/tasks".format(DEFAULT_ARK_BASE_URL),
                headers=ark_headers(payload.api_key),
                json=body,
            )
        if response.status_code >= 400:
            raise ark_error(response)
        return response.json()

    @app.post("/api/v1/seedance/status")
    async def get_seedance_status(payload: TaskStatusRequest):
        timeout = httpx.Timeout(30.0, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.get(
                "{}/contents/generations/tasks/{}".format(DEFAULT_ARK_BASE_URL, payload.task_id),
                headers=ark_headers(payload.api_key),
            )
        if response.status_code >= 400:
            raise ark_error(response)
        return response.json()
    @app.post("/api/v1/subtitles/tasks")
    async def create_subtitle_task(payload: SubtitleSubmitRequest):
        if not payload.video_url.lower().startswith("https://"):
            raise HTTPException(status_code=400, detail="字幕处理仅支持 HTTPS 视频地址")
        credentials = get_subtitle_credentials()
        headers = subtitle_headers()
        timeout = httpx.Timeout(120.0, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=True) as client:
            video_response = await client.get(payload.video_url)
            if video_response.status_code >= 400:
                raise HTTPException(status_code=502, detail="无法下载 Seedance 成片以生成字幕")
            if len(video_response.content) > 100 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="视频文件过大，暂不支持自动生成字幕")
            audio_bytes = extract_audio_from_video(video_response.content)
            expected_text = clean_expected_subtitle_text(payload.expected_text or "")
            if expected_text:
                response = await client.post(
                    "https://openspeech.bytedance.com/api/v1/vc/ata/submit",
                    params={
                        "appid": credentials["app_id"],
                        "caption_type": "speech",
                    },
                    headers=headers,
                    files={
                        "data": ("audio.mp3", audio_bytes, "audio/mpeg"),
                        "audio-text": (None, expected_text),
                    },
                )
                task_prefix = "ata:"
            else:
                response = await client.post(
                    "https://openspeech.bytedance.com/api/v1/vc/submit",
                    params={
                        "appid": credentials["app_id"],
                        "language": "zh-CN",
                        "use_itn": "True",
                        "use_capitalize": "True",
                        "max_lines": "1",
                        "words_per_line": "15",
                    },
                    headers={**headers, "Content-Type": "audio/mpeg"},
                    content=audio_bytes,
                )
                task_prefix = "asr:"
        try:
            body = response.json()
        except Exception as error:
            raise HTTPException(status_code=502, detail="字幕服务返回了无法解析的结果") from error
        if response.status_code >= 400 or str(body.get("code")) != "0":
            raise subtitle_error(body)
        task_id = body.get("id")
        if not task_id:
            raise HTTPException(status_code=502, detail="字幕服务未返回任务 ID")
        return {"id": "{}{}".format(task_prefix, task_id), "status": "queued"}

    @app.post("/api/v1/subtitles/status")
    async def get_subtitle_status(payload: SubtitleStatusRequest):
        credentials = get_subtitle_credentials()
        if payload.task_id.startswith("ata:"):
            task_id = payload.task_id[4:]
            query_url = "https://openspeech.bytedance.com/api/v1/vc/ata/query"
        elif payload.task_id.startswith("asr:"):
            task_id = payload.task_id[4:]
            query_url = "https://openspeech.bytedance.com/api/v1/vc/query"
        else:
            task_id = payload.task_id
            query_url = "https://openspeech.bytedance.com/api/v1/vc/query"
        timeout = httpx.Timeout(45.0, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.get(
                query_url,
                params={"appid": credentials["app_id"], "id": task_id, "blocking": "0"},
                headers=subtitle_headers(),
            )
        try:
            body = response.json()
        except Exception as error:
            raise HTTPException(status_code=502, detail="字幕服务返回了无法解析的结果") from error
        try:
            code = int(body.get("code"))
        except (TypeError, ValueError):
            code = -1
        if code == 2000:
            return {"id": payload.task_id, "status": "running"}
        if response.status_code >= 400 or code != 0:
            raise subtitle_error(body)
        utterances = body.get("utterances") or []
        return {
            "id": payload.task_id,
            "status": "succeeded",
            "duration": body.get("duration"),
            "utterances": utterances,
            "srt": utterances_to_srt(utterances),
        }
    @app.post("/api/v1/subtitles/burn")
    async def burn_subtitles(payload: BurnSubtitlesRequest):
        if not payload.video_url.lower().startswith("https://"):
            raise HTTPException(status_code=400, detail="字幕合成仅支持 HTTPS 视频地址")
        timeout = httpx.Timeout(120.0, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=True) as client:
            video_response = await client.get(payload.video_url)
        if video_response.status_code >= 400:
            raise HTTPException(status_code=502, detail="无法下载 Seedance 成片以合成字幕")
        if len(video_response.content) > 100 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="视频文件过大，暂不支持字幕合成")

        with tempfile.TemporaryDirectory(prefix="biscuit-burn-") as temp_dir:
            video_path = os.path.join(temp_dir, "input.mp4")
            subtitle_path = os.path.join(temp_dir, "subtitles.ass")
            output_path = os.path.join(temp_dir, "biscuit-with-subtitles.mp4")
            with open(video_path, "wb") as video_file:
                video_file.write(video_response.content)
            with open(subtitle_path, "w", encoding="utf-8") as subtitle_file:
                subtitle_file.write(utterances_to_ass(payload.utterances))
            fonts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
            command = [
                imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", video_path,
                "-vf", "ass={}:fontsdir={}".format(subtitle_path, fonts_dir),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", output_path,
            ]
            completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
            if completed.returncode != 0 or not os.path.exists(output_path):
                LOGGER.error("FFmpeg subtitle burn failed: %s", completed.stderr[-1500:])
                raise HTTPException(status_code=502, detail="字幕合成失败，请稍后重试")
            with open(output_path, "rb") as output_file:
                result = output_file.read()
        return Response(
            content=result,
            media_type="video/mp4",
            headers={"Content-Disposition": 'attachment; filename="biscuit-with-subtitles.mp4"'},
        )


app = FastAPI(
    title="Biscuit Studio API",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", JWT_HEADER],
)
setup_permissions(app)
register_routes(app)


# ---------------------------DO NOT EDIT CODE BELOW THIS LINE---------------------------------
# This is the entry point for the FastAPI application.
if __name__ == "__main__":
    port = int(os.environ.get("_BYTEFAAS_RUNTIME_PORT", 8000))
    config = uvicorn.Config("main:app", port=port, log_level="info", host=None)
    server = uvicorn.Server(config)
    server.run()
# --------------------------------------------------------------------------------------------
