from app.services.error_messages import build_task_error_message


def test_task_error_message_classifies_api_key_failure_with_segment_context():
    message = build_task_error_message(
        RuntimeError("段落 2 在 polish 阶段失败: Error code: 401 - Incorrect API key provided")
    )

    assert message.startswith("第 2 段润色失败：")
    assert "API Key 无效或权限不足" in message
    assert "Incorrect API key" not in message


def test_task_error_message_classifies_model_not_found():
    message = build_task_error_message(
        RuntimeError("段落 1 在 enhance 阶段失败: model_not_found: model does not exist")
    )

    assert message.startswith("第 1 段降重失败：")
    assert "模型不存在" in message


def test_task_error_message_classifies_rate_limit_timeout_network_and_quota():
    assert "限流" in build_task_error_message(RuntimeError("HTTP 429 rate limit exceeded"))
    assert "超时" in build_task_error_message(TimeoutError("request timeout expired"))
    assert "无法连接 API 服务" in build_task_error_message(RuntimeError("connection refused"))
    assert "余额不足" in build_task_error_message(RuntimeError("insufficient_quota"))


def test_task_error_message_truncates_long_unknown_errors_without_leaking_full_detail():
    message = build_task_error_message(RuntimeError("x" * 1000), max_length=120)

    assert len(message) <= 120
    assert message.endswith("[错误信息已截断]")
    assert "x" * 200 not in message
