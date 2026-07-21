#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按目录批量生图工作流。

输入目录结构：
root/
  product-a/
    in/
      any-name.txt
      ref-1.jpg
    output/

当前实现使用双链路：
- 图片理解：POST {IMG_BASE_URL}/v1/chat/completions
- 图片生成：POST {IMG_BASE_URL}/v1/media/generate
- 状态轮询：GET  {IMG_BASE_URL}/v1/skills/task-status?task_id=...
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import datetime as dt
import http.client
import json
import mimetypes
import os
import random
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import apply_config_file


UNDERSTANDING_ENDPOINT = "/v1/chat/completions"
UNDERSTANDING_MODEL = "gpt-5.4"
GENERATION_ENDPOINT = "/v1/media/generate"
TASK_STATUS_ENDPOINT = "/v1/skills/task-status"
GENERATION_MODEL_FALLBACK = "gpt-image-2"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
TASK_STATES = {
    "pending",
    "validating",
    "understanding",
    "planning",
    "submitting",
    "polling",
    "downloading",
    "completed",
    "failed",
    "interrupted",
    "skipped",
}
ENV_BASE_URL = "IMG_BASE_URL"
ENV_MODEL = "IMG_MODEL"
ENV_API_KEY = "IMG_API_KEY"
ENV_UNDERSTANDING_BASE_URL = "UNDERSTANDING_BASE_URL"
ENV_UNDERSTANDING_MODEL = "UNDERSTANDING_MODEL"
ENV_UNDERSTANDING_API_KEY = "UNDERSTANDING_API_KEY"
ENV_COS_BUCKET_URL = "COS_BUCKET_URL"
ENV_COS_UPLOAD_PREFIX = "COS_UPLOAD_PREFIX"
ENV_ALIASES = {
    ENV_BASE_URL: ("API_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE", "BASE_URL"),
    ENV_MODEL: ("IMAGE_MODEL", "OPENAI_IMAGE_MODEL", "OPENAI_MODEL"),
    ENV_API_KEY: ("API_KEY", "OPENAI_API_KEY"),
    ENV_UNDERSTANDING_BASE_URL: (ENV_BASE_URL,),
    ENV_UNDERSTANDING_MODEL: (ENV_MODEL,),
    ENV_UNDERSTANDING_API_KEY: (ENV_API_KEY,),
}
MARKET_LANGUAGE_RULES = {
    "马来西亚": ("Malaysia", "Malay"),
    "越南": ("Vietnam", "Vietnamese"),
    "新加坡": ("Singapore", "English"),
    "菲律宾": ("Philippines", "English"),
    "泰国": ("Thailand", "Thai"),
    "英国": ("United Kingdom", "English"),
    "UK": ("United Kingdom", "English"),
    "法国": ("France", "French"),
    "西班牙": ("Spain", "Spanish"),
    "德国": ("Germany", "German"),
    "意大利": ("Italy", "Italian"),
    "荷兰": ("Netherlands", "Dutch"),
    "波兰": ("Poland", "Polish"),
    "日本": ("Japan", "Japanese"),
    "韩国": ("South Korea", "Korean"),
    "美国": ("United States", "English"),
    "加拿大": ("Canada", "English"),
    "澳大利亚": ("Australia", "English"),
    "新西兰": ("New Zealand", "English"),
    "墨西哥": ("Mexico", "Spanish"),
    "巴西": ("Brazil", "Portuguese"),
    "葡萄牙": ("Portugal", "Portuguese"),
    "智利": ("Chile", "Spanish"),
    "哥伦比亚": ("Colombia", "Spanish"),
    "秘鲁": ("Peru", "Spanish"),
    "阿根廷": ("Argentina", "Spanish"),
    "土耳其": ("Turkey", "Turkish"),
    "沙特": ("Saudi Arabia", "Arabic"),
    "阿联酋": ("United Arab Emirates", "Arabic"),
    "南非": ("South Africa", "English"),
}
LANGUAGE_KEYWORDS = {
    "马来语": "Malay",
    "马来文": "Malay",
    "越南语": "Vietnamese",
    "越文": "Vietnamese",
    "英语": "English",
    "英文": "English",
    "泰语": "Thai",
    "泰文": "Thai",
    "法语": "French",
    "法文": "French",
    "西班牙语": "Spanish",
    "西语": "Spanish",
    "德语": "German",
    "德文": "German",
    "意大利语": "Italian",
    "荷兰语": "Dutch",
    "波兰语": "Polish",
    "日语": "Japanese",
    "日文": "Japanese",
    "韩语": "Korean",
    "韩文": "Korean",
    "葡萄牙语": "Portuguese",
    "葡语": "Portuguese",
    "土耳其语": "Turkish",
    "阿拉伯语": "Arabic",
    "中文": "Chinese",
    "汉语": "Chinese",
    "华文": "Chinese",
}
DEFAULT_PRIMARY_COUNTS = {
    "hero": 5,
    "detail": 8,
    "model": 4,
}
DEFAULT_OPTIONAL_COUNTS = {
    "lifestyle": 2,
}
JOB_TEMPLATE_MAP = {
    "hero": "01-hero-image.json",
    "lifestyle": "02-lifestyle-scene.json",
    "model": "08-model-showcase.json",
    "detail": "11-infographic.json",
}
JOB_SIZE_CYCLES = {
    "hero": ["1:1"],
    "lifestyle": ["1:1"],
    "model": ["1:1"],
    "detail": ["9:16"],
}
SIZE_PRESETS = {
    "1:1": "1024x1024",
    "2:3": "1024x1536",
    "3:2": "1536x1024",
    "3:4": "960x1280",
    "4:3": "1280x960",
    "4:5": "960x1280",
    "5:4": "1280x960",
    "9:16": "1088x1920",
    "16:9": "1920x1088",
}
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "references" / "templates"


class BatchWorkflowError(Exception):
    """批量流程普通失败。"""


class TaskInterruptedError(Exception):
    """需要标记为 interrupted 的失败。"""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


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


@dataclass
class AnalysisResult:
    raw_text: str
    structured: dict[str, Any] | None = None


@dataclass
class ParsedRequirement:
    market: str | None
    language: str
    explicit_language: str | None
    contains_tiktok_market_only: bool
    needs_flag_element: bool
    style_requirement: str | None
    raw_text: str
    counts: dict[str, int]
    detail_size: str
    size_overrides: dict[str, str | None]


