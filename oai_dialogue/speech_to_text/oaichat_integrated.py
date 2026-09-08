import traceback
from typing import Callable, List
import dotenv
try:
    import silerovad
    from pcm_processor import PcmProcessor
except ImportError:
    import oai_dialogue.speech_to_text.silerovad as silerovad
    from oai_dialogue.speech_to_text.pcm_processor import PcmProcessor
dotenv.load_dotenv()
import os, threading, time
import numpy as np
from openai import OpenAI
import io
import wave
import urllib.parse
from oai_dialogue.content_filter import is_inappropriate

API_KEY = os.environ.get("OPENAI_KEY", "")
assert API_KEY, "Set OPENAI_KEY in your environment."

INAPPROPRIATE_REDIRECT = "I can't help with that. Let's talk about something else!"

GESTURE_NAMES = ("wave", "nod", "point", "bow", "no", "think", "shrug", "excited", "laugh", "sad", "show_tablet")
GESTURE_CHOICE_PROMPT = (
    "You choose a physical gesture for a robot to perform alongside a reply "
    "it just gave, based on the reply's content and tone. Valid gestures: "
    "wave (greeting/farewell), nod (agreement/confirmation), point "
    "(directing attention to something), bow (thanks/apology), "
    "no (disagreement/refusal), think (pondering/considering), "
    "shrug (uncertainty/not sure/don't know), excited (enthusiasm/good news), "
    "laugh (something funny/amusing), sad (bad news/sympathy), "
    "show_tablet (directing attention to the tablet on its chest). Respond "
    "with exactly one word: one of wave, nod, point, bow, no, think, shrug, "
    "excited, laugh, sad, show_tablet, or none if no gesture clearly fits. "
    "No punctuation, no explanation."
)

class Query:
    def __init__(self):
        self.start_time = time.time()
        self.query_text = ""
        self.response_text = ""
        self.done = False
        self.duration = 0
    def __str__(self):
        return str(self.__dict__)


