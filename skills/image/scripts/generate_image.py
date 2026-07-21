#!/usr/bin/env python3
"""统一图像生成脚本，当前仅使用 VTeTech。

配置来自环境变量或 .env 文件：
- IMG_BASE_URL / API_BASE_URL / IMG_MODEL / IMAGE_MODEL / IMG_API_KEY / API_KEY: VTeTech 图像接口配置
"""

from __future__ import annotations

import argparse
import base64
import http.client
import mimetypes
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from config import apply_config_file


# ── Active VTeTech-only configuration ─────────────────────────────
ENV_BASE_URL = "IMG_BASE_URL"
ENV_MODEL = "IMG_MODEL"
ENV_API_KEY = "IMG_API_KEY"
ENV_COS_BUCKET_URL = "COS_BUCKET_URL"
ENV_COS_UPLOAD_PREFIX = "COS_UPLOAD_PREFIX"
ENV_ALIASES = {
    ENV_BASE_URL: ("API_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE", "BASE_URL"),
    ENV_MODEL: ("IMAGE_MODEL", "OPENAI_IMAGE_MODEL", "OPENAI_MODEL"),
    ENV_API_KEY: ("API_KEY", "OPENAI_API_KEY"),
}
UPLOAD_CACHE: dict[str, str] = {}
DEFAULT_OUTPUT_ROOT = Path("output")

VALID_RESOLUTIONS = ("1k", "2k", "4k")
MEDIA_GENERATE_PATH = "/v1/media/generate"
TASK_STATUS_PATH = "/v1/skills/task-status"
BALANCE_PATH = "/v1/skills/balance"
SELL_POINT_ANALYSIS_MODEL = "gpt-5.4"
SELL_POINT_ANALYSIS_MAX_OUTPUT_TOKENS = 768
SELL_POINT_TRIGGER_PHRASES = (
    "根据图片生成卖点",
    "根据图片提炼卖点",
    "根据图生成卖点",
    "根据参考图生成卖点",
    "提炼卖点",
    "卖点总结",
    "卖点提炼",
    "看图生成卖点",
)
DATA_URI_PATTERN = re.compile(r"^data:(?P<mime>[^;,]+)(?:;charset=[^;,]+)?;base64,(?P<data>.+)$", re.I | re.S)
SELL_POINT_ANALYSIS_CACHE: dict[tuple[str, ...], dict[str, Any]] = {}

SIZE_PRESETS: dict[str, dict[str, str]] = {
    "1k": {
        "1:1": "1024x1024",
        "2:3": "1024x1536",
        "3:2": "1536x1024",
        "3:4": "960x1280",
        "4:3": "1280x960",
        "9:16": "1088x1920",
        "16:9": "1920x1088",
    },
    "2k": {
        "1:1": "2048x2048",
        "2:3": "2048x3072",
        "3:2": "3072x2048",
        "3:4": "1920x2560",
        "4:3": "2560x1920",
        "9:16": "1440x2560",
        "16:9": "2560x1440",
    },
    "4k": {
        "1:1": "2880x2880",
        "2:3": "2304x3456",
        "3:2": "3456x2304",
        "3:4": "2400x3200",
        "4:3": "3200x2400",
        "9:16": "2160x3840",
        "16:9": "3840x2160",
    },
}

RATIO_ALIASES: dict[str, str] = {
    "5:4": "4:3",
    "4:5": "3:4",
    "2:1": "16:9",
    "1:2": "9:16",
    "21:9": "16:9",
    "9:21": "9:16",
}

