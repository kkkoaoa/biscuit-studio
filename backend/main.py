import base64
import json
import logging
import os
import random
import re
import subprocess
import tempfile
import time
import unicodedata
from functools import lru_cache
from typing import Any, Dict, List, Optional

import httpx
import imageio_ffmpeg
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

LOGGER = logging.getLogger(__name__)
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


def get_cors_origins() -> List[str]:
    """Return the comma-separated browser origins allowed to call the API."""
    default_origins = (
        "http://localhost:3000,http://localhost:5173,"
        "http://127.0.0.1:3000,http://127.0.0.1:5173"
    )
    configured_origins = os.environ.get("CORS_ORIGINS", default_origins)
    origins = [origin.strip().rstrip("/") for origin in configured_origins.split(",") if origin.strip()]
    return origins or default_origins.split(",")


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
    content_mode: str = Field("knowledge", regex=r"^(knowledge|dialogue)$")


DIALOGUE_PARTNERS = (
    {
        "name": "小猫",
        "appearance": "一只小巧的银灰色短毛猫，翠绿色圆眼睛，白色下巴，戴细窄的珊瑚橙色项圈，不穿衣服",
        "voice": "轻柔机灵的年轻女童声，音高略高，语尾轻快",
    },
    {
        "name": "小水獭",
        "appearance": "一只圆脸的深棕色小水獭，浅米色口鼻和胸口，黑色豆豆眼，戴湖蓝色小领巾",
        "voice": "温暖活泼的少年童声，音色圆润，语速自然",
    },
    {
        "name": "小仓鼠",
        "appearance": "一只掌心大小的金棕色小仓鼠，奶白色肚皮，圆耳朵和鼓鼓脸颊，背迷你薄荷绿斜挎包",
        "voice": "清脆略快的幼童声，音量柔和，紧张时有短暂停顿",
    },
    {
        "name": "小鸟",
        "appearance": "一只小巧的天蓝色圆滚滚小鸟，白色脸颊，淡黄色短喙，右脚戴一枚红色细脚环",
        "voice": "清亮有节奏的中性童声，音高明快但不尖锐",
    },
)


class ScriptResult(BaseModel):
    title: str
    script: str
    storyboard: str
    subtitles: str
    prompt: str


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


VIDEO_WIDTH_PX = 720
SUBTITLE_FONT_SIZE_PX = 56
SUBTITLE_SIDE_MARGIN_PX = 48
# 720 - 2 * 48 leaves 624px. Reserve 8px for the 3px outline and rasterisation.
ASS_LINE_WIDTH = float(VIDEO_WIDTH_PX - 2 * SUBTITLE_SIDE_MARGIN_PX - 8)
MIN_SUBTITLE_SEGMENT_MS = 500
EDITOR_MARKER_RE = re.compile(r"(?:【\s*(?:重点)?\s*】|\[\s*(?:重点)?\s*\])", re.IGNORECASE)
SUBTITLE_BRACKET_RE = re.compile(r"[【】\[\]]")
HIDDEN_DISPLAY_PUNCTUATION = set("，。")
BREAK_AFTER_PUNCTUATION = set("，。！？；：、,.!?;:）)]}》〉」』”’")
PHRASE_BOUNDARY_CHARACTERS = set("的了呢吗吧啊呀和与但而在把被让给是有到从向对将就也都又再")
SUBTITLE_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['’.-][A-Za-z0-9]+)*|\s+|.", re.DOTALL)
LATIN_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’.-][A-Za-z0-9]+)*")


