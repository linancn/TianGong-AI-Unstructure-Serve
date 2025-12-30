from typing import Optional

from src.config.config import OPENAI_API_KEY
from src.services.vision_service_openai_compatible import (
    OpenAICompatibleClientPool,
    vision_completion_openai_compatible,
)

DEFAULT_VISION_MODEL = "gpt-5-mini"
_CLIENT_POOL = OpenAICompatibleClientPool(api_key=OPENAI_API_KEY)


def vision_completion_openai(
    image_path: str,
    context: str = "",
    model: Optional[str] = None,
    prompt: Optional[str] = None,
) -> str:
    if not _CLIENT_POOL.has_clients():
        raise RuntimeError("OpenAI vision client is not configured. Set OPENAI_API_KEY.")
    return vision_completion_openai_compatible(
        image_path,
        context=context,
        model=model,
        prompt=prompt,
        default_model=DEFAULT_VISION_MODEL,
        client_pool=_CLIENT_POOL,
    )
