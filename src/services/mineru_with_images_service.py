import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Sequence, Tuple, Union

from loguru import logger

from src.models.models import ResponseWithPageNum, TextElementWithPageNum
from src.services.mineru_service_full import parse_doc
from src.utils.text_output import build_plain_text
from src.services.vision_service import (
    VisionModel,
    VisionProvider,
    vision_completion,
)


def _env_context_window() -> int:
    raw_value = os.getenv("VISION_CONTEXT_WINDOW")
    if raw_value is None:
        return 2
    try:
        parsed = int(raw_value)
        return max(parsed, 0)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid VISION_CONTEXT_WINDOW=%s, falling back to default (2).",
            raw_value,
        )
        return 2


CONTEXT_WINDOW = _env_context_window()


def _env_vision_batch_size() -> int:
    raw_value = os.getenv("VISION_BATCH_SIZE")
    if raw_value is None:
        return 3
    try:
        parsed = int(raw_value)
        return max(parsed, 1)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid VISION_BATCH_SIZE=%s, falling back to default (3).",
            raw_value,
        )
        return 3


VISION_BATCH_SIZE = _env_vision_batch_size()


def clean_text(text: str) -> str:
    """Clean text to remove surrogate characters and other problematic encodings."""
    if not text:
        return ""
    text = re.sub(r"[\ud800-\udfff]", "", text)
    try:
        return text.encode("utf-8", errors="ignore").decode("utf-8")
    except UnicodeError:
        return text.encode("ascii", errors="ignore").decode("ascii")


def image_text(item: Dict) -> str:
    captions = item.get("img_caption") or []
    footnotes = item.get("img_footnote") or []
    text = "\n".join([*captions, *footnotes])
    return clean_text(text)


def table_text(item: Dict) -> str:
    text = "\n".join(
        filter(
            None,
            [
                "\n".join(item.get("table_caption", [])),
                item.get("table_body", ""),
                "\n".join(item.get("table_footnote", [])),
            ],
        )
    )
    return clean_text(text)


def list_text(item: Dict) -> str:
    items = item.get("list_items") or []
    if items:
        return clean_text("\n".join(items))
    return clean_text(item.get("text", ""))


def _format_context_line(page_idx: int, text: str, is_title: bool = False) -> str:
    if not text:
        return ""
    prefixes: List[str] = []
    if page_idx is not None and page_idx >= 0:
        prefixes.append(f"[Page {int(page_idx) + 1}]")
    chunk_marker = "[ChunkType=Title]" if is_title else "[ChunkType=Body]"
    prefixes.append(chunk_marker)
    if prefixes:
        return f"{' '.join(prefixes)} {text}"
    return text


def get_prev_context(context_elements: List[Dict], cur_idx: int, n: int) -> str:
    """获取前 n 个非空上下文块文本，倒序拼接。"""
    if cur_idx is None or cur_idx < 0 or not context_elements:
        return ""
    res: List[str] = []
    j = cur_idx - 1
    while j >= 0 and len(res) < n:
        if j < len(context_elements):
            block = context_elements[j]
            text = block["text"].strip()
            if text:
                formatted = _format_context_line(
                    block.get("page_idx", -1),
                    text,
                    block.get("is_title", False),
                )
                res.insert(0, formatted)
        j -= 1
    return "\n".join(res)


def get_next_context(context_elements: List[Dict], cur_idx: int, n: int) -> str:
    """获取后 n 个非空上下文块文本，正序拼接。"""
    if cur_idx is None or not context_elements:
        return ""
    res: List[str] = []
    j = cur_idx + 1
    while j < len(context_elements) and len(res) < n:
        if j >= 0:
            block = context_elements[j]
            text = block["text"].strip()
            if text:
                formatted = _format_context_line(
                    block.get("page_idx", -1),
                    text,
                    block.get("is_title", False),
                )
                res.append(formatted)
        j += 1
    return "\n".join(res)


def _build_context_blocks(content_list: List[Dict]) -> List[Dict]:
    context_blocks: List[Dict] = []
    for item in content_list:
        block: Optional[Dict] = None
        if item["type"] in ("text", "equation"):
            if item.get("text", "").strip():
                is_title = bool(item.get("text_level") is not None)
                block = {
                    "type": item["type"],
                    "text": clean_text(item["text"]),
                    "page_idx": item.get("page_idx", -1),
                    "orig_item": item,
                    "is_title": is_title,
                }
        elif item["type"] == "list":
            list_txt = list_text(item)
            if list_txt.strip():
                block = {
                    "type": "list",
                    "text": list_txt,
                    "page_idx": item.get("page_idx", -1),
                    "orig_item": item,
                    "is_title": bool(item.get("text_level") is not None),
                }
        elif item["type"] == "table":
            table_txt = table_text(item)
            if table_txt.strip():
                block = {
                    "type": "table",
                    "text": table_txt,
                    "page_idx": item.get("page_idx", -1),
                    "orig_item": item,
                    "is_title": False,
                }
        elif item["type"] == "image":
            img_txt = image_text(item)
            if img_txt.strip():
                block = {
                    "type": "image_caption",
                    "text": img_txt,
                    "page_idx": item.get("page_idx", -1),
                    "orig_item": item,
                    "is_title": False,
                }
        if block:
            context_blocks.append(block)
    return context_blocks