def strip_subtitle_editor_markers(text: str) -> str:
    """Remove review markup and every line-breaking/bracket delimiter."""
    cleaned = EDITOR_MARKER_RE.sub("", text)
    cleaned = cleaned.replace("\\N", " ").replace("\\n", " ")
    cleaned = SUBTITLE_BRACKET_RE.sub("", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def subtitle_display_text(text: str) -> str:
    """Return exactly what may be rendered in a final ASS/SRT cue."""
    cleaned = strip_subtitle_editor_markers(text)
    cleaned = "".join(character for character in cleaned if character not in HIDDEN_DISPLAY_PUNCTUATION)
    return re.sub(r"\s+", " ", cleaned).strip()


def subtitle_character_width(character: str) -> float:
    """Estimate Noto Sans CJK SC bold glyph advance at the configured 56px size."""
    if character.isspace():
        return SUBTITLE_FONT_SIZE_PX * 0.28
    if unicodedata.east_asian_width(character) in {"W", "F", "A"}:
        return float(SUBTITLE_FONT_SIZE_PX)
    if character in "ilI1'’`|.,:;!":
        return SUBTITLE_FONT_SIZE_PX * 0.28
    if character in "fjrt()[]{}":
        return SUBTITLE_FONT_SIZE_PX * 0.38
    if character in "mwMW@#%&QO0":
        return SUBTITLE_FONT_SIZE_PX * 0.86
    if character.isupper():
        return SUBTITLE_FONT_SIZE_PX * 0.67
    if character.isdigit():
        return SUBTITLE_FONT_SIZE_PX * 0.56
    if character.islower():
        return SUBTITLE_FONT_SIZE_PX * 0.54
    return SUBTITLE_FONT_SIZE_PX * 0.58


def subtitle_text_width(text: str) -> float:
    return sum(subtitle_character_width(character) for character in text)


def _break_priority(tokens: List[str], index: int) -> int:
    """Rank a boundary after tokens[index]: punctuation, spaces, phrase, CJK."""
    token = tokens[index]
    if token and token[-1] in BREAK_AFTER_PUNCTUATION:
        return 4
    if token.isspace():
        return 3
    if token and token[-1] in PHRASE_BOUNDARY_CHARACTERS:
        return 2
    if token and unicodedata.east_asian_width(token[-1]) in {"W", "F", "A"}:
        return 1
    return 0


def _is_orphan_fragment(text: str, width: float, max_width: float) -> bool:
    """Identify endings that look accidental rather than like a readable phrase."""
    cjk_count = sum(
        1 for character in text
        if unicodedata.east_asian_width(character) in {"W", "F", "A"}
        and character not in BREAK_AFTER_PUNCTUATION
    )
    latin_words = LATIN_WORD_RE.findall(text)
    if cjk_count and not latin_words:
        return cjk_count <= 3
    if latin_words and not cjk_count:
        return len(latin_words) == 1 and width < max_width * 0.38
    return width < max_width * 0.20


def wrap_subtitle_text(text: str, max_width: float = ASS_LINE_WIDTH) -> List[str]:
    """Globally balance single-line cues while retaining natural source boundaries."""
    normalized = strip_subtitle_editor_markers(text)
    rendered_full_text = subtitle_display_text(normalized)
    if not rendered_full_text:
        return []
    # Do not let punctuation or a rough character count split text that really fits.
    if subtitle_text_width(rendered_full_text) <= max_width:
        return [rendered_full_text]

    tokens = SUBTITLE_TOKEN_RE.findall(normalized)
    token_count = len(tokens)
    edges: Dict[int, List[tuple]] = {index: [] for index in range(token_count)}
    for start in range(token_count):
        for end in range(start + 1, token_count + 1):
            fragment = subtitle_display_text("".join(tokens[start:end]))
            if not fragment:
                continue
            width = subtitle_text_width(fragment)
            if width > max_width:
                # A single Latin token remains atomic even in this exceptional case.
                if end == start + 1 and LATIN_WORD_RE.fullmatch(tokens[start]):
                    edges[start].append((end, fragment, width, _break_priority(tokens, end - 1)))
                break
            edges[start].append((end, fragment, width, _break_priority(tokens, end - 1)))

    # First find the fewest safe cues. This guarantees that text fitting one line
    # never fragments and avoids the former overly conservative local decisions.
    infinity = token_count + 1
    minimum_parts = [infinity] * (token_count + 1)
    minimum_parts[0] = 0
    for start in range(token_count):
        if minimum_parts[start] == infinity:
            continue
        for end, _, _, _ in edges.get(start, []):
            minimum_parts[end] = min(minimum_parts[end], minimum_parts[start] + 1)
    part_count = minimum_parts[token_count]
    if part_count == infinity:
        return [rendered_full_text]

    target_width = subtitle_text_width(rendered_full_text) / part_count
    states: Dict[tuple, tuple] = {(0, 0): (0.0, [])}
    boundary_penalty = {4: 0.0, 3: 0.5, 2: 2.0, 1: 5.0, 0: 9.0}
    for used_parts in range(part_count):
        for start in range(token_count):
            state = states.get((used_parts, start))
            if state is None:
                continue
            old_cost, old_fragments = state
            for end, fragment, width, priority in edges.get(start, []):
                if used_parts + 1 == part_count and end != token_count:
                    continue
                if used_parts + 1 < part_count and end == token_count:
                    continue
                imbalance = ((width - target_width) / max_width) ** 2 * 100.0
                orphan_penalty = 0.0
                if _is_orphan_fragment(fragment, width, max_width):
                    orphan_penalty = 1000000.0 if end == token_count else 10000.0
                semantic_penalty = 0.0 if end == token_count else boundary_penalty[priority]
                new_cost = old_cost + imbalance + orphan_penalty + semantic_penalty
                key = (used_parts + 1, end)
                if key not in states or new_cost < states[key][0]:
                    states[key] = (new_cost, old_fragments + [fragment])

    final_state = states.get((part_count, token_count))
    return final_state[1] if final_state else [rendered_full_text]


def subtitle_reading_weight(text: str) -> float:
    """Weight CJK by character and Latin/digit content by readable word size."""
    weight = 0.0
    for token in SUBTITLE_TOKEN_RE.findall(text):
        if token.isspace():
            continue
        if LATIN_WORD_RE.fullmatch(token):
            weight += max(1.0, len(token) * 0.35)
        elif token in BREAK_AFTER_PUNCTUATION:
            weight += 0.2
        else:
            weight += 1.0
    return max(weight, 0.1)


def split_subtitle_utterance(utterance: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Split one cue and distribute its original interval into contiguous cues."""
    fragments = wrap_subtitle_text(str(utterance.get("text") or ""))
    if not fragments:
        return []
    start = max(0, int(utterance.get("start_time") or 0))
    end = max(start, int(utterance.get("end_time") or start))
    if len(fragments) == 1:
        return [{**utterance, "text": fragments[0], "start_time": start, "end_time": end}]

    duration = end - start
    weights = [subtitle_reading_weight(fragment) for fragment in fragments]
    minimum = MIN_SUBTITLE_SEGMENT_MS if duration >= len(fragments) * MIN_SUBTITLE_SEGMENT_MS else 0
    distributable = max(0, duration - minimum * len(fragments))
    total_weight = sum(weights)
    boundaries = [start]
    allocated = 0
    for index, weight in enumerate(weights[:-1]):
        allocated += minimum + int(round(distributable * weight / total_weight))
        remaining = len(fragments) - index - 1
        latest = end - minimum * remaining
        boundaries.append(min(start + allocated, latest))
    boundaries.append(end)

    result: List[Dict[str, Any]] = []
    for index, fragment in enumerate(fragments):
        result.append({
            **utterance,
            "text": fragment,
            "start_time": boundaries[index],
            "end_time": boundaries[index + 1],
        })
    return result


def split_subtitle_utterances(utterances: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize all cues while preserving order and already-short timings."""
    result: List[Dict[str, Any]] = []
    for utterance in utterances:
        result.extend(split_subtitle_utterance(utterance))
    return result


def clean_expected_subtitle_text(text: str) -> str:
    """Convert the reviewed subtitle draft into plain spoken text for alignment."""
    cleaned_lines: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*\d.、\s]+", "", line)
        line = re.sub(r"^【(?:画外男声|采访者|小饼干)】\s*[:：]?\s*", "", line)
        line = strip_subtitle_editor_markers(line)
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
    for index, utterance in enumerate(split_subtitle_utterances(utterances), start=1):
        start = format_srt_time(utterance["start_time"])
        end = format_srt_time(utterance["end_time"])
        blocks.append("{}\n{} --> {}\n{}".format(index, start, end, utterance["text"]))
    return "\n\n".join(blocks)


def format_ass_time(milliseconds: int) -> str:
    milliseconds = max(0, int(milliseconds))
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, millis = divmod(remainder, 1000)
    return "{}:{:02d}:{:02d}.{:02d}".format(hours, minutes, seconds, millis // 10)


def highlight_english_for_ass(text: str) -> str:
    safe = text.replace("{", "（").replace("}", "）")
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
    for utterance in split_subtitle_utterances(utterances):
        start = format_ass_time(utterance["start_time"])
        end = format_ass_time(utterance["end_time"])
        ass_text = highlight_english_for_ass(utterance["text"])
        lines.append("Dialogue: 0,{},{},Default,,0,0,0,,{}".format(start, end, ass_text))
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


@lru_cache(maxsize=2)
def get_script_prompt_template(content_mode: str = "knowledge") -> str:
    filename = "biscuit_dialogue_prompt.txt" if content_mode == "dialogue" else "biscuit_script_prompt.txt"
    prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", filename)
    with open(prompt_path, "r", encoding="utf-8") as prompt_file:
        return prompt_file.read()


def select_dialogue_partner() -> Dict[str, str]:
    return random.choice(DIALOGUE_PARTNERS)


def build_script_instruction(payload: GenerateScriptRequest) -> str:
    if payload.content_mode == "dialogue":
        partner = select_dialogue_partner()
        return get_script_prompt_template("dialogue").format(
            topic=payload.topic,
            scene=payload.scene,
            partner_name=partner["name"],
            partner_appearance=partner["appearance"],
            partner_voice=partner["voice"],
        )
    return get_script_prompt_template("knowledge").format(topic=payload.topic, scene=payload.scene)


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
            "max_output_tokens": 2200,
            "thinking": {"type": "disabled"},
        }
        timeout = httpx.Timeout(90.0, connect=10.0)
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
    allow_origins=get_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
register_routes(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
