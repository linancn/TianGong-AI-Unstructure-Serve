import shutil
from typing import Any, Dict

from celery.utils.log import get_task_logger

from src.services.celery_app import celery_app
from src.services.mineru_task_runner import MineruTaskError, run_mineru_local_job

logger = get_task_logger(__name__)


@celery_app.task(name="mineru.parse")
def run_mineru_task(payload: Dict[str, Any]) -> dict:
    """Celery entrypoint for MinerU parsing."""
    # Copy so we can safely pop housekeeping values
    task_payload = dict(payload or {})
    workspace = task_payload.pop("workspace", None)
    try:
        return run_mineru_local_job(**task_payload)
    except MineruTaskError as exc:
        logger.warning("MinerU task validation failed: %s", exc)
        raise
    finally:
        if workspace:
            shutil.rmtree(workspace, ignore_errors=True)


@celery_app.task(name="mineru.parse_images")
def run_mineru_with_images_task(payload: Dict[str, Any]) -> dict:
    """Celery entrypoint for MinerU image-aware parsing."""
    task_payload = dict(payload or {})
    workspace = task_payload.pop("workspace", None)
    try:
        return run_mineru_local_job(pipeline="images", **task_payload)
    except MineruTaskError as exc:
        logger.warning("MinerU task validation failed: %s", exc)
        raise
    finally:
        if workspace:
            shutil.rmtree(workspace, ignore_errors=True)