def _reindex_blocks(blocks: List[Dict]) -> Dict[int, int]:
    return {
        id(block.get("orig_item")): idx
        for idx, block in enumerate(blocks)
        if block.get("orig_item") is not None
    }


def _resolve_context_windows(
    working_blocks: List[Dict], cur_idx: Optional[int], item: Dict
) -> Dict[str, str]:
    before_ctx = ""
    after_ctx = ""
    if not working_blocks:
        return {"before": before_ctx, "after": after_ctx}

    if cur_idx is not None and 0 <= cur_idx < len(working_blocks):
        before_ctx = get_prev_context(working_blocks, cur_idx, n=CONTEXT_WINDOW)
        after_ctx = get_next_context(working_blocks, cur_idx, n=CONTEXT_WINDOW)
        return {"before": before_ctx, "after": after_ctx}

    current_page = item.get("page_idx", -1)
    ref_idx: Optional[int] = None
    for idx, block in enumerate(working_blocks):
        block_page = block.get("page_idx", -1)
        if block_page <= current_page:
            ref_idx = idx
        else:
            break

    if ref_idx is not None:
        before_ctx = get_prev_context(working_blocks, ref_idx + 1, n=CONTEXT_WINDOW)
        after_ctx = get_next_context(working_blocks, ref_idx, n=CONTEXT_WINDOW)
    else:
        after_ctx = get_next_context(working_blocks, -1, n=CONTEXT_WINDOW)
    return {"before": before_ctx, "after": after_ctx}


def _build_vision_prompt(item: Dict, contexts: Dict[str, str]) -> Tuple[str, List[Tuple[str, str]]]:
    captions = "\n".join(item.get("img_caption") or [])
    footnotes = "\n".join(item.get("img_footnote") or [])
    prompt_parts: List[Tuple[str, str]] = []
    page_idx = item.get("page_idx", -1)
    page_suffix = f" (Page {int(page_idx) + 1})" if page_idx is not None and page_idx >= 0 else ""
    if captions.strip():
        prompt_parts.append((f"Image caption{page_suffix}", captions))
    if footnotes.strip():
        prompt_parts.append((f"Image footnote{page_suffix}", footnotes))
    if contexts["before"].strip():
        prompt_parts.append(("Context before", contexts["before"]))
    if contexts["after"].strip():
        prompt_parts.append(("Context after", contexts["after"]))
    prompt_lines = [f"{label}: {value}" for label, value in prompt_parts]
    return "\n".join(prompt_lines), prompt_parts


def _log_vision_prompt(
    page_number: int, contexts: Dict[str, str], prompt_parts: Sequence[Tuple[str, str]]
) -> None:
    before_ctx = contexts.get("before", "").strip() or "<empty>"
    after_ctx = contexts.get("after", "").strip() or "<empty>"
    logger.debug(
        "Vision context for page {page_number}\n  before: {before}\n  after: {after}",
        page_number=page_number,
        before=before_ctx,
        after=after_ctx,
    )
    if prompt_parts:
        formatted = "\n".join(f"  {label}: {value}" for label, value in prompt_parts)
        logger.info(f"Vision prompt payload for page {page_number}:\n{formatted}")
    else:
        logger.info(f"Vision prompt payload for page {page_number}: <empty>")


