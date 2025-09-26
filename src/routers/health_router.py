from fastapi import APIRouter, Depends, status

from src.utils.response_utils import json_response, pretty_response_flag

router = APIRouter()


@router.get("/health", summary="Service health check (liveness/readiness)")
async def health_check(pretty: bool = Depends(pretty_response_flag)):
    """Return service health status for readiness/liveness probes."""
    return json_response({"status": "healthy"}, pretty, status_code=status.HTTP_200_OK)
