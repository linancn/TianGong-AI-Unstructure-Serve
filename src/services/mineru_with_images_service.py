import os
import re
import tempfile
from typing import Dict, List, Optional

from loguru import logger

from src.models.models import ResponseWithPageNum, TextElementWithPageNum
from src.services.mineru_service_full import parse_doc
from src.services.vision_service import vision_completion


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


def get_prev_context(context_elements: List[Dict], cur_idx: int, n: int = 2) -> str:
    """获取前 n 个非空上下文块文本，倒序拼接。"""
    if cur_idx is None or cur_idx < 0 or not context_elements:
        return ""
    res: List[str] = []
    j = cur_idx - 1
    while j >= 0 and len(res) < n:
        if j < len(context_elements):
            text = context_elements[j]["text"].strip()
            if text:
                res.insert(0, text)
        j -= 1
    return "\n".join(res)


def get_next_context(context_elements: List[Dict], cur_idx: int, n: int = 2) -> str:
    """获取后 n 个非空上下文块文本，正序拼接。"""
    if cur_idx is None or not context_elements:
        return ""
    res: List[str] = []
    j = cur_idx + 1
    while j < len(context_elements) and len(res) < n:
        if j >= 0:
            text = context_elements[j]["text"].strip()
            if text:
                res.append(text)
        j += 1
    return "\n".join(res)


def _build_context_blocks(content_list: List[Dict]) -> List[Dict]:
    context_blocks: List[Dict] = []
    for item in content_list:
        block: Optional[Dict] = None
        if item["type"] in ("text", "equation"):
            if item.get("text", "").strip():
                block = {
                    "type": item["type"],
                    "text": clean_text(item["text"]),
                    "page_idx": item.get("page_idx", -1),
                    "orig_item": item,
                }
        elif item["type"] == "table":
            table_txt = table_text(item)
            if table_txt.strip():
                block = {
                    "type": "table",
                    "text": table_txt,
                    "page_idx": item.get("page_idx", -1),
                    "orig_item": item,
                }
        elif item["type"] == "image":
            img_txt = image_text(item)
            if img_txt.strip():
                block = {
                    "type": "image_caption",
                    "text": img_txt,
                    "page_idx": item.get("page_idx", -1),
                    "orig_item": item,
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
        before_ctx = get_prev_context(working_blocks, cur_idx, n=2)
        after_ctx = get_next_context(working_blocks, cur_idx, n=2)
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
        before_ctx = get_prev_context(working_blocks, ref_idx + 1, n=2)
        after_ctx = get_next_context(working_blocks, ref_idx, n=2)
    else:
        after_ctx = get_next_context(working_blocks, -1, n=2)
    return {"before": before_ctx, "after": after_ctx}


def _build_vision_prompt(item: Dict, contexts: Dict[str, str]) -> str:
    captions = "\n".join(item.get("img_caption") or [])
    footnotes = "\n".join(item.get("img_footnote") or [])
    prompt_parts: List[str] = []
    if captions.strip():
        prompt_parts.append(f"Image caption: {captions}")
    if footnotes.strip():
        prompt_parts.append(f"Image footnote: {footnotes}")
    if contexts["before"].strip():
        prompt_parts.append(f"Context before: {contexts['before']}")
    if contexts["after"].strip():
        prompt_parts.append(f"Context after: {contexts['after']}")
    return "\n".join(prompt_parts)


def _log_vision_context(item: Dict, contexts: Dict[str, str], prompt: str) -> None:
    page_number = int(item.get("page_idx", 0)) + 1
    before_ctx = contexts["before"] or "<empty>"
    after_ctx = contexts["after"] or "<empty>"
    logger.info(f"Vision context for page {page_number} | before: {before_ctx} | after: {after_ctx}")
    if prompt:
        logger.info(f"Vision prompt composed for page {page_number}:\n{prompt}")


def parse_with_images(file_path: str) -> List[Dict[str, object]]:
    """Run MinerU parsing (GPU scheduler friendly) then enrich figures via multimodal vision."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        content_list, output_dir = parse_doc([file_path], tmp_dir)

        working_blocks = _build_context_blocks(content_list)
        item_to_block_idx = _reindex_blocks(working_blocks)

        result_items: List[Dict[str, object]] = []
        total_images = sum(
            1
            for item in content_list
            if item["type"] == "image"
            and item.get("img_path")
            and item["img_path"].strip()
        )
        image_count = 0

        for item in content_list:
            cur_idx = item_to_block_idx.get(id(item))
            page_number = int(item.get("page_idx", 0)) + 1

            if (
                item["type"] == "image"
                and item.get("img_path")
                and item["img_path"].strip()
            ):
                img_path = os.path.join(output_dir, item["img_path"])
                if not os.path.exists(img_path):
                    logger.info(f"Skipping image on page {page_number}: file not found at {img_path}")
                    continue

                image_count += 1
                logger.info(
                    f"Processing image {image_count}/{total_images} on page {page_number}..."
                )

                contexts = _resolve_context_windows(working_blocks, cur_idx, item)
                prompt = _build_vision_prompt(item, contexts)
                _log_vision_context(item, contexts, prompt)

                logger.info(f"Image path: {img_path}")
                logger.info(f"Calling vision completion for image {image_count}/{total_images}...")

                try:
                    vision_result = clean_text(vision_completion(img_path, prompt))
                    logger.info(f"✓ Vision analysis complete for image {image_count}/{total_images}")

                    vision_block = {
                        "type": "image_vision_desc",
                        "text": vision_result,
                        "page_idx": item.get("page_idx", -1),
                        "orig_item": item,
                    }
                    insert_idx = cur_idx + 1 if cur_idx is not None else len(working_blocks)
                    working_blocks.insert(insert_idx, vision_block)
                    item_to_block_idx = _reindex_blocks(working_blocks)

                    base_text = image_text(item)
                    if base_text:
                        combined_text = f"{base_text}\nImage Description: {vision_result}"
                    else:
                        combined_text = f"Image Description: {vision_result}"
                    result_items.append(
                        {
                            "text": combined_text,
                            "page_number": page_number,
                        }
                    )
                except Exception as exc:  # noqa: broad-except - vision call can fail
                    logger.info(
                        f"Error processing image {image_count}/{total_images}: {str(exc)}"
                    )
                    img_txt = image_text(item)
                    if img_txt.strip():
                        result_items.append({"text": img_txt, "page_number": page_number})

            elif item["type"] in ("text", "equation") and item.get("text", "").strip():
                result_items.append(
                    {"text": clean_text(item["text"]), "page_number": page_number}
                )
            elif item["type"] == "table" and (
                item.get("table_caption") or item.get("table_body") or item.get("table_footnote")
            ):
                result_items.append({"text": table_text(item), "page_number": page_number})
            elif (
                item["type"] == "image"
                and (item.get("img_caption") or item.get("img_footnote"))
                and not (item.get("img_path") and item["img_path"].strip())
            ):
                img_txt = image_text(item)
                if img_txt.strip():
                    result_items.append({"text": img_txt, "page_number": page_number})

    logger.info(f"Completed processing all {total_images} images")
    return result_items


def mineru_service(file_path: str) -> ResponseWithPageNum:
    payload = parse_with_images(file_path)
    items = [
        TextElementWithPageNum(text=entry["text"], page_number=int(entry["page_number"]))
        for entry in payload
    ]
    return ResponseWithPageNum(result=items)
