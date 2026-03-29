# Copyright (c) Opendatalab. All rights reserved.
import json
import os
from itertools import cycle
from pathlib import Path
from threading import Lock
from typing import Optional

from dotenv import load_dotenv
from loguru import logger

from mineru.cli.common import do_parse as mineru_do_parse
from mineru.cli.common import read_fn

from src.utils.mineru_backend import normalize_backend, resolve_backend, resolve_backend_from_env

DEFAULT_VLLM_SERVER_URL = "http://127.0.0.1:30000"
_SERVER_URL_ENV_KEYS: tuple[str, ...] = (
    "MINERU_VLLM_SERVER_URLS",
    "MINERU_VLLM_SERVER_URL",
    "MINERU_VLM_SERVER_URLS",
    "MINERU_VLM_SERVER_URL",
)
_DEFAULT_BACKEND = "vlm-http-client"
_DEFAULT_LANG = "ch"
_DEFAULT_METHOD = "auto"
_SERVER_URL_CYCLE_LOCK = Lock()
_SERVER_URL_CACHE: tuple[str, ...] = ()
_SERVER_URL_CYCLE = None

load_dotenv()

# Expose the upstream entrypoint so tests and downstream code can monkeypatch it directly.
do_parse = mineru_do_parse


def _normalize_server_url_input(raw_value) -> list[str]:
    """Accept strings, comma-separated strings, JSON arrays, or iterables."""
    if raw_value is None:
        return []

    if isinstance(raw_value, (list, tuple, set)):
        normalized: list[str] = []
        for item in raw_value:
            normalized.extend(_normalize_server_url_input(item))
        return normalized

    if isinstance(raw_value, str):
        candidate = raw_value.strip()
        if not candidate:
            return []
        if candidate.startswith("[") and candidate.endswith("]"):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                pass
            else:
                return _normalize_server_url_input(parsed)
        if "," in candidate:
            return [part.strip() for part in candidate.split(",") if part.strip()]
        return [candidate]

    return _normalize_server_url_input(str(raw_value))


def _server_urls_from_env() -> list[str]:
    for key in _SERVER_URL_ENV_KEYS:
        raw_value = os.getenv(key)
        if not raw_value:
            continue
        urls = _normalize_server_url_input(raw_value)
        if urls:
            return urls
    return []


def _resolve_server_urls(server_url) -> list[str]:
    explicit_urls = _normalize_server_url_input(server_url)
    if explicit_urls:
        return explicit_urls

    env_urls = _server_urls_from_env()
    if env_urls:
        return env_urls

    return [DEFAULT_VLLM_SERVER_URL]


def _resolve_server_headers(headers: Optional[dict[str, str]] = None) -> Optional[dict[str, str]]:
    if headers:
        return headers

    auth_header = os.getenv("MINERU_VLLM_AUTH_HEADER")
    api_key = os.getenv("MINERU_VLLM_API_KEY")
    resolved: dict[str, str] = {}
    if auth_header and auth_header.strip():
        resolved["Authorization"] = auth_header.strip()
    elif api_key and api_key.strip():
        resolved["Authorization"] = f"Bearer {api_key.strip()}"

    return resolved or None


def _next_server_url(urls: list[str]) -> str:
    if not urls:
        raise ValueError("No VLM server URLs available.")
    if len(urls) == 1:
        return urls[0]

    global _SERVER_URL_CYCLE, _SERVER_URL_CACHE
    urls_tuple = tuple(urls)
    with _SERVER_URL_CYCLE_LOCK:
        if _SERVER_URL_CYCLE is None or _SERVER_URL_CACHE != urls_tuple:
            _SERVER_URL_CYCLE = cycle(urls_tuple)
            _SERVER_URL_CACHE = urls_tuple
            logger.debug("Configured VLM server pool: %s", urls_tuple)
        return next(_SERVER_URL_CYCLE)


def _env_default_lang() -> str:
    raw_value = os.getenv("MINERU_DEFAULT_LANG")
    if raw_value is not None:
        candidate = raw_value.strip()
        if candidate:
            return candidate
    return _DEFAULT_LANG


def _env_default_method() -> str:
    raw_value = os.getenv("MINERU_DEFAULT_METHOD")
    if raw_value is not None:
        candidate = raw_value.strip()
        if candidate:
            return candidate
    return _DEFAULT_METHOD


def _resolve_backend_value(backend: Optional[str]) -> str:
    normalized = normalize_backend(backend)
    if normalized is not None:
        return resolve_backend(normalized) or _DEFAULT_BACKEND

    resolved_from_env = resolve_backend_from_env()
    if resolved_from_env is not None:
        return resolved_from_env

    return _DEFAULT_BACKEND


def _content_list_search_roots(
    output_dir: Path,
    pdf_file_name: str,
    backend: str,
    parse_method: str,
) -> list[Path]:
    file_root = output_dir / pdf_file_name
    roots: list[Path] = []

    if backend == "pipeline":
        roots.append(file_root / parse_method)
    elif backend.startswith("hybrid-"):
        roots.append(file_root / f"hybrid_{parse_method}")
    else:
        roots.append(file_root / "vlm")

    roots.append(file_root)
    return roots


