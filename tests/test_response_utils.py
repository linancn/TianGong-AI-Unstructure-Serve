from pydantic import BaseModel

from src.utils.response_utils import json_response


class DemoModel(BaseModel):
    name: str
    optional: str | None = None


def test_json_response_compact_encoding():
    response = json_response({"alpha": 1, "beta": 2}, pretty=False, status_code=201)
    assert response.status_code == 201
    assert response.media_type == "application/json"
    # Compact formatting should omit extra spaces
    assert response.body == b'{"alpha":1,"beta":2}'


def test_json_response_pretty_encoding():
    response = json_response({"alpha": 1}, pretty=True)
    assert response.status_code == 200
    assert response.body.startswith(b'{\n  "alpha": 1\n')


def test_json_response_pydantic_compact():
    payload = DemoModel(name="example")
    response = json_response(payload, pretty=False)
    # None values should be excluded and unicode preserved
    assert response.body == b'{"name":"example"}'
