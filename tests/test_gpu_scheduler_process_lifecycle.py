import concurrent.futures
import importlib
import sys

import pytest


def test_gpu_scheduler_shutdown_closes_executors(monkeypatch):
    created_executors = []

    class DummyProcessPoolExecutor:
        def __init__(self, *args, **kwargs):
            self.shutdown_calls = []
            created_executors.append(self)

        def submit(self, *_args, **_kwargs):
            future = concurrent.futures.Future()
            future.set_result({"result": []})
            return future

        def shutdown(self, wait: bool = True, cancel_futures: bool = False):
            self.shutdown_calls.append({"wait": wait, "cancel_futures": cancel_futures})

    monkeypatch.setenv("GPU_IDS", "0,1")
    monkeypatch.setattr(concurrent.futures, "ProcessPoolExecutor", DummyProcessPoolExecutor)
    sys.modules.pop("src.services.gpu_scheduler", None)

    try:
        module = importlib.import_module("src.services.gpu_scheduler")
        created_executors.clear()

        scheduler = module.GPUScheduler()
        scheduler.shutdown(wait=True)
        scheduler.shutdown(wait=True)

        assert len(created_executors) == 2
        assert [executor.shutdown_calls for executor in created_executors] == [
            [{"wait": True, "cancel_futures": True}],
            [{"wait": True, "cancel_futures": True}],
        ]
        with pytest.raises(RuntimeError, match="GPU scheduler is shut down"):
            scheduler.submit("/tmp/input.pdf")
    finally:
        sys.modules.pop("src.services.gpu_scheduler", None)