SUPPORTED_EXACT_SIZES = {
    size
    for preset in SIZE_PRESETS.values()
    for size in preset.values()
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def fail(message: str, exit_code: int = 1) -> None:
    print(f"错误：{message}", file=sys.stderr)
    raise SystemExit(exit_code)


class ApiRequestError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        detail: str = "",
        payload: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail
        self.payload = payload


def is_public_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_data_uri(value: str) -> bool:
    return value.strip().lower().startswith("data:")


def guess_content_type(path: Path) -> str:
    content_type, _ = mimetypes.guess_type(str(path))
    if content_type:
        return content_type
    return "application/octet-stream"


def collect_reference_image_inputs(raw_images: Any) -> list[str]:
    if not raw_images:
        return []
    values = raw_images if isinstance(raw_images, list) else [raw_images]
    collected: list[str] = []
    for raw_value in values:
        for candidate in str(raw_value).split(","):
            candidate = candidate.strip()
            if not candidate:
                continue
            if is_public_url(candidate) or is_data_uri(candidate):
                collected.append(candidate)
                continue
            path = Path(candidate).expanduser()
            if not path.is_file():
                fail(f"参考图片必须是本地文件路径或可公开访问的 http/https URL：{candidate}")
            collected.append(str(path))
    if len(collected) > 10:
        fail("参考图片最多支持 10 张。")
    return collected


def should_analyze_sell_points(prompt: str) -> bool:
    normalized = re.sub(r"\s+", "", prompt)
    return any(phrase in normalized for phrase in SELL_POINT_TRIGGER_PHRASES)


def strip_sell_point_request(prompt: str) -> str:
    cleaned = prompt
    for phrase in SELL_POINT_TRIGGER_PHRASES:
        cleaned = cleaned.replace(phrase, "")
    cleaned = re.sub(r"^[\s，,、;；:：\-–—]+", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned or prompt.strip()


def parse_data_uri(value: str) -> tuple[str, bytes]:
    match = DATA_URI_PATTERN.match(value.strip())
    if not match:
        fail("data URI 格式不正确。")
    mime_type = match.group("mime").strip() or "application/octet-stream"
    raw_data = match.group("data").strip()
    try:
        return mime_type, base64.b64decode(raw_data)
    except (ValueError, OSError) as exc:
        fail(f"无法解析 data URI：{exc}")


def load_reference_image_bytes(candidate: str) -> tuple[str, bytes]:
    if is_data_uri(candidate):
        return parse_data_uri(candidate)
    if is_public_url(candidate):
        request = urllib.request.Request(candidate, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read()
                mime_type = response.headers.get_content_type()
                if not mime_type or mime_type == "application/octet-stream":
                    mime_type = guess_content_type(Path(urllib.parse.urlparse(candidate).path))
                return mime_type, data
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            fail(f"无法下载参考图片，HTTP {exc.code}：{detail}")
        except urllib.error.URLError as exc:
            fail(f"无法下载参考图片：{exc.reason}")
        except TimeoutError:
            fail("下载参考图片超时。")
    path = Path(candidate).expanduser()
    if not path.is_file():
        fail(f"参考图片不存在：{candidate}")
    return guess_content_type(path), path.read_bytes()


def build_openai_image_parts(reference_inputs: list[str]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for candidate in reference_inputs:
        mime_type, data = load_reference_image_bytes(candidate)
        parts.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}",
                }
            }
        )
    return parts


def extract_openai_text(result: dict[str, Any]) -> str:
    choices = result.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                texts: list[str] = []
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text")
                        if isinstance(text, str) and text.strip():
                            texts.append(text.strip())
                if texts:
                    return "\n".join(texts).strip()
    return ""


def parse_json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S | re.I)
        if fenced:
            cleaned = fenced.group(1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def build_sell_point_analysis_prompt() -> str:
    return (
        "你是电商商品分析助手。请只根据输入图片做卖点总结，不要编造图片中看不到的品牌、材质、尺寸、工艺或功能。"
        "优先识别：产品类型、外观特征、结构特征、可见材质、配色、使用方式、适合的场景。"
        "请输出严格 JSON，不要输出代码块，不要输出解释文字，格式如下："
        '{"product_type":"","core_sell_points":[{"point":"","evidence":""}],"style_keywords":[],"scene_suggestions":[],"risk_notes":[]}'
    )


def format_sell_point_context(raw_text: str, structured: dict[str, Any] | None) -> str:
    lines = [
        "Reference sell points extracted from the reference image(s):",
    ]
    if structured:
        product_type = structured.get("product_type")
        if isinstance(product_type, str) and product_type.strip():
            lines.append(f"- Product type: {product_type.strip()}")
        core_sell_points = structured.get("core_sell_points")
        if isinstance(core_sell_points, list):
            for index, item in enumerate(core_sell_points, start=1):
                if isinstance(item, dict):
                    point = str(item.get("point") or item.get("sell_point") or "").strip()
                    evidence = str(item.get("evidence") or "").strip()
                    if point:
                        line = f"- Sell point {index}: {point}"
                        if evidence:
                            line += f" | Evidence: {evidence}"
                        lines.append(line)
                elif isinstance(item, str) and item.strip():
                    lines.append(f"- Sell point {index}: {item.strip()}")
        style_keywords = structured.get("style_keywords")
        if isinstance(style_keywords, list):
            keywords = [str(item).strip() for item in style_keywords if str(item).strip()]
            if keywords:
                lines.append(f"- Style keywords: {', '.join(keywords)}")
        scene_suggestions = structured.get("scene_suggestions")
        if isinstance(scene_suggestions, list):
            scenes = [str(item).strip() for item in scene_suggestions if str(item).strip()]
            if scenes:
                lines.append(f"- Scene suggestions: {', '.join(scenes)}")
        risk_notes = structured.get("risk_notes")
        if isinstance(risk_notes, list):
            risks = [str(item).strip() for item in risk_notes if str(item).strip()]
            if risks:
                lines.append(f"- Risk notes: {', '.join(risks)}")
    elif raw_text.strip():
        lines.append(raw_text.strip())
    lines.append("Use these as factual reference only. Do not invent unobserved features.")
    return "\n".join(lines)


def analyze_sell_points_with_gemini(base_url: str, api_key: str, reference_inputs: list[str]) -> dict[str, Any]:
    normalized_inputs = tuple(reference_inputs)
    if normalized_inputs in SELL_POINT_ANALYSIS_CACHE:
        return SELL_POINT_ANALYSIS_CACHE[normalized_inputs]
    if not reference_inputs:
        fail("提示词要求根据图片生成卖点，但没有提供参考图片。")
    endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": SELL_POINT_ANALYSIS_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": build_sell_point_analysis_prompt()},
                    *build_openai_image_parts(reference_inputs),
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": SELL_POINT_ANALYSIS_MAX_OUTPUT_TOKENS,
    }
    print(f"[analysis] 使用 GPT 5.4 提炼卖点: {endpoint}", file=sys.stderr)
    result = request_json("POST", endpoint, api_key, payload, timeout=120)
    if result.get("error"):
        error = result["error"]
        fail(f"GPT 5.4 卖点提炼失败：{error.get('message', json.dumps(result, ensure_ascii=False)[:300])}")
    text = extract_openai_text(result)
    if not text:
        fail(f"GPT 5.4 卖点提炼返回空内容：{json.dumps(result, ensure_ascii=False)[:500]}")
    structured = parse_json_object(text)
    analysis = {"raw_text": text, "structured": structured}
    SELL_POINT_ANALYSIS_CACHE[normalized_inputs] = analysis
    return analysis


