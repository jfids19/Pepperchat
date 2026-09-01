# -*- coding: utf-8 -*-
# Standalone spike: does our Groq API key have access to a vision-capable model?
# Not wired into the app. Run directly: python3 spike_groq_vision.py
# Requires GROQ_API_KEY in .env (repo root) and Pillow (pip install Pillow).

import base64
import io
import os

import dotenv
dotenv.load_dotenv()

from openai import OpenAI
from PIL import Image, ImageDraw

CANDIDATE_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",  # believed deprecated 2026-07-17 per Groq docs
    "qwen/qwen3.6-27b",
    "qwen/qwen3.8-27b",
]


def make_test_image_data_uri():
    img = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(img)
    draw.ellipse((40, 40, 160, 160), fill="red")
    draw.rectangle((220, 60, 360, 200), fill="blue")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return "data:image/jpeg;base64," + b64


def main():
    api_key = os.getenv("GROQ_API_KEY")
    assert api_key, "Set GROQ_API_KEY in .env"

    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
    data_uri = make_test_image_data_uri()

    print("Test image: white 400x300, red circle top-left, blue square right.\n")

    for model in CANDIDATE_MODELS:
        print("=" * 60)
        print("Model:", model)
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe this image in one sentence."},
                            {"type": "image_url", "image_url": {"url": data_uri}},
                        ],
                    }
                ],
                max_tokens=150,
            )
            text = resp.choices[0].message.content
            print("SUCCESS")
            print("Response:", text)
        except Exception as e:
            print("FAILED:", type(e).__name__, "-", str(e))
        print()


if __name__ == "__main__":
    main()
