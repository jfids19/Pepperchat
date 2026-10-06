# PepperChat — Project Context for Claude Code

Pepper (SoftBank/NAO humanoid) dialogue system, Nescot College computing dept, Epsom.
Fork of https://github.com/ilabsweden/pepperchat, heavily modified: Groq API (not paid OpenAI),
PS5 controller movement, custom lesson engine, wttr.in/DuckDuckGo web search, Nescot tablet subtitle UI.

## Run it (4 terminals, in this order)

1. WSL, Python 2 (needs `naoqi` SDK in `~/pynaoqi/`):
   `cd /mnt/c/Users/nesco/pepperchat && python2 module_commandable.py --pip <pepper_ip>`
2. WSL, Python 3.8:
   `cd /mnt/c/Users/nesco/pepperchat && python3 dispatcher.py --prompt oaichat/openai.prompt`
3. Windows PowerShell, Python 3.13:
   `cd C:\Users\nesco\pepperchat; py -3.13 windows_scripts\mic_streamer.py`
4. Windows PowerShell, Python 3.13:
   `cd C:\Users\nesco\pepperchat; py -3.13 windows_scripts\pepper_control.py`

Pepper's IP is DHCP — press its chest button to hear the current IP before starting terminal 1.
Module_commandable (terminal 1) must be up before dispatcher (terminal 2) or ZMQ times out (there's a retry loop, so it recovers, just slower to start).

## Hard constraints — do not violate

- Do NOT upgrade the `openai` python lib beyond 1.57.0 (breaks on Python 3.8).
- Do NOT use Python 3.12+ syntax/features anywhere under `oai_dialogue/` or `dispatcher.py` — WSL runs 3.8.
- Do NOT set `ALAutonomousLife` to `disabled` — it kills all movement. Keep it in `solitary` (see `ConfigSpeech` handling in `module_commandable.py`).
- Do NOT use `pcm_utils.listen_on_local_mic()` from WSL — there's no audio device there. Dispatcher uses `listen_on_streamed_audio()`.
- Do NOT change the multicast join in `udp.py`/`audio_stream.py` to bind a local IP instead of `0.0.0.0` — breaks the WSL/Windows boundary.
- `module_commandable.py` is Python 2 (requires the NaoQi SDK, which has no Python 3 build). Everything else under `oai_dialogue/` is Python 3.8.

## Architecture (verified against source, not just docs)

- `dispatcher.py` (py3) — entry point. Wires up `pepper_command.CommandSender`, `PepperTextSpeaker`,
  `subtitles.SubtitleServer`, `OaiChatIntegrated`, `LessonEngine`, the `muter()` echo-suppression thread,
  and a UDP command server on port 7356 for the PS5 control panel.
- `module_commandable.py` (py2) — the only process touching NaoQi directly (ALMotion, ALRobotPosture,
  ALAutonomousLife, ALTextToSpeech, ALAnimatedSpeech, ALTabletService, ALAudioDevice). Handles `Say`,
  `ConfigSpeech`, `ConfigAudio`, `Move`, `ConfigTabletWifi`, `OpenUrlOnTablet` commands. Move locks the
  head via `setAngles` at speed 1.0 on every nonzero move (overrides face tracking), releases at zero;
  `_moving` flag prevents redundant lock calls.
- Tablet screen switching: `ShowTabletUrl(url=None)` (`pepper_command.py`) loads a URL and shows the
  webview immediately, deliberately **skipping** `connect_tablet_wifi()` — unlike `OpenUrlOnTablet`,
  which gates on it and is kept only for the one-time load at dispatcher startup (cold boot, tablet wifi
  genuinely may not be up yet). **Do not route repeated/interactive tablet switches through
  `OpenUrlOnTablet`** — that gate polls `getWifiStatus()` for up to 3s and, on failure, tries
  `configureWifi` + another 5s wait, which is exactly what made "toggle back to subtitles" silently stall
  for ~8s after "open wifi menu" had just run (fixed 2026-10-05). `url=None` means
  `net_config.robot_settings_url()`. Reached by the UDP verbs `TABLET_WIFI` / `TABLET_SUBTITLES` on 7356
  (both now send `ShowTabletUrl`, just with different urls), bound to the controller's Share button (a
  toggle) and to buttons in `windows_scripts/event_setup.py`. Note new `Command` subclasses must be
  declared with the bare base name `Command`: the allowlist in `pepper_command.py` is an AST scan
  matching on `ast.Name`.
