import os
import re
import threading

import dotenv
dotenv.load_dotenv()

from openai import OpenAI

try:
    import pepper_command
except ImportError:
    import oai_dialogue.pepper_command as pepper_command

VISION_TRIGGER_PHRASES = [
    "look at this",
    "what is this",
    "what do you see",
    "take a look",
    "what am i holding",
]

VISION_MODEL = "qwen/qwen3.6-27b"

VISION_INSTRUCTIONS = (
    "You are now looking through your camera. Describe what you see or answer the "
    "question factually in 1-2 short spoken sentences. Stay in your own voice as "
    "described above - do not roleplay as any other character (e.g. a cartoon "
    "character). Plain language only - no markdown, no headers, no numbered lists."
)

THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think(text):
    stripped = THINK_TAG_RE.sub("", text).strip()
    if "<think>" in stripped:
        return None
    return stripped


class VisionEngine:
    def __init__(self, command_sender, speak_callback, busy_callback, system_prompt=""):
        self.command_sender = command_sender
        self.speak_callback = speak_callback
        self.busy_callback = busy_callback
        self.system_prompt = system_prompt
        self.client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=os.getenv("GROQ_API_KEY"),
        )

    def check_trigger(self, text):
        text_lower = text.lower()
        if any(phrase in text_lower for phrase in VISION_TRIGGER_PHRASES):
            threading.Thread(target=self._handle, args=(text,), daemon=True).start()
            return True
        return False

    def _handle(self, user_text):
        self.busy_callback(True)
        try:
            response = self.command_sender.send(pepper_command.CaptureImage())
            image_b64 = response.get("image_b64") if response else None
            if not image_b64:
                print("VisionEngine: capture failed:", response)
                self.speak_callback("Sorry, I couldn't get a picture from my camera.")
                return

            if isinstance(image_b64, bytes):
                image_b64 = image_b64.decode("ascii")
            data_uri = "data:image/jpeg;base64," + image_b64

            system_content = (
                self.system_prompt + "\n\n" + VISION_INSTRUCTIONS
                if self.system_prompt
                else VISION_INSTRUCTIONS
            )

            completion = self.client.chat.completions.create(
                model=VISION_MODEL,
                messages=[
                    {"role": "system", "content": system_content},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_text},
                            {"type": "image_url", "image_url": {"url": data_uri}},
                        ],
                    },
                ],
                max_tokens=300,
                extra_body={"reasoning_effort": "none"},
            )
            text = strip_think(completion.choices[0].message.content)
            print("VisionEngine response:", text)
            if not text:
                self.speak_callback("Sorry, I'm having trouble describing that right now.")
                return
            self.speak_callback(text)
        except Exception:
            import traceback
            traceback.print_exc()
            self.speak_callback("Sorry, something went wrong trying to look at that.")
        finally:
            self.busy_callback(False)
