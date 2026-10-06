from dataclasses import dataclass
import json
import os
import platform
import re
import socket
import sys
import threading
import time
import traceback
import binascii
import http.server
import socketserver
from typing import Callable, List, Tuple
import numpy as np

# Reach the repo root so net_config is importable however this module is
# started (dispatcher.py from the root, or this file directly for its __main__).
# Same shape as the sibling __parentdir.py.
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
import net_config

htmlfile = os.path.dirname(os.path.realpath(__file__)) + "/subtitles.html"
class SubtitleServer:
    class HttpHandler(http.server.BaseHTTPRequestHandler):
        pending_text = "*"
        listening = False
        muted = False
        def do_GET(self):
            # TEMPORARY diagnostic (2026-10-06): confirms whether a request
            # from the tablet is reaching this server at all on the hotspot,
            # where everything server-side has been verified correct and
            # reachable from ordinary devices, yet the tablet still shows
            # white. Remove once that's answered either way.
            print("SUBTITLE GET from %s: %s" % (self.client_address[0], self.path))
            # Ignore favicon with an empty 200
            if "favicon" in self.path:
                content = b""
            else:
                with open(htmlfile, "rb") as f:
                    content = f.read()

            # Exactly one status line + header block + body. This used to
            # send a second, duplicate 200-with-headers right after the
            # first (which itself had no Content-Length and no body) —
            # two concatenated HTTP responses on one connection. Desktop
            # browsers tolerated it; Pepper's embedded tablet WebView did
            # not and rendered a blank white page. That was the real cause
            # of the white-screen tablet bug, separate from the IP/portproxy
            # one fixed earlier.
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            # This exact URL was genuinely broken more than once earlier
            # (stale IP, then the malformed-double-response bug above) while
            # Pepper's tablet kept loading it — without this, a WebView that
            # cached any of those broken responses would keep replaying a
            # blank cached page forever, indistinguishable from a server
            # that's still broken. The query-string cache-bust in
            # dispatcher.py's ShowTabletUrl calls is the other half of this.
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(content)
        
        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            import json
            payload = json.dumps({
                "text": self.pending_text,
                "listening": self.listening,
                "muted": self.muted
            })
            self.wfile.write(payload.encode("utf-8"))

        def log_message(self, format, *args):
            return
            return super().log_message(format, *args)
    
    _instance:"SubtitleServer" = None
    def __init__(self, http_port = None):
        if(self._instance):
            return self._instance
        self._instance = self
        if http_port is None:
            http_port = net_config.subtitle_port()
        # The tablet has to reach the Windows host, not WSL, so this address
        # comes from network.env (written by fix_subtitle_portproxy.ps1 or
        # event_setup.py). A missing value means no subtitles, not no Pepper.
        try:
            self.url = net_config.subtitle_url()
        except net_config.NetConfigError as err:
            print("SUBTITLES DISABLED: " + str(err))
            self.url = None

        def listen():
            socketserver.TCPServer.allow_reuse_address = True
            with socketserver.TCPServer(("", http_port), self.HttpHandler) as httpd:
                print(f"Serving on port {http_port}...")
                try:
                    httpd.serve_forever()
                except KeyboardInterrupt:
                    print("\nShutting down server.")
                    httpd.server_close()
        self.handler: SubtitleServer.HttpHandler = None
        threading.Thread(target=listen, daemon=True).start()
    def set_text(self, text:str):
        self.HttpHandler.pending_text = text
    def set_listening(self, listening:bool):
        self.HttpHandler.listening = listening
    def set_muted(self, muted:bool):
        self.HttpHandler.muted = muted

def split_into_sentences(text) -> List[str]:
    parts = re.split(r'([.?!])', text)
    out = []
    for i in range(0, len(parts)-1, 2):
        out.append(parts[i] + parts[i+1])
    return out

class AudioSynchronizedSubtitleProvider:
    def __init__(self):
        self.signal_threshold = 500
        self.duration_threshold = .1
        self._consecutive_silent_sample_cnt = 0
        self._sample_cnt = 0
        self._sample_rate = -1
        self._collected_text = ""
        self._last_pcm_time = 0
        self._start_time = 0
        self._cur_subtitle = ""
        self._server = SubtitleServer()
        self._silences:List[Tuple[float,float]] = [] 
        """(start, duration)"""
        def loop():
            while True:
                now = time.time()
                if self._sample_cnt > 0:
                    speech_dur = self._sample_cnt / self._sample_rate
                    play_time = now - self._start_time
                    remaining_time = speech_dur - play_time
                    pcm_input_done = time.time() - self._last_pcm_time > .5
                    if pcm_input_done and remaining_time < -3:
                        self.reset()
                    elif pcm_input_done and remaining_time <= 0:
                        self._set_subtitle(self._collected_text)
                    else:
                        if sentences := split_into_sentences(self._collected_text):
                            applicable_silence_cnt = min(len(self._silences), len(sentences)-1)
                            applicable_silences = sorted(self._silences, reverse=True, key=lambda silence: silence[1])[:applicable_silence_cnt]
                            number_of_texts_to_show = 1 + len([silence for silence in applicable_silences if (silence[0] + silence[1]) < play_time])
                            self._set_subtitle("".join([sentence.strip() for sentence in sentences[:number_of_texts_to_show]]))
                time.sleep(.2)
        threading.Thread(target=loop, daemon=True).start()

    def _set_subtitle(self, text):
        if text != self._cur_subtitle:
            print(text)
            self._cur_subtitle = text
            self._server.set_text(text)
            
    def reset(self):
        if self._sample_cnt > 0:
            self._set_subtitle("")
            self._collected_text = ""
            self._sample_cnt = 0
            self._silences = []
   

    def push_text(self, text:str):
        self._collected_text += text

    def push_pcm16_frames(self, sample_rate:int, channel_cnt:int, frames:np.ndarray):
        if channel_cnt > 1:
            return False
        self._last_pcm_time = time.time()
        self._sample_rate = sample_rate
        if self._sample_cnt == 0:
            self._start_time = time.time()
        abs_amplitudes = np.abs(frames)
        silent_sample_cnt_threshold = int(sample_rate * self.duration_threshold)
        for amp in abs_amplitudes:
            self._sample_cnt += 1
            if amp < self.signal_threshold:
                self._consecutive_silent_sample_cnt += 1
            else:
                if self._consecutive_silent_sample_cnt >= silent_sample_cnt_threshold:
                    self._silences.append((
                        (self._sample_cnt - self._consecutive_silent_sample_cnt) / sample_rate,
                        self._consecutive_silent_sample_cnt / sample_rate
                    ))
                self._consecutive_silent_sample_cnt = 0

if __name__ == "__main__":
    ss = SubtitleServer()
    subs = ["Apa","asdfdfasdkj asdf jklö asdf df", "gfagfgh sdgfas"]
    idx = 0
    while True:
        ss.set_text(subs[idx%len(subs)])
        idx += 1
        time.sleep(2)

