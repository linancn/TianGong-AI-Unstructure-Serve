from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health", summary="Service health check (liveness/readiness)")
async def health_check():
    """Return service health status for readiness/liveness probes."""
    return JSONResponse(content={"status": "healthy"}, status_code=status.HTTP_200_OK)
