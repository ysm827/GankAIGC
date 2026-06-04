import re
from typing import Optional


DEFAULT_MAX_ERROR_MESSAGE_LENGTH = 500

STAGE_LABELS = {
    "polish": "润色",
    "enhance": "降重",
    "emotion_polish": "感情润色",
    "compression": "历史压缩",
}


def truncate_error_message(message: str, max_length: int = DEFAULT_MAX_ERROR_MESSAGE_LENGTH) -> str:
    if len(message) <= max_length:
        return message
    suffix = "... [错误信息已截断]"
    return message[: max(max_length - len(suffix), 0)] + suffix


def _extract_segment_context(message: str) -> tuple[Optional[int], Optional[str], str]:
    match = re.search(r"段落\s*(\d+)\s*在\s*([a-zA-Z_]+)\s*阶段失败[:：]\s*(.*)", message, re.S)
    if not match:
        return None, None, message
    return int(match.group(1)), match.group(2), match.group(3).strip()


def _classify_error_message(message: str) -> str:
    normalized = message.lower()

    if any(keyword in normalized for keyword in ("朱雀", "zhuque", "chrome cdp", "chrome ", "matrix.tencent.com/ai-detect", "remote-debugging-port")):
        return message.strip()
    if any(keyword in normalized for keyword in ("incorrect api key", "invalid api key", "authentication", "unauthorized", "401")):
        return "API Key 无效或权限不足，请在系统配置或自带 API 配置里重新填写。"
    if any(keyword in normalized for keyword in ("insufficient_quota", "insufficient quota", "quota", "余额不足", "额度不足", "billing")):
        return "API 额度或余额不足，请检查服务商账户余额，或切换其他可用 API。"
    if any(keyword in normalized for keyword in ("model_not_found", "model not found", "model does not exist", "404")):
        return "模型不存在或当前 Key 无权访问该模型，请检查模型名称和账号权限。"
    if any(keyword in normalized for keyword in ("rate limit", "too many requests", "429", "限流")):
        return "API 请求被限流，请稍后重试，或调大请求间隔后继续处理。"
    if any(keyword in normalized for keyword in ("timeout", "timed out", "超时")):
        return "API 请求超时，请检查 Base URL、服务器网络或稍后继续处理。"
    if any(keyword in normalized for keyword in ("connection", "connect", "network", "dns", "proxy", "连接失败", "无法连接")):
        return "无法连接 API 服务，请检查 Base URL、网络、防火墙或代理设置。"

    return message.strip() or "未知错误"


def build_task_error_message(error: Exception, max_length: int = DEFAULT_MAX_ERROR_MESSAGE_LENGTH) -> str:
    raw_message = str(error) or error.__class__.__name__
    segment_index, stage, detail = _extract_segment_context(raw_message)
    friendly_detail = _classify_error_message(detail)

    if segment_index is not None:
        stage_label = STAGE_LABELS.get(stage or "", stage or "处理")
        message = f"第 {segment_index} 段{stage_label}失败：{friendly_detail}"
    else:
        message = friendly_detail

    return truncate_error_message(message, max_length=max_length)
