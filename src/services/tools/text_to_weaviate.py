from io import StringIO
import logging
from bs4 import BeautifulSoup
import pandas as pd
import tiktoken


def num_tokens_from_string(string: str) -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.get_encoding("cl100k_base")
    num_tokens = len(encoding.encode(string))
    return num_tokens


# def merge_pickle_list(data):
#     temp = ""
#     result = []
#     for d in data:
#         if not isinstance(d, str):  # If d is not a string
#             d = str(d)  # Convert d to a string
#         if len(d) > 8000:
#             soup = BeautifulSoup(d, "html.parser")
#             tables = soup.find_all("table")
#             for table in tables:
#                 table_content = str(table)
#                 if table_content:  # If the table is not empty
#                     result.append(table_content)
#         elif num_tokens_from_string(d) < 15:
#             temp += d + " "
#         else:
#             result.append(temp + d)
#             temp = ""
#     if temp:
#         result.append(temp)

#     return result


def fix_utf8(original_list):
    cleaned_list = []
    for original_str in original_list:
        cleaned_str = original_str.replace("\ufffd", " ")
        cleaned_list.append(cleaned_str)
    return cleaned_list


def split_chunks(id: str, text_list: list, source: str):
    chunks = []
    for index, text in enumerate(text_list):
        doc_chunk_id = f"{id}_{index}"
        chunks.append({"doc_chunk_id": doc_chunk_id, "content": text, "source": source})
    return chunks


def split_dataframe_table(html_table, chunk_size=8100):
    dfs = pd.read_html(StringIO(html_table))
    if not dfs:
        return []

    df = dfs[0]
    tables = []
    sub_df = pd.DataFrame()
    token_count = 0

    for _, row in df.iterrows():
        row_html = row.to_frame().T.to_html(index=False, border=0, classes=None)
        row_token_count = num_tokens_from_string(row_html)

        if token_count + row_token_count > chunk_size and not sub_df.empty:
            sub_html = sub_df.to_html(index=False, border=0, classes=None)
            tables.append(sub_html)
            sub_df = pd.DataFrame()
            token_count = 0

        sub_df = pd.concat([sub_df, row.to_frame().T])
        token_count += row_token_count

    if not sub_df.empty:
        sub_html = sub_df.to_html(index=False, border=0, classes=None)
        tables.append(sub_html)

    return tables


def merge_pickle_list(data):
    temp = ""
    result = []
    for d in data:
        if num_tokens_from_string(d) > 8000:
            soup = BeautifulSoup(d, "html.parser")
            tables = soup.find_all("table")
            for table in tables:
                table_content = str(table)
                if num_tokens_from_string(table_content) < 8100:
                    if table_content:  # check if table_content is not empty
                        result.append(table_content)
                else:
                    try:
                        sub_tables = split_dataframe_table(table_content)
                        for sub_table in sub_tables:
                            if sub_table:
                                soup = BeautifulSoup(sub_table, "html.parser")
                                result.append(str(soup))
                    except Exception as e:
                        logging.error(f"Error splitting dataframe table: {e}")
        elif num_tokens_from_string(d) < 15:
            temp += d + " "
        else:
            result.append((temp + d))
            temp = ""
    if temp:
        result.append(temp)

    return result
