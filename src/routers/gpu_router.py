from fastapi import APIRouter, Depends
from src.services.gpu_scheduler import scheduler
from src.utils.response_utils import json_response, pretty_response_flag

router = APIRouter()


@router.get(
    "/gpu/status",
    summary="Get GPU scheduler status",
    response_description="Current status of the GPU processing queue",
)
async def gpu_status(pretty: bool = Depends(pretty_response_flag)):
    """
    Returns the current status of the GPU scheduler, including pending tasks for each GPU.
    """
    return json_response(scheduler.status(), pretty)
