def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_health_endpoint_pretty_json(client):
    response = client.get("/health", params={"pretty": "true"})
    assert response.status_code == 200
    # FastAPI TestClient automatically parses JSON regardless of formatting, so reuse assertion
    assert response.json() == {"status": "healthy"}
    # Ensure pretty flag adds indentation to raw text payload
    assert "\n  " in response.text