def inject_context_after_prefix(prompt: str, prefix: str, context: str) -> str:
    if not context.strip():
        return prompt
    if prefix and prompt.startswith(prefix):
        remainder = prompt[len(prefix):].lstrip("\n")
        parts = [prefix.rstrip(), "", context.strip()]
        if remainder.strip():
            parts.extend(["", remainder.strip()])
        return "\n".join(parts).strip()
    return f"{context.strip()}\n\n{prompt.strip()}".strip()


def extract_leading_campaign_style_lock(prompt: str) -> str:
    stripped = prompt.lstrip()
    if not stripped.startswith(("Campaign Style Lock:", "Campaign Style Lock：")):
        return ""
    blocks = re.split(r"\n\s*\n", stripped, maxsplit=1)
    return blocks[0].strip()


def prepare_prompt_with_sell_points(
    prompt: str,
    reference_inputs: list[str],
    lk_config: dict[str, str] | None,
) -> tuple[str, str | None]:
    if not should_analyze_sell_points(prompt):
        return prompt.strip(), None
    if lk_config is None:
        fail("提示词要求根据图片生成卖点，但 VTeTech 未配置，无法调用 GPT 5.4。")
    analysis = analyze_sell_points_with_gemini(lk_config["base_url"], lk_config["api_key"], reference_inputs)
    context = format_sell_point_context(analysis["raw_text"], analysis.get("structured"))
    print(f"[analysis] 已提炼卖点并注入后续 Prompt，参考图 {len(reference_inputs)} 张。", file=sys.stderr)
    return strip_sell_point_request(prompt), context


def materialize_reference_images(reference_inputs: list[str]) -> list[str]:
    normalized: list[str] = []
    for candidate in reference_inputs:
        if is_public_url(candidate) or is_data_uri(candidate):
            normalized.append(candidate)
            continue
        path = Path(candidate).expanduser()
        normalized.append(ensure_public_reference_url(path))
    return normalized


def get_config_value(name: str, default: str = "") -> str:
    candidates = (name, *ENV_ALIASES.get(name, ()))
    for candidate in candidates:
        value = os.environ.get(candidate, "").strip()
        if value:
            return value
    return default


def build_cos_object_key(source_path: Path) -> str:
    prefix = get_config_value(ENV_COS_UPLOAD_PREFIX, "image").strip("/")
    timestamp = time.strftime("%Y%m%d/%H%M%S")
    nonce = uuid.uuid4().hex[:8]
    filename = f"{source_path.stem}-{timestamp}-{nonce}{source_path.suffix.lower()}"
    parts = [part for part in (prefix, filename) if part]
    return "/".join(parts)


def build_reference_data_uri(source_path: Path) -> str:
    cache_key = f"data:{source_path.resolve()}"
    if cache_key in UPLOAD_CACHE:
        return UPLOAD_CACHE[cache_key]
    try:
        data = source_path.read_bytes()
    except OSError as exc:
        fail(f"Unable to read local reference image: {exc}")
    data_uri = f"data:{guess_content_type(source_path)};base64,{base64.b64encode(data).decode('ascii')}"
    UPLOAD_CACHE[cache_key] = data_uri
    print("[upload] COS 未配置，使用 base64 传递本地参考图", file=sys.stderr)
    return data_uri


