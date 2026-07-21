#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Excel/CSV product-list batch image generation workflow.

This entrypoint is intentionally independent from batch-directory-generate.py.
Reference images are passed as public URLs and are never cached locally.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import apply_config_file

if hasattr(__import__("sys").stdout, "reconfigure"):
    __import__("sys").stdout.reconfigure(encoding="utf-8", errors="replace")


DEFAULT_OUTPUT_ROOT = Path("excel-output")
UNDERSTANDING_MODEL = "gpt-5.4"
GENERATION_MODEL = "gpt-image-2"
GENERATION_STATUS_PATH = "/v1/skills/task-status"
GENERATION_STATUS_FALLBACK_PATH = "/v1/media/status"
USER_AGENT = "image-excel-workflow/1.0"
MAX_REFERENCES = 10
MIN_ANALYSIS_REFERENCES = 3
MAX_DOWNLOAD_AGE_SECONDS = 48 * 3600
FINAL_STATES = {"success", "completed", "succeeded", "failed", "error", "cancelled"}


def install_runtime_proxy() -> None:
    proxies = {
        scheme: value
        for scheme, value in urllib.request.getproxies().items()
        if scheme in {"http", "https"} and value
    }
    if proxies:
        urllib.request.install_opener(
            urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
        )

UNDERSTANDING_PROMPT_C = """You are an ecommerce visual marketing analyst. Analyze the target product, its SKU variants, and the supplied labeled reference images for downstream advertising and listing image planning.

Separate all output into two evidence classes:
- observed: facts directly visible in the images and supported by reference IDs.
- suggested: marketing, audience, positioning, and scene recommendations that are not product facts.

Requirements:
1. Identify the target product and its immutable visible identity.
2. Map each supplied SKU ID and specification to visible color, variant, accessory, and packaging differences.
3. Extract supported visual selling points with evidence and confidence.
4. Suggest suitable audiences, use scenes, positioning, visual tone, and short creative directions, clearly marked as suggestions.
5. Record product-consistency constraints and image-generation risks.
6. Do not invent functions, materials, certifications, measurements, performance data, brands, popularity, reviews, or guarantees.

Return strict JSON only with this schema:
{
  "observed_facts": [{"fact": "", "reference_ids": [], "confidence": "high|medium|low"}],
  "sku_variants": [{"sku_id": "", "specification": "", "visible_differences": [], "reference_ids": []}],
  "supported_sell_points": [{"point": "", "evidence": "", "reference_ids": []}],
  "suggested_audiences": [],
  "suggested_scenes": [],
  "suggested_positioning": [],
  "suggested_visual_tone": [],
  "generation_constraints": {"must_preserve": [], "must_not_invent_or_change": []},
  "generation_risks": [],
  "unknowns": []
}
No Markdown, code fences, or extra explanation."""

HEADER_ALIASES = {
    "sku_id": ["SKU ID", "SKU_ID", "sku id"],
    "sku_name": ["SKU名称", "SKU 名称", "SKU name", "sku_name"],
    "main_urls": ["产品主图url", "产品主图URL", "产品主图", "main_image_url", "main_urls"],
    "sku_urls": ["SKU图片url", "SKU图片URL", "SKU图片", "sku_image_url", "sku_urls"],
    "product_id": ["产品ID", "产品 ID", "product_id", "product id"],
    "product_name": ["产品名称", "product_name", "product name"],
    "category": ["产品类目", "类目", "category"],
    "spec": ["规格", "产品规格", "spec", "specification"],
}
REQUIRED_COLUMNS = tuple(column for column in HEADER_ALIASES if column != "sku_name")


class WorkflowError(Exception):
    pass


@dataclass
class Requirements:
    raw: str
    market: str | None
    language: str
    resolution: str
    sizes: dict[str, str]
    counts: dict[str, int | str]
    order: list[str]
    style: str
    add_flag: bool
    all_skus: bool
    same_model_scene: bool = False


@dataclass
class Product:
    product_id: str
    product_name: str
    category: str
    rows: list[dict[str, Any]]
    main_urls: list[str]
    sku_urls: list[str]
    analysis_refs: list[str] = field(default_factory=list)
    analysis: dict[str, Any] | None = None
    analysis_model: str | None = None
    analysis_endpoint: str | None = None
    status: str = "pending"
    error: str | None = None
    product_dir: Path | None = None
    manifest_path: Path | None = None
    log_path: Path | None = None
    rate_limited: bool = False


@dataclass
class Job:
    job_id: str
    product_id: str
    kind: str
    index: int
    filename: str
    ratio: str
    prompt: str
    references: list[str]
    status: str = "pending"
    task_id: str | None = None
    result_urls: list[str] = field(default_factory=list)
    output_files: list[str] = field(default_factory=list)
    attempts: int = 0
    poll_events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    submitted_at: str | None = None
    completed_at: str | None = None
    downloaded_at: str | None = None
    remote_finished_epoch: float | None = None
    poll_started_epoch: float | None = None
    rate_limited: bool = False
    submit_seconds: float | None = None
    remote_duration_seconds: float | None = None
    download_seconds: float | None = None
    cost: float | None = None


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_env(path: Path | None) -> None:
    if not path or not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip("\"'")


