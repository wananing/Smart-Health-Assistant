"""
Vision input adapter for report interpretation and pharmacy photo flows.

This module keeps image recognition separate from medical/pharmacy reasoning:
an OpenAI-compatible multimodal model extracts visible facts, then the existing
report/pharmacy agents interpret those facts.
"""
from __future__ import annotations

import base64
import re
from typing import Literal

from agents.llm import LLMConfigurationError, resolve_model_settings


VisionScanType = Literal["report", "drug_box", "trace_code"]

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024

SCAN_TYPE_TO_AGENT = {
    "report": "report_agent",
    "drug_box": "pharmacy_agent",
    "trace_code": "pharmacy_agent",
}


class VisionInputError(ValueError):
    """Raised when an uploaded image or scan type is invalid."""


def normalize_scan_type(scan_type: str) -> VisionScanType:
    normalized = scan_type.strip().lower()
    if normalized in SCAN_TYPE_TO_AGENT:
        return normalized  # type: ignore[return-value]
    raise VisionInputError("scan_type must be one of: report, drug_box, trace_code")


def validate_image_upload(content_type: str | None, size_bytes: int) -> None:
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise VisionInputError("Only JPEG, PNG, and WebP images are supported")
    if size_bytes <= 0:
        raise VisionInputError("Uploaded image is empty")
    if size_bytes > MAX_IMAGE_BYTES:
        raise VisionInputError("Uploaded image must be 8 MB or smaller")


def build_vision_prompt(scan_type: VisionScanType) -> str:
    if scan_type == "report":
        return (
            "请识别这张检查/检验报告图片中的医学信息。\n"
            "只提取报告类型、检查项目、数值、单位、参考范围、异常标记、报告日期。\n"
            "不要提取或输出姓名、身份证号、手机号、住址、就诊卡号、病历号、条形码号等个人身份信息。\n"
            "如果这些信息出现在图片中，请统一写为「已隐藏」。\n"
            "如果字段看不清，请写「无法确认」。\n"
            "不要诊断疾病，不要给治疗方案，只输出可用于后续报告解读的结构化内容。"
        )

    if scan_type == "trace_code":
        return (
            "请识别这张药品追溯码或药品包装图片中的可见信息。\n"
            "提取药品名称、通用名、规格、生产厂家、批准文号、有效期、批号、追溯码可见内容。\n"
            "如果字段看不清，请写「无法确认」。\n"
            "不要判断真伪，不要编造监管查询结果，只输出图片中可确认的信息。"
        )

    return (
        "请识别这张药品包装图片中的药品信息。\n"
        "提取药品名称、通用名、规格、生产厂家、批准文号、有效期、用法用量、是否处方药。\n"
        "如果字段看不清，请写「无法确认」。\n"
        "不要编造说明书内容，不要给超出图片和药品知识的结论。"
    )


_LABEL_PATTERN = re.compile(
    r"(姓名|身份证号?|手机号|电话|住址|地址|就诊卡号|病历号|条形码号?|患者ID|门诊号|住院号)"
    r"\s*[:：]\s*[^\n，,；;]+"
)
_PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_ID_PATTERN = re.compile(r"(?<![0-9A-Za-z])\d{6}(?:19|20)?\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![0-9A-Za-z])")


def redact_sensitive_text(text: str) -> str:
    """Best-effort redaction for common PII that a vision model may return."""

    def replace_label(match: re.Match[str]) -> str:
        label = match.group(1)
        return f"{label}：已隐藏"

    redacted = _LABEL_PATTERN.sub(replace_label, text)
    redacted = _PHONE_PATTERN.sub("已隐藏手机号", redacted)
    redacted = _ID_PATTERN.sub("已隐藏身份证号", redacted)
    return redacted


def compose_agent_message(scan_type: VisionScanType, vision_text: str) -> str:
    safe_text = redact_sensitive_text(vision_text).strip() or "无法确认"
    if scan_type == "report":
        return (
            "用户上传了一张检验报告图片，个人身份信息已隐藏。视觉模型识别结果：\n"
            f"{safe_text}\n\n"
            "请基于以上内容进行报告解读。"
        )

    if scan_type == "trace_code":
        return (
            "用户上传了一张药品追溯码或药品包装图片。视觉模型识别结果：\n"
            f"{safe_text}\n\n"
            "请说明可识别出的药品信息、用药注意事项，并提醒用户真伪需以正规追溯平台查询为准。"
        )

    return (
        "用户上传了一张药盒图片。视觉模型识别结果：\n"
        f"{safe_text}\n\n"
        "请说明这个药的用途、用法用量、禁忌、注意事项，以及是否适合当前用户。"
    )


def image_to_data_url(image_bytes: bytes, content_type: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


async def recognize_image(image_bytes: bytes, content_type: str, scan_type: VisionScanType) -> str:
    """
    Call the configured multimodal model and return redacted visible facts.

    The returned content is user-provided context for downstream agents, never a
    system prompt.
    """
    validate_image_upload(content_type, len(image_bytes))

    try:
        settings = resolve_model_settings(purpose="vision")
    except LLMConfigurationError as exc:
        raise VisionInputError(str(exc)) from exc

    from openai import AsyncOpenAI

    client_kwargs = {"api_key": settings.api_key}
    if settings.base_url:
        client_kwargs["base_url"] = settings.base_url
    client = AsyncOpenAI(**client_kwargs)

    request = {
        "model": settings.model,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": build_vision_prompt(scan_type)},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_to_data_url(image_bytes, content_type)},
                    },
                ],
            }
        ],
    }
    if settings.extra_body:
        request["extra_body"] = settings.extra_body
    response = await client.chat.completions.create(**request)

    content = response.choices[0].message.content if response.choices else ""
    if isinstance(content, list):
        content = "\n".join(str(part) for part in content)
    return redact_sensitive_text(str(content))
