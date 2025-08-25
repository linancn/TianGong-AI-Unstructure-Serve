import logging
import os
from typing import Literal, Optional

from src.config.config import GENIMI_API_KEY, OPENAI_API_KEY
from src.services.vision_service_genimi import vision_completion_genimi
from src.services.vision_service_openai import vision_completion_openai


Provider = Literal["openai", "gemini"]


def _resolve_provider(explicit: Optional[str] = None) -> Provider:
    # Priority: explicit arg -> env var -> by available keys -> default openai
    prov = (explicit or os.getenv("VISION_PROVIDER", "")).strip().lower()
    if prov in ("openai", "gemini"):
        return prov  # type: ignore[return-value]

    if OPENAI_API_KEY:
        return "openai"  # type: ignore[return-value]
    if GENIMI_API_KEY:
        return "gemini"  # type: ignore[return-value]

    # Fallback
    return "openai"  # type: ignore[return-value]


def vision_completion(image_path: str, context: str = "", provider: Optional[Provider] = None) -> str:
    """High-level vision completion API that routes to the configured provider.

    Selection order:
      1) provider param (if given)
      2) VISION_PROVIDER env var ("openai"|"gemini")
      3) Presence of corresponding API keys
      4) Default to "openai"
    If the chosen provider fails, it will try the alternative if available.
    """
    chosen = _resolve_provider(provider)

    def _try_openai() -> Optional[str]:
        if not OPENAI_API_KEY:
            return None
        try:
            return vision_completion_openai(image_path, context)
        except Exception as e:
            logging.info(f"OpenAI vision failed: {e}")
            return None

    def _try_gemini() -> Optional[str]:
        if not GENIMI_API_KEY:
            return None
        try:
            return vision_completion_genimi(image_path, context)
        except Exception as e:
            logging.info(f"Gemini vision failed: {e}")
            return None

    # Try chosen first, then fallback
    if chosen == "openai":
        result = _try_openai()
        if result is not None:
            return result
        fallback = _try_gemini()
        if fallback is not None:
            return fallback
    else:
        result = _try_gemini()
        if result is not None:
            return result
        fallback = _try_openai()
        if fallback is not None:
            return fallback

    raise RuntimeError(
        "No working vision provider found. Ensure VISION_PROVIDER is set correctly and API keys are configured."
    )