@dataclass
class ImageJob:
    job_name: str
    job_type: str
    template_name: str
    size: str
    prompt: str
    market: str | None
    target_language: str
    status: str = "pending"
    task_id: str | None = None
    output_files: list[str] = field(default_factory=list)
    error: str | None = None
    attempt_count: int = 0


@dataclass
class ProductTask:
    task_name: str
    source_dir: Path
    input_dir: Path
    output_base_dir: Path
    output_dir: Path
    requirement_file: Path | None
    reference_images: list[Path]
    requirement_text: str | None = None
    market: str | None = None
    language: str | None = None
    status: str = "pending"
    validation_errors: list[str] = field(default_factory=list)
    image_jobs: list[ImageJob] = field(default_factory=list)
    error: str | None = None
    interrupt_reason: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    log_path: Path | None = None
    manifest_path: Path | None = None


@dataclass
class BatchConfig:
    root_dir: Path
    run_timestamp: str
    dry_run: bool
    max_parallel_products: int = 2
    per_product_poll_workers: int = 2
    poll_interval_seconds: int = 5
    poll_timeout_seconds: int = 300
    max_retries: int = 3
    submit_interval_min_seconds: float = 3.0
    submit_interval_max_seconds: float = 5.0


@dataclass
class BatchSummary:
    total: int = 0
    completed: int = 0
    failed: int = 0
    interrupted: int = 0
    skipped: int = 0


class PlainLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def log(self, message: str) -> None:
        timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


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
    lines = env_file.read_text(encoding="utf-8-sig").splitlines()
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise BatchWorkflowError(f".env 第 {line_number} 行格式不正确，应为 KEY=value。")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise BatchWorkflowError(f".env 第 {line_number} 行缺少变量名。")
        os.environ[key] = strip_env_value(value)


def get_config_value(name: str, default: str = "") -> str:
    candidates = (name, *ENV_ALIASES.get(name, ()))
    for candidate in candidates:
        value = os.environ.get(candidate, "").strip()
        if value:
            return value
    return default


def require_config(name: str) -> str:
    value = get_config_value(name)
    if value:
        return value
    accepted = "、".join((name, *ENV_ALIASES.get(name, ())))
    raise BatchWorkflowError(f"缺少配置 {name}，可接受变量名：{accepted}")


def is_public_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def guess_content_type(path: Path) -> str:
    content_type, _ = mimetypes.guess_type(str(path))
    return content_type or "application/octet-stream"


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
    return parsed if isinstance(parsed, dict) else None


def extract_openai_text(result: dict[str, Any]) -> str:
    choices = result.get("choices")
    if not isinstance(choices, list):
        return ""
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
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            if parts:
                return "\n".join(parts).strip()
    return ""


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


def sanitize_filename_part(text: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_-]+", "-", text.strip())
    sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-")
    return sanitized or "image"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_template(template_name: str) -> dict[str, Any]:
    path = TEMPLATES_DIR / template_name
    return json.loads(path.read_text(encoding="utf-8"))


def build_image_understanding_prompt(target_language: str = "Chinese") -> str:
    return (
        "你是电商商品分析助手。请只根据输入图片总结商品视觉特征，不要编造看不到的信息。"
        f"目标市场的图片文案和分析字段使用 {target_language}；产品事实必须保持准确，不要把无法确认的信息翻译或补全。"
        "优先输出：product_type、core_sell_points、style_keywords、scene_suggestions、risk_notes。"
        "请严格输出 JSON，不要输出代码块，不要输出额外解释。"
        '{"product_type":"","core_sell_points":[{"point":"","evidence":""}],"style_keywords":[],"scene_suggestions":[],"risk_notes":[]}'
    )


def format_analysis_summary(analysis: AnalysisResult) -> str:
    structured = analysis.structured or {}
    lines: list[str] = []
    product_type = structured.get("product_type")
    if isinstance(product_type, str) and product_type.strip():
        lines.append(f"Product type: {product_type.strip()}")
    core_sell_points = structured.get("core_sell_points")
    if isinstance(core_sell_points, list):
        for index, item in enumerate(core_sell_points, start=1):
            if isinstance(item, dict):
                point = str(item.get("point") or "").strip()
                evidence = str(item.get("evidence") or "").strip()
                if point:
                    if evidence:
                        lines.append(f"Sell point {index}: {point} | Evidence: {evidence}")
                    else:
                        lines.append(f"Sell point {index}: {point}")
    style_keywords = structured.get("style_keywords")
    if isinstance(style_keywords, list):
        cleaned = [str(item).strip() for item in style_keywords if str(item).strip()]
        if cleaned:
            lines.append(f"Style keywords: {', '.join(cleaned)}")
    scene_suggestions = structured.get("scene_suggestions")
    if isinstance(scene_suggestions, list):
        cleaned = [str(item).strip() for item in scene_suggestions if str(item).strip()]
        if cleaned:
            lines.append(f"Scene suggestions: {', '.join(cleaned)}")
    risk_notes = structured.get("risk_notes")
    if isinstance(risk_notes, list):
        cleaned = [str(item).strip() for item in risk_notes if str(item).strip()]
        if cleaned:
            lines.append(f"Risk notes: {', '.join(cleaned)}")
    if not lines and analysis.raw_text.strip():
        lines.append(analysis.raw_text.strip())
    return "\n".join(lines).strip()


def detect_market(requirement_text: str) -> tuple[str | None, str]:
    for keyword, (market, language) in MARKET_LANGUAGE_RULES.items():
        if keyword in requirement_text:
            return market, language
    return None, "Chinese"


def detect_explicit_language(requirement_text: str) -> str | None:
    for keyword, language in LANGUAGE_KEYWORDS.items():
        if keyword in requirement_text:
            return language
    return None


def contains_tiktok_market_only(requirement_text: str) -> bool:
    normalized = requirement_text.lower()
    if "tiktok" not in normalized:
        return False
    for keyword in MARKET_LANGUAGE_RULES:
        if keyword in requirement_text:
            return False
    return True


