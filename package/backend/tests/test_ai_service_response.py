from app.services.ai_service import create_async_openai_client, extract_completion_content


def test_extract_completion_content_accepts_plain_string_gateway_response():
    assert extract_completion_content("rewritten text") == "rewritten text"


def test_extract_completion_content_accepts_openai_compatible_dict():
    response = {"choices": [{"message": {"content": "rewritten text"}}]}

    assert extract_completion_content(response) == "rewritten text"

def test_extract_completion_content_accepts_anthropic_message_dict():
    response = {"content": [{"type": "text", "text": "rewritten text"}]}

    assert extract_completion_content(response) == "rewritten text"


def test_create_async_openai_client_survives_httpx_without_proxies_kwarg():
    client = create_async_openai_client(
        api_key="sk-test",
        base_url="https://api.example/v1",
        timeout=1.0,
        max_retries=0,
    )

    assert client is not None
