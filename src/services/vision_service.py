import base64

from openai import OpenAI

from src.config.config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)


# Function to encode the image
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def vision_completion(image_path: str, context: str = "") -> str:
    base64_image = encode_image(image_path)
    prompt = "What is in this image? Only return neat facts."
    
    if context:
        prompt = f"Analyze this image with the following context:\n{context}\n\nPlease describe the image considering this context."
    
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
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
        max_tokens=300,
    )
    return response.choices[0].message.content