def extract_style_requirement(requirement_text: str) -> str | None:
    patterns = [
        r"风格要求[:：]\s*([^\n。]+)",
        r"风格[:：]\s*([^\n。]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, requirement_text, re.I)
        if match:
            value = normalize_whitespace(match.group(1))
            return value or None
    return None


def extract_count(requirement_text: str, keywords: list[str]) -> int | None:
    for keyword in keywords:
        pattern = rf"(\d+)\s*张[^。\n，,;；]*?{re.escape(keyword)}"
        match = re.search(pattern, requirement_text, re.I)
        if match:
            return int(match.group(1))
        reverse_pattern = rf"{re.escape(keyword)}[^。\n，,;；]*?(\d+)\s*张"
        match = re.search(reverse_pattern, requirement_text, re.I)
        if match:
            return int(match.group(1))
    return None


def requirement_mentions_any(requirement_text: str, keywords: list[str]) -> bool:
    return any(keyword in requirement_text for keyword in keywords)


def detect_job_type_from_segment(segment: str) -> str | None:
    if requirement_mentions_any(segment, ["9:16详情图", "9:16 详情图", "详情图", "信息图"]):
        return "detail"
    if requirement_mentions_any(segment, ["手部场景图", "手模图", "手持场景图"]):
        return "lifestyle"
    if requirement_mentions_any(segment, ["模特佩戴场景图", "模特佩戴图", "模特图", "上身图", "模特手拿", "模特展示图", "模特展示", "手拿展示图"]):
        return "model"
    if "场景图" in segment:
        return "model"
    if requirement_mentions_any(segment, ["商品白底主图", "白底主图", "主图", "白底图"]):
        return "hero"
    return None


def extract_ratio_from_segment(segment: str) -> str | None:
    match = re.search(r"(\d+\s*:\s*\d+)", segment)
    if not match:
        return None
    return match.group(1).replace(" ", "")


def extract_counts_and_sizes_by_segment(
    requirement_text: str,
) -> tuple[dict[str, int | None], dict[str, str | None]]:
    counts: dict[str, int | None] = {"hero": None, "lifestyle": None, "model": None, "detail": None}
    size_overrides: dict[str, str | None] = {"hero": None, "lifestyle": None, "model": None, "detail": None}
    segments = re.split(r"[+＋]", requirement_text)
    for segment in segments:
        job_type = detect_job_type_from_segment(segment)
        if not job_type:
            continue
        match = re.search(r"(\d+)\s*张", segment)
        if match:
            value = int(match.group(1))
            counts[job_type] = (counts[job_type] or 0) + value
        ratio = extract_ratio_from_segment(segment)
        if ratio:
            size_overrides[job_type] = ratio
    return counts, size_overrides


def parse_requirement(requirement_text: str) -> ParsedRequirement:
    market, market_language = detect_market(requirement_text)
    explicit_language = detect_explicit_language(requirement_text)
    language = market_language if market else (explicit_language or "Chinese")
    primary_keywords = {
        "hero": ["白底主图", "商品白底主图", "主图", "白底图"],
        "lifestyle": ["手部场景图", "手模图", "手持场景图"],
        "model": ["模特佩戴场景图", "模特佩戴图", "模特图", "上身图", "模特手拿", "模特展示图", "模特展示", "手拿展示图"],
        "detail": ["详情图", "信息图", "9:16 详情图", "9:16详情图"],
    }
    counts, size_overrides = extract_counts_and_sizes_by_segment(requirement_text)
    for key, keywords in primary_keywords.items():
        if counts[key] is None:
            counts[key] = extract_count(requirement_text, keywords)
    mentions = {
        key: requirement_mentions_any(requirement_text, keywords)
        for key, keywords in primary_keywords.items()
    }
    explicit_count_exists = any(value is not None for value in counts.values())
    if not explicit_count_exists and not any(mentions.values()):
        counts.update(DEFAULT_PRIMARY_COUNTS)
    else:
        for key in ("hero", "detail", "model"):
            if mentions[key] and counts[key] is None:
                counts[key] = DEFAULT_PRIMARY_COUNTS[key]
        if mentions["lifestyle"] and counts["lifestyle"] is None:
            counts["lifestyle"] = DEFAULT_OPTIONAL_COUNTS["lifestyle"]
    counts = {key: (value or 0) for key, value in counts.items()}
    detail_size = "9:16" if "9:16" in requirement_text.replace(" ", "") else "9:16"
    return ParsedRequirement(
        market=market,
        language=language,
        explicit_language=explicit_language,
        contains_tiktok_market_only=contains_tiktok_market_only(requirement_text),
        needs_flag_element="国旗" in requirement_text,
        style_requirement=extract_style_requirement(requirement_text),
        raw_text=requirement_text,
        counts=counts,
        detail_size=detail_size,
        size_overrides=size_overrides,
    )


def build_job_size(job_type: str, index: int, parsed: ParsedRequirement) -> str:
    override = parsed.size_overrides.get(job_type)
    if override:
        return override
    if job_type == "detail":
        return parsed.detail_size
    cycle = JOB_SIZE_CYCLES[job_type]
    return cycle[(index - 1) % len(cycle)]


def build_product_summary_for_prompt(task: ProductTask, analysis: AnalysisResult) -> str:
    summary = format_analysis_summary(analysis)
    if summary:
        return summary
    return "Match the product in the reference images exactly, without redesigning the SKU."


def build_job_prompt(
    task: ProductTask,
    job_type: str,
    job_index: int,
    parsed: ParsedRequirement,
    analysis: AnalysisResult,
) -> str:
    template_name = JOB_TEMPLATE_MAP[job_type]
    template = read_template(template_name)
    template_name_human = str(template.get("name") or template_name)
    prompt_template = template.get("prompt_template") if isinstance(template.get("prompt_template"), dict) else {}
    prompt_lines = [
        "Create a clean TikTok Shop ecommerce product image for short-video commerce use.",
        "Generate exactly one standalone image for this request.",
        "This request is only for one image, not for the whole image pack.",
        f"Job type: {job_type}.",
        f"Template direction: {template_name_human}.",
        "Keep the product SKU exactly consistent with the reference images.",
        "Do not change the structure, silhouette, hardware, proportions, opening shape, or visible product details.",
        "Do not create a collage, grid, multi-panel layout, contact sheet, before-after board, or mixed scene summary.",
        "Do not combine hero image, model image, hand scene image, and detail infographic requirements into one frame.",
        "Ignore all other image types mentioned in the batch requirement. Only render the current job.",
    ]
    if task.market:
        prompt_lines.append(f"Target market reference: {task.market}.")
    prompt_lines.append(f"Target visible-copy language: {parsed.language}. Use only this language for any on-image copy; do not mix in Chinese, English, or source-language copy unless it is part of the verified product packaging.")
    if parsed.contains_tiktok_market_only and not task.market:
        prompt_lines.append("Target market context: generic ecommerce social commerce market.")
    if parsed.needs_flag_element and task.market:
        prompt_lines.append(f"If any localized design cue is needed, use very subtle {task.market} color cues instead of explicit flag stickers or badges.")
    style_requirement = parsed.style_requirement or "clean, premium, minimal, Apple keynote style"
    prompt_lines.append(f"Style requirement: {style_requirement}.")
    if prompt_template:
        for key in ("type", "background", "lighting", "composition", "quality"):
            value = prompt_template.get(key)
            if isinstance(value, str) and value.strip():
                prompt_lines.append(f"{key.capitalize()}: {value.strip()}.")
    if job_type == "detail":
        prompt_lines.extend(
            [
                "Generate one single 9:16 infographic image only.",
                "This must be an ecommerce infographic, not a plain scene photo.",
                "Use a 9:16 composition with headline, short benefit labels, structured feature callouts, and clean visual hierarchy.",
                "Keep all on-image copy factual, neutral, and product-descriptive only.",
                "Do not include guarantee claims, certification badges, medical claims, safety promises, seller assurance labels, ranking claims, or exaggerated promotional language.",
                "Do not use before-after comparison, review screenshot, trust badge wall, or compliance-looking stamp graphics.",
            ]
        )
    elif job_type == "hero":
        prompt_lines.extend(
            [
                "Generate one single hero image only.",
                "Use clean white or minimal studio background suitable for product hero image.",
                "Prefer no on-image text. If text is absolutely needed, keep it minimal, factual, and non-promotional.",
                "Do not add flag stickers, badge labels, ranking labels, assurance labels, or sales banners.",
            ]
        )
    elif job_type == "lifestyle":
        prompt_lines.extend(
            [
                "Generate one single hand/lifestyle image only.",
                "Use hand interaction or light lifestyle usage scenario while keeping the product dominant.",
            ]
        )
    elif job_type == "model":
        prompt_lines.extend(
            [
                "Generate one single model showcase image only.",
                "Use model wearing/holding scenario while keeping the product structure exact.",
                "Prefer no on-image text. If text is absolutely needed, keep it minimal, factual, and non-promotional.",
            ]
        )
    prompt_lines.append(f"Current image index in the batch: {job_index}.")
    prompt_lines.append("Product understanding from the reference images:")
    prompt_lines.append(build_product_summary_for_prompt(task, analysis))
    prompt_lines.append("Batch requirement context for reference only:")
    prompt_lines.append(parsed.raw_text.strip())
    prompt_lines.append(
        "Negative constraints: no SKU drift, no fake brand, no extra product parts, no distorted proportions, "
        "no guarantee claim, no medical or safety claim, no certification badge, no seller assurance badge, no fake review block."
    )
    return "\n".join(prompt_lines).strip()


def is_hand_accessory_product(task: ProductTask, parsed: ParsedRequirement, analysis: AnalysisResult) -> bool:
    source_text = " ".join(
        [
            parsed.raw_text,
            analysis.raw_text,
            json.dumps(analysis.structured or {}, ensure_ascii=False),
            " ".join(path.stem for path in task.reference_images),
        ]
    ).lower()
    keywords = [
        "戒指",
        "手链",
        "手镯",
        "手表",
        "手串",
        "指环",
        "美甲",
        "nail",
        "ring",
        "bracelet",
        "bangle",
        "watch",
    ]
    return any(keyword in source_text for keyword in keywords)


def plan_image_jobs(task: ProductTask, parsed: ParsedRequirement, analysis: AnalysisResult) -> list[ImageJob]:
    jobs: list[ImageJob] = []
    effective_counts = dict(parsed.counts)
    if effective_counts.get("lifestyle", 0) > 0 and not is_hand_accessory_product(task, parsed, analysis):
        effective_counts["model"] = effective_counts.get("model", 0) + effective_counts["lifestyle"]
        effective_counts["lifestyle"] = 0
    for job_type in ("hero", "lifestyle", "model", "detail"):
        count = effective_counts.get(job_type, 0)
        if count <= 0:
            continue
        for index in range(1, count + 1):
            size = build_job_size(job_type, index, parsed)
            job_name = f"{job_type}-{index:02d}"
            jobs.append(
                ImageJob(
                    job_name=job_name,
                    job_type=job_type,
                    template_name=JOB_TEMPLATE_MAP[job_type],
                    size=size,
                    prompt=build_job_prompt(task, job_type, index, parsed, analysis),
                    market=task.market,
                    target_language=task.language or parsed.language,
                )
            )
    return jobs


def task_to_manifest(task: ProductTask) -> dict[str, Any]:
    return {
        "task_name": task.task_name,
        "source_dir": str(task.source_dir),
        "input_dir": str(task.input_dir),
        "output_dir": str(task.output_dir),
        "requirement_file": task.requirement_file.name if task.requirement_file else None,
        "reference_images": [path.name for path in task.reference_images],
        "market": task.market,
        "language": task.language,
        "status": task.status,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "image_jobs": [
            {
                "job_name": job.job_name,
                "job_type": job.job_type,
                "template_name": job.template_name,
                "size": job.size,
                "market": job.market,
                "target_language": job.target_language,
                "task_id": job.task_id,
                "status": job.status,
                "attempt_count": job.attempt_count,
                "output_files": job.output_files,
                "error": job.error,
            }
            for job in task.image_jobs
        ],
        "error": task.error,
        "interrupt_reason": task.interrupt_reason,
        "validation_errors": task.validation_errors,
    }


def create_placeholder_png(path: Path) -> None:
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WH0l1wAAAAASUVORK5CYII="
    )
    path.write_bytes(png_bytes)


