# Copyright (c) Opendatalab. All rights reserved.
import base64
import copy
import json
import os
from itertools import cycle
from pathlib import Path
from threading import Lock
from typing import Any, Optional

from dotenv import load_dotenv
from loguru import logger

from mineru.cli.common import convert_pdf_bytes_to_bytes_by_pypdfium2, prepare_env, read_fn
from mineru.data.data_reader_writer import FileBasedDataWriter
from mineru.utils.draw_bbox import draw_layout_bbox, draw_span_bbox
from mineru.utils.enum_class import MakeMode
from mineru.backend.vlm.vlm_analyze import doc_analyze as vlm_doc_analyze
from mineru.backend.pipeline.pipeline_analyze import doc_analyze as pipeline_doc_analyze
from mineru.backend.pipeline.pipeline_middle_json_mkcontent import union_make as pipeline_union_make
from mineru.backend.pipeline.model_json_to_middle_json import (
    result_to_middle_json as pipeline_result_to_middle_json,
)
from mineru.backend.vlm.vlm_middle_json_mkcontent import union_make as vlm_union_make


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


def _env_default_backend() -> str:
    raw_value = os.getenv("MINERU_DEFAULT_BACKEND")
    if raw_value is not None:
        candidate = raw_value.strip()
        if candidate:
            return candidate
    return _DEFAULT_BACKEND


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


def _debug_default_serializer(obj: Any):
    if isinstance(obj, (bytes, bytearray)):
        try:
            return obj.decode("utf-8")
        except UnicodeDecodeError:
            return {
                "__type__": "bytes",
                "base64": base64.b64encode(obj).decode("ascii"),
            }
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "__dict__") and obj.__dict__:
        return {key: value for key, value in obj.__dict__.items() if not key.startswith("_")}
    return repr(obj)


def _serialize_debug_payload(payload: dict[str, Any]) -> str:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            indent=4,
            default=_debug_default_serializer,
        )
    except Exception as exc:
        raise ValueError("Failed to serialize debug payload") from exc


def _output_debug_payload(
    writer: Optional[FileBasedDataWriter],
    filename: str,
    payload: dict[str, Any],
    *,
    dump: bool,
    log: bool,
) -> None:
    if not dump and not log:
        return

    try:
        serialized = _serialize_debug_payload(payload)
    except ValueError:
        logger.exception("Failed to prepare debug payload for %s", filename)
        return

    if dump and writer is not None:
        try:
            writer.write_string(filename, serialized)
        except Exception:
            logger.exception("Failed to dump debug payload for %s", filename)

    if log:
        logger.info("Intermediate payload for %s:\n%s", filename, serialized)
        print(f"[mineru-debug] {filename} ->\n{serialized}", flush=True)