- `windows_scripts/event_setup.py` — tkinter window for the arrival-at-an-event routine (check Pepper's
  IP against NaoQi on 9559, write `PEPPER_IP` + tablet wifi credentials, run the portproxy script
  elevated, test the subtitle URL, drive the tablet). See the ARRIVING AT AN EVENT section of
  `STARTUP.txt`. Config is read at process start, so edits apply to the *next* dispatcher run.
- `oai_dialogue/pepper_command.py` — Command classes + ZMQ `CommandSender`/`CommandReceiver` on port
  **51001** (dispatcher.py ↔ module_commandable.py). Socket resets to `None` on `zmq.error.ZMQError` so
  the next `send()` reconnects.
- `oai_dialogue/comm.py` — `RobotStateReporter`/`Listener` (UDP multicast 224.1.1.7:50007 —
  talking/head_touched/just_started) and `TranscriptSender`/`Receiver` (224.1.1.6:50006, defined but
  not actually wired into dispatcher.py's flow).
- `oai_dialogue/audio_stream.py` — mic audio over UDP multicast 224.1.1.5:50005, 16-byte packet header
  (idx, sample_rate, channel_cnt, pcm_size).
- `oai_dialogue/lesson_engine.py` — loads `lessons/*.txt` (`LESSON_TITLE:` / `LESSON_TRIGGER:` /
  `STEP_N:` / `END_LESSON`), advances on "no more questions", cancels on phrases like "cancel lesson".
  Lesson intercept is checked before Groq is called. **`move_callback` is assigned in dispatcher.py but
  never actually invoked inside `LessonEngine` — pacing movement between lesson steps is not implemented,
  not just partial.**
- `oai_dialogue/speech_to_text/oaichat_integrated.py` — Groq chat (`openai/gpt-oss-120b` → fallback
  `openai/gpt-oss-20b`, updated 2026-08-26 after Groq retired `llama-3.3-70b-versatile` /
  `llama-3.1-8b-instant` from the free/developer tier on 2026-08-16 — see
  https://console.groq.com/docs/deprecations for the current free-tier model list if these ever need
  changing again) + Groq Whisper (`whisper-large-v3`) STT. `needs_web_search()` keyword-gates a
  search; weather queries always hit `wttr.in` for the hardcoded location `"Epsom"`; everything else
  goes to the DuckDuckGo instant-answer API. Constructs Silero VAD with `threshold=.35` — **overridden**
  by dispatcher.py to `.99` (not 0.95 — check dispatcher.py's `oai.silero.threshold` line before assuming).
- `oai_dialogue/speech_to_text/pepper_text_speaker.py` — sentence-splitting speech queue; on construction
  sends `OpenUrlOnTablet(subtitle_server.url)` once, which is how the tablet gets pointed at the subtitle
  page (via `ALTabletService.configureWifi` using `TABLET_WIFI_SSID/PWD/SECURITY` from `.env`, then
  `loadUrl`/`showWebview`).
- `oai_dialogue/speech_to_text/subtitles.py` — HTTP server on 8088; `SubtitleServer.url` now comes from
  `net_config.subtitle_url()` (i.e. `WINDOWS_IP` + `SUBTITLE_PORT` in `network.env`), no longer hardcoded.
  If `WINDOWS_IP` is unset it prints `SUBTITLES DISABLED` and leaves `url = None` rather than raising —
  Pepper still talks, there are just no subtitles, and `pepper_text_speaker.py` skips `OpenUrlOnTablet`.
- `oai_dialogue/speech_to_text/pcm_utils.py` — `listen_on_streamed_audio()` (used) vs
  `listen_on_local_mic()` (present, must not be used from WSL).

## Known dead code / legacy — don't confuse with the live path

- `oai_dialogue/mic_streamer.py` + `oai_dialogue/module_mic_streamer.py` — legacy Python 2 NaoQi
  on-robot mic capture (old `except BaseException, err:` syntax). Predates the current Windows-side UDP
  mic pipeline. Not the same file as `windows_scripts/mic_streamer.py`, which is the one actually used.
- `oaichat/` (openaichat.py, oaiclient.py, oairesponse.py, oaiserver.py, oaitest.py) — pre-Groq scaffolding,
  effectively unused. Only `oaichat/openai.prompt` is still referenced (as the `--prompt` CLI default),
  though the real system prompt Pepper uses comes from `dialogue.env`'s `PROMPT` var.
- `dispatcher.py.save*`, `nano.save*` — nano crash-recovery artifacts, safe to delete.
- Port 7357 (documented "WSL→Windows mute signal, broken") doesn't appear anywhere in current code —
  fully superseded by the control-panel mute path over port 7356. Not flaky, just unused.

## Env files

- `.env` — `GROQ_API_KEY`, `OPENAI_KEY=dummy`, `OPENAI_PROMPTFILE`, `LANGUAGE`, `SAY`, and
  `TABLET_WIFI_SSID`/`TABLET_WIFI_PWD`/`TABLET_WIFI_SECURITY` (real credentials — never print these
  into logs, commits, or chat).
- `dialogue.env` — just `PROMPT="..."`, the actual persona text injected into the system prompt.
- `network.env` — the drifting addresses only, no secrets (see the Network section). Gitignored;
  `network.env.example` is the committed template.

## Network (Pepper is DHCP — these drift; re-check before trusting them)

**All drifting addresses now live in `network.env` (gitignored; template in `network.env.example`),
read via `net_config.py` at the repo root.** `net_config.py` is deliberately Python 2.7/3.8/3.13 safe
and stdlib-only, because `module_commandable.py` (py2) imports it too. Keys: `PEPPER_IP`, `WINDOWS_IP`,
`WSL_IP`, `SUBTITLE_PORT`, optional `ROBOT_SETTINGS_URL`. A real env var of the same name overrides the
file. Do not reintroduce IP literals — `grep -rn "172\.2[0-9]\." --include="*.py"` should stay empty.

Key asymmetry: `WSL_IP=auto` resolves from either side (socket-route trick on WSL, `wsl hostname -I` on
Windows), but `WINDOWS_IP=auto` is resolvable **only on Windows** — from WSL the WiFi address the tablet
needs is invisible (you only get the NAT gateway `172.31.80.1`), so `windows_ip()` raises a
`NetConfigError` naming what to run. `fix_subtitle_portproxy.ps1` and `event_setup.py` are the writers.

Pepper 172.22.34.14 · WSL 172.31.94.202 · Windows 172.22.34.18 (as of 2026-10-06) · WSL gateway 172.31.80.1.
These are now just a record of what `network.env` happened to hold — the file is the source of truth.
Ports: 50005 mic audio, 50006 transcript (unused), 50007 robot state, 51001 ZMQ (dispatcher↔module),
7356 control-panel commands, 7357 mute (dead/unused), 8088 subtitle HTTP (portproxy'd from WSL).

**8088 is the only port the subtitle server is ever forwarded on — do not add a port-80 forward.**
Tried on 2026-10-06 to match the implicit `:80` of the one tablet load known to work
(`ROBOT_SETTINGS_URL`), on the theory the tablet's webview refused non-standard ports. Wrong: Windows
already runs IIS bound to port 80 on this machine, which intercepts port-80 traffic ahead of the
portproxy forward — the tablet ended up rendering IIS's own default page instead of the subtitle page.
Confirmed (not inferred) once the tablet successfully rendered *something real* on port 80, ruling out
every webview/DNS/stale-wifi theory that had been tested up to that point. `subtitle_port()` /
`subtitle_url()` in `net_config.py` only ever use one port now.

Port 8088's portproxy binding goes stale on its own (survives in `netsh interface portproxy show
v4tov4` but stops forwarding) whenever WSL's IP changes on restart — this is the recurring "tablet
screen is white" cause. **As of 2026-10-05 that script also writes `WINDOWS_IP`/`WSL_IP` into
`network.env`** instead of merely logging a warning about a hardcoded constant it could not fix, so
logon → detect → write → correct subtitle URL is now a closed loop. Fix lives at
`C:\Users\nesco\fix_subtitle_portproxy.ps1` (not in this repo —
unlike `windows_scripts/mic_streamer.py`/`pepper_control.py`, which were moved in on 2026-09-03), which re-binds it to WSL's current IP; it's
meant to run at Windows logon via a Task Scheduler entry named "PepperChat Subtitle Portproxy Fix"
(2026-09-03) — check `schtasks /query /tn "PepperChat Subtitle Portproxy Fix"` on a fresh machine, since
registering it requires an elevated PowerShell one-time setup that may not have been done everywhere.

## Open work

- Wire `lesson_engine.py`'s `move_callback` into `_deliver_step`/`_next_step`.
- `ROBOT_SETTINGS_URL`'s default `http://198.18.0.1/` and `BUTTON_SHARE = 4` in `pepper_control.py` were
  both exercised successfully during the 2026-10-06 tablet-toggle debugging session — treat as confirmed
  working rather than open, barring a different controller.
- Confirm the "PepperChat Subtitle Portproxy Fix" scheduled task is actually registered (see Network
  section above) — the fix script existing isn't enough, the elevated one-time registration step
  still needs to be run and verified after a reboot.
- Prune the legacy files listed above.
