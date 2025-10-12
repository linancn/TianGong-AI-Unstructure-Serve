from typing import Optional

from PIL import Image
from google import genai

from src.config.config import GENIMI_API_KEY

client = genai.Client(api_key=GENIMI_API_KEY)

DEFAULT_VISION_MODEL = "gemini-2.5-flash"


def _resolve_model(explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    return DEFAULT_VISION_MODEL


def vision_completion_genimi(
    image_path: str, context: str = "", model: Optional[str] = None
) -> str:
    image = Image.open(image_path)
    prompt = "What is in this image? Only return neat facts."

    if context:
        prompt = (
            "Analyze this image with the following context:\n"
            f"{context}\n"
            "Describe the image considering this context. Only return neat facts in the language of the context."
        )

    response = client.models.generate_content(model=_resolve_model(model), contents=[image, prompt])

    return response.text