def find_env(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    for directory in (Path.cwd(), *Path.cwd().parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    candidate = Path(__file__).resolve().parents[1] / ".env"
    return candidate if candidate.is_file() else None


def split_urls(value: Any) -> list[str]:
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    parts = re.split(r"[,;；，\n\r\t]+", text)
    return list(dict.fromkeys(item.strip() for item in parts if item.strip()))


PROMO_TITLE_PATTERNS = [
    r"\bviral\b.*$",
    r"\bcod\b.*$",
    r"\bgift\b.*$",
    r"\bhadiah\b.*$",
    r"\bfree\b.*$",
    r"\bbonus\b.*$",
    r"\bpromo\b.*$",
    r"\bbest\s*seller\b.*$",
    r"\btop\s*seller\b.*$",
    r"\bwholesale\b.*$",
    r"\breview\b.*$",
    r"\bpopular\b.*$",
]

PROMO_TITLE_PHRASES = [
    "viral",
    "cod",
    "gift",
    "hadiah",
    "free",
    "bonus",
    "promo",
    "best seller",
    "top seller",
    "wholesale",
    "review",
    "popular",
    "comel",
    "teman isteri",
    "untuk teman",
    "untuk isteri",
    "untuk ibu",
    "untuk diri sendiri",
    "2026",
]


def clean_prompt_text(text: str) -> str:
    """Remove promotional chatter while preserving factual product identity."""
    value = str(text or "").strip()
    if not value:
        return ""
    value = re.sub(r"[\u0000-\u001f]+", " ", value)
    value = re.sub(r"[|/\\]+", " ", value)
    for pattern in PROMO_TITLE_PATTERNS:
        value = re.sub(pattern, "", value, flags=re.I)
    lowered = value.lower()
    for phrase in PROMO_TITLE_PHRASES:
        lowered = lowered.replace(phrase, " ")
    value = re.sub(r"\s+", " ", lowered)
    value = re.sub(r"\s*([,;:()\[\]{}])\s*", r"\1 ", value)
    return re.sub(r"\s{2,}", " ", value).strip(" ,-;:()[]{}")


def canonical_header(value: Any) -> str:
    return re.sub(r"[\s_]+", "", str(value or "").strip()).lower()


def map_headers(headers: list[Any]) -> dict[str, str]:
    normalized = {canonical_header(h): str(h) for h in headers if h is not None}
    mapped: dict[str, str] = {}
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            key = canonical_header(alias)
            if key in normalized:
                mapped[canonical] = normalized[key]
                break
    return mapped


def load_tables(path: Path) -> list[tuple[str, list[dict[str, Any]], dict[str, str]]]:
    tables: list[tuple[str, list[dict[str, Any]], dict[str, str]]] = []
    if path.suffix.lower() == ".csv":
        raw = path.read_bytes()
        text = None
        for encoding in ("utf-8-sig", "gb18030", "utf-8"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise WorkflowError("CSV 无法按 UTF-8 或 GB18030 读取")
        rows = list(csv.DictReader(io.StringIO(text)))
        headers = list(rows[0].keys()) if rows else []
        tables.append(("CSV", rows, map_headers(headers)))
        return tables

    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise WorkflowError("只支持 .xlsx、.xlsm 或 .csv")
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise WorkflowError("缺少 openpyxl，请使用工作区 Python 依赖运行") from exc
    workbook = load_workbook(path, read_only=True, data_only=True)
    for sheet in workbook.worksheets:
        values = list(sheet.values)
        if not values:
            continue
        header_index = next((i for i, row in enumerate(values) if any(v not in (None, "") for v in row)), None)
        if header_index is None:
            continue
        headers = list(values[header_index])
        mapping = map_headers(headers)
        rows = [dict(zip(headers, row)) for row in values[header_index + 1 :] if any(v not in (None, "") for v in row)]
        tables.append((sheet.title, rows, mapping))
    return tables


def validate_tables(path: Path) -> list[Product]:
    candidates = []
    for sheet_name, rows, mapping in load_tables(path):
        missing = [column for column in REQUIRED_COLUMNS if column not in mapping]
        if not missing and ("sku_name" in mapping or "spec" in mapping):
            candidates.append((sheet_name, rows, mapping))
    if not candidates:
        found = []
        for sheet_name, _, mapping in load_tables(path):
            found.append(f"{sheet_name}: {', '.join(mapping)}")
        raise WorkflowError("未找到符合模板的工作表。必需字段：" + ", ".join(REQUIRED_COLUMNS) + "。已识别：" + " | ".join(found))
    if len(candidates) > 1:
        raise WorkflowError("检测到多个符合模板的工作表，请只保留一个符合模板的表")

    _, raw_rows, mapping = candidates[0]
    normalized_rows: list[dict[str, Any]] = []
    last_product: dict[str, Any] = {}
    seen: set[tuple[str, str]] = set()
    errors: list[str] = []
    for row_number, raw in enumerate(raw_rows, start=2):
        row = {canonical: str(raw.get(header) or "").strip() for canonical, header in mapping.items()}
        row.setdefault("sku_name", "")
        row.setdefault("spec", "")
        if not row["sku_name"]:
            row["sku_name"] = row["spec"]
        for key in ("product_id", "product_name", "category"):
            if not row.get(key) and last_product.get(key):
                row[key] = last_product[key]
        required_row = ("product_id", "sku_id", "product_name", "category", "main_urls", "sku_urls")
        missing = [key for key in required_row if not row.get(key)]
        if not row.get("sku_name") and not row.get("spec"):
            missing.append("sku_name 或 spec")
        if missing:
            errors.append(f"第 {row_number} 行缺少：{', '.join(missing)}")
            continue
        last_product = row
        pair = (row["product_id"], row["sku_id"])
        if pair in seen:
            errors.append(f"第 {row_number} 行重复 SKU：产品 {pair[0]} / SKU {pair[1]}")
            continue
        seen.add(pair)
        row["main_urls_list"] = split_urls(row["main_urls"])
        row["sku_urls_list"] = split_urls(row["sku_urls"])
        if not row["main_urls_list"] or not row["sku_urls_list"]:
            errors.append(f"第 {row_number} 行必须同时有产品主图 URL 和 SKU 图片 URL")
            continue
        normalized_rows.append(row)
    if errors:
        raise WorkflowError("表格校验失败：" + "；".join(errors[:12]))

    groups: dict[str, list[dict[str, Any]]] = {}
    for row in normalized_rows:
        groups.setdefault(row["product_id"], []).append(row)
    products: list[Product] = []
    for product_id, group in groups.items():
        main_urls = list(dict.fromkeys(url for row in group for url in row["main_urls_list"]))
        sku_urls = list(dict.fromkeys(url for row in group for url in row["sku_urls_list"]))
        products.append(Product(product_id, group[0]["product_name"], group[0]["category"], group, main_urls, sku_urls))
    return products


def detect_market(text: str) -> tuple[str | None, str]:
    rules = {
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
    for keyword, value in rules.items():
        if keyword in text:
            return value
    language_rules = {
        "英语": "English", "英文": "English", "法语": "French", "法文": "French",
        "西班牙语": "Spanish", "西语": "Spanish", "德语": "German", "德文": "German",
        "意大利语": "Italian", "荷兰语": "Dutch", "波兰语": "Polish",
        "日语": "Japanese", "日文": "Japanese", "韩语": "Korean", "韩文": "Korean",
        "葡萄牙语": "Portuguese", "葡语": "Portuguese", "土耳其语": "Turkish",
        "阿拉伯语": "Arabic", "马来语": "Malay", "越南语": "Vietnamese", "泰语": "Thai",
        "中文": "Chinese", "汉语": "Chinese", "华文": "Chinese",
    }
    for keyword, language in language_rules.items():
        if keyword in text:
            return None, language
    if any(word in text.lower() for word in ("海外", "国际", "东南亚")):
        raise WorkflowError("目标市场不完整，请指定具体国家；通用市场请明确写‘通用市场’")
    return None, "Chinese"


def parse_count(text: str, keywords: list[str]) -> int | None:
    # 只认“数量 + 张/个”这种紧邻关系，不回看前面别的数量，避免
    # “主图4张、场景图4张、详情图8张”被后面的关键词误吃成 4。
    sanitized = re.sub(r"\b[0-9]+\s*:\s*[0-9]+\b", " ", text)
    collapsed = re.sub(r"\s+", "", sanitized)
    for keyword in keywords:
        keyword_re = re.escape(keyword.replace(" ", ""))
        # 形如“主图4张”“详情图8个”
        after_match = re.search(rf"{keyword_re}(?:[:：]?)?([0-9]+)(?:张|个)", collapsed, re.I)
        if after_match:
            return int(after_match.group(1))
        # 兼容少量“4张主图”“8个详情图”
        before_match = re.search(rf"([0-9]+)(?:张|个){keyword_re}", collapsed, re.I)
        if before_match:
            return int(before_match.group(1))
    return None


def parse_same_model_scene(text: str) -> bool:
    normalized = text.replace(" ", "")
    return any(
        phrase in normalized
        for phrase in (
            "同一个模特",
            "同一模特",
            "同模特",
            "同一个人",
            "同一人",
            "模特形象一致",
            "模特一致",
            "形象一致",
            "保持同一模特",
        )
    )


DEFAULT_IMAGE_SIZES = {"hero": "1:1", "sku": "1:1", "model": "1:1", "detail": "9:16"}
SIZE_KIND_ALIASES = {
    "hero": ["电商主图", "多颜色主图", "多颜色产品主图", "产品主图", "主图"],
    "sku": ["SKU图", "SKU主图", "SKU图片"],
    "model": ["模特图", "模特场景图", "产品场景图", "场景图"],
    "detail": ["详情图", "产品详情图"],
}


def parse_size_overrides(text: str) -> dict[str, str]:
    sizes = DEFAULT_IMAGE_SIZES.copy()
    compact = re.sub(r"\s+", "", text or "")
    for kind, aliases in SIZE_KIND_ALIASES.items():
        alias_pattern = "|".join(re.escape(alias.replace(" ", "")) for alias in aliases)
        after_match = re.search(rf"(?:{alias_pattern}).{{0,12}}?(1:1|9:16)", compact, re.I)
        before_match = re.search(rf"(1:1|9:16).{{0,12}}?(?:{alias_pattern})", compact, re.I)
        match = after_match or before_match
        if match:
            sizes[kind] = match.group(1)
    return sizes


def parse_requirements(text: str) -> Requirements:
    market, language = detect_market(text)
    all_skus = "全部SKU" in text.replace(" ", "") or "所有SKU" in text.replace(" ", "")
    same_model_scene = parse_same_model_scene(text)
    counts: dict[str, int | str] = {}
    if all_skus:
        counts["sku"] = "all"
    else:
        count = parse_count(text, ["SKU图", "SKU主图", "SKU图片"])
        if count is not None:
            counts["sku"] = count
    aliases = {
        "hero": ["电商主图", "多颜色主图", "多颜色产品主图", "产品主图", "主图"],
        "model": ["模特图", "模特场景图", "产品场景图", "场景图"],
        "detail": ["详情图", "产品详情图"],
    }
    for kind, keywords in aliases.items():
        count = parse_count(text, keywords)
        if count is not None:
            counts[kind] = count
    if not counts:
        raise WorkflowError("未解析到图片类型和数量，请说明主图、SKU 图、模特图或详情图数量")
    order_keywords = {
        "hero": ["电商主图", "多颜色产品主图", "多颜色主图", "产品主图", "主图"],
        "sku": ["全部 SKU", "全部SKU", "所有 SKU", "所有SKU", "SKU主图", "SKU图", "SKU图片"],
        "model": ["模特场景图", "模特图", "产品场景图", "场景图"],
        "detail": ["产品详情图", "详情图"],
    }
    positions: list[tuple[int, str]] = []
    for kind in counts:
        position = min((text.find(keyword) for keyword in order_keywords[kind] if text.find(keyword) >= 0), default=10**9)
        positions.append((position, kind))
    order = [kind for _, kind in sorted(positions)]
    sizes = parse_size_overrides(text)
    resolution = "1K"
    resolution_match = re.search(r"\b([124])\s*[Kk]\b", text)
    if resolution_match:
        resolution = resolution_match.group(1) + "K"
    style = "TikTok 电商高转化感，简约大气，苹果发布会式高级产品展示"
    style_match = re.search(r"风格(?:要求)?[:：]\s*([^\n。]+)", text)
    if style_match:
        style = style_match.group(1).strip()
    return Requirements(text, market, language, resolution, sizes, counts, order, style, market is not None, all_skus, same_model_scene)


def choose_analysis_refs(product: Product) -> list[str]:
    # User rule: image understanding prefers main images, then fills with SKU images.
    return list(dict.fromkeys((product.main_urls + product.sku_urls)[:MAX_REFERENCES]))


def choose_generation_refs(product: Product, sku: dict[str, Any] | None = None) -> list[str]:
    preferred = []
    if sku:
        preferred.extend(sku.get("sku_urls_list", []))
    preferred.extend(product.main_urls)
    preferred.extend(product.sku_urls)
    return list(dict.fromkeys(preferred))[:MAX_REFERENCES]


def extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S | re.I)
    if fenced:
        cleaned = fenced.group(1).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    parsed = json.loads(cleaned)
    return parsed if isinstance(parsed, dict) else {}


def is_rate_limit_error(error: Exception) -> bool:
    text = str(error).lower()
    return any(token in text for token in ("429", "rate limit", "too many", "busy", "overload", "限流", "繁忙"))


def is_content_policy_error(error: Exception) -> bool:
    text = str(error).lower()
    return any(token in text for token in ("内容政策", "违反了我们的内容政策", "content policy", "policy"))


def api_json(url: str, api_key: str, method: str = "POST", payload: dict[str, Any] | None = None, timeout: int = 120) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
            result = value if isinstance(value, dict) else {"data": value}
            code = result.get("code")
            if code not in (None, 0, 200, "0", "200"):
                raise WorkflowError(f"API 返回 code={code}: {json.dumps(result, ensure_ascii=False)[:800]}")
            if result.get("error"):
                raise WorkflowError(f"API 返回错误: {json.dumps(result['error'], ensure_ascii=False)[:800]}")
            return result
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise WorkflowError(f"HTTP {exc.code}: {detail}") from exc


def call_understanding_api(model: str, content: list[dict[str, Any]], api_key: str) -> tuple[str, str]:
    response_content: list[dict[str, Any]] = []
    for block in content:
        if block.get("type") == "text":
            response_content.append({"type": "input_text", "text": block.get("text", "")})
        elif block.get("type") == "image_url":
            image_url = block.get("image_url", {})
            if isinstance(image_url, dict) and image_url.get("url"):
                response_content.append({"type": "input_image", "image_url": image_url["url"]})
    chat_payload = {
        "model": model,
        "messages": [{"role": "system", "content": UNDERSTANDING_PROMPT_C}, {"role": "user", "content": content}],
        "max_tokens": 8192,
        "reasoning_effort": "low",
    }
    base_url = os.getenv("IMG_BASE_URL", "").rstrip("/")
    if not base_url:
        raise WorkflowError("缺少配置 IMG_BASE_URL，请先在 image-config.json 或环境变量中录入 Vetech AI 服务地址")
    try:
        result = api_json(f"{base_url}/v1/chat/completions", api_key, payload=chat_payload, timeout=240)
        for choice in result.get("choices", []):
            if not isinstance(choice, dict):
                continue
            message = choice.get("message", {})
            raw_content = message.get("content", "") if isinstance(message, dict) else ""
            text = "\n".join(str(item.get("text", "")) for item in raw_content if isinstance(item, dict)).strip() if isinstance(raw_content, list) else str(raw_content or "").strip()
            if text:
                return text, f"chat_completions@{base_url}"
    except Exception as exc:
        raise WorkflowError(f"VTeTech image understanding failed: {exc}") from exc
    raise WorkflowError("VTeTech image understanding returned empty content")


def analyze_product(product: Product, requirements: Requirements, api_key: str, log) -> Product:
    product.analysis_refs = choose_analysis_refs(product)
    if not product.main_urls or not product.sku_urls:
        product.status = "failed"
        product.error = "至少需要 1 张主图 URL 和 1 张 SKU 图片 URL"
        return product
    sku_lookup = {url: row for row in product.rows for url in row.get("sku_urls_list", [])}
    reference_sets: list[list[str]] = []
    current_refs = list(product.analysis_refs[:MAX_REFERENCES])
    while current_refs:
        reference_sets.append(current_refs[:])
        if len(current_refs) <= MIN_ANALYSIS_REFERENCES:
            break
        current_refs = current_refs[: max(MIN_ANALYSIS_REFERENCES, len(current_refs) - 2)]

    last_error: Exception | None = None
    for refs in reference_sets:
        content: list[dict[str, Any]] = [{
            "type": "text",
            "text": (
                f"Product ID: {product.product_id}\n"
                f"Product name: {clean_prompt_text(product.product_name)}\n"
                f"Product category: {clean_prompt_text(product.category)}\n"
                f"Target market for downstream copy: {requirements.market or 'general market'}\n"
                f"Target visible-copy language: {requirements.language}. Return descriptive analysis values in this language when practical; preserve exact product text from packaging as observed.\n"
                "Analyze the labeled references below. Product facts and SKU specifications override marketing phrases in the title."
            ),
        }]
        main_index = 0
        for url in refs:
            if url in product.main_urls:
                main_index += 1
                label = f"Reference ID: REF_MAIN_{main_index:02d}; kind: product main image."
            else:
                row = sku_lookup.get(url, {})
                sku_id = row.get("sku_id", "unknown")
                label = f"Reference ID: REF_SKU_{sku_id}; kind: SKU image; SKU ID: {sku_id}; specification: {row.get('spec', '')}."
            content.extend([{"type": "text", "text": label}, {"type": "image_url", "image_url": {"url": url}}])
        for attempt in range(2):
            try:
                log(product, f"UNDERSTAND_START model={UNDERSTANDING_MODEL} attempt={attempt + 1} refs={len(refs)}")
                raw_text, endpoint = call_understanding_api(UNDERSTANDING_MODEL, content, api_key)
                product.analysis = extract_json(raw_text)
                product.analysis_model = UNDERSTANDING_MODEL
                product.analysis_endpoint = endpoint
                product.analysis_refs = refs
                product.status = "analyzed"
                log(product, f"UNDERSTAND_OK model={UNDERSTANDING_MODEL} endpoint={endpoint} attempt={attempt + 1} refs={len(refs)}")
                return product
            except Exception as exc:
                last_error = exc
                if is_rate_limit_error(exc):
                    product.rate_limited = True
                log(product, f"UNDERSTAND_FAILED model={UNDERSTANDING_MODEL} attempt={attempt + 1} refs={len(refs)} error={type(exc).__name__}: {exc}")
                if "524" in str(exc) or "timeout" in str(exc).lower():
                    break
                time.sleep(min(8, 2 ** attempt))
    product.status = "failed"
    product.error = f"VTeTech image understanding failed: {last_error}" if last_error else "VTeTech image understanding failed"
    return product


def localized_points(product: Product, requirements: Requirements) -> list[str]:
    analysis = product.analysis or {}
    points = analysis.get("supported_sell_points") or analysis.get("core_sell_points") or []
    values = []
    for item in points:
        if isinstance(item, dict) and item.get("point"):
            values.append(clean_prompt_text(str(item["point"]).strip()))
        elif isinstance(item, str) and item.strip():
            values.append(clean_prompt_text(item.strip()))
    return values[:4]


def focused_sell_point(product: Product, requirements: Requirements, kind: str, index: int) -> str:
    points = localized_points(product, requirements)
    if not points:
        return "只围绕参考图能够确认的一个核心卖点展开，避免卖点堆叠"
    zero_based = max(0, index - 1)
    if kind == "hero":
        return points[zero_based % len(points)]
    if kind == "model":
        return points[zero_based % len(points)]
    if kind == "detail":
        return points[zero_based % len(points)]
    return points[0]


def build_prompt(product: Product, requirements: Requirements, kind: str, sku: dict[str, Any] | None, index: int) -> str:
    focus_point = focused_sell_point(product, requirements, kind, index)
    text_rule = "不要添加任何文字。" if kind == "sku" else f"先将卖点改写为自然、精炼、符合目标市场用语的 {requirements.language}，再把文字实际呈现在画面中；画面可见文案只使用 {requirements.language}，不要混入英语或源语言。每个卖点只写一个短标题，不加第二行解释句，不要密集排版，不要添加底部重复卖点栏。"
    flag_rule = "可加入目标国家小尺寸国旗作为辅助本地化元素，不使用地图轮廓、国家徽章或国家徽标。" if requirements.add_flag and kind in {"hero", "model", "detail"} else "不要加入国旗或国家徽章。"
    same_model_rule = "同一个模特的场景图必须保持模特形象一致，只改变姿态、镜头和场景，不要在同一组图里出现明显不同的人脸、发型、体型或整体人设。" if requirements.same_model_scene and kind == "model" else ""
    single_point_rule = f"这张图只突出一个卖点：{focus_point}。不要把其他卖点、功能点或概念混进同一张图。"
    sku_rule = "第一个有效 SKU 放大展示，其他 SKU 全部缩小但完整呈现。" if kind == "hero" else ""
    sku_context = f"当前 SKU：{sku['sku_id']} / {clean_prompt_text(sku['sku_name'])} / {clean_prompt_text(sku['spec'])}。" if sku else ""
    def sku_label(row: dict[str, Any]) -> str:
        values = [row["sku_id"], clean_prompt_text(row["sku_name"])]
        if row["spec"] and row["spec"] != row["sku_name"]:
            values.append(clean_prompt_text(row["spec"]))
        return " / ".join(values)
    all_sku_context = "全部 SKU（必须完整展示）：" + "；".join(sku_label(row) for row in product.rows) if kind == "hero" else ""
    clean_name = clean_prompt_text(product.product_name)
    clean_category = clean_prompt_text(product.category)
    return f"""Generate exactly one {requirements.sizes[kind]} ecommerce image, never a collage, grid, multi-panel summary board, or multiple outputs.
Product: {clean_name}. Category: {clean_category}. {sku_context}{all_sku_context}
Preserve the real product identity, materials, structure, proportions, colors, and SKU differences from the references. Do not redesign or invent features.
Style: {requirements.style}. Target market: {requirements.market or 'general market'}.
Core visual fact to emphasize in this image: {focus_point}.
{single_point_rule}
{sku_rule}{text_rule}{flag_rule}{same_model_rule}
Leave generous whitespace, keep the product clear and dominant, use clean ecommerce composition, and keep all visible copy concise and natural for the target market.
For detail images, use an ecommerce infographic layout with clear hierarchy, short labels, and one focused benefit per visual block. No unsupported claims, certifications, prices, rankings, popularity claims, bestseller language, fake logos, medical claims, seller badges, seller identity, or assurance text. Never write "popular in [country]", "bestseller", "seller", or equivalent claims. Never turn a general claim into a specific metric or standard; for example, "UV protection" must not become "UV400" unless UV400 is explicitly present in the spreadsheet facts."""


def build_jobs(product: Product, requirements: Requirements) -> list[Job]:
    jobs: list[Job] = []
    serial = 0
    for kind in requirements.order:
        requested = requirements.counts.get(kind)
        if requested is None:
            continue
        sku_rows = [row for row in product.rows if row.get("sku_urls_list")] if kind == "sku" and (requested == "all" or requirements.all_skus) else []
        count = len(sku_rows) if sku_rows else int(requested)
        for offset in range(count):
            serial += 1
            sku = sku_rows[offset] if sku_rows else (product.rows[offset % len(product.rows)] if product.rows else None)
            if kind == "sku":
                filename = f"sku-{offset + 1:02d}-{sku['sku_id']}.png"
            else:
                filename = f"{kind}-{offset + 1:02d}.png"
            refs = choose_generation_refs(product, sku if kind in {"sku", "model", "detail"} else None)
            jobs.append(Job(f"{product.product_id}-{kind}-{offset + 1:02d}", product.product_id, kind, offset + 1, filename, requirements.sizes[kind], build_prompt(product, requirements, kind, sku, offset + 1), refs))
    return jobs


def task_id_from(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("task_id", "taskId", "id"):
            if value.get(key) is not None:
                return str(value[key])
        for nested in value.values():
            found = task_id_from(nested)
            if found:
                return found
    return str(value) if isinstance(value, (int, str)) and str(value).strip() else None


def result_urls(value: Any) -> list[str]:
    urls: list[str] = []
    def append(candidate: Any) -> None:
        if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
            urls.append(candidate)
        elif isinstance(candidate, list):
            for item in candidate:
                append(item)
        elif isinstance(candidate, dict):
            for key in ("url", "result_url", "image_url", "download_url"):
                append(candidate.get(key))
    if isinstance(value, dict):
        append(value.get("result_url"))
        result = value.get("result")
        if isinstance(result, dict):
            append(result.get("url"))
            append(result.get("result_url"))
            append(result.get("images"))
            append(result.get("image_urls"))
        else:
            append(result)
        append(value.get("images"))
        append(value.get("image_urls"))
    else:
        append(value)
    return list(dict.fromkeys(urls))


def task_state(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get("state") or value.get("status") or value.get("task_status") or "").lower()


def is_final(state: str, value: dict[str, Any] | None = None) -> bool:
    if value is not None:
        flag = value.get("is_final")
        if flag is True or str(flag).strip().lower() in {"true", "1", "yes"}:
            return True
    return state in FINAL_STATES or any(word in state for word in ("success", "complete", "finish", "done", "fail", "error", "cancel"))


class Runner:
    def __init__(self, batch_dir: Path, products: list[Product], requirements: Requirements, api_key: str, generation_key: str, args: argparse.Namespace, resume: bool = False):
        self.batch_dir, self.products, self.requirements = batch_dir, products, requirements
        self.api_key, self.generation_key, self.args = api_key, generation_key, args
        self.base_url = os.getenv("IMG_BASE_URL", "").rstrip("/")
        if not self.base_url:
            raise WorkflowError("缺少配置 IMG_BASE_URL，请先在 image-config.json 或环境变量中录入 Vetech AI 服务地址")
        self.resume = resume
        self.batch_log = batch_dir / "batch-run.log"
        self.manifest_path = batch_dir / "manifest.json"
        self.lock = threading.RLock()
        self.jobs: list[Job] = []
        self.job_by_id: dict[str, Job] = {}
        self.generation_limit = args.generation_concurrency
        self.generation_stable_cycles = 0

    def product_log(self, product: Product, message: str) -> None:
        line = f"{now_iso()} {message}"
        with self.lock:
            with self.batch_log.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            if product.log_path:
                with product.log_path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            self.write_manifests()

    def manifest_data(self) -> dict[str, Any]:
        completed_jobs = sum(job.status == "completed" for job in self.jobs)
        failed_jobs = sum(job.status == "failed" for job in self.jobs)
        return {
            "workflow": "excel-batch-image-generation",
            "started_at": getattr(self, "started_at", now_iso()),
            "finished_at": getattr(self, "finished_at", None),
            "requirements": self.requirements.__dict__,
            "products": [self.product_data(product) for product in self.products],
            "config": {"understanding_concurrency": self.args.understanding_concurrency, "generation_concurrency": self.args.generation_concurrency, "download_concurrency": self.args.download_concurrency, "poll_interval": self.args.poll_interval, "max_retries": self.args.max_retries},
            "summary": {"total_products": len(self.products), "total_jobs": len(self.jobs), "completed_jobs": completed_jobs, "failed_jobs": failed_jobs, "total_cost": round(sum(job.cost or 0 for job in self.jobs), 4)},
        }

    def product_data(self, product: Product) -> dict[str, Any]:
        jobs = [self.job_data(job) for job in self.jobs if job.product_id == product.product_id]
        return {"product_id": product.product_id, "product_name": product.product_name, "category": product.category, "skus": product.rows, "main_urls": product.main_urls, "sku_urls": product.sku_urls, "analysis_refs": product.analysis_refs, "analysis": product.analysis, "analysis_model": product.analysis_model, "analysis_endpoint": product.analysis_endpoint, "status": product.status, "error": product.error, "product_dir": str(product.product_dir) if product.product_dir else None, "jobs": jobs}

    @staticmethod
    def job_data(job: Job) -> dict[str, Any]:
        return {key: getattr(job, key) for key in ("job_id", "product_id", "kind", "index", "filename", "ratio", "prompt", "references", "status", "task_id", "result_urls", "output_files", "attempts", "poll_events", "error", "submitted_at", "completed_at", "downloaded_at", "submit_seconds", "remote_duration_seconds", "download_seconds", "cost")}

    @staticmethod
    def restore_job_state(job: Job, restored: Job) -> Job:
        job.status = restored.status
        job.task_id = restored.task_id
        job.result_urls = list(restored.result_urls)
        job.output_files = list(restored.output_files)
        job.attempts = restored.attempts
        job.poll_events = list(restored.poll_events)
        job.error = restored.error
        job.submitted_at = restored.submitted_at
        job.completed_at = restored.completed_at
        job.downloaded_at = restored.downloaded_at
        job.submit_seconds = restored.submit_seconds
        job.remote_duration_seconds = restored.remote_duration_seconds
        job.download_seconds = restored.download_seconds
        job.cost = restored.cost
        job.remote_finished_epoch = restored.remote_finished_epoch
        job.poll_started_epoch = restored.poll_started_epoch
        job.rate_limited = restored.rate_limited
        return job

    @staticmethod
    def _atomic_write_json(path: Path, data: dict[str, Any], retries: int = 5, delay: float = 0.4) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        temp.write_text(payload, encoding="utf-8")
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                temp.replace(path)
                return
            except PermissionError as exc:
                last_error = exc
                if attempt == retries:
                    break
                time.sleep(delay)
        assert last_error is not None
        raise last_error

    def write_manifests(self) -> None:
        data = self.manifest_data()
        self._atomic_write_json(self.manifest_path, data)
        for product in self.products:
            if product.manifest_path:
                self._atomic_write_json(product.manifest_path, self.product_data(product))

    def submit(self, job: Job) -> Job:
        job.attempts += 1
        size_map = {"1:1": "1024x1024", "9:16": "1088x1920", "2:3": "1024x1536", "3:4": "960x1280", "4:5": "960x1280"}
        params: dict[str, Any] = {"size": size_map.get(job.ratio, "1024x1024"), "quality": "low"}
        if job.references:
            params["images"] = job.references
        payload = {"model": GENERATION_MODEL, "prompt": job.prompt, "params": params}
        job.status = "submitting"
        submit_started = time.perf_counter()
        self.product_log(next(p for p in self.products if p.product_id == job.product_id), f"SUBMIT_START job={job.job_id} refs={len(job.references)} attempt={job.attempts}")
        try:
            response = api_json(self.base_url + "/v1/media/generate", self.generation_key, payload=payload, timeout=180)
            task_id = task_id_from(response.get("data", response))
            if not task_id:
                raise WorkflowError("生图提交响应缺少 task_id")
            job.task_id = task_id
            job.status = "submitted"
            job.submitted_at = now_iso()
            job.poll_started_epoch = time.time()
            job.submit_seconds = round(time.perf_counter() - submit_started, 3)
            self.product_log(next(p for p in self.products if p.product_id == job.product_id), f"SUBMIT_OK job={job.job_id} task_id={job.task_id}")
        except Exception as exc:
            job.rate_limited = is_rate_limit_error(exc)
            should_retry = job.attempts < self.args.max_retries and (job.rate_limited or is_content_policy_error(exc))
            job.status = "retry" if should_retry else "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            if job.status == "retry":
                job.task_id = None
                job.result_urls = []
                job.remote_finished_epoch = None
            job.submit_seconds = round(time.perf_counter() - submit_started, 3)
            self.product_log(next(p for p in self.products if p.product_id == job.product_id), f"SUBMIT_FAILED job={job.job_id} status={job.status} error={job.error}")
        return job

    def poll(self, job: Job) -> Job:
        product = next(p for p in self.products if p.product_id == job.product_id)
        if job.poll_started_epoch and time.time() - job.poll_started_epoch > self.args.poll_timeout:
            job.status = "retry" if job.attempts < self.args.max_retries else "failed"
            job.error = f"轮询超过 {self.args.poll_timeout} 秒"
            self.product_log(product, f"POLL_TIMEOUT job={job.job_id} status={job.status}")
            return job
        try:
            try:
                response = api_json(self.base_url + GENERATION_STATUS_PATH + "?task_id=" + urllib.parse.quote(str(job.task_id)), self.generation_key, method="GET", timeout=45)
            except Exception:
                response = api_json(self.base_url + GENERATION_STATUS_FALLBACK_PATH + "?task_id=" + urllib.parse.quote(str(job.task_id)), self.generation_key, method="GET", timeout=45)
            data = response.get("data", response)
            state = task_state(data)
            job.poll_events.append({"at": now_iso(), "state": state, "progress": data.get("progress") if isinstance(data, dict) else None})
            if not is_final(state, data if isinstance(data, dict) else None):
                job.status = "polling"
            elif "success" in state or "complete" in state or "succeed" in state:
                job.status = "ready"
                job.result_urls = result_urls(data)
                job.completed_at = now_iso()
                job.remote_finished_epoch = time.time()
                if isinstance(data, dict):
                    duration = data.get("duration_seconds") or data.get("actual_time") or data.get("duration")
                    job.remote_duration_seconds = float(duration) if isinstance(duration, (int, float)) else None
                    cost = data.get("cost")
                    job.cost = float(cost) if isinstance(cost, (int, float)) else None
                if not job.result_urls:
                    job.status = "failed"
                    job.error = "生图成功但未返回下载 URL"
            else:
                job.status = "retry" if job.attempts < self.args.max_retries else "failed"
                job.error = f"远程任务失败，状态：{state}"
            self.product_log(product, f"POLL job={job.job_id} state={state} status={job.status}")
        except Exception as exc:
            if is_rate_limit_error(exc):
                job.rate_limited = True
            if is_content_policy_error(exc) or is_rate_limit_error(exc):
                job.status = "retry" if job.attempts < self.args.max_retries else "failed"
                if job.status == "retry":
                    job.task_id = None
                    job.result_urls = []
                    job.remote_finished_epoch = None
            else:
                job.status = "polling"
            job.error = f"{type(exc).__name__}: {exc}"
            self.product_log(product, f"POLL_ERROR job={job.job_id} error={job.error}")
        return job

    def download(self, job: Job) -> Job:
        product = next(p for p in self.products if p.product_id == job.product_id)
        if job.remote_finished_epoch and time.time() - job.remote_finished_epoch > MAX_DOWNLOAD_AGE_SECONDS:
            job.status, job.error = "failed", "下载 URL 已超过 48 小时有效期"
            return job
        target = product.product_dir / job.filename
        url = job.result_urls[0]
        download_started = time.perf_counter()
        for attempt in range(1, self.args.max_retries + 1):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=180) as response:
                    target.write_bytes(response.read())
                job.output_files = [str(target)]
                job.status, job.downloaded_at = "completed", now_iso()
                job.download_seconds = round(time.perf_counter() - download_started, 3)
                self.product_log(product, f"DOWNLOAD_OK job={job.job_id} file={target} attempt={attempt}")
                return job
            except Exception as exc:
                job.error = f"{type(exc).__name__}: {exc}"
                self.product_log(product, f"DOWNLOAD_FAILED job={job.job_id} attempt={attempt} error={job.error}")
                if attempt < self.args.max_retries:
                    time.sleep(min(8, 2 ** (attempt - 1)))
        job.status = "failed"
        return job

    def run(self) -> None:
        self.started_at = now_iso()
        for product in self.products:
            product.product_dir = self.batch_dir / product.product_id
            product.product_dir.mkdir(parents=True, exist_ok=True)
            product.manifest_path = product.product_dir / "manifest.json"
            product.log_path = product.product_dir / "product-run.log"
            product.analysis_refs = choose_analysis_refs(product)
        self.write_manifests()
        understanding_pending = [product for product in self.products if product.status not in {"failed", "completed"} and not product.analysis]
        understanding_limit = min(self.args.understanding_concurrency, max(1, len(understanding_pending)))
        understanding_stable_cycles = 0
        while understanding_pending:
            batch = understanding_pending[:understanding_limit]
            del understanding_pending[:understanding_limit]
            with ThreadPoolExecutor(max_workers=understanding_limit) as pool:
                futures = [pool.submit(analyze_product, product, self.requirements, self.api_key, self.product_log) for product in batch]
                for future in as_completed(futures):
                    future.result()
            if any(product.rate_limited for product in batch):
                understanding_limit = max(min(4, self.args.understanding_concurrency), understanding_limit - 2)
                understanding_stable_cycles = 0
                for product in batch:
                    product.rate_limited = False
            else:
                understanding_stable_cycles += 1
                if understanding_stable_cycles >= 2:
                    understanding_limit = min(self.args.understanding_concurrency, understanding_limit + 2)
                    understanding_stable_cycles = 0
        if self.resume:
            restored_by_id = {job.job_id: job for job in self.jobs}
            rebuilt_jobs: list[Job] = []
            for product in self.products:
                fresh_jobs = build_jobs(product, self.requirements)
                for job in fresh_jobs:
                    restored = restored_by_id.get(job.job_id)
                    if restored:
                        job = self.restore_job_state(job, restored)
                    rebuilt_jobs.append(job)
                if not product.analysis and product.status not in {"analyzed", "completed"}:
                    product.error = product.error or "图片理解失败"
            self.jobs = rebuilt_jobs
            self.job_by_id = {job.job_id: job for job in self.jobs}
        else:
            for product in self.products:
                existing_jobs = [job for job in self.jobs if job.product_id == product.product_id]
                if product.status == "analyzed" and not existing_jobs:
                    product_jobs = build_jobs(product, self.requirements)
                    self.jobs.extend(product_jobs)
                    self.job_by_id.update({job.job_id: job for job in product_jobs})
                elif product.status not in {"analyzed", "completed"} and not product.analysis:
                    product.error = product.error or "图片理解失败"
        self.write_manifests()
        pending = [job for job in self.jobs if job.status in {"pending", "retry", "download_retry"}]
        remote: list[Job] = [job for job in self.jobs if job.status in {"submitted", "polling"} and job.task_id]
        download_futures = []
        with ThreadPoolExecutor(max_workers=self.args.generation_concurrency) as submit_pool, ThreadPoolExecutor(max_workers=self.args.generation_concurrency) as poll_pool, ThreadPoolExecutor(max_workers=self.args.download_concurrency) as download_pool:
            ready_jobs = [job for job in self.jobs if job.status == "ready" and job.result_urls]
            for job in ready_jobs:
                download_futures.append(download_pool.submit(self.download, job))
            while pending or remote:
                slots = max(0, self.generation_limit - len(remote))
                if slots and pending:
                    batch = pending[:slots]
                    del pending[:slots]
                    for job in submit_pool.map(self.submit, batch):
                        if job.status == "submitted":
                            remote.append(job)
                        elif job.status == "retry":
                            pending.append(job)
                    if any(job.rate_limited for job in batch):
                        self.generation_limit = max(min(4, self.args.generation_concurrency), self.generation_limit - 2)
                        self.generation_stable_cycles = 0
                    else:
                        self.generation_stable_cycles += 1
                        if self.generation_stable_cycles >= 3:
                            self.generation_limit = min(self.args.generation_concurrency, self.generation_limit + 2)
                            self.generation_stable_cycles = 0
                if remote:
                    polled = list(poll_pool.map(self.poll, list(remote)))
                    remote = []
                    for job in polled:
                        if job.status in {"polling", "submitted"}:
                            remote.append(job)
                        elif job.status == "ready":
                            download_futures.append(download_pool.submit(self.download, job))
                        elif job.status == "retry":
                            pending.append(job)
                self.write_manifests()
                if remote:
                    time.sleep(self.args.poll_interval)
            for future in as_completed(download_futures):
                future.result()
        for product in self.products:
            product_jobs = [job for job in self.jobs if job.product_id == product.product_id]
            if product.status == "failed":
                continue
            if not product_jobs:
                product.status = "failed"
                product.error = product.error or "没有生成任务"
            elif all(job.status == "completed" for job in product_jobs):
                product.status = "completed"
            else:
                product.status = "partial_completed"
                product.error = "; ".join(f"{job.job_id}: {job.error}" for job in product_jobs if job.status != "completed")
        self.finished_at = now_iso()
        self.write_manifests()


def url_preflight(products: list[Product], log_path: Path, concurrency: int = 10) -> None:
    urls = list(dict.fromkeys(url for product in products for url in product.main_urls + product.sku_urls))
    def check(url: str) -> tuple[str, bool]:
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return url, 200 <= response.status < 400
        except urllib.error.HTTPError as exc:
            return url, exc.code in {405, 403}
        except Exception:
            return url, False
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        valid = dict(pool.map(check, urls))
    for product in products:
        product.main_urls = [url for url in product.main_urls if valid.get(url)]
        product.sku_urls = [url for url in product.sku_urls if valid.get(url)]
        for row in product.rows:
            row["main_urls_list"] = [url for url in row["main_urls_list"] if valid.get(url)]
            row["sku_urls_list"] = [url for url in row["sku_urls_list"] if valid.get(url)]
        product.rows = [row for row in product.rows if row["sku_urls_list"]]
        if not product.main_urls or not product.sku_urls:
            product.status, product.error = "failed", "URL 预检后缺少有效主图或 SKU 图"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{now_iso()} URL_PREFLIGHT total={len(urls)} valid={sum(valid.values())}\n")


def balance_preflight(base_url: str, api_key: str) -> dict[str, Any]:
    result = api_json(base_url.rstrip("/") + "/v1/skills/balance", api_key, method="GET", timeout=30)
    candidates = [result.get("balance")]
    if isinstance(result.get("data"), dict):
        candidates.append(result["data"].get("balance"))
    balance = next((float(value) for value in candidates if isinstance(value, (int, float))), None)
    if balance is None:
        raise WorkflowError(f"余额接口返回格式异常：{json.dumps(result, ensure_ascii=False)[:500]}")
    if balance <= 0:
        raise WorkflowError("生图账户余额不足")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Excel/CSV product-list batch image generation")
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("--requirements", help="用户确认后的统一生图要求")
    parser.add_argument("--resume", type=Path, help="恢复已有批次目录")
    parser.add_argument("--env-file")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--understanding-concurrency", type=int, default=10)
    parser.add_argument("--generation-concurrency", type=int, default=10)
    parser.add_argument("--download-concurrency", type=int, default=4)
    parser.add_argument("--poll-interval", type=float, default=3.0)
    parser.add_argument("--poll-timeout", type=float, default=1800.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--skip-url-preflight", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    apply_config_file()
    read_env(find_env(args.env_file))
    if args.output_root == DEFAULT_OUTPUT_ROOT:
        args.output_root = Path(os.getenv("EXCEL_OUTPUT_ROOT", str(DEFAULT_OUTPUT_ROOT)))
    install_runtime_proxy()
    resume = bool(args.resume)
    if resume:
        if args.source or args.requirements:
            raise WorkflowError("恢复批次时不需要 source 或 --requirements")
        batch_dir = args.resume
        manifest_path = batch_dir / "manifest.json"
        if not manifest_path.is_file():
            raise WorkflowError(f"恢复目录缺少 manifest.json：{batch_dir}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        requirements = Requirements(**manifest["requirements"])
        products = []
        restored_jobs = []
        for item in manifest.get("products", []):
            product = Product(
                product_id=item["product_id"],
                product_name=item.get("product_name", ""),
                category=item.get("category", ""),
                rows=item.get("skus", []),
                main_urls=item.get("main_urls", []),
                sku_urls=item.get("sku_urls", []),
                analysis_refs=item.get("analysis_refs", []),
                analysis=item.get("analysis"),
                analysis_model=item.get("analysis_model"),
                analysis_endpoint=item.get("analysis_endpoint"),
                status=item.get("status", "pending"),
                error=item.get("error"),
            )
            products.append(product)
            for raw_job in item.get("jobs", []):
                job = Job(
                    job_id=raw_job["job_id"],
                    product_id=raw_job["product_id"],
                    kind=raw_job["kind"],
                    index=raw_job["index"],
                    filename=raw_job["filename"],
                    ratio=raw_job["ratio"],
                    prompt=raw_job["prompt"],
                    references=raw_job.get("references", []),
                    status=raw_job.get("status", "pending"),
                    task_id=raw_job.get("task_id"),
                    result_urls=raw_job.get("result_urls", []),
                    output_files=raw_job.get("output_files", []),
                    attempts=raw_job.get("attempts", 0),
                    poll_events=raw_job.get("poll_events", []),
                    error=raw_job.get("error"),
                    submitted_at=raw_job.get("submitted_at"),
                    completed_at=raw_job.get("completed_at"),
                    downloaded_at=raw_job.get("downloaded_at"),
                    poll_started_epoch=time.time() if raw_job.get("status") in {"submitted", "polling"} else None,
                    remote_finished_epoch=time.time() if raw_job.get("status") == "ready" else None,
                    submit_seconds=raw_job.get("submit_seconds"),
                    remote_duration_seconds=raw_job.get("remote_duration_seconds"),
                    download_seconds=raw_job.get("download_seconds"),
                    cost=raw_job.get("cost"),
                )
                restored_jobs.append(job)
        args.output_root = batch_dir.parent.parent
    else:
        if not args.source or not args.source.is_file():
            raise WorkflowError(f"找不到输入表格：{args.source}")
        if not args.requirements:
            raise WorkflowError("首次运行必须提供 --requirements")
        requirements = parse_requirements(args.requirements)
        products = validate_tables(args.source)
        started = dt.datetime.now().astimezone()
        batch_dir = args.output_root / started.strftime("%Y-%m-%d") / started.strftime("%Y-%m-%d_%H%M%S")
        batch_dir.mkdir(parents=True, exist_ok=False)
        shutil.copy2(args.source, batch_dir / args.source.name)
        (batch_dir / "source.sha256").write_text(sha256_file(args.source) + "  " + args.source.name + "\n", encoding="utf-8")
    if not args.skip_url_preflight and not args.dry_run:
        url_preflight(products, batch_dir / "batch-run.log")
    if args.dry_run:
        for product in products:
            print(json.dumps({"product_id": product.product_id, "sku_count": len(product.rows), "main_urls": len(product.main_urls), "sku_urls": len(product.sku_urls), "analysis_refs": choose_analysis_refs(product), "counts": requirements.counts}, ensure_ascii=False))
        print(f"DRY_RUN_BATCH={batch_dir}")
        return 0
    api_key = os.getenv("IMG_API_KEY") or os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
    generation_key = os.getenv("IMG_API_KEY") or os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("IMG_BASE_URL", "").rstrip("/")
    if not base_url:
        raise WorkflowError("缺少配置 IMG_BASE_URL，请先在 image-config.json 或环境变量中录入 Vetech AI 服务地址")
    if not api_key or not generation_key:
        raise WorkflowError("缺少图片理解或生图 API key 配置")
    try:
        balance = balance_preflight(base_url, generation_key)
    except Exception as exc:
        raise WorkflowError(f"余额预检失败，未启动生图：{exc}") from exc
    (batch_dir / "balance-preflight.json").write_text(json.dumps(balance, ensure_ascii=False, indent=2), encoding="utf-8")
    runner = Runner(batch_dir, products, requirements, api_key, generation_key, args, resume=resume)
    if resume:
        runner.jobs = restored_jobs
        runner.job_by_id = {job.job_id: job for job in restored_jobs}
    runner.run()
    print(f"BATCH_DIR={batch_dir}")
    print(json.dumps({"completed": sum(p.status == "completed" for p in products), "partial": sum(p.status == "partial_completed" for p in products), "failed": sum(p.status == "failed" for p in products), "products": len(products)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except WorkflowError as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(2)