class LkClient:
    def __init__(
        self,
        generation_base_url: str,
        model: str,
        api_key: str,
        understanding_base_url: str,
        understanding_model: str,
        understanding_api_key: str,
    ) -> None:
        self.generation_base_url = generation_base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.understanding_base_url = understanding_base_url.rstrip("/")
        self.understanding_model = understanding_model
        self.understanding_api_key = understanding_api_key
        self._upload_cache: dict[str, str] = {}

    def request_json(
        self,
        method: str,
        url: str,
        api_key: str,
        payload: dict[str, Any] | None = None,
        timeout: int = 120,
    ) -> dict[str, Any]:
        last_error: ApiRequestError | None = None
        for attempt in range(1, 4):
            body = json.dumps(payload).encode("utf-8") if payload is not None else None
            headers = {"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT}
            if payload is not None:
                headers["Content-Type"] = "application/json"
            request = urllib.request.Request(url, data=body, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw = response.read().decode("utf-8")
                parsed_result = json.loads(raw)
                if not isinstance(parsed_result, dict):
                    raise ApiRequestError(f"接口返回格式异常：{raw[:500]}")
                return parsed_result
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                parsed = None
                try:
                    parsed = json.loads(detail)
                except json.JSONDecodeError:
                    parsed = None
                raise ApiRequestError(
                    f"HTTP {exc.code}",
                    status_code=exc.code,
                    detail=detail,
                    payload=parsed,
                ) from exc
            except json.JSONDecodeError as exc:
                last_error = ApiRequestError(f"接口返回的不是有效 JSON：{str(exc)}")
            except urllib.error.URLError as exc:
                last_error = ApiRequestError(f"无法连接接口：{exc.reason}")
            except (http.client.RemoteDisconnected, TimeoutError) as exc:
                last_error = ApiRequestError("接口连接失败或超时，请稍后重试。")
            if attempt < 3:
                time.sleep(1.5 * attempt)
        raise last_error or ApiRequestError("接口请求失败。")

    def _load_reference_image_bytes(self, source_path: Path) -> tuple[str, bytes]:
        return guess_content_type(source_path), source_path.read_bytes()

    def _build_openai_image_parts(self, reference_images: list[Path]) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        for source_path in reference_images:
            mime_type, image_bytes = self._load_reference_image_bytes(source_path)
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}",
                    },
                }
            )
        return parts

    def analyze_product_images(self, reference_images: list[Path], target_language: str = "Chinese") -> AnalysisResult:
        if not reference_images:
            raise BatchWorkflowError("图片理解阶段缺少参考图。")
        payload = {
            "model": self.understanding_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": build_image_understanding_prompt(target_language)},
                        *self._build_openai_image_parts(reference_images),
                    ],
                }
            ],
            "temperature": 0,
            "max_tokens": 768,
        }
        endpoint = f"{self.understanding_base_url}{UNDERSTANDING_ENDPOINT}"
        result = self.request_json("POST", endpoint, self.understanding_api_key, payload, timeout=120)
        if result.get("error"):
            error = extract_error_text(result.get("error")) or json.dumps(result, ensure_ascii=False)[:300]
            raise BatchWorkflowError(f"{self.understanding_model} 图片理解失败：{error}")
        text = extract_openai_text(result)
        if not text:
            raise BatchWorkflowError(f"{self.understanding_model} 图片理解返回空内容：{json.dumps(result, ensure_ascii=False)[:300]}")
        return AnalysisResult(raw_text=text, structured=parse_json_object(text))

    def _build_cos_object_key(self, source_path: Path) -> str:
        prefix = get_config_value(ENV_COS_UPLOAD_PREFIX, "image").strip("/")
        timestamp = time.strftime("%Y%m%d/%H%M%S")
        nonce = uuid.uuid4().hex[:8]
        filename = f"{source_path.stem}-{timestamp}-{nonce}{source_path.suffix.lower()}"
        parts = [part for part in (prefix, filename) if part]
        return "/".join(parts)

    def _ensure_public_reference_url(self, source_path: Path) -> str:
        cache_key = str(source_path.resolve())
        if cache_key in self._upload_cache:
            return self._upload_cache[cache_key]
        if get_config_value("REFERENCE_IMAGE_MODE", "base64").lower() != "cos":
            try:
                data = source_path.read_bytes()
            except OSError as exc:
                raise BatchWorkflowError(f"Unable to read reference image: {exc}") from exc
            data_uri = f"data:{guess_content_type(source_path)};base64,{base64.b64encode(data).decode('ascii')}"
            self._upload_cache[cache_key] = data_uri
            return data_uri
        bucket_url = get_config_value(ENV_COS_BUCKET_URL)
        if not bucket_url:
            try:
                data = source_path.read_bytes()
            except OSError as exc:
                raise BatchWorkflowError(f"Unable to read reference image: {exc}") from exc
            data_uri = f"data:{guess_content_type(source_path)};base64,{base64.b64encode(data).decode('ascii')}"
            self._upload_cache[cache_key] = data_uri
            return data_uri
        if not bucket_url.startswith(("http://", "https://")):
            raise BatchWorkflowError("COS_BUCKET_URL 必须是以 http:// 或 https:// 开头的公网桶地址。")
        object_key = self._build_cos_object_key(source_path)
        upload_url = f"{bucket_url.rstrip('/')}/{urllib.parse.quote(object_key, safe='/')}"
        request = urllib.request.Request(
            upload_url,
            data=source_path.read_bytes(),
            headers={
                "Content-Type": guess_content_type(source_path),
                "Content-Length": str(source_path.stat().st_size),
                "User-Agent": USER_AGENT,
            },
            method="PUT",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                if response.status not in {200, 201, 204}:
                    raise BatchWorkflowError(f"COS 上传失败，HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise BatchWorkflowError(f"COS 上传失败，HTTP {exc.code}：{detail}") from exc
        except urllib.error.URLError as exc:
            raise BatchWorkflowError(f"COS 上传失败：{exc.reason}") from exc
        except TimeoutError as exc:
            raise BatchWorkflowError("COS 上传超时。") from exc
        self._upload_cache[cache_key] = upload_url
        return upload_url

    def _materialize_reference_images(self, reference_images: list[Path]) -> list[str]:
        results: list[str] = []
        for path in reference_images:
            results.append(self._ensure_public_reference_url(path))
        return results

    def submit_image_job(self, job: ImageJob, reference_images: list[Path]) -> str:
        payload = {
            "model": self.model,
            "prompt": job.prompt,
            "params": {
                "size": SIZE_PRESETS.get(job.size, job.size),
                "quality": "auto",
            },
        }
        materialized_images = self._materialize_reference_images(reference_images)
        if materialized_images:
            payload["params"]["images"] = materialized_images
        endpoint = f"{self.generation_base_url}{GENERATION_ENDPOINT}"
        result = self.request_json("POST", endpoint, self.api_key, payload, timeout=120)
        task_id = self._extract_task_id(result.get("data"))
        if not task_id:
            raise BatchWorkflowError(f"提交响应缺少 task_id：{json.dumps(result, ensure_ascii=False)[:300]}")
        return task_id

    def poll_image_task(self, task_id: str, timeout_seconds: int, interval_seconds: int) -> dict[str, Any]:
        endpoint = (
            f"{self.generation_base_url}{TASK_STATUS_ENDPOINT}"
            f"?{urllib.parse.urlencode({'task_id': task_id})}"
        )
        started = time.time()
        while True:
            elapsed = time.time() - started
            if elapsed > timeout_seconds:
                raise TaskInterruptedError("api_timeout", f"任务 {task_id} 轮询超时（>{timeout_seconds}s）")
            result = self.request_json("GET", endpoint, self.api_key, timeout=30)
            task_data = result.get("data", result)
            if not isinstance(task_data, dict):
                raise BatchWorkflowError(f"任务状态返回格式异常：{json.dumps(result, ensure_ascii=False)[:300]}")
            if self._task_is_final(task_data):
                if self._task_is_failed(task_data):
                    message = self._extract_task_error(task_data)
                    raise TaskInterruptedError("api_failed", f"任务 {task_id} 失败：{message}")
                return task_data
            time.sleep(interval_seconds)

    def download_result_images(self, task_data: dict[str, Any], output_dir: Path, job_name: str) -> list[Path]:
        urls = self._collect_result_urls(task_data)
        if not urls:
            raise BatchWorkflowError(f"任务结果缺少图片地址：{json.dumps(task_data, ensure_ascii=False)[:300]}")
        output_dir.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        for index, image_url in enumerate(urls, start=1):
            suffix = self._suffix_from_url(image_url)
            output_path = output_dir / f"{job_name}-{index:02d}.{suffix}"
            request = urllib.request.Request(image_url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    output_path.write_bytes(response.read())
            except urllib.error.URLError as exc:
                raise BatchWorkflowError(f"下载图片失败：{exc.reason}") from exc
            except TimeoutError as exc:
                raise BatchWorkflowError("下载图片超时。") from exc
            saved.append(output_path)
        return saved

    @staticmethod
    def _extract_task_id(data: Any) -> str | None:
        if isinstance(data, dict):
            for key in ("task_id", "id"):
                value = data.get(key)
                if value is not None:
                    return str(value)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    for key in ("task_id", "id"):
                        value = item.get(key)
                        if value is not None:
                            return str(value)
        return None

    @staticmethod
    def _task_is_final(task_data: dict[str, Any]) -> bool:
        is_final = task_data.get("is_final")
        if isinstance(is_final, bool):
            return is_final
        if isinstance(is_final, str) and is_final.strip().lower() in {"true", "1", "yes", "y"}:
            return True
        state = str(task_data.get("state") or task_data.get("status") or "").strip().lower()
        return state in {"success", "completed", "complete", "finished", "done", "已完成"}

    @staticmethod
    def _task_is_failed(task_data: dict[str, Any]) -> bool:
        state = str(task_data.get("state") or task_data.get("status") or "").strip().lower()
        return state in {"failed", "error", "fail", "失败", "生成失败"}

    @staticmethod
    def _extract_task_error(task_data: dict[str, Any]) -> str:
        error = task_data.get("error")
        if error:
            return extract_error_text(error)
        return extract_error_text(task_data)

    @staticmethod
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
        append_value(result)
        seen: set[str] = set()
        unique: list[str] = []
        for item in urls:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique

    @staticmethod
    def _suffix_from_url(url: str) -> str:
        suffix = Path(urllib.parse.urlparse(url).path).suffix.lower().lstrip(".")
        return suffix if suffix in {"png", "jpg", "jpeg", "webp"} else "png"


class DryRunClient:
    def __init__(self) -> None:
        self._task_counter = 0
        self._task_store: dict[str, dict[str, Any]] = {}

    def analyze_product_images(self, reference_images: list[Path], target_language: str = "Chinese") -> AnalysisResult:
        product_type = "generic product"
        if reference_images:
            product_type = reference_images[0].stem.replace("-", " ")
        structured = {
            "product_type": product_type,
            "core_sell_points": [
                {"point": "clean visible structure", "evidence": "reference image"},
                {"point": "usable for ecommerce packaging", "evidence": "reference image"},
            ],
            "style_keywords": ["minimal", "clean", "commercial"],
            "scene_suggestions": ["studio", "lifestyle", "infographic"],
            "risk_notes": ["do not change sku"],
        }
        return AnalysisResult(raw_text=json.dumps(structured, ensure_ascii=False), structured=structured)

    def submit_image_job(self, job: ImageJob, reference_images: list[Path]) -> str:
        self._task_counter += 1
        task_id = f"dry-run-{self._task_counter:04d}"
        self._task_store[task_id] = {
            "job_name": job.job_name,
            "reference_count": len(reference_images),
        }
        return task_id

    def poll_image_task(self, task_id: str, timeout_seconds: int, interval_seconds: int) -> dict[str, Any]:
        _ = (timeout_seconds, interval_seconds)
        if task_id not in self._task_store:
            raise TaskInterruptedError("api_failed", f"dry-run task missing: {task_id}")
        return {
            "task_id": task_id,
            "state": "success",
            "is_final": True,
            "result_url": f"https://dry-run.local/{task_id}.png",
        }

    def download_result_images(self, task_data: dict[str, Any], output_dir: Path, job_name: str) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{job_name}-01.png"
        create_placeholder_png(output_path)
        return [output_path]


class BatchProcessor:
    def __init__(self, config: BatchConfig, client: LkClient | DryRunClient) -> None:
        self.config = config
        self.client = client
        self.root_log_path = self.config.root_dir / f"batch-run-{self.config.run_timestamp}.log"
        self.root_logger = PlainLogger(self.root_log_path)

    def scan_tasks(self) -> list[ProductTask]:
        if not self.config.root_dir.exists():
            raise BatchWorkflowError(f"主目录不存在：{self.config.root_dir}")
        if not self.config.root_dir.is_dir():
            raise BatchWorkflowError(f"主目录不是目录：{self.config.root_dir}")
        root_in_dir = self.config.root_dir / "in"
        if root_in_dir.is_dir():
            product_dirs = [self.config.root_dir]
        else:
            product_dirs = sorted(
                [path for path in self.config.root_dir.iterdir() if path.is_dir()],
                key=lambda item: item.name.lower(),
            )
        if not product_dirs:
            raise BatchWorkflowError(f"主目录下没有商品子目录：{self.config.root_dir}")
        tasks: list[ProductTask] = []
        for product_dir in product_dirs:
            input_dir = product_dir / "in"
            output_base_dir = product_dir / "output"
            output_dir = output_base_dir / self.config.run_timestamp
            requirement_file: Path | None = None
            reference_images: list[Path] = []
            validation_errors: list[str] = []
            if not input_dir.is_dir():
                validation_errors.append("缺少 in 目录")
            else:
                txt_files = sorted(input_dir.glob("*.txt"), key=lambda item: item.name.lower())
                if len(txt_files) != 1:
                    validation_errors.append(f"in 目录中必须且只允许存在 1 个 txt，当前为 {len(txt_files)} 个")
                else:
                    requirement_file = txt_files[0]
                reference_images = sorted(
                    [
                        path
                        for path in input_dir.iterdir()
                        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
                    ],
                    key=lambda item: item.name.lower(),
                )
                if not reference_images:
                    validation_errors.append("缺少合法参考图")
                elif len(reference_images) > 10:
                    reference_images = reference_images[:10]
            task = ProductTask(
                task_name=product_dir.name,
                source_dir=product_dir,
                input_dir=input_dir,
                output_base_dir=output_base_dir,
                output_dir=output_dir,
                requirement_file=requirement_file,
                reference_images=reference_images,
                validation_errors=validation_errors,
                log_path=output_dir / "product-run.log",
                manifest_path=output_dir / "manifest.json",
            )
            tasks.append(task)
        return tasks

    def run(self) -> BatchSummary:
        self.root_logger.log(f"批量任务启动，主目录：{self.config.root_dir}")
        tasks = self.scan_tasks()
        summary = BatchSummary(total=len(tasks))
        with ThreadPoolExecutor(max_workers=self.config.max_parallel_products) as executor:
            futures = {executor.submit(self.process_task, task): task for task in tasks}
            for future in as_completed(futures):
                task = futures[future]
                try:
                    future.result()
                except Exception as exc:  # pragma: no cover - 防止线程异常漏掉日志
                    task.status = "failed"
                    task.error = f"未捕获异常：{exc}"
                    self.root_logger.log(f"[{task.task_name}] 未捕获异常：{exc}")
                    self.root_logger.log(traceback.format_exc())
                    self.finalize_task(task)
                if task.status == "completed":
                    summary.completed += 1
                elif task.status == "failed":
                    summary.failed += 1
                elif task.status == "interrupted":
                    summary.interrupted += 1
                elif task.status == "skipped":
                    summary.skipped += 1
        self.root_logger.log(
            "批量任务结束："
            f"total={summary.total}, completed={summary.completed}, failed={summary.failed}, "
            f"interrupted={summary.interrupted}, skipped={summary.skipped}"
        )
        return summary

    def set_task_state(self, task: ProductTask, state: str) -> None:
        if state not in TASK_STATES:
            raise ValueError(f"未知任务状态：{state}")
        task.status = state
        self.root_logger.log(f"[{task.task_name}] 状态 -> {state}")
        if task.log_path:
            PlainLogger(task.log_path).log(f"状态 -> {state}")

    def process_task(self, task: ProductTask) -> None:
        task.output_dir.mkdir(parents=True, exist_ok=True)
        product_logger = PlainLogger(task.log_path or (task.output_dir / "product-run.log"))
        task.started_at = now_iso()
        product_logger.log(f"商品任务启动：{task.task_name}")
        if task.validation_errors:
            self.set_task_state(task, "skipped")
            task.error = "; ".join(task.validation_errors)
            product_logger.log(f"跳过：{task.error}")
            self.root_logger.log(f"[{task.task_name}] 跳过：{task.error}")
            self.finalize_task(task)
            return
        if task.requirement_file is None:
            self.set_task_state(task, "failed")
            task.error = "requirement_file 为空"
            self.finalize_task(task)
            return
        try:
            self.set_task_state(task, "validating")
            task.requirement_text = task.requirement_file.read_text(encoding="utf-8").strip()
            if not task.requirement_text:
                raise BatchWorkflowError("txt 内容为空")
            parsed = parse_requirement(task.requirement_text)
            task.market = parsed.market
            task.language = parsed.language
            if len(list(task.input_dir.glob("*"))) > len(task.reference_images) + 1:
                product_logger.log("提示：in 目录存在非 txt/图片文件，已忽略。")
            self.set_task_state(task, "understanding")
            analysis = self.client.analyze_product_images(task.reference_images, task.language or parsed.language)
            product_logger.log("图片理解完成。")
            self.set_task_state(task, "planning")
            task.image_jobs = plan_image_jobs(task, parsed, analysis)
            if not task.image_jobs:
                raise BatchWorkflowError("未能从 txt 规划出任何图片任务")
            product_logger.log(f"任务规划完成，共 {len(task.image_jobs)} 个图片任务。")
            self.submit_all_jobs(task, product_logger)
            self.poll_and_download_all_jobs(task, product_logger)
            if any(job.status == "interrupted" for job in task.image_jobs):
                task.status = "interrupted"
            elif any(job.status == "failed" for job in task.image_jobs):
                task.status = "failed"
            else:
                task.status = "completed"
        except TaskInterruptedError as exc:
            task.status = "interrupted"
            task.error = str(exc)
            task.interrupt_reason = exc.reason
            product_logger.log(f"中断：{exc.reason} - {exc}")
        except KeyboardInterrupt:
            task.status = "interrupted"
            task.error = "脚本被人工停止"
            task.interrupt_reason = "script_stop"
            product_logger.log("中断：脚本被人工停止")
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            product_logger.log(f"失败：{exc}")
            product_logger.log(traceback.format_exc())
        finally:
            self.finalize_task(task)

    def submit_all_jobs(self, task: ProductTask, product_logger: PlainLogger) -> None:
        self.set_task_state(task, "submitting")
        for index, job in enumerate(task.image_jobs, start=1):
            job.status = "submitting"
            job.task_id = self.submit_single_job_with_retry(task, job, product_logger)
            product_logger.log(
                f"[{job.job_name}] 提交成功，task_id={job.task_id}，size={job.size}，template={job.template_name}"
            )
            self.root_logger.log(f"[{task.task_name}] [{job.job_name}] 已提交 task_id={job.task_id}")
            if index < len(task.image_jobs):
                self.sleep_between_submissions()

    def submit_single_job_with_retry(
        self,
        task: ProductTask,
        job: ImageJob,
        product_logger: PlainLogger,
    ) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                return self.client.submit_image_job(job, task.reference_images)
            except (ApiRequestError, BatchWorkflowError) as exc:
                last_error = exc
                job.error = str(exc)
                if attempt >= self.config.max_retries:
                    break
                product_logger.log(f"[{job.job_name}] 提交第 {attempt} 次失败，重试中：{exc}")
                time.sleep(1.5)
        raise BatchWorkflowError(f"[{job.job_name}] 提交失败：{last_error}")

    def sleep_between_submissions(self) -> None:
        minimum = self.config.submit_interval_min_seconds
        maximum = self.config.submit_interval_max_seconds
        if maximum < minimum:
            minimum, maximum = maximum, minimum
        delay = random.uniform(minimum, maximum) if maximum > minimum else minimum
        if delay > 0:
            time.sleep(delay)

    def poll_and_download_all_jobs(self, task: ProductTask, product_logger: PlainLogger) -> None:
        self.set_task_state(task, "polling")
        with ThreadPoolExecutor(max_workers=self.config.per_product_poll_workers) as executor:
            futures = {executor.submit(self.finish_job, task, job, product_logger): job for job in task.image_jobs}
            for future in as_completed(futures):
                job = futures[future]
                try:
                    future.result()
                except Exception as exc:  # pragma: no cover - 最终兜底
                    job.status = "failed"
                    job.error = str(exc)
                    product_logger.log(f"[{job.job_name}] 未捕获异常：{exc}")

    def finish_job(self, task: ProductTask, job: ImageJob, product_logger: PlainLogger) -> None:
        for attempt in range(1, self.config.max_retries + 1):
            job.attempt_count = attempt
            try:
                job.status = "polling"
                task_data = self.client.poll_image_task(
                    job.task_id or "",
                    timeout_seconds=self.config.poll_timeout_seconds,
                    interval_seconds=self.config.poll_interval_seconds,
                )
                self.set_task_state(task, "downloading")
                output_paths = self.client.download_result_images(task_data, task.output_dir, job.job_name)
                job.output_files = [path.name for path in output_paths]
                job.status = "completed"
                product_logger.log(f"[{job.job_name}] 完成，输出 {len(output_paths)} 张图片。")
                self.root_logger.log(f"[{task.task_name}] [{job.job_name}] 完成")
                return
            except TaskInterruptedError as exc:
                job.error = str(exc)
                if attempt >= self.config.max_retries:
                    job.status = "interrupted"
                    product_logger.log(f"[{job.job_name}] 中断：{exc.reason} - {exc}")
                    raise
                product_logger.log(f"[{job.job_name}] 第 {attempt} 次失败，重试中：{exc}")
                time.sleep(1)
            except Exception as exc:
                job.error = str(exc)
                if attempt >= self.config.max_retries:
                    job.status = "failed"
                    product_logger.log(f"[{job.job_name}] 失败：{exc}")
                    return
                product_logger.log(f"[{job.job_name}] 第 {attempt} 次失败，重试中：{exc}")
                time.sleep(1)

    def finalize_task(self, task: ProductTask) -> None:
        task.finished_at = now_iso()
        write_json(task.manifest_path or (task.output_dir / "manifest.json"), task_to_manifest(task))
        PlainLogger(task.log_path or (task.output_dir / "product-run.log")).log(
            f"商品任务结束，状态={task.status}"
        )
        self.root_logger.log(f"[{task.task_name}] 结束，状态={task.status}")


def build_config_from_args(args: argparse.Namespace) -> BatchConfig:
    return BatchConfig(
        root_dir=Path(args.root_dir).expanduser().resolve(),
        run_timestamp=args.run_timestamp or dt.datetime.now().strftime("%Y-%m-%d_%H%M%S"),
        dry_run=args.dry_run,
        max_parallel_products=max(1, args.max_parallel_products),
        per_product_poll_workers=max(1, args.per_product_poll_workers),
        poll_interval_seconds=max(1, args.poll_interval_seconds),
        poll_timeout_seconds=max(30, args.poll_timeout_seconds),
        max_retries=max(1, args.max_retries),
        submit_interval_min_seconds=max(0.0, args.submit_interval_min_seconds),
        submit_interval_max_seconds=max(0.0, args.submit_interval_max_seconds),
    )


def build_client(args: argparse.Namespace) -> LkClient | DryRunClient:
    if args.dry_run:
        return DryRunClient()
    generation_base_url = require_config(ENV_BASE_URL)
    model = get_config_value(ENV_MODEL, GENERATION_MODEL_FALLBACK)
    api_key = require_config(ENV_API_KEY)
    understanding_base_url = require_config(ENV_BASE_URL)
    understanding_model = get_config_value(ENV_MODEL, UNDERSTANDING_MODEL)
    understanding_api_key = require_config(ENV_API_KEY)
    return LkClient(
        generation_base_url=generation_base_url,
        model=model,
        api_key=api_key,
        understanding_base_url=understanding_base_url,
        understanding_model=understanding_model,
        understanding_api_key=understanding_api_key,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按目录批量生图工作流（VTeTech-only）")
    parser.add_argument("root_dir", help="主目录路径，主目录下每个一级子目录视为一个商品任务")
    parser.add_argument("--env-file", help="显式指定 .env 文件路径")
    parser.add_argument("--run-timestamp", help="指定输出时间戳，默认当前时间")
    parser.add_argument("--dry-run", action="store_true", help="不调用真实 API，生成占位输出用于联调和测试")
    parser.add_argument("--max-parallel-products", type=int, default=2, help="商品子目录并发数，默认 2")
    parser.add_argument("--per-product-poll-workers", type=int, default=2, help="单商品轮询下载并发数，默认 2")
    parser.add_argument("--poll-interval-seconds", type=int, default=5, help="轮询间隔秒数，默认 5")
    parser.add_argument("--poll-timeout-seconds", type=int, default=300, help="单图轮询超时时间，默认 300")
    parser.add_argument("--max-retries", type=int, default=3, help="轮询/下载最大重试次数，默认 3")
    parser.add_argument("--submit-interval-min-seconds", type=float, default=3.0, help="两次提交最小间隔秒数，默认 3")
    parser.add_argument("--submit-interval-max-seconds", type=float, default=5.0, help="两次提交最大间隔秒数，默认 5")
    return parser.parse_args(argv)


def run_batch(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    apply_config_file()
    env_file = Path(args.env_file).expanduser() if args.env_file else find_default_env_file()
    try:
        load_env_file(env_file)
        config = build_config_from_args(args)
        client = build_client(args)
        processor = BatchProcessor(config, client)
        summary = processor.run()
    except BatchWorkflowError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("错误：脚本被人工停止。", file=sys.stderr)
        return 130
    if summary.failed or summary.interrupted:
        return 2
    return 0


def main() -> None:
    raise SystemExit(run_batch())


if __name__ == "__main__":
    main()
