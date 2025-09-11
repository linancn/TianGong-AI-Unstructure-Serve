from fastapi import APIRouter
from src.services.gpu_scheduler import scheduler

router = APIRouter()


@router.get(
    "/gpu/status",
    summary="Get GPU scheduler status",
    response_description="Current status of the GPU processing queue",
)
async def gpu_status():
    """
    Returns the current status of the GPU scheduler, including pending tasks for each GPU.
    """
    return scheduler.status()
