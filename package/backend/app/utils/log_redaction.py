import logging
import re


_QUERY_SECRET_PATTERN = re.compile(
    r"([?&](?:stream_token|access_token|token)=)[^&\s]+",
    flags=re.IGNORECASE,
)


def redact_url_query_secrets(value: str) -> str:
    return _QUERY_SECRET_PATTERN.sub(r"\1<redacted>", value)


class UvicornAccessTokenRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            args = list(record.args)
            if isinstance(args[2], str):
                args[2] = redact_url_query_secrets(args[2])
                record.args = tuple(args)
        return True


def install_uvicorn_access_log_redaction() -> None:
    logger = logging.getLogger("uvicorn.access")
    if any(isinstance(item, UvicornAccessTokenRedactionFilter) for item in logger.filters):
        return
    logger.addFilter(UvicornAccessTokenRedactionFilter())
