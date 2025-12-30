from typing import Optional

from PIL import Image
from google import genai

from src.config.config import GENIMI_API_KEY
from src.services.vision_prompts import build_vision_prompt

client = genai.Client(api_key=GENIMI_API_KEY)

DEFAULT_VISION_MODEL = "gemini-2.5-flash"


def _resolve_model(explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    return DEFAULT_VISION_MODEL


def vision_completion_genimi(
    image_path: str,
    context: str = "",
    model: Optional[str] = None,
    prompt: Optional[str] = None,
) -> str:
    image = Image.open(image_path)
    prompt_text = build_vision_prompt(context, prompt)

    response = client.models.generate_content(
        model=_resolve_model(model),
        contents=[image, prompt_text],
    )

    return response.text