def do_parse(
    output_dir,  # Output directory for storing parsing results
    pdf_file_names: list[str],  # List of PDF file names to be parsed
    pdf_bytes_list: list[bytes],  # List of PDF bytes to be parsed
    p_lang_list: list[str],  # List of languages for each PDF, default is 'ch' (Chinese)
    backend="pipeline",  # The backend for parsing PDF, default is 'pipeline'
    parse_method="auto",  # The method for parsing PDF, default is 'auto'
    p_formula_enable=True,  # Enable formula parsing
    p_table_enable=True,  # Enable table parsing
    server_url=None,  # Server URL for vlm-sglang-client backend
    server_headers=None,  # Optional headers (e.g., Authorization) for vlm-http-client backend
    f_draw_layout_bbox=True,  # Whether to draw layout bounding boxes
    f_draw_span_bbox=True,  # Whether to draw span bounding boxes
    f_dump_md=False,  # Whether to dump markdown files
    f_dump_middle_json=False,  # Whether to dump middle JSON files
    f_dump_model_output=False,  # Whether to dump model output files
    f_dump_debug_intermediate=False,  # Whether to dump intermediate debug payloads
    f_log_debug_intermediate=False,  # Whether to log intermediate debug payloads
    f_dump_orig_pdf=False,  # Whether to dump original PDF files
    f_dump_content_list=False,  # Whether to dump content list files
    f_make_md_mode=MakeMode.MM_MD,  # The mode for making markdown content, default is MM_MD
    start_page_id=0,  # Start page ID for parsing, default is 0
    end_page_id=None,  # End page ID for parsing, default is None (parse all pages until the end of the document)
    return_content_list=True,  # Whether to return content lists
):  # Store all content lists if returning them

    last_content_list = None
    last_local_md_dir = None

    if backend == "pipeline":
        for idx, pdf_bytes in enumerate(pdf_bytes_list):
            new_pdf_bytes = convert_pdf_bytes_to_bytes_by_pypdfium2(
                pdf_bytes, start_page_id, end_page_id
            )
            pdf_bytes_list[idx] = new_pdf_bytes

        infer_results, all_image_lists, all_pdf_docs, lang_list, ocr_enabled_list = (
            pipeline_doc_analyze(
                pdf_bytes_list,
                p_lang_list,
                parse_method=parse_method,
                formula_enable=p_formula_enable,
                table_enable=p_table_enable,
            )
        )

        for idx, model_list in enumerate(infer_results):
            model_json = copy.deepcopy(model_list)
            pdf_file_name = pdf_file_names[idx]
            local_image_dir, local_md_dir = prepare_env(output_dir, pdf_file_name, parse_method)
            image_writer, md_writer = FileBasedDataWriter(local_image_dir), FileBasedDataWriter(
                local_md_dir
            )
            last_local_md_dir = local_md_dir

            images_list = all_image_lists[idx]
            pdf_doc = all_pdf_docs[idx]
            _lang = lang_list[idx]
            _ocr_enable = ocr_enabled_list[idx]
            middle_json = pipeline_result_to_middle_json(
                model_list, images_list, pdf_doc, image_writer, _lang, _ocr_enable, p_formula_enable
            )

            pdf_info = middle_json["pdf_info"]

            pdf_bytes = pdf_bytes_list[idx]
            if f_draw_layout_bbox:
                draw_layout_bbox(pdf_info, pdf_bytes, local_md_dir, f"{pdf_file_name}_layout.pdf")

            if f_draw_span_bbox:
                draw_span_bbox(pdf_info, pdf_bytes, local_md_dir, f"{pdf_file_name}_span.pdf")

            if f_dump_orig_pdf:
                md_writer.write(
                    f"{pdf_file_name}_origin.pdf",
                    pdf_bytes,
                )

            if f_dump_md:
                image_dir = str(os.path.basename(local_image_dir))
                md_content_str = pipeline_union_make(pdf_info, f_make_md_mode, image_dir)
                md_writer.write_string(
                    f"{pdf_file_name}.md",
                    md_content_str,
                )

            # Generate content list if needed for saving or returning
            content_list = None
            if f_dump_content_list or return_content_list:
                image_dir = str(os.path.basename(local_image_dir))
                content_list = pipeline_union_make(pdf_info, MakeMode.CONTENT_LIST, image_dir)
                last_content_list = content_list

                if f_dump_content_list:
                    md_writer.write_string(
                        f"{pdf_file_name}_content_list.json",
                        json.dumps(content_list, ensure_ascii=False, indent=4),
                    )

            if f_dump_middle_json:
                md_writer.write_string(
                    f"{pdf_file_name}_middle.json",
                    json.dumps(middle_json, ensure_ascii=False, indent=4),
                )

            if f_dump_model_output:
                md_writer.write_string(
                    f"{pdf_file_name}_model.json",
                    json.dumps(model_json, ensure_ascii=False, indent=4),
                )

            if f_dump_debug_intermediate or f_log_debug_intermediate:
                debug_payload = {
                    "pdf_file_name": pdf_file_name,
                    "backend": "pipeline",
                    "parse_method": parse_method,
                    "lang": _lang,
                    "ocr_enabled": _ocr_enable,
                    "model_output": model_json,
                    "middle_json": middle_json,
                    "content_list": content_list,
                }
                _output_debug_payload(
                    md_writer,
                    f"{pdf_file_name}_debug.json",
                    debug_payload,
                    dump=f_dump_debug_intermediate,
                    log=f_log_debug_intermediate,
                )

            logger.info(f"local output dir is {local_md_dir}")
    else:
        if backend.startswith("vlm-"):
            backend = backend[4:]

        f_draw_span_bbox = False
        parse_method = "vlm"
        server_urls = _resolve_server_urls(server_url)
        resolved_headers = _resolve_server_headers(server_headers)
        assigned_urls = [_next_server_url(server_urls) for _ in range(len(pdf_bytes_list))]
        for idx, pdf_bytes in enumerate(pdf_bytes_list):
            pdf_file_name = pdf_file_names[idx]
            pdf_bytes = convert_pdf_bytes_to_bytes_by_pypdfium2(
                pdf_bytes, start_page_id, end_page_id
            )
            local_image_dir, local_md_dir = prepare_env(output_dir, pdf_file_name, parse_method)
            image_writer, md_writer = FileBasedDataWriter(local_image_dir), FileBasedDataWriter(
                local_md_dir
            )
            last_local_md_dir = local_md_dir
            logger.debug(
                "Dispatching %s to backend '%s' via %s", pdf_file_name, backend, assigned_urls[idx]
            )
            middle_json, infer_result = vlm_doc_analyze(
                pdf_bytes,
                image_writer=image_writer,
                backend=backend,
                server_url=assigned_urls[idx],
                server_headers=resolved_headers,
            )

            pdf_info = middle_json["pdf_info"]

            if f_draw_layout_bbox:
                draw_layout_bbox(pdf_info, pdf_bytes, local_md_dir, f"{pdf_file_name}_layout.pdf")

            if f_draw_span_bbox:
                draw_span_bbox(pdf_info, pdf_bytes, local_md_dir, f"{pdf_file_name}_span.pdf")

            if f_dump_orig_pdf:
                md_writer.write(
                    f"{pdf_file_name}_origin.pdf",
                    pdf_bytes,
                )

            if f_dump_md:
                image_dir = str(os.path.basename(local_image_dir))
                md_content_str = vlm_union_make(pdf_info, f_make_md_mode, image_dir)
                md_writer.write_string(
                    f"{pdf_file_name}.md",
                    md_content_str,
                )

            # Generate content list if needed for saving or returning
            content_list = None
            if f_dump_content_list or return_content_list:
                image_dir = str(os.path.basename(local_image_dir))
                content_list = vlm_union_make(pdf_info, MakeMode.CONTENT_LIST, image_dir)
                last_content_list = content_list

                if f_dump_content_list:
                    md_writer.write_string(
                        f"{pdf_file_name}_content_list.json",
                        json.dumps(content_list, ensure_ascii=False, indent=4),
                    )

            if f_dump_middle_json:
                md_writer.write_string(
                    f"{pdf_file_name}_middle.json",
                    json.dumps(middle_json, ensure_ascii=False, indent=4),
                )

            if f_dump_model_output:
                model_output = ("\n" + "-" * 50 + "\n").join(infer_result)
                md_writer.write_string(
                    f"{pdf_file_name}_model_output.txt",
                    model_output,
                )

            if f_dump_debug_intermediate or f_log_debug_intermediate:
                debug_payload = {
                    "pdf_file_name": pdf_file_name,
                    "backend": f"vlm-{backend}",
                    "server_url": assigned_urls[idx],
                    "parse_method": parse_method,
                    "infer_result": infer_result,
                    "middle_json": middle_json,
                    "content_list": content_list,
                }
                _output_debug_payload(
                    md_writer,
                    f"{pdf_file_name}_debug.json",
                    debug_payload,
                    dump=f_dump_debug_intermediate,
                    log=f_log_debug_intermediate,
                )

            logger.info(f"local output dir is {local_md_dir}")

    # Return content lists if requested
    if return_content_list:
        return last_content_list, last_local_md_dir


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
    dump_debug_intermediate=False,  # Dump intermediate payloads for debugging
    log_debug_intermediate=False,  # Log intermediate payloads for debugging
    return_txt=False,  # Retained for API compatibility; plain text is composed upstream
):
    """
    Parameter description:
    path_list: List of document paths to be parsed, can be PDF or image files.
    output_dir: Output directory for storing parsing results.
    lang: Language option, default from MINERU_DEFAULT_LANG (fallback 'ch'); optional values include['ch', 'ch_server', 'ch_lite', 'en', 'korean', 'japan', 'chinese_cht', 'ta', 'te', 'ka']。
        Input the languages in the pdf (if known) to improve OCR accuracy.  Optional.
        Adapted only for the case where the backend is set to "pipeline"
    backend: the backend for parsing pdf (default from MINERU_DEFAULT_BACKEND, fallback 'vlm-http-client'):
    backend options:
        pipeline: More general.
        vlm-transformers: More general.
        vlm-vllm-engine: Faster (vLLM engine).
        vlm-lmdeploy-engine: Faster (LMDeploy engine).
        vlm-http-client: Faster (HTTP client).
        vlm-mlx-engine: Apple silicon local engine.
    method: the method for parsing pdf (default from MINERU_DEFAULT_METHOD, fallback 'auto'):
        auto: Automatically determine the method based on the file type.
        txt: Use text extraction method.
        ocr: Use OCR method for image-based PDFs.
        Without method specified, 'auto' will be used by default.
        Adapted only for the case where the backend is set to "pipeline".
    server_url: A single URL, an iterable of URLs, or a comma/JSON-separated string pointing to VLM servers.
        When omitted, the service checks the environment variables
        MINERU_VLLM_SERVER_URLS / MINERU_VLM_SERVER_URLS (and singular forms) before
        falling back to http://127.0.0.1:30000.
    server_headers: Optional dict of headers (e.g., Authorization). When omitted, the service builds
        Authorization automatically from MINERU_VLLM_AUTH_HEADER or MINERU_VLLM_API_KEY.
    dump_debug_intermediate: When True, writes out intermediate parsing payloads for debugging.
    log_debug_intermediate: When True, logs intermediate parsing payloads for debugging.
    return_txt: When True, callers are expected to compose a plain-text string from parsed chunks.
    """
    try:
        effective_backend = (backend or "").strip() or _env_default_backend()
        effective_lang = (lang or "").strip() or _env_default_lang()
        effective_method = (method or "").strip() or _env_default_method()
        file_name_list = []
        pdf_bytes_list = []
        lang_list = []
        for path in path_list:
            file_name = str(Path(path).stem)
            pdf_bytes = read_fn(path)
            file_name_list.append(file_name)
            pdf_bytes_list.append(pdf_bytes)
            lang_list.append(effective_lang)
        response = do_parse(
            output_dir=output_dir,
            pdf_file_names=file_name_list,
            pdf_bytes_list=pdf_bytes_list,
            p_lang_list=lang_list,
            backend=effective_backend,
            parse_method=effective_method,
            server_url=server_url,
            server_headers=server_headers,
            start_page_id=start_page_id,
            end_page_id=end_page_id,
            f_dump_debug_intermediate=dump_debug_intermediate,
            f_log_debug_intermediate=log_debug_intermediate,
        )
        if response is None:
            return None, None, None

        content_list, output_dir_path = response
        return content_list, output_dir_path, None
    except Exception as e:
        logger.exception(e)


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
    # parse_doc(
    #     doc_path_list,
    #     output_dir,
    #     backend="vlm-http-client",
    #     server_url=["http://127.0.0.1:30000", "http://127.0.0.1:30001"],
    # )  # faster(client) with multi-backend round robin.
