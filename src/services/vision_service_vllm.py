import base64
import os
from typing import Optional

from openai import OpenAI

from src.config.config import VLLM_API_KEY, VLLM_BASE_URL

DEFAULT_VISION_MODEL = "Qwen/Qwen2.5-VL-72B-Instruct-AWQ"
_FALLBACK_API_KEY = "not-required"


def _resolve_api_key() -> str:
    env_override = os.getenv("VLLM_API_KEY")
    if env_override:
        return env_override
    if VLLM_API_KEY:
        return VLLM_API_KEY
    return _FALLBACK_API_KEY


_client: Optional[OpenAI] = None
if VLLM_BASE_URL:
    _client = OpenAI(api_key=_resolve_api_key(), base_url=VLLM_BASE_URL.strip())


# Function to encode the image
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def _resolve_model(explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    return DEFAULT_VISION_MODEL


def _get_client() -> OpenAI:
    if _client is None:
        raise RuntimeError(
            "vLLM vision client is not configured. Ensure VLLM_BASE_URL is set (API key optional)."
        )
    return _client


def vision_completion_vllm(image_path: str, context: str = "", model: Optional[str] = None) -> str:
    base64_image = encode_image(image_path)
    prompt = "What is in this image? Only return neat facts."

    if context:
        prompt = (
            "Analyze this image with the following context:\n"
            f"{context}\n"
            "Describe the image considering this context. Only return neat facts in the language of the context."
        )

    client = _get_client()
    response = client.chat.completions.create(
        model=_resolve_model(model),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}",
                        },
                    },
                ],
            }
        ],
    )
    return response.choices[0].message.content
