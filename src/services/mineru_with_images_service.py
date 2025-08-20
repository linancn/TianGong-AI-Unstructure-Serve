import os
import tempfile
import logging

from src.models.models import ResponseWithPageNum, TextElementWithPageNum
from src.services.mineru_service_full import parse_doc

# from src.services.vision_service_openai import vision_completion_openai
from src.services.vision_service_genimi import vision_completion_genimi


def image_text(item):
    captions = item.get("img_caption") or []
    footnotes = item.get("img_footnote") or []
    return "\n".join([*captions, *footnotes])


def table_text(item):
    return "\n".join(
        filter(
            None,
            [
                "\n".join(item.get("table_caption", [])),
                item.get("table_body", ""),
                "\n".join(item.get("table_footnote", [])),
            ],
        )
    )


def get_prev_context(context_elements, cur_idx, n=2):
    """获取前 n 个非空上下文块文本，倒序拼接"""
    if cur_idx is None or cur_idx < 0 or not context_elements:
        return ""

    res = []
    j = cur_idx - 1
    while j >= 0 and len(res) < n:
        if j < len(context_elements):
            text = context_elements[j]["text"].strip()
            if text:
                res.insert(0, text)  # 保证顺序
        j -= 1
    return "\n".join(res)


def get_next_context(context_elements, cur_idx, n=2):
    """获取后 n 个非空上下文块文本，正序拼接"""
    if cur_idx is None or not context_elements:
        return ""

    res = []
    j = cur_idx + 1
    while j < len(context_elements) and len(res) < n:
        if j >= 0:
            text = context_elements[j]["text"].strip()
            if text:
                res.append(text)
        j += 1
    return "\n".join(res)


