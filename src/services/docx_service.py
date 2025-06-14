from unstructured.partition.docx import partition_docx
from unstructured.chunking.title import chunk_by_title
from unstructured.documents.elements import CompositeElement, Table


def unstructure_docx(file_name):
    elements = partition_docx(
        filename=file_name,
        multipage_sections=True,
        infer_table_structure=True,
        include_page_breaks=False,
    )

    chunks = chunk_by_title(
        elements=elements,
        multipage_sections=True,
        combine_text_under_n_chars=0,
        new_after_n_chars=None,
        max_characters=4000,
    )

    text_list = []

    for chunk in chunks:
        if isinstance(chunk, CompositeElement):
            text = chunk.text
            if chunk.metadata.text_as_html:
                text += "\nTable Content:\n" + chunk.metadata.text_as_html
            text_list.append(text)
        elif isinstance(chunk, Table):
            if text_list:
                text_list[-1] = text_list[-1] + "\n" + chunk.metadata.text_as_html
            else:
                text_list.append(chunk.metadata.text_as_html)

    merged_list = []
    title_buffer = []

    for text in text_list:
        stripped_text = text.strip()
        if stripped_text and (
            not stripped_text.endswith(".") and not "\n" in stripped_text
        ):  # This is a title block
            title_buffer.append(stripped_text)
        else:
            if title_buffer:
                merged_title = "\n".join(title_buffer)
                merged_list.append(merged_title + "\n" + text)
                title_buffer = []
            else:
                merged_list.append(text)

    if title_buffer:
        if merged_list:
            last_text, _ = merged_list[-1]
            merged_list[-1] = last_text + "\n" + "\n".join(title_buffer)
        else:
            merged_list.append("\n".join(title_buffer))

    return merged_list
