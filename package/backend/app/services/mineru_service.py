"""MinerU precise PDF parsing client.

This module owns the external MinerU v4 protocol only. It deliberately returns
the documented ``*_content_list.json`` items without trying to classify them;
project-specific semantic mapping stays in ``document_structure_service``.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings


MINERU_FILE_URLS_BATCH_PATH = "/api/v4/file-urls/batch"
MINERU_EXTRACT_RESULTS_BATCH_PATH = "/api/v4/extract-results/batch/{batch_id}"
MINERU_CONTENT_LIST_SUFFIX = "_content_list.json"
MINERU_CONTENT_LIST_V2_SUFFIX = "_content_list_v2.json"
MINERU_DONE_STATE = "done"
MINERU_FAILED_STATE = "failed"
MINERU_POLL_STATES = {"waiting-file", "pending", "running", "converting"}
MINERU_PLACEHOLDER_TOKENS = {
    "",
    "replace-with-mineru-api-token",
    "please-change-mineru-api-token",
}


class MinerUError(RuntimeError):
    """Base error for MinerU parse failures."""


class MinerUConfigError(MinerUError):
    """MinerU is not configured enough to call the API."""


class MinerUTimeoutError(MinerUError):
    """MinerU polling did not finish before the configured timeout."""


@dataclass(frozen=True)
class MinerUParseResult:
    batch_id: str
    trace_id: str
    model_version: str
    content_items: list[dict[str, Any]]
    content_list_name: str
    full_zip_url: str


class MinerUService:
    """Synchronous MinerU v4 client used from FastAPI threadpool parsing."""

    def parse_pdf(self, filename: str, content: bytes) -> MinerUParseResult:
        token = (settings.MINERU_API_TOKEN or "").strip()
        if token.lower() in MINERU_PLACEHOLDER_TOKENS:
            raise MinerUConfigError("未配置 MINERU_API_TOKEN")
        if not content:
            raise MinerUError("PDF 内容为空")

        base_url = (settings.MINERU_BASE_URL or "https://mineru.net").rstrip("/")
        timeout_seconds = max(1, int(settings.MINERU_TIMEOUT_SECONDS or 300))
        deadline = time.monotonic() + timeout_seconds
        headers = {"Authorization": f"Bearer {token}"}

        with httpx.Client(timeout=httpx.Timeout(30.0, read=60.0)) as client:
            upload_url_result = self._request_upload_url(client, base_url, headers, filename)
            batch_id = upload_url_result["batch_id"]
            trace_id = upload_url_result["trace_id"]
            file_url = upload_url_result["file_url"]

            upload_response = client.put(file_url, content=content)
            self._raise_for_http_status(upload_response, "MinerU 文件上传失败")

            extract_result = self._poll_extract_result(client, base_url, headers, batch_id, deadline)
            full_zip_url = str(extract_result.get("full_zip_url") or "").strip()
            if not full_zip_url:
                raise MinerUError("MinerU 结果缺少 full_zip_url")

            zip_response = client.get(full_zip_url)
            self._raise_for_http_status(zip_response, "MinerU 结果包下载失败")
            content_list_name, content_items = self._extract_content_list(zip_response.content)

        return MinerUParseResult(
            batch_id=batch_id,
            trace_id=trace_id,
            model_version=str(settings.MINERU_MODEL_VERSION or ""),
            content_items=content_items,
            content_list_name=content_list_name,
            full_zip_url=full_zip_url,
        )

    def _request_upload_url(
        self,
        client: httpx.Client,
        base_url: str,
        headers: dict[str, str],
        filename: str,
    ) -> dict[str, str]:
        request_body: dict[str, Any] = {
            "files": [
                {
                    "name": filename or "paper.pdf",
                    "is_ocr": bool(settings.MINERU_IS_OCR),
                }
            ],
            "model_version": settings.MINERU_MODEL_VERSION or "vlm",
            "enable_formula": bool(settings.MINERU_ENABLE_FORMULA),
            "enable_table": bool(settings.MINERU_ENABLE_TABLE),
        }
        language = (settings.MINERU_LANGUAGE or "").strip()
        if language:
            request_body["language"] = language

        response = client.post(
            f"{base_url}{MINERU_FILE_URLS_BATCH_PATH}",
            headers={**headers, "Content-Type": "application/json"},
            json=request_body,
        )
        self._raise_for_http_status(response, "MinerU 申请上传地址失败")
        payload = self._response_json(response, "MinerU 上传地址响应不是合法 JSON")
        if payload.get("code") != 0:
            message = str(payload.get("msg") or "MinerU 申请上传地址失败")
            raise MinerUError(message)

        data = payload.get("data")
        if not isinstance(data, dict):
            raise MinerUError("MinerU 上传地址响应缺少 data")
        batch_id = str(data.get("batch_id") or "").strip()
        file_urls = data.get("file_urls")
        if not batch_id:
            raise MinerUError("MinerU 上传地址响应缺少 batch_id")
        if not isinstance(file_urls, list) or not file_urls or not isinstance(file_urls[0], str):
            raise MinerUError("MinerU 上传地址响应缺少 file_urls")

        return {
            "batch_id": batch_id,
            "trace_id": str(payload.get("trace_id") or ""),
            "file_url": file_urls[0],
        }

    def _poll_extract_result(
        self,
        client: httpx.Client,
        base_url: str,
        headers: dict[str, str],
        batch_id: str,
        deadline: float,
    ) -> dict[str, Any]:
        poll_interval = max(0.5, float(settings.MINERU_POLL_INTERVAL_SECONDS or 2.0))
        url = f"{base_url}{MINERU_EXTRACT_RESULTS_BATCH_PATH.format(batch_id=batch_id)}"
        last_state = ""

        while True:
            if time.monotonic() > deadline:
                timeout = int(settings.MINERU_TIMEOUT_SECONDS or 300)
                state_suffix = f"，最后状态：{last_state}" if last_state else ""
                raise MinerUTimeoutError(f"MinerU 解析超时（{timeout} 秒）{state_suffix}")

            response = client.get(url, headers=headers)
            self._raise_for_http_status(response, "MinerU 查询解析结果失败")
            payload = self._response_json(response, "MinerU 查询响应不是合法 JSON")
            if payload.get("code") != 0:
                message = str(payload.get("msg") or "MinerU 查询解析结果失败")
                raise MinerUError(message)

            data = payload.get("data")
            if not isinstance(data, dict):
                raise MinerUError(f"MinerU 查询响应 data 类型错误：{type(data).__name__}")
            extract_result = self._select_extract_result(data)

            state = str(extract_result.get("state") or "").strip()
            last_state = state
            if state == MINERU_DONE_STATE:
                return extract_result
            if state == MINERU_FAILED_STATE:
                err_msg = str(extract_result.get("err_msg") or "MinerU 解析失败")
                raise MinerUError(err_msg)
            if state in MINERU_POLL_STATES:
                sleep_seconds = min(poll_interval, max(0.0, deadline - time.monotonic()))
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
                continue
            raise MinerUError(f"MinerU 返回未知解析状态：{state or '<empty>'}")

    def _select_extract_result(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return the single file result from MinerU batch query data.

        The query endpoint is a batch API. Real MinerU responses can carry the
        file results as ``data.extract_result`` array even when this product
        uploads exactly one PDF; older examples show the same field as an
        object. We accept only those two explicit shapes and require exactly one
        file result so a multi-file response cannot be silently mis-associated.
        """
        extract_result = data.get("extract_result")
        if isinstance(extract_result, dict):
            return extract_result
        if isinstance(extract_result, list):
            result_items = [item for item in extract_result if isinstance(item, dict)]
            if len(result_items) == 1:
                return result_items[0]
            raise MinerUError(f"MinerU 查询响应 extract_result 数量异常：{len(result_items)}")
        raise MinerUError(f"MinerU 查询响应 extract_result 类型错误：{type(extract_result).__name__}")

    def _extract_content_list(self, zip_content: bytes) -> tuple[str, list[dict[str, Any]]]:
        try:
            archive = zipfile.ZipFile(io.BytesIO(zip_content))
        except zipfile.BadZipFile as exc:
            raise MinerUError("MinerU 结果包不是合法 ZIP") from exc

        with archive:
            content_list_names = [
                name
                for name in archive.namelist()
                if name.endswith(MINERU_CONTENT_LIST_SUFFIX)
                and not name.endswith(MINERU_CONTENT_LIST_V2_SUFFIX)
            ]
            if not content_list_names:
                raise MinerUError("MinerU 结果包缺少 content_list.json")
            if len(content_list_names) > 1:
                raise MinerUError("MinerU 结果包包含多个 content_list.json")

            content_list_name = content_list_names[0]
            with archive.open(content_list_name) as file_obj:
                try:
                    payload = json.load(file_obj)
                except json.JSONDecodeError as exc:
                    raise MinerUError("MinerU content_list.json 不是合法 JSON") from exc

        if not isinstance(payload, list):
            raise MinerUError("MinerU content_list.json 顶层不是数组")
        content_items = [item for item in payload if isinstance(item, dict)]
        if not content_items:
            raise MinerUError("MinerU content_list.json 未提取到有效项目")
        return content_list_name, content_items

    @staticmethod
    def _response_json(response: httpx.Response, error_message: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise MinerUError(error_message) from exc
        if not isinstance(payload, dict):
            raise MinerUError(error_message)
        return payload

    @staticmethod
    def _raise_for_http_status(response: httpx.Response, message: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MinerUError(f"{message}: HTTP {response.status_code}") from exc


mineru_service = MinerUService()