def mineru_service(file_path):
    with tempfile.TemporaryDirectory() as tmp_dir:
        content_list_content, output_dir = parse_doc([file_path], tmp_dir)
        # logging.info(content_list_content)

        # with open(os.path.join(tmp_dir, "content_list.json"), "w", encoding="utf-8") as f:
        #     import json

        #     json.dump(content_list_content, f, ensure_ascii=False, indent=2)

        # 预处理：把所有元素转换成"可用上下文块"
        context_blocks = []  # [{type, text, page_idx, orig_item, ...}]
        for item in content_list_content:
            block = None
            if item["type"] in ("text", "equation"):
                if item.get("text", "").strip():
                    block = {
                        "type": item["type"],
                        "text": item["text"],
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
                # 初始图片描述（未 vision 前），只收集 caption/footnote
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

        # 主处理流程
        result_items = []
        total_images = sum(
            1
            for item in content_list_content
            if item["type"] == "image"
            and "img_path" in item
            and item["img_path"]
            and item["img_path"].strip()
        )
        image_count = 0

        # 为了递推式查找/插入，构造"主流式内容块"
        # 新建一个 working_blocks 列表，后续还会不断插入图片 vision 结果
        working_blocks = context_blocks.copy()

        # mapping from original item id to index in working_blocks
        # 用于后续定位图片插入位置
        item_to_block_idx = {}
        for idx, block in enumerate(working_blocks):
            orig_item = block.get("orig_item")
            if orig_item is not None:
                item_to_block_idx[id(orig_item)] = idx

        for item in content_list_content:
            item_id = id(item)
            # 查找本item在working_blocks的索引
            cur_idx = item_to_block_idx.get(item_id, None)

            if (
                item["type"] == "image"
                and "img_path" in item
                and item["img_path"]
                and item["img_path"].strip()
            ):
                # 检查图片文件是否实际存在
                img_path = os.path.join(output_dir, item["img_path"])
                if not os.path.exists(img_path):
                    logging.info(
                        f"Skipping image on page {item['page_idx'] + 1}: file not found at {img_path}"
                    )
                    continue

                image_count += 1
                logging.info(
                    f"Processing image {image_count}/{total_images} on page {item['page_idx'] + 1}..."
                )

                # 安全的上下文查找
                before_ctx = ""
                after_ctx = ""
                if working_blocks:
                    if cur_idx is not None and 0 <= cur_idx < len(working_blocks):
                        before_ctx = get_prev_context(working_blocks, cur_idx, n=2)
                        after_ctx = get_next_context(working_blocks, cur_idx, n=2)
                    else:
                        # 如果当前item不在working_blocks中，尝试根据页面顺序找到合适的位置
                        current_page = item.get("page_idx", -1)

                        # 找到一个合适的参考位置
                        ref_idx = None
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
                            # 如果找不到合适的位置，使用开头或结尾
                            if working_blocks:
                                before_ctx = ""
                                after_ctx = get_next_context(working_blocks, -1, n=2)

                # 准备 prompt
                captions = "\n".join(item.get("img_caption") or [])
                footnotes = "\n".join(item.get("img_footnote") or [])
                prompt_parts = []
                if captions.strip():
                    prompt_parts.append(f"Image caption: {captions}")
                if footnotes.strip():
                    prompt_parts.append(f"Image footnote: {footnotes}")
                if before_ctx.strip():
                    prompt_parts.append(f"Context before: {before_ctx}")
                if after_ctx.strip():
                    prompt_parts.append(f"Context after: {after_ctx}")

                logging.info(img_path)
                logging.info("\n".join(prompt_parts))
                logging.info(f"Calling vision completion for image {image_count}/{total_images}...")

                try:
                    vision_result = vision_completion_genimi(
                        img_path,
                        "\n".join(prompt_parts),
                    )
                    logging.info(
                        f"✓ Vision analysis complete for image {image_count}/{total_images}"
                    )

                    # 将 vision 结果也插入 working_blocks，作为新的上下文块
                    vision_block = {
                        "type": "image_vision_desc",
                        "text": vision_result,
                        "page_idx": item.get("page_idx", -1),
                        "orig_item": item,
                    }

                    # 安全的插入位置计算
                    if cur_idx is not None and 0 <= cur_idx < len(working_blocks):
                        insert_idx = cur_idx + 1
                    else:
                        insert_idx = len(working_blocks)

                    working_blocks.insert(insert_idx, vision_block)

                    # 重建索引映射
                    item_to_block_idx = {
                        id(b.get("orig_item")): idx
                        for idx, b in enumerate(working_blocks)
                        if b.get("orig_item") is not None
                    }

                    # 记录最终输出
                    result_items.append(
                        TextElementWithPageNum(
                            text=f"{image_text(item)}\nImage Description: {vision_result}",
                            page_number=item["page_idx"] + 1,
                        )
                    )
                except Exception as e:
                    logging.info(f"Error processing image {image_count}/{total_images}: {str(e)}")
                    # 即使vision失败，也可以输出原始caption/footnote
                    img_txt = image_text(item)
                    if img_txt.strip():
                        result_items.append(
                            TextElementWithPageNum(
                                text=img_txt,
                                page_number=item["page_idx"] + 1,
                            )
                        )

            elif item["type"] in ("text", "equation") and item.get("text", "").strip():
                result_items.append(
                    TextElementWithPageNum(
                        text=item["text"],
                        page_number=item["page_idx"] + 1,
                    )
                )
            elif item["type"] == "table" and (
                item.get("table_caption") or item.get("table_body") or item.get("table_footnote")
            ):
                result_items.append(
                    TextElementWithPageNum(
                        text=table_text(item),
                        page_number=item["page_idx"] + 1,
                    )
                )
            elif (
                item["type"] == "image"
                and (item.get("img_caption") or item.get("img_footnote"))
                and not (item.get("img_path") and item["img_path"].strip())
            ):
                # 没有 img_path（不可 vision），但有caption/footnote
                result_items.append(
                    TextElementWithPageNum(
                        text=image_text(item),
                        page_number=item["page_idx"] + 1,
                    )
                )

    logging.info(f"Completed processing all {total_images} images")
    response = ResponseWithPageNum(result=result_items)
    return response
