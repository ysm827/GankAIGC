import base64
import hashlib
from collections.abc import Iterable, MutableMapping

from starlette.responses import Response


SECURITY_HEADER_VALUES = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
        "magnetometer=(), gyroscope=(), accelerometer=()"
    ),
}


def csp_hash_for_inline_script(script_content: str) -> str:
    digest = hashlib.sha256(script_content.encode("utf-8")).digest()
    return f"'sha256-{base64.b64encode(digest).decode('ascii')}'"


def build_content_security_policy(
    script_sources: Iterable[str] = (),
    style_sources: Iterable[str] = (),
    img_sources: Iterable[str] = (),
    font_sources: Iterable[str] = (),
) -> str:
    script_src = ["'self'", *script_sources]
    style_src = ["'self'", "'unsafe-inline'", *style_sources]
    img_src = ["'self'", "data:", "blob:", *img_sources]
    font_src = ["'self'", "data:", *font_sources]
    directives = [
        ("default-src", ["'self'"]),
        ("script-src", script_src),
        ("style-src", style_src),
        ("img-src", img_src),
        ("font-src", font_src),
        ("connect-src", ["'self'"]),
        ("object-src", ["'none'"]),
        ("base-uri", ["'self'"]),
        ("form-action", ["'self'"]),
        ("frame-ancestors", ["'none'"]),
        ("frame-src", ["'none'"]),
    ]
    return "; ".join(f"{name} {' '.join(values)}" for name, values in directives)


def build_security_headers(
    script_sources: Iterable[str] = (),
    style_sources: Iterable[str] = (),
    img_sources: Iterable[str] = (),
    font_sources: Iterable[str] = (),
) -> dict[str, str]:
    return {
        **SECURITY_HEADER_VALUES,
        "Content-Security-Policy": build_content_security_policy(
            script_sources=script_sources,
            style_sources=style_sources,
            img_sources=img_sources,
            font_sources=font_sources,
        ),
    }


def build_docs_security_headers() -> dict[str, str]:
    return build_security_headers(
        script_sources=("'unsafe-inline'", "https://cdn.jsdelivr.net"),
        style_sources=("https://cdn.jsdelivr.net",),
        img_sources=("https://fastapi.tiangolo.com",),
        font_sources=("https://cdn.jsdelivr.net",),
    )


def update_security_headers(
    headers: MutableMapping[str, str],
    script_sources: Iterable[str] = (),
) -> None:
    for name, value in build_security_headers(script_sources).items():
        headers.setdefault(name, value)


def add_security_headers(
    response: Response,
    script_sources: Iterable[str] = (),
) -> Response:
    update_security_headers(response.headers, script_sources)
    return response


def add_docs_security_headers(response: Response) -> Response:
    for name, value in build_docs_security_headers().items():
        response.headers.setdefault(name, value)
    return response
