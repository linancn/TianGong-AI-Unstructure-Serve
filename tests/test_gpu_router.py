from collections import deque


def test_gpu_status_endpoint(client, monkeypatch):
    fake_payload = {"gpus": [{"gpu_id": "0", "pending": 3}], "total_pending": 3}

    class DummyScheduler:
        def __init__(self, snapshots):
            self._snapshots = deque(snapshots)

        def status(self):
            return self._snapshots[0]

    monkeypatch.setattr(
        "src.routers.gpu_router.scheduler",
        DummyScheduler([fake_payload]),
        raising=True,
    )

    response = client.get("/gpu/status")
    assert response.status_code == 200
    assert response.json() == fake_payload
