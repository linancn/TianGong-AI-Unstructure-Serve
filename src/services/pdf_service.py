import tempfile
import logging

from dotenv import load_dotenv
from src.services.vision_service_openai import vision_completion_openai
from unstructured.chunking.title import chunk_by_title
from unstructured.cleaners.core import clean, group_broken_paragraphs
from unstructured.documents.elements import (
    CompositeElement,
    Footer,
    Header,
    Image,
    Table,
)
from unstructured.partition.pdf import partition_pdf

load_dotenv()


def unstructure_pdf(file_name, languages=["chi_sim"], extract_images=False):
    min_image_width = 250
    min_image_height = 270

    elements = partition_pdf(
        filename=file_name,
        pdf_extract_images=extract_images,
        pdf_image_output_dir_path=tempfile.gettempdir(),
        strategy="hi_res",
        infer_table_structure=True,
        hi_res_model_name="yolox",
        languages=languages,
        ocr_agent="unstructured.partition.utils.ocr_models.paddle_ocr.OCRAgentPaddle",
        table_ocr_agent="unstructured.partition.utils.ocr_models.paddle_ocr.OCRAgentPaddle",
    )

    filtered_elements = [
        element
        for element in elements
        if not (isinstance(element, Header) or isinstance(element, Footer))
    ]

    for element in filtered_elements:
        if element.text != "":
            element.text = group_broken_paragraphs(element.text)
            element.text = clean(
                element.text,
                bullets=False,
                extra_whitespace=True,
                dashes=False,
                trailing_punctuation=False,
            )
        if extract_images:
            if isinstance(element, Image):
                point1 = element.metadata.coordinates.points[0]
                point2 = element.metadata.coordinates.points[2]
                width = abs(point2[0] - point1[0])
                height = abs(point2[1] - point1[1])
                if width >= min_image_width and height >= min_image_height:
                    element.text = vision_completion_openai(element.metadata.image_path)

    chunks = chunk_by_title(
        elements=filtered_elements,
        multipage_sections=True,
        combine_text_under_n_chars=100,
        new_after_n_chars=512,
        max_characters=4096,
    )

    text_list = []
    for chunk in chunks:
        if isinstance(chunk, CompositeElement):
            text = str(chunk.text)
            page_number = chunk.metadata.page_number
            text_list.append((text, page_number))
        elif isinstance(chunk, Table):
            if text_list:
                text_list[-1] = (
                    text_list[-1][0] + "\n" + chunk.metadata.text_as_html,
                    text_list[-1][1],
                )
            else:
                page_number = chunk.metadata.page_number
                text_list.append((chunk.metadata.text_as_html, page_number))

    return text_list


# def process_pdf(record):
#     record_id = record[0]
#     language = [record[1]]

#     text_list = unstructure_pdf(
#         pdf_name="docs/ali/" + record_id + ".pdf", languages=language
#     )

#     with open("processed_docs/ali_pickle/" + record_id + ".pdf" + ".pkl", "wb") as f:
#         pickle.dump(text_list, f)

#     text_str_list = [
#         "Page {}: {}".format(page_number, text) for text, page_number in text_list
#     ]

#     text_str = "\n----------\n".join(text_str_list)

#     with open("processed_docs/ali_txt/" + record_id + ".pdf" + ".txt", "w") as f:
#         f.write(text_str)


# def safe_process_pdf(record):
#     try:
#         return process_pdf(record)
#     except Exception as e:
#         logging.info(f"Error processing {record}: {str(e)}")
#         return None


# # record = {"id": "af183ae1-c64b-417a-a19d-bf4d9611ce90", "language": "chi_sim"}

# # safe_process_pdf(record)

# for record in records:
#     process_pdf(record)
#     cur.execute(
#         sql.SQL("UPDATE ali SET unstructure_time = %s WHERE id = %s"),
#         [datetime.now(), record[0]],
#     )
#     conn.commit()

# cur.close()
# conn.close()
# logging.info("Data unstructured successfully")
