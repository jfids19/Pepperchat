# windows_scripts

These two scripts run under native Windows Python 3.13 — NOT WSL. Run them from a normal
Windows PowerShell window, not the WSL/Cursor terminal:

```powershell
py -3.13 -m pip install -r windows_scripts\requirements.txt
py -3.13 windows_scripts\mic_streamer.py
py -3.13 windows_scripts\pepper_control.py
```

- `mic_streamer.py` — captures the laptop mic and streams it over UDP to WSL (port 50005),
  with a mute/unmute control socket on port 7357.
- `pepper_control.py` — reads a PS5 controller via pygame and sends movement/mute/lesson-cancel/gesture
  commands to dispatcher.py's control server on port 7356.
