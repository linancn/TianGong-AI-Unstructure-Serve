from PIL import Image
from google import genai

from src.config.config import GENIMI_API_KEY

client = genai.Client(api_key=GENIMI_API_KEY)


def vision_completion_genimi(image_path: str, context: str = "") -> str:
    image = Image.open(image_path)
    prompt = "What is in this image? Only return neat facts."

    if context:
        prompt = f"Analyze this image with the following context:\n{context}\nDescribe the image considering this context. Only return neat facts in the language of the context."

    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-05-20", contents=[image, prompt]
    )

    return response.text
