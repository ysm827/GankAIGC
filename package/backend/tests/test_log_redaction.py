import logging

from app.utils.log_redaction import (
    UvicornAccessTokenRedactionFilter,
    redact_url_query_secrets,
)


def test_url_query_secret_redaction_covers_stream_and_access_tokens():
    value = "/api/stream?stream_token=secret-value&safe=1&access_token=other"

    redacted = redact_url_query_secrets(value)

    assert "secret-value" not in redacted
    assert "other" not in redacted
    assert "safe=1" in redacted
    assert redacted.count("<redacted>") == 2


def test_uvicorn_access_filter_rewrites_request_target_argument():
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1", "GET", "/stream?stream_token=secret", "1.1", 200),
        exc_info=None,
    )

    assert UvicornAccessTokenRedactionFilter().filter(record) is True
    assert "secret" not in record.args[2]
    assert "<redacted>" in record.args[2]