def _find_content_list_file(
    output_dir: Path,
    pdf_file_name: str,
    backend: str,
    parse_method: str,
) -> Optional[Path]:
    target_name = f"{pdf_file_name}_content_list.json"
    for root in _content_list_search_roots(output_dir, pdf_file_name, backend, parse_method):
        candidate = root / target_name
        if candidate.exists():
            return candidate

    file_root = output_dir / pdf_file_name
    if not file_root.exists():
        return None

    matches = list(file_root.rglob(target_name))
    if not matches:
        return None

    def _mtime_ns(path: Path) -> int:
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return -1

    matches.sort(key=_mtime_ns, reverse=True)
    return matches[0]


def _load_content_list(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text("utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Missing MinerU content list file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid MinerU content list JSON: {path}") from exc

    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected MinerU content list payload in {path}")
    return payload


def parse_doc(
    path_list: list[Path],
    output_dir,
    lang: Optional[str] = None,
    backend: Optional[str] = None,
    method: Optional[str] = None,
    server_url=None,
    server_headers=None,
    start_page_id=0,  # Start page ID for parsing, default is 0
    end_page_id=None,  # End page ID for parsing, default is None (parse all pages until the end of the document)
    dump_debug_intermediate=False,  # Retained for compatibility with the previous local wrapper
    log_debug_intermediate=False,  # Retained for compatibility with the previous local wrapper
    return_txt=False,  # Retained for API compatibility; plain text is composed upstream
):
    """
    Thin compatibility wrapper around MinerU's official `mineru.cli.common.do_parse`.

    MinerU 3.x no longer returns `content_list` directly from `do_parse`, so this service
    keeps the historical contract by reading `{stem}_content_list.json` back from MinerU's
    output directory and returning `(content_list, output_dir_path, None)` to downstream code.
    """
    del return_txt  # kept only to preserve the public function signature

    if not path_list:
        raise ValueError("path_list must not be empty.")

    if dump_debug_intermediate or log_debug_intermediate:
        logger.warning(
            "dump_debug_intermediate/log_debug_intermediate are ignored by the MinerU "
            "3.x compatibility wrapper."
        )

    effective_backend = _resolve_backend_value(backend)
    effective_lang = (lang or "").strip() or _env_default_lang()
    effective_method = (method or "").strip() or _env_default_method()
    resolved_headers = _resolve_server_headers(server_headers)
    server_urls = _resolve_server_urls(server_url)
    output_dir_path = Path(output_dir)

    last_content_list: Optional[list[dict]] = None
    last_local_output_dir: Optional[str] = None

    try:
        for path in path_list:
            file_path = Path(path)
            file_name = str(file_path.stem)
            pdf_bytes = read_fn(file_path)
            assigned_server_url = _next_server_url(server_urls)

            logger.debug(
                "Dispatching %s to MinerU backend '%s' via %s",
                file_name,
                effective_backend,
                assigned_server_url,
            )
            do_parse(
                output_dir=output_dir,
                pdf_file_names=[file_name],
                pdf_bytes_list=[pdf_bytes],
                p_lang_list=[effective_lang],
                backend=effective_backend,
                parse_method=effective_method,
                server_url=assigned_server_url,
                server_headers=resolved_headers,
                start_page_id=start_page_id,
                end_page_id=end_page_id,
                f_draw_layout_bbox=False,
                f_draw_span_bbox=False,
                f_dump_md=False,
                f_dump_middle_json=False,
                f_dump_model_output=False,
                f_dump_orig_pdf=False,
                f_dump_content_list=True,
            )

            content_list_path = _find_content_list_file(
                output_dir_path, file_name, effective_backend, effective_method
            )
            if content_list_path is None:
                raise RuntimeError(
                    "MinerU did not produce "
                    f"{file_name}_content_list.json under {output_dir_path}"
                )

            last_content_list = _load_content_list(content_list_path)
            last_local_output_dir = str(content_list_path.parent)

        if last_content_list is None or last_local_output_dir is None:
            raise RuntimeError("MinerU did not return any parsed content.")

        return last_content_list, last_local_output_dir, None
    except Exception as exc:
        logger.exception(exc)
        raise


if __name__ == "__main__":
    # args
    __dir__ = os.path.dirname(os.path.abspath(__file__))
    pdf_files_dir = os.path.join(__dir__, "../../pdfs")
    output_dir = os.path.join(__dir__, "./../output")
    pdf_suffixes = [".pdf"]
    image_suffixes = [".png", ".jpeg", ".jpg"]

    doc_path_list = []
    for doc_path in Path(pdf_files_dir).glob("*"):
        if doc_path.suffix in pdf_suffixes + image_suffixes:
            doc_path_list.append(doc_path)

    """如果您由于网络问题无法下载模型，可以设置环境变量MINERU_MODEL_SOURCE为modelscope使用免代理仓库下载模型"""
    os.environ["MINERU_MODEL_SOURCE"] = "modelscope"

    """Use pipeline mode if your environment does not support VLM"""
    parse_doc(doc_path_list, output_dir, backend="pipeline")

    """To enable VLM mode, change the backend to one of the vlm-* options"""
    # parse_doc(doc_path_list, output_dir, backend="vlm-transformers")  # more general.
    # parse_doc(doc_path_list, output_dir, backend="vlm-vllm-engine")  # vLLM engine.
    # parse_doc(doc_path_list, output_dir, backend="vlm-lmdeploy-engine")  # LMDeploy engine.
    # parse_doc(doc_path_list, output_dir, backend="vlm-http-client")  # HTTP client.
    # parse_doc(doc_path_list, output_dir, backend="vlm-mlx-engine")  # Apple silicon engine.
    # parse_doc(doc_path_list, output_dir, backend="hybrid-auto-engine")