def parse_with_images(
    file_path: str,
    *,
    chunk_type: bool = False,
    backend: Optional[str] = None,
    vision_provider: Optional[VisionProvider] = None,
    vision_model: Optional[Union[VisionModel, str]] = None,
    vision_prompt: Optional[str] = None,
    return_txt: bool = False,
) -> Tuple[List[Dict[str, object]], Optional[str]]:
    """Run MinerU parsing (GPU scheduler friendly) then enrich figures via multimodal vision."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        content_list, output_dir, _ = parse_doc([file_path], tmp_dir, backend=backend)

        context_blocks = _build_context_blocks(content_list)
        item_to_block_idx = _reindex_blocks(context_blocks)

        prompt_override = (
            vision_prompt.strip() if vision_prompt is not None and vision_prompt.strip() else None
        )

        image_jobs: List[Dict[str, object]] = []
        for item in content_list:
            if not (item["type"] == "image" and item.get("img_path") and item["img_path"].strip()):
                continue

            img_path = os.path.join(output_dir, item["img_path"])
            page_number = int(item.get("page_idx", 0)) + 1
            if not os.path.exists(img_path):
                logger.info(f"Skipping image on page {page_number}: file not found at {img_path}")
                continue

            cur_idx = item_to_block_idx.get(id(item))
            contexts = _resolve_context_windows(context_blocks, cur_idx, item)
            context_payload, prompt_parts = _build_vision_prompt(item, contexts)
            _log_vision_prompt(page_number, contexts, prompt_parts)

            logger.info(
                f"Queueing image {len(image_jobs) + 1} "
                f"(page {page_number}, batch size {VISION_BATCH_SIZE})..."
            )

            image_jobs.append(
                {
                    "item": item,
                    "page_number": page_number,
                    "is_title": bool(item.get("text_level") is not None),
                    "img_path": img_path,
                    "context_payload": context_payload,
                    "base_text": image_text(item),
                }
            )

        for idx, job in enumerate(image_jobs, start=1):
            job["seq"] = idx

        total_images = len(image_jobs)
        image_results: Dict[int, Dict[str, object]] = {}
        image_count = 0

        for start in range(0, total_images, VISION_BATCH_SIZE):
            batch = image_jobs[start : start + VISION_BATCH_SIZE]
            if not batch:
                continue

            logger.info(
                f"Dispatching batch of {len(batch)} images "
                f"(total={total_images}, processed={image_count})..."
            )

            with ThreadPoolExecutor(max_workers=VISION_BATCH_SIZE) as executor:
                futures = [
                    executor.submit(
                        vision_completion,
                        job["img_path"],
                        job["context_payload"],
                        prompt_override,
                        vision_provider,
                        vision_model,
                    )
                    for job in batch
                ]

                for job, future in zip(batch, futures):
                    seq = job["seq"]
                    page_number = job["page_number"]
                    base_text = job["base_text"]
                    is_title = job["is_title"]

                    logger.info(f"Image path: {job['img_path']}")
                    logger.info(
                        f"Calling vision completion for image {seq}/{total_images} "
                        f"(batch size {VISION_BATCH_SIZE})..."
                    )
                    try:
                        vision_result = clean_text(future.result())
                        logger.info(f"✓ Vision analysis complete for image {seq}/{total_images}")

                        vision_summary = vision_result.strip()
                        if base_text and vision_summary:
                            combined_text = f"{base_text}\nImage Description: {vision_result}"
                        elif base_text:
                            combined_text = base_text
                        elif vision_summary:
                            combined_text = f"Image Description: {vision_result}"
                        else:
                            combined_text = ""

                        if combined_text:
                            chunk = {"text": combined_text, "page_number": page_number}
                            if chunk_type and is_title:
                                chunk["type"] = "title"
                            image_results[id(job["item"])] = chunk
                    except Exception as exc:  # noqa: BLE001 - vision call can fail
                        logger.info(f"Error processing image {seq}/{total_images}: {str(exc)}")
                        if base_text.strip():
                            chunk = {"text": base_text, "page_number": page_number}
                            if chunk_type and is_title:
                                chunk["type"] = "title"
                            image_results[id(job["item"])] = chunk

            image_count += len(batch)

        logger.info(f"Completed processing all {total_images} images")

        result_items: List[Dict[str, object]] = []
        for item in content_list:
            page_number = int(item.get("page_idx", 0)) + 1
            is_title = item.get("type") == "text" and item.get("text_level") is not None

            if item["type"] == "image" and item.get("img_path") and item["img_path"].strip():
                chunk = image_results.get(id(item))
                if chunk:
                    result_items.append(chunk)
            elif item["type"] in ("header", "footer"):
                if not chunk_type:
                    continue
                header_txt = clean_text(item.get("text", ""))
                if header_txt.strip():
                    chunk = {
                        "text": header_txt,
                        "page_number": page_number,
                        "type": item["type"],
                    }
                    result_items.append(chunk)

            elif item["type"] == "list":
                list_txt = list_text(item)
                if list_txt.strip():
                    chunk = {"text": list_txt, "page_number": page_number}
                    if chunk_type and is_title:
                        chunk["type"] = "title"
                    result_items.append(chunk)

            elif item["type"] in ("text", "equation") and item.get("text", "").strip():
                chunk = {"text": clean_text(item["text"]), "page_number": page_number}
                if chunk_type and is_title:
                    chunk["type"] = "title"
                result_items.append(chunk)
            elif item["type"] == "table" and (
                item.get("table_caption") or item.get("table_body") or item.get("table_footnote")
            ):
                chunk = {"text": table_text(item), "page_number": page_number}
                if chunk_type and is_title:
                    chunk["type"] = "title"
                result_items.append(chunk)
            elif (
                item["type"] == "image"
                and (item.get("img_caption") or item.get("img_footnote"))
                and not (item.get("img_path") and item["img_path"].strip())
            ):
                img_txt = image_text(item)
                if img_txt.strip():
                    chunk = {"text": img_txt, "page_number": page_number}
                    if chunk_type and is_title:
                        chunk["type"] = "title"
                    result_items.append(chunk)

        txt_text = build_plain_text(result_items) if return_txt else None
        return result_items, txt_text


def mineru_service(
    file_path: str, *, chunk_type: bool = False, return_txt: bool = False
) -> ResponseWithPageNum:
    payload, txt_text = parse_with_images(
        file_path,
        chunk_type=chunk_type,
        return_txt=return_txt,
    )
    items = [
        TextElementWithPageNum(
            text=entry["text"],
            page_number=int(entry["page_number"]),
            type=entry.get("type"),
        )
        for entry in payload
    ]
    return ResponseWithPageNum(result=items, txt=txt_text)
