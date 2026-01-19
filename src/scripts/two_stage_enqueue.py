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
MAX_ATTEMPTS = 3  # initial attempt + up to 2 retries
BATCH_SIZE = 5000

VISION_PROVIDER = (os.environ.get("VISION_PROVIDER") or "").strip()
VISION_MODEL = (os.environ.get("VISION_MODEL") or "").strip()
VISION_PROMPT = (os.environ.get("VISION_PROMPT") or "").strip()
PRIORITY = (os.environ.get("TWO_STAGE_PRIORITY") or "normal").strip().lower() or "normal"


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
    form["priority"] = PRIORITY
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
        "Submitting %s with priority=%s provider=%s model=%s",
        pdf_path,
        form_data.get("priority", "<default>"),
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


def fetch_status(
    session: requests.Session,
    task_id: str,
    token: str,
) -> Dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = session.get(
        f"{API_BASE}/two_stage/task/{task_id}",
        headers=headers,
        timeout=30000,
    )
    resp.raise_for_status()
    return resp.json()


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

    input_dir = Path(
        os.environ.get("TWO_STAGE_INPUT_DIR")
        or os.environ.get("ESG_INPUT_DIR")
        or DEFAULT_INPUT_DIR
    )
    output_dir = Path(
        os.environ.get("TWO_STAGE_OUTPUT_DIR")
        or os.environ.get("ESG_OUTPUT_DIR")
        or DEFAULT_OUTPUT_DIR
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    try:
        pdfs = [
            p for p in sorted(iter_pdfs(input_dir)) if not (output_dir / f"{p.stem}.pkl").exists()
        ]
        if not pdfs:
            logging.info("No PDFs found under %s", input_dir)
            return

        attempts: Dict[Path, int] = {}

        successes: Dict[Path, str] = {}
        failures: Dict[Path, str] = {}

        for batch_start in range(0, len(pdfs), BATCH_SIZE):
            batch = pdfs[batch_start : batch_start + BATCH_SIZE]
            tasks: Dict[str, Path] = {}
            run_start_times: Dict[str, float] = {}

            for pdf_path in batch:
                task_id = submit_task(session, pdf_path, token)
                tasks[task_id] = pdf_path
                attempts[pdf_path] = 1

            if not tasks:
                logging.info("All PDFs already processed under %s", input_dir)
                return

            while tasks:
                finished: Dict[str, Path] = {}
                for task_id, pdf_path in list(tasks.items()):
                    try:
                        data = fetch_status(session, task_id, token)
                        state = data.get("state")
                        if not state:
                            raise RuntimeError(f"Task {task_id} response missing state: {data}")
                        if state == "SUCCESS":
                            result = data.get("result") or data.get("Result")
                            if result is None:
                                raise RuntimeError(f"Task {task_id} succeeded without result")
                        elif state in {"FAILURE", "REVOKED"}:
                            raise RuntimeError(f"Task failed: {data.get('error')}")
                        else:
                            if state == "STARTED" and task_id not in run_start_times:
                                run_start_times[task_id] = time.time()
                            started_at = run_start_times.get(task_id)
                            if started_at is not None:
                                elapsed = time.time() - started_at
                                if elapsed >= DEFAULT_TIMEOUT:
                                    raise TimeoutError(f"Task {task_id} timeout")
                            continue
                        pickle_path = output_dir / f"{pdf_path.stem}.pkl"
                        with pickle_path.open("wb") as f:
                            pickle.dump(result, f)
                        logging.info("Wrote %s", pickle_path)
                        finished[task_id] = pdf_path
                        successes[pdf_path] = task_id
                    except TimeoutError:
                        error_msg = f"timeout after {DEFAULT_TIMEOUT:.1f}s"
                        logging.error("Task %s timed out for %s (%s)", task_id, pdf_path, error_msg)
                        finished[task_id] = pdf_path
                        attempts[pdf_path] = attempts.get(pdf_path, 1)
                        if attempts[pdf_path] < MAX_ATTEMPTS:
                            attempts[pdf_path] += 1
                            logging.info(
                                "Retrying %s (attempt %d/%d)...",
                                pdf_path,
                                attempts[pdf_path],
                                MAX_ATTEMPTS,
                            )
                            new_task = submit_task(session, pdf_path, token)
                            tasks[new_task] = pdf_path
                        else:
                            failures[pdf_path] = error_msg
                    except Exception as exc:
                        logging.error("Failed to process %s (task %s): %s", pdf_path, task_id, exc)
                        finished[task_id] = pdf_path
                        attempts[pdf_path] = attempts.get(pdf_path, 1)
                        if attempts[pdf_path] < MAX_ATTEMPTS:
                            attempts[pdf_path] += 1
                            logging.info(
                                "Retrying %s (attempt %d/%d)...",
                                pdf_path,
                                attempts[pdf_path],
                                MAX_ATTEMPTS,
                            )
                            new_task = submit_task(session, pdf_path, token)
                            tasks[new_task] = pdf_path
                        else:
                            failures[pdf_path] = str(exc)

                for task_id in finished:
                    tasks.pop(task_id, None)
                    run_start_times.pop(task_id, None)

                if tasks:
                    time.sleep(DEFAULT_INTERVAL)

        logging.info(
            "Finished two-stage enqueue: %d successes, %d failures.", len(successes), len(failures)
        )
        for pdf_path, err in failures.items():
            logging.error(
                "Failed after %d attempts: %s (%s)", attempts.get(pdf_path, 0), pdf_path, err
            )
    finally:
        session.close()


if __name__ == "__main__":
    main()
