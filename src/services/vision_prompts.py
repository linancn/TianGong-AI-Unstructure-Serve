from typing import Optional

DEFAULT_VISION_PROMPT = (
    "What is in this image? Base your answer primarily on the visual content; if the"
    " surrounding context conflicts with or seems unrelated to the image, ignore it and"
    " trust what you see. Only return neat facts. Respond directly with the core findings—do"
    " not add lead-in phrases such as 'Based on the context' or 'Here is the summary', and"
    " avoid Chinese introductions like '根据您提供的上下文信息' or '以下是'. Do not include"
    " any [Page ...] or [ChunkType=...] markers in your response."
)


def build_vision_prompt(context: str, prompt_override: Optional[str]) -> str:
    """Merge user prompt override with contextual instructions."""
    if prompt_override and prompt_override.strip():
        custom_prompt = prompt_override.strip()
        if context:
            return (
                f"{custom_prompt}\n\nContext (lines may include [Page N] and [ChunkType=Title] markers; "
                "use them only for positioning and do not output them):\n"
                f"{context}"
            )
        return custom_prompt

    if context:
        return (
            "Analyze this image with the following context. Lines may include [Page N] and"
            " [ChunkType=Title] markers indicating document structure:\n"
            f"{context}\n"
            "Describe what is visually present first, using the page and title cues only to"
            " clarify placement. If the text context conflicts with or seems unrelated to the"
            " visible content, explicitly prefer the image and ignore that context. Only return"
            " neat facts in the language of the context. Respond with the key details only—do not"
            " preface the answer with meta commentary such as '根据您提供的上下文信息' or '以下是',"
            " and do not repeat any [Page ...] or [ChunkType=...] markers."
        )

    return DEFAULT_VISION_PROMPT