def ensure_public_reference_url(source_path: Path) -> str:
    cache_key = str(source_path.resolve())
    if cache_key in UPLOAD_CACHE:
        return UPLOAD_CACHE[cache_key]
    reference_mode = get_config_value("REFERENCE_IMAGE_MODE", "base64").lower()
    if reference_mode != "cos":
        return build_reference_data_uri(source_path)
    bucket_url = get_config_value(ENV_COS_BUCKET_URL)
    if not bucket_url:
        return build_reference_data_uri(source_path)
    if not bucket_url.startswith(("http://", "https://")):
        fail("COS_BUCKET_URL 必须是以 http:// 或 https:// 开头的公网桶地址。")
    try:
        data = source_path.read_bytes()
    except OSError as exc:
        fail(f"无法读取本地参考图片：{exc}")
    object_key = build_cos_object_key(source_path)
    upload_url = f"{bucket_url.rstrip('/')}/{urllib.parse.quote(object_key, safe='/')}"
    content_type = guess_content_type(source_path)
    request = urllib.request.Request(
        upload_url,
        data=data,
        headers={
            "Content-Type": content_type,
            "Content-Length": str(len(data)),
            "User-Agent": UA,
        },
        method="PUT",
    )
    print(f"[upload] 上传参考图片到 COS: {upload_url}", file=sys.stderr)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.status not in {200, 201, 204}:
                fail(f"COS 上传失败，HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        fail(f"COS 上传失败，HTTP {exc.code}：{detail}")
    except urllib.error.URLError as exc:
        fail(f"COS 上传失败：{exc.reason}")
    except TimeoutError:
        fail("COS 上传超时。")
    UPLOAD_CACHE[cache_key] = upload_url
    return upload_url


def normalize_size(size: str, resolution: str) -> str:
    cleaned_size = size.strip().lower()
    if cleaned_size == "auto":
        return "auto"
    if cleaned_size in SUPPORTED_EXACT_SIZES:
        return cleaned_size
    if re.fullmatch(r"\d+x\d+", cleaned_size):
        return cleaned_size
    resolved_ratio = RATIO_ALIASES.get(cleaned_size, cleaned_size)
    if resolved_ratio not in SIZE_PRESETS[resolution]:
        supported = ", ".join(sorted(SIZE_PRESETS[resolution].keys()))
        fail(
            f"不支持的尺寸 '{size}'。请使用 auto、像素尺寸（如 2048x2048）或这些比例：{supported}。"
        )
    return SIZE_PRESETS[resolution][resolved_ratio]


# ── 配置与环境 ──────────────────────────────────────────────

def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt:
        prompt = args.prompt.strip()
    else:
        try:
            prompt = Path(args.prompt_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            fail(f"无法读取 prompt 文件：{exc}")
    if not prompt:
        fail("prompt 不能为空。")
    return prompt


def strip_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def find_default_env_file() -> Path | None:
    for directory in (Path.cwd(), *Path.cwd().parents):
        env_file = directory / ".env"
        if env_file.is_file():
            return env_file
    skill_env_file = Path(__file__).resolve().parents[1] / ".env"
    if skill_env_file.is_file():
        return skill_env_file
    return None


def load_env_file(env_file: Path | None) -> None:
    if env_file is None:
        return
    try:
        lines = env_file.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        fail(f"无法读取 .env 文件：{exc}")
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            fail(f".env 第 {line_number} 行格式不正确，应为 KEY=value。")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            fail(f".env 第 {line_number} 行缺少变量名。")
        os.environ[key] = strip_env_value(value)


def require_config(name: str) -> str:
    candidates = (name, *ENV_ALIASES.get(name, ()))
    for candidate in candidates:
        value = os.environ.get(candidate, "").strip()
        if value:
            return value
    accepted = "、".join(candidates)
    fail(
        f"缺少配置 {name}。请在 .env 中设置 VTeTech 的 IMG_BASE_URL、IMG_MODEL、IMG_API_KEY 或 API_KEY；"
        f"也兼容这些变量名：{accepted}。"
    )


# ── 模式检测 ──────────────────────────────────────────────

def detect_mode(base_url: str, explicit_mode: str | None) -> str:
    if explicit_mode in ("sync", "async", "media"):
        return "media"
    return "media"


# ── HTTP 工具 ──────────────────────────────────────────────

def try_parse_json(raw: str) -> Any | None:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def request_json(
    method: str,
    url: str,
    api_key: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {api_key}", "User-Agent": UA}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        parsed = try_parse_json(detail)
        raise ApiRequestError(
            f"HTTP {exc.code}",
            status_code=exc.code,
            detail=detail,
            payload=parsed,
        ) from exc
    except urllib.error.URLError as exc:
        raise ApiRequestError(f"无法连接接口：{exc.reason}") from exc
    except (http.client.RemoteDisconnected, TimeoutError) as exc:
        raise ApiRequestError("接口连接失败或超时，请稍后重试。") from exc
    parsed = try_parse_json(raw)
    if not isinstance(parsed, dict):
        raise ApiRequestError(f"接口返回的不是有效 JSON：{raw[:500]}", detail=raw)
    return parsed


def format_request_error(prefix: str, exc: ApiRequestError) -> str:
    detail = exc.detail or extract_error_text(exc.payload) or str(exc)
    if exc.status_code is not None:
        return f"{prefix} HTTP {exc.status_code}：{detail}"
    return f"{prefix}：{detail}"


def http_post(url: str, api_key: str, payload: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    try:
        return request_json("POST", url, api_key, payload, timeout)
    except ApiRequestError as exc:
        fail(format_request_error("接口返回错误", exc))


def http_get(url: str, api_key: str, timeout: int = 30) -> dict[str, Any]:
    try:
        return request_json("GET", url, api_key, timeout=timeout)
    except ApiRequestError as exc:
        fail(format_request_error("查询接口返回错误", exc))


def check_balance(base_url: str, api_key: str) -> None:
    endpoint = f"{base_url}{BALANCE_PATH}"
    try:
        result = http_get(endpoint, api_key, timeout=30)
    except SystemExit as exc:
        print(f"[balance] 无法查询余额，继续执行前请手动确认额度。", file=sys.stderr)
        if exc.code not in (0, None):
            return
        return
    balance = result.get("balance")
    if isinstance(balance, (int, float)):
        print(f"[balance] 当前算力：{balance} {result.get('unit', '')}".strip(), file=sys.stderr)
        if balance <= 0:
            fail("算力余额不足，请先到墨然AI官网充值后再生成图片。")
        return
    print(f"[balance] 返回格式异常：{json.dumps(result, ensure_ascii=False)[:200]}", file=sys.stderr)


# ── 媒体生成模式（墨然AI）──────────────────────────────────

def build_media_payload_from_options(
    prompt: str,
    model: str,
    size: str,
    resolution: str,
    quality: str | None,
    reference_inputs: list[str] | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"size": normalize_size(size, resolution)}
    if quality:
        params["quality"] = quality
    reference_images = materialize_reference_images(reference_inputs or [])
    if reference_images:
        params["images"] = reference_images
    return {"model": model, "prompt": prompt, "params": params}


def build_media_payload(args: argparse.Namespace, prompt: str, model: str, reference_inputs: list[str]) -> dict[str, Any]:
    return build_media_payload_from_options(
        prompt=prompt,
        model=model,
        size=args.size,
        resolution=args.resolution,
        quality=args.quality,
        reference_inputs=reference_inputs,
    )


def run_media(base_url: str, api_key: str, payload: dict[str, Any],
              output_dir: Path, fmt: str, poll_interval: int, timeout: int) -> list[Path]:
    endpoint = f"{base_url}{MEDIA_GENERATE_PATH}"
    print(f"[media] 提交生成请求到 {endpoint}...", file=sys.stderr)
    result = http_post(endpoint, api_key, payload, timeout=120)

    code = result.get("code")
    if code not in (None, 200):
        error = result.get("error", {})
        fail(f"提交失败（code={code}）：{error.get('message', json.dumps(result, ensure_ascii=False))}")

    data = result.get("data")
    task_id = _extract_task_id(data)
    if not task_id:
        fail(f"提交响应缺少 task_id：{json.dumps(result, ensure_ascii=False)[:300]}")

    print(f"[media] 任务已提交: {task_id}，开始轮询任务状态...", file=sys.stderr)
    task_data = _poll_task(base_url, api_key, task_id, poll_interval, timeout)
    actual_time = task_data.get("duration_seconds") or task_data.get("actual_time") or task_data.get("duration") or 0
    cost = task_data.get("cost", 0)
    print(f"[media] 任务完成，耗时 {actual_time}s，费用 ${float(cost or 0):.4f}", file=sys.stderr)

    return _save_task_images(task_data, output_dir, fmt)


def _extract_task_id(data: Any) -> str | None:
    if isinstance(data, dict):
        for key in ("task_id", "id"):
            value = data.get(key)
            if value is not None:
                return str(value)
        tasks = data.get("任务ids")
        if isinstance(tasks, list) and tasks:
            return str(tasks[0])
    if isinstance(data, list) and data:
        first_item = data[0]
        if isinstance(first_item, dict):
            for key in ("task_id", "id"):
                value = first_item.get(key)
                if value is not None:
                    return str(value)
    return None


def _poll_task(base_url: str, api_key: str, task_id: str,
               poll_interval: int, timeout: int) -> dict[str, Any]:
    url = f"{base_url}{TASK_STATUS_PATH}?{urllib.parse.urlencode({'task_id': task_id})}"
    start = time.time()
    while True:
        elapsed = time.time() - start
        if elapsed > timeout:
            fail(f"任务 {task_id} 超时（{timeout}s），请稍后手动查询。")
        result = http_get(url, api_key)
        if result.get("error"):
            error = result["error"]
            fail(f"查询任务失败：{error.get('message', json.dumps(result, ensure_ascii=False)[:300])}")
        task_data = result.get("data", result)
        if not isinstance(task_data, dict):
            fail(f"任务状态返回格式不正确：{json.dumps(result, ensure_ascii=False)[:300]}")
        if _task_is_final(task_data):
            if _task_is_failed(task_data):
                error_message = _extract_task_error(task_data)
                fail(f"任务 {task_id} 失败：{error_message}")
            return task_data
        progress = task_data.get("progress", 0)
        status = task_data.get("state") or task_data.get("status") or ""
        print(f"  轮询中... 状态={status} 进度={progress} 耗时={elapsed:.0f}s", file=sys.stderr)
        time.sleep(poll_interval)


def _task_is_final(task_data: dict[str, Any]) -> bool:
    is_final = task_data.get("is_final")
    if isinstance(is_final, bool):
        return is_final
    if isinstance(is_final, str):
        lowered = is_final.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
    status_text = str(task_data.get("state") or task_data.get("status") or "").strip().lower()
    return status_text in {"completed", "complete", "finished", "done", "succeeded", "success", "生成完成", "已完成"}


def _task_is_failed(task_data: dict[str, Any]) -> bool:
    status_text = str(task_data.get("state") or task_data.get("status") or "").strip().lower()
    return status_text in {"failed", "error", "fail", "生成失败", "失败"}


def _extract_task_error(task_data: dict[str, Any]) -> str:
    error = task_data.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if message:
            return str(message)
    if error:
        return str(error)
    message = task_data.get("message")
    if message:
        return str(message)
    return json.dumps(task_data, ensure_ascii=False)[:300]


def _collect_result_urls(task_data: dict[str, Any]) -> list[str]:
    urls: list[str] = []

    def append_value(value: Any) -> None:
        if isinstance(value, str) and value:
            urls.append(value)
        elif isinstance(value, list):
            for item in value:
                append_value(item)
        elif isinstance(value, dict):
            for key in ("url", "result_url", "image_url", "download_url"):
                append_value(value.get(key))

    append_value(task_data.get("result_url"))
    result = task_data.get("result")
    if isinstance(result, dict):
        append_value(result.get("url"))
        append_value(result.get("result_url"))
        append_value(result.get("images"))
        append_value(result.get("image_urls"))
    elif isinstance(result, list):
        append_value(result)

    seen: set[str] = set()
    unique_urls: list[str] = []
    for item in urls:
        if item not in seen:
            seen.add(item)
            unique_urls.append(item)
    return unique_urls


def _save_task_images(task_data: dict[str, Any], output_dir: Path, fmt: str) -> list[Path]:
    image_urls = _collect_result_urls(task_data)
    if not image_urls:
        fail(f"任务结果中缺少可下载的图片地址：{json.dumps(task_data, ensure_ascii=False)[:300]}")
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, image_url in enumerate(image_urls, start=1):
        suffix = _suffix_from_url(image_url, fmt)
        output_path = output_dir / filename_for(suffix, index)
        print(f"  下载图片: {image_url}", file=sys.stderr)
        dl_req = urllib.request.Request(image_url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(dl_req, timeout=120) as resp:
                output_path.write_bytes(resp.read())
        except urllib.error.URLError as exc:
            fail(f"无法下载图片：{exc.reason}")
        except TimeoutError:
            fail("下载图片超时。")
        paths.append(output_path)
    return paths


def filename_for(suffix: str, index: int = 1) -> str:
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    return f"image-{timestamp}-{index:02d}.{suffix.lstrip('.')}"


def build_timestamp_output_dir(base_dir: Path | None = None) -> Path:
    root = base_dir or Path(get_config_value("IMAGE_OUTPUT_ROOT", str(DEFAULT_OUTPUT_ROOT)))
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    return root / timestamp


def resolve_skill_output_dir(raw_output_dir: str = "") -> Path:
    return build_timestamp_output_dir(Path(raw_output_dir) if raw_output_dir else None)


# ── 工具函数 ──────────────────────────────────────────────

def _suffix_from_url(url: str, fallback: str) -> str:
    path = urllib.parse.urlparse(url).path
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix in {"png", "jpg", "jpeg", "webp"}:
        return "jpg" if suffix == "jpeg" else suffix
    return fallback


def extract_error_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("message", "msg", "error", "detail", "reason", "code"):
            nested = extract_error_text(value.get(key))
            if nested:
                return nested
        return json.dumps(value, ensure_ascii=False)[:500]
    if isinstance(value, list):
        for item in value:
            nested = extract_error_text(item)
            if nested:
                return nested
        return ""
    return str(value)


def get_lk_config(required: bool = False) -> dict[str, str] | None:
    base_url = get_config_value(ENV_BASE_URL).rstrip("/")
    model = get_config_value(ENV_MODEL)
    api_key = get_config_value(ENV_API_KEY)
    if base_url and model and api_key:
        return {"base_url": base_url, "model": model, "api_key": api_key}
    if required:
        require_config(ENV_BASE_URL)
        require_config(ENV_MODEL)
        require_config(ENV_API_KEY)
    return None


def ensure_lk_balance(route_state: dict[str, bool], lk_config: dict[str, str]) -> None:
    if route_state.get("lk_balance_checked"):
        return
    check_balance(lk_config["base_url"], lk_config["api_key"])
    route_state["lk_balance_checked"] = True


def run_with_provider_route(
    *,
    prompt: str,
    size: str,
    resolution: str,
    quality: str | None,
    reference_inputs: list[str],
    output_dir: Path,
    fmt: str,
    poll_interval: int,
    timeout: int,
    lk_config: dict[str, str] | None,
    route_state: dict[str, bool],
) -> list[Path]:
    if lk_config is None:
        fail("未完整配置 VTeTech 链路（IMG_BASE_URL / IMG_MODEL / IMG_API_KEY 或 API_KEY）。")
    ensure_lk_balance(route_state, lk_config)
    lk_payload = build_media_payload_from_options(
        prompt=prompt,
        model=lk_config["model"],
        size=size,
        resolution=resolution,
        quality=quality,
        reference_inputs=reference_inputs,
    )
    return run_media(
        lk_config["base_url"],
        lk_config["api_key"],
        lk_payload,
        output_dir,
        fmt,
        poll_interval,
        timeout,
    )


# ── 批量图片包 ──────────────────────────────────────────────

def load_pack_file(pack_file: str) -> dict[str, Any]:
    path = Path(pack_file)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        fail(f"无法读取 pack 文件：{exc}")
    except json.JSONDecodeError as exc:
        fail(f"pack 文件不是有效 JSON：第 {exc.lineno} 行第 {exc.colno} 列，{exc.msg}")
    if not isinstance(data, dict):
        fail("pack 文件顶层必须是 JSON 对象。")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        fail("pack 文件必须包含非空 items 数组。")
    return data


def run_pack(
    pack: dict[str, Any],
    lk_config: dict[str, str] | None,
    args: argparse.Namespace,
    route_state: dict[str, bool],
) -> list[Path]:
    defaults = pack.get("defaults") if isinstance(pack.get("defaults"), dict) else {}
    raw_output_dir = str(pack.get("output_dir") or args.output_dir).strip()
    base_output_dir = resolve_skill_output_dir(raw_output_dir)
    style_lock = str(pack.get("style_lock") or "").strip()
    global_images = collect_reference_image_inputs(pack.get("reference_images") or pack.get("images") or args.image)
    all_paths: list[Path] = []

    for index, raw_item in enumerate(pack["items"], start=1):
        if not isinstance(raw_item, dict):
            fail(f"pack items[{index - 1}] 必须是对象。")
        item_id = str(raw_item.get("id") or raw_item.get("name") or f"image-{index:02d}")
        prompt = read_pack_item_prompt(raw_item)

        item_images = collect_reference_image_inputs(raw_item.get("reference_images") or raw_item.get("images"))
        reference_images = global_images + item_images
        if len(reference_images) > 10:
            fail(f"图片任务 {item_id} 的参考图片超过 10 张。")

        prompt, analysis_context = prepare_prompt_with_sell_points(prompt, reference_images, lk_config)
        if style_lock and not prompt.startswith(style_lock):
            prompt = f"{style_lock}\n\n{prompt}"
        if analysis_context:
            prompt = inject_context_after_prefix(prompt, style_lock, analysis_context)

        size = str(raw_item.get("size") or defaults.get("size") or args.size)
        resolution = str(raw_item.get("resolution") or defaults.get("resolution") or args.resolution)
        if resolution not in VALID_RESOLUTIONS:
            fail(f"图片任务 {item_id} 的 resolution 不支持：{resolution}")
        quality_value = raw_item.get("quality", defaults.get("quality", args.quality))
        quality = str(quality_value) if quality_value else None
        fmt_value = raw_item.get("format", defaults.get("format", args.format))
        fmt = str(fmt_value or args.format)
        if fmt not in {"png", "jpeg", "webp"}:
            fail(f"图片任务 {item_id} 的 format 不支持：{fmt}")

        output_dir = base_output_dir
        print(f"[pack] ({index}/{len(pack['items'])}) 生成 {item_id}", file=sys.stderr)
        all_paths.extend(
            run_with_provider_route(
                prompt=prompt,
                size=size,
                resolution=resolution,
                quality=quality,
                reference_inputs=reference_images,
                output_dir=output_dir,
                fmt=fmt,
                poll_interval=args.poll_interval,
                timeout=args.timeout,
                lk_config=lk_config,
                route_state=route_state,
            )
        )
    return all_paths


def read_pack_item_prompt(item: dict[str, Any]) -> str:
    prompt = item.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt.strip()
    prompt_file = item.get("prompt_file")
    if isinstance(prompt_file, str) and prompt_file.strip():
        try:
            return Path(prompt_file).read_text(encoding="utf-8-sig").strip()
        except OSError as exc:
            fail(f"无法读取图片任务 prompt_file：{exc}")
    fail("每个 pack item 必须包含 prompt 或 prompt_file。")


def safe_relative_dir(value: str) -> Path:
    parts: list[str] = []
    for raw_part in re.split(r"[\\/]+", value.strip()):
        part = raw_part.strip()
        if not part or part in {".", ".."}:
            continue
        cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "-", part).strip(".-")
        if cleaned:
            parts.append(cleaned[:80])
    if not parts:
        return Path("image")
    return Path(*parts)


# ── CLI ──────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="统一图像生成脚本：当前仅使用 VTeTech。"
    )
    prompt_group = parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt", help="直接传入图片生成 Prompt。")
    prompt_group.add_argument("--prompt-file", help="从文本文件读取图片生成 Prompt。")
    prompt_group.add_argument("--pack-file", help="批量生图 JSON 配置文件；每个 item 独立生成一张图片。")
    parser.add_argument("--output-dir", default="", help="图片输出目录；未指定时使用 IMAGE_OUTPUT_ROOT/时间戳子目录。")
    parser.add_argument("--env-file", help="指定 .env 配置文件；不指定时从当前目录向上查找。")
    parser.add_argument("--mode", help="保留兼容参数；当前仅用于 VTeTech 媒体接口兼容。")
    parser.add_argument("--size", default="1:1", help="图片尺寸。支持比例（如 1:1、2:3、16:9）或模型返回的像素尺寸（如 2048x2048）；传比例时按 --resolution 映射。")
    parser.add_argument("--resolution", default="2k", choices=VALID_RESOLUTIONS, help="比例尺寸映射档位，默认 2k。")
    parser.add_argument("--quality", help="图片质量参数，例如 auto、low、medium、high。")
    parser.add_argument("--n", type=int, default=1, help="兼容参数；当前平台每次请求只创建一个任务。")
    parser.add_argument("--image", nargs="+", help="参考图片路径或公开 URL，可传 1-10 张；本地图片会自动上传到 COS 后传给 VTeTech。")
    parser.add_argument("--poll-interval", type=int, default=5, help="任务轮询间隔秒数，默认 5。")
    parser.add_argument("--timeout", type=int, default=1800, help="任务轮询超时秒数，默认 1800。")
    parser.add_argument("--format", choices=("png", "jpeg", "webp"), default="png", help="图片保存格式，默认 png。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    apply_config_file()
    env_file = Path(args.env_file) if args.env_file else find_default_env_file()
    load_env_file(env_file)
    lk_config = get_lk_config(required=True)
    route_state = {"force_lk": False, "lk_balance_checked": False}

    assert lk_config is not None
    mode = detect_mode(lk_config["base_url"], args.mode)
    print(f"API 路由: 仅 VTeTech | 模式={mode} | base_url={lk_config['base_url']} | model={lk_config['model']}", file=sys.stderr)
    if args.n != 1:
        print("[info] 当前平台忽略 --n，单次请求只会创建一个任务。", file=sys.stderr)

    if args.pack_file:
        pack = load_pack_file(args.pack_file)
        paths = run_pack(pack, lk_config, args, route_state)
    else:
        prompt = read_prompt(args)
        reference_inputs = collect_reference_image_inputs(args.image)
        prompt, analysis_context = prepare_prompt_with_sell_points(prompt, reference_inputs, lk_config)
        leading_style_lock = extract_leading_campaign_style_lock(prompt)
        if analysis_context:
            prompt = inject_context_after_prefix(prompt, leading_style_lock, analysis_context)
        output_dir = resolve_skill_output_dir(args.output_dir)
        paths = run_with_provider_route(
            prompt=prompt,
            size=args.size,
            resolution=args.resolution,
            quality=args.quality,
            reference_inputs=reference_inputs,
            output_dir=output_dir,
            fmt=args.format,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
            lk_config=lk_config,
            route_state=route_state,
        )

    print("生成完成：")
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
