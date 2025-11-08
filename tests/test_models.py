from src.models.models import (
    ResponseWithPageNum,
    ResponseWithoutPageNum,
    TextElementWithPageNum,
)


def test_response_with_page_num_from_result():
    response = ResponseWithPageNum.from_result([("content", 2)])
    assert len(response.result) == 1
    chunk = response.result[0]
    assert isinstance(chunk, TextElementWithPageNum)
    assert chunk.text == "content"
    assert chunk.page_number == 2


def test_response_without_page_num_from_result():
    response = ResponseWithoutPageNum.from_result(["text"])
    assert len(response.result) == 1
    assert response.result[0].text == "text"
