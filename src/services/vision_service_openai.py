import base64

from openai import OpenAI

from src.config.config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)


# Function to encode the image
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def vision_completion_openai(image_path: str, context: str = "") -> str:
    base64_image = encode_image(image_path)
    prompt = "What is in this image? Only return neat facts."

    if context:
        prompt = f"Analyze this image with the following context:\n{context}\nDescribe the image considering this context. Only return neat facts in the language of the context."

    response = client.chat.completions.create(
        model="gpt-5-mini",
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
