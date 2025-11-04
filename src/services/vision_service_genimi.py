from typing import Optional

from PIL import Image
from google import genai

from src.config.config import GENIMI_API_KEY

client = genai.Client(api_key=GENIMI_API_KEY)

DEFAULT_VISION_MODEL = "gemini-2.5-flash"
_DEFAULT_PROMPT = (
    "What is in this image? Use any provided page numbers and [ChunkType=Title] markers to"
    " infer the correct page context. Base your answer primarily on the visual content; if"
    " the surrounding context conflicts with or seems unrelated to the image, ignore it and"
    " trust what you see. Only return neat facts."
)


def _resolve_model(explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    return DEFAULT_VISION_MODEL


def _build_prompt(context: str, prompt_override: Optional[str]) -> str:
    """Merge user prompt override with contextual instructions."""
    if prompt_override and prompt_override.strip():
        custom_prompt = prompt_override.strip()
        if context:
            return (
                f"{custom_prompt}\n\nContext (page numbers and [ChunkType=Title] markers indicate document structure):\n"
                f"{context}"
            )
        return custom_prompt

    if context:
        return (
            "Analyze this image with the following context. Page numbers and [ChunkType=Title]"
            " markers indicate the document structure:\n"
            f"{context}\n"
            "Describe what is visually present first, using the page and title cues only to"
            " clarify placement. If the text context conflicts with or seems unrelated to the"
            " visible content, explicitly prefer the image and ignore that context. Only return"
            " neat facts in the language of the context."
        )

    return _DEFAULT_PROMPT


def vision_completion_genimi(
    image_path: str,
    context: str = "",
    model: Optional[str] = None,
    prompt: Optional[str] = None,
) -> str:
    image = Image.open(image_path)
    prompt_text = _build_prompt(context, prompt)

    response = client.models.generate_content(
        model=_resolve_model(model),
        contents=[image, prompt_text],
    )

    return response.text
