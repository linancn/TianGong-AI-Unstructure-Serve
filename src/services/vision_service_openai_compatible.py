import base64
from itertools import cycle
from threading import Lock
from typing import Iterator, List, Optional, Sequence

from openai import OpenAI

from src.services.vision_prompts import build_vision_prompt


def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


class OpenAICompatibleClientPool:
    """Lightweight client pool that supports OpenAI-compatible endpoints."""

    def __init__(
        self,
        api_key: str,
        base_urls: Optional[Sequence[str]] = None,
        fallback_api_key: Optional[str] = None,
    ):
        resolved_urls = [url.strip() for url in base_urls or [] if url and url.strip()]
        resolved_key = (api_key or "").strip()
        if resolved_urls and not resolved_key and fallback_api_key is not None:
            resolved_key = fallback_api_key

        self._clients = self._build_clients(resolved_key, resolved_urls)
        self._single = self._clients[0] if len(self._clients) == 1 else None
        self._cycle: Optional[Iterator[OpenAI]] = (
            cycle(self._clients) if len(self._clients) > 1 else None
        )
        self._lock = Lock()

    @staticmethod
    def _build_clients(api_key: str, base_urls: List[str]) -> List[OpenAI]:
        clients: List[OpenAI] = []
        if base_urls:
            clients = [OpenAI(api_key=api_key, base_url=url) for url in base_urls]
        elif api_key:
            clients = [OpenAI(api_key=api_key)]
        return clients

    def has_clients(self) -> bool:
        return bool(self._clients)

    def get_client(self) -> OpenAI:
        if not self._clients:
            raise RuntimeError("OpenAI-compatible vision client is not configured.")
        if self._single:
            return self._single
        assert self._cycle is not None  # for mypy
        with self._lock:
            return next(self._cycle)


def vision_completion_openai_compatible(
    image_path: str,
    *,
    context: str = "",
    model: Optional[str] = None,
    prompt: Optional[str] = None,
    default_model: str,
    client_pool: OpenAICompatibleClientPool,
) -> str:
    base64_image = encode_image(image_path)
    prompt_text = build_vision_prompt(context, prompt)

    client = client_pool.get_client()
    response = client.chat.completions.create(
        model=model or default_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                    },
                ],
            }
        ],
    )
    return response.choices[0].message.content
