import logging
import os
import pickle
import time
from pathlib import Path
from typing import Dict, Iterable

import requests
from dotenv import load_dotenv

load_dotenv()

API_BASE = (
    os.environ.get("TWO_STAGE_BASE")
    or os.environ.get("MINERU_TASK_BASE")
    or "http://localhost:8770"
).rstrip("/")
SUBMIT_URL = f"{API_BASE}/two_stage/task"
LOG_FILE = "celery_two_stage.log"
DEFAULT_INPUT_DIR = Path("pdfs")
DEFAULT_OUTPUT_DIR = Path("pickle")
DEFAULT_INTERVAL = float(os.environ.get("TWO_STAGE_POLL_INTERVAL", 3))
DEFAULT_TIMEOUT = float(os.environ.get("TWO_STAGE_POLL_TIMEOUT", 800))

VISION_PROVIDER = (os.environ.get("VISION_PROVIDER") or "").strip()
VISION_MODEL = (os.environ.get("VISION_MODEL") or "").strip()
VISION_PROMPT = (os.environ.get("VISION_PROMPT") or "").strip()


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


CHUNK_TYPE = _bool_env("TWO_STAGE_CHUNK_TYPE", False)
RETURN_TXT = _bool_env("TWO_STAGE_RETURN_TXT", False)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    filemode="w",
    force=True,
)


def _build_form_data() -> Dict[str, str]:
    form: Dict[str, str] = {}
    if VISION_PROVIDER:
        form["provider"] = VISION_PROVIDER
    if VISION_MODEL:
        form["model"] = VISION_MODEL
    if VISION_PROMPT:
        form["prompt"] = VISION_PROMPT
    if CHUNK_TYPE:
        form["chunk_type"] = "true"
    if RETURN_TXT:
        form["return_txt"] = "true"
    return form


def submit_task(session: requests.Session, pdf_path: Path, token: str) -> str:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    form_data = _build_form_data()
    logging.info(
        "Submitting %s with provider=%s model=%s",
        pdf_path,
        form_data.get("provider", "<default>"),
        form_data.get("model", "<default>"),
    )
    with pdf_path.open("rb") as f:
        resp = session.post(
            SUBMIT_URL,
            files={"file": f},
            data=form_data,
            headers=headers,
            timeout=120,
        )
    resp.raise_for_status()
    data = resp.json()
    task_id = data.get("task_id")
    if not task_id:
        raise RuntimeError(f"Task ID missing in response for {pdf_path}")
    logging.info("Submitted %s -> task %s", pdf_path, task_id)
    return task_id


def fetch(
    session: requests.Session,
    task_id: str,
    token: str,
    interval: float = DEFAULT_INTERVAL,
    timeout: float = DEFAULT_TIMEOUT,
):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    start = time.time()
    while True:
        resp = session.get(
            f"{API_BASE}/two_stage/task/{task_id}",
            headers=headers,
            timeout=30000,
        )
        resp.raise_for_status()
        data = resp.json()
        state = data["state"]
        if state == "SUCCESS":
            return data.get("result") or data.get("Result")
        if state in {"FAILURE", "REVOKED"}:
            raise RuntimeError(f"Task failed: {data.get('error')}")
        if time.time() - start > timeout:
            raise TimeoutError(f"Task {task_id} timeout")
        time.sleep(interval)


def iter_pdfs(input_dir: Path) -> Iterable[Path]:
    if not input_dir.exists():
        return []
    for path in input_dir.iterdir():
        if path.is_file() and path.suffix.lower() == ".pdf":
            yield path


def main() -> None:
    token = os.environ.get("FASTAPI_BEARER_TOKEN")
    if not token:
        raise RuntimeError("FASTAPI_BEARER_TOKEN not found in environment")

    input_dir = Path(os.environ.get("ESG_INPUT_DIR", DEFAULT_INPUT_DIR))
    output_dir = Path(os.environ.get("ESG_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    try:
        pdfs = [
            p for p in sorted(iter_pdfs(input_dir)) if not (output_dir / f"{p.stem}.pkl").exists()
        ]
        if not pdfs:
            logging.info("No PDFs found under %s", input_dir)
            return

        tasks: Dict[str, Path] = {}
        start_times: Dict[str, float] = {}

        for pdf_path in pdfs:
            task_id = submit_task(session, pdf_path, token)
            tasks[task_id] = pdf_path
            start_times[task_id] = time.time()

        if not tasks:
            logging.info("All PDFs already processed under %s", input_dir)
            return

        successes: Dict[str, Path] = {}
        failures: Dict[str, str] = {}

        while tasks:
            finished: Dict[str, Path] = {}
            for task_id, pdf_path in list(tasks.items()):
                try:
                    remaining = DEFAULT_TIMEOUT - (time.time() - start_times[task_id])
                    if remaining <= 0:
                        raise TimeoutError(f"Task {task_id} timeout")
                    result = fetch(
                        session,
                        task_id,
                        token,
                        interval=DEFAULT_INTERVAL,
                        timeout=remaining,
                    )
                    pickle_path = output_dir / f"{pdf_path.stem}.pkl"
                    with pickle_path.open("wb") as f:
                        pickle.dump(result, f)
                    logging.info("Wrote %s", pickle_path)
                    finished[task_id] = pdf_path
                    successes[task_id] = pdf_path
                except TimeoutError:
                    logging.error("Task %s timed out after %.1fs", task_id, DEFAULT_TIMEOUT)
                    finished[task_id] = pdf_path
                    failures[task_id] = "timeout"
                except Exception as exc:
                    logging.error("Failed to process %s (task %s): %s", pdf_path, task_id, exc)
                    finished[task_id] = pdf_path
                    failures[task_id] = str(exc)

            for task_id in finished:
                tasks.pop(task_id, None)

            if tasks:
                time.sleep(DEFAULT_INTERVAL)

        logging.info(
            "Finished two-stage enqueue: %d successes, %d failures.", len(successes), len(failures)
        )
        for task_id, err in failures.items():
            logging.error("Task %s failed: %s", task_id, err)
    finally:
        session.close()


if __name__ == "__main__":
    main()