class OaiChatIntegrated:
    STATE_IDLE = "IDLE"
    STATE_SENDING_SPEECH = "SENDING_SPEECH"
    STATE_RECEIVING_RESPONSE = "RECEIVING_RESPONSE"

    def __init__(self,
                 system_prompt="",
                 language="en",
                 voice="sage",
                 temperature=0.8,
                 query_update_callback: Callable[[Query], None] = None,
                 state_callback: Callable[[str], None] = None,
                 response_audio_callback=None,
                 intermediate_response_text_callback: Callable[[str], None] = None,
                 lesson_intercept_callback: Callable[[str], bool] = None,
                 gesture_callback: Callable[[str], None] = None
                ):

        self.system_prompt = system_prompt
        self.language = language
        self.temperature = temperature
        self.state_callback = state_callback
        self.query_response_callback = query_update_callback
        self.intermediate_response_text_callback = intermediate_response_text_callback
        self.lesson_intercept_callback = lesson_intercept_callback
        self.gesture_callback = gesture_callback
        self._listening = True
        self._state = self.STATE_IDLE
        self._cur_query = Query()
        self.conversation_history = []
        if system_prompt:
            self.conversation_history.append({"role": "system", "content": system_prompt})

        # Groq client for chat
        self.chat_client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=os.getenv("GROQ_API_KEY"),
        )

        # Whisper client for speech-to-text (also via Groq - free tier)
        self.whisper_client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=os.getenv("GROQ_API_KEY"),
        )

        self.pcm_processor = PcmProcessor(24000, 1, millis_per_chunk=100)

        def do_web_search(query):
            try:
                import urllib.request
                import json
                text_lower = query.lower()

                # Weather queries - use wttr.in free weather API
                if any(w in text_lower for w in ['weather', 'temperature', 'forecast', 'raining', 'sunny']):
                    location = "Epsom"
                    url = f"https://wttr.in/{location}?format=3"
                    req = urllib.request.urlopen(url, timeout=5)
                    result = req.read().decode('utf-8').strip()
                    print("WEATHER RESULT:", result)
                    return f"Current weather: {result}"

                # News/general - use DuckDuckGo instant answer API
                encoded = urllib.parse.quote(query)
                url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
                req = urllib.request.urlopen(url, timeout=5)
                data = json.loads(req.read().decode('utf-8'))
                abstract = data.get('AbstractText', '')
                if abstract:
                    print("DDG RESULT:", abstract[:100])
                    return f"Information: {abstract[:300]}"
            except Exception as e:
                print("Search failed:", e)
            return ""

        def choose_gesture(user_text, response_text):
            if not self.gesture_callback or not response_text:
                return
            try:
                result = self.chat_client.chat.completions.create(
                    model="openai/gpt-oss-20b",
                    messages=[
                        {"role": "system", "content": GESTURE_CHOICE_PROMPT},
                        {"role": "user", "content": "User said: %s\nRobot replied: %s" % (user_text, response_text)},
                    ],
                    max_tokens=20,
                    temperature=0,
                    extra_body={"reasoning_effort": "low"},
                )
                choice_text = (result.choices[0].message.content or "").strip().lower()
                # Word-boundary match, not substring - "no" must not match inside "none".
                import re
                words = re.findall(r"[a-z_]+", choice_text)
                choice = next((w for w in words if w in GESTURE_NAMES), None)
                print("GESTURE CHOICE:", choice_text, "->", choice)
                if choice:
                    self.gesture_callback(choice)
            except Exception:
                traceback.print_exc()

        def needs_web_search(user_text):
            text_lower = user_text.lower()
            search_keywords = [
                'weather', 'temperature', 'forecast', 'raining', 'sunny',
                'today', 'news', 'latest', 'current', 'score',
                'price', 'who is', 'what is', 'when is', 'where is',
                'how much', 'how many', 'what time'
            ]
            return any(keyword in text_lower for keyword in search_keywords)

        def on_pcm16_frames(sample_rate: int, channel_cnt: int, frames: np.ndarray):
            self._set_state(self.STATE_SENDING_SPEECH)

        def on_speech_end(sample_rate: int, channel_cnt: int, pcm16_chunks: List[np.ndarray]):
            try:
                self._set_state(self.STATE_RECEIVING_RESPONSE)

                # Combine all audio chunks
                all_frames = np.concatenate(pcm16_chunks) if len(pcm16_chunks) > 1 else pcm16_chunks[0]

                # Convert to WAV in memory
                wav_buffer = io.BytesIO()
                with wave.open(wav_buffer, 'wb') as wf:
                    wf.setnchannels(channel_cnt)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(all_frames.tobytes())
                wav_buffer.seek(0)
                wav_buffer.name = "audio.wav"

                # Transcribe with Groq Whisper
                transcription = self.whisper_client.audio.transcriptions.create(
                    model="whisper-large-v3",
                    file=wav_buffer,
                    language=self.language,
                )
                user_text = transcription.text.strip()
                if not user_text:
                    self._set_state(self.STATE_IDLE)
                    return

                self._cur_query.query_text = user_text
                if self.query_response_callback:
                    self.query_response_callback(self._cur_query)

                # Safety filter - block inappropriate content before it ever reaches
                # the lesson engine, web search, or the LLM.
                if is_inappropriate(user_text):
                    print("BLOCKED (inappropriate):", user_text)
                    self._cur_query.response_text = INAPPROPRIATE_REDIRECT
                    if self.intermediate_response_text_callback:
                        self.intermediate_response_text_callback(INAPPROPRIATE_REDIRECT)
                    self._cur_query.done = True
                    self._cur_query.duration = time.time() - self._cur_query.start_time
                    if self.query_response_callback:
                        self.query_response_callback(self._cur_query)
                    self._set_state(self.STATE_IDLE)
                    return

                # Check lesson intercept before sending to AI
                if self.lesson_intercept_callback and self.lesson_intercept_callback(user_text):
                    self._cur_query.done = True
                    self._cur_query.duration = time.time() - self._cur_query.start_time
                    if self.query_response_callback:
                        self.query_response_callback(self._cur_query)
                    self._set_state(self.STATE_IDLE)
                    return

                # Check if web search is needed
                search_context = ""
                if needs_web_search(user_text):
                    print("WEB SEARCH:", user_text)
                    # Strip common greeting prefixes before searching
                    import re
                    clean_query = re.sub(r'^(hello|hi|hey|pepper|peppa)[,\s]+', '', user_text, flags=re.IGNORECASE).strip()
                    search_context = do_web_search(clean_query)

                # Build messages with optional search context
                self.conversation_history.append({"role": "user", "content": user_text})
                messages_with_context = self.conversation_history.copy()
                if search_context:
                    messages_with_context[-1] = {
                        "role": "user",
                        "content": user_text + "\n\n" + search_context
                    }

                # Try primary model, fall back if over capacity
                # NOTE: llama-3.3-70b-versatile / llama-3.1-8b-instant were retired from the
                # free/developer tier on 2026-08-16 (Enterprise-only now). Swapped to Groq's
                # current free-tier models per https://console.groq.com/docs/deprecations.
                try:
                    stream = self.chat_client.chat.completions.create(
                        model="openai/gpt-oss-120b",
                        messages=messages_with_context,
                        max_tokens=150,
                        stream=True,
                    )
                except Exception:
                    print("Primary model unavailable, trying fallback...")
                    stream = self.chat_client.chat.completions.create(
                        model="openai/gpt-oss-20b",
                        messages=messages_with_context,
                        max_tokens=150,
                        stream=True,
                    )

                full_response = ""
                for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        full_response += delta
                        self._cur_query.response_text += delta
                        if self.intermediate_response_text_callback:
                            self.intermediate_response_text_callback(delta)
                        if self.query_response_callback:
                            self.query_response_callback(self._cur_query)

                self.conversation_history.append({"role": "assistant", "content": full_response})
                threading.Thread(target=choose_gesture, args=(user_text, full_response), daemon=True).start()
                self._cur_query.done = True
                self._cur_query.duration = time.time() - self._cur_query.start_time
                if self.query_response_callback:
                    self.query_response_callback(self._cur_query)

            except Exception:
                traceback.print_exc()
            finally:
                self._set_state(self.STATE_IDLE)

        self.silero = silerovad.SileroVad(
            threshold=.35,
            head_millis=1000,
            speech_stream_callback=on_pcm16_frames,
            speech_end_callback=on_speech_end,
        )

    @property
    def state(self):
        return self._state

    def _set_state(self, state):
        if self._state != state:
            if state == self.STATE_SENDING_SPEECH:
                self._cur_query = Query()
            self._state = state
            if self.state_callback:
                self.state_callback(state)

    def push_pcm16_frames(self, sample_rate: int, channel_cnt: int, frames: np.ndarray):
        if self._listening:
            self.silero.push_pcm16_frames(sample_rate, channel_cnt, frames)

    def set_listening(self, listening):
        if self._listening != listening:
            print("listening:", listening)
            self._listening = listening

    def cancel_current(self):
        self._set_state(self.STATE_IDLE)
