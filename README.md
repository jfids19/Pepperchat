# Pepper Chat — Nescot College Edition

A fork of [ilabsweden/pepperchat](https://github.com/ilabsweden/pepperchat), adapted for the
Computing department at [Nescot College](https://www.nescot.ac.uk/), Epsom, to run our SoftBank
Pepper robot as an interactive assistant for open days, taster sessions, and the department itself.

The original project connects a Pepper/Nao robot to OpenAI's ChatGPT for open-ended spoken
conversation. This fork keeps that core idea but reworks the pieces we needed to run it day-to-day
in our own setup:

- **Groq instead of paid OpenAI** — chat and speech-to-text run through the [Groq API](https://groq.com/)
  (an OpenAI-compatible client pointed at Groq's endpoint) rather than a paid OpenAI subscription.
- **PS5 controller movement** — a control panel drives Pepper's movement over a PS5 controller
  instead of only autonomous/scripted motion.
- **A custom lesson engine** — `lessons/*.txt` define step-by-step guided lessons (e.g. our Tinkercad
  lesson) that Pepper can walk a student through, separate from free-form chat.
- **Live web search** — weather questions go to [wttr.in](https://wttr.in/) for our location; other
  factual questions are answered via the DuckDuckGo instant-answer API.
- **A tablet subtitle UI** — Pepper's chest tablet is pointed at a small local web page that shows
  live subtitles of what Pepper is hearing/saying, useful in a noisy open department.
- **Department knowledge** — `staff.txt`, `courses.txt`, and `events.txt` give Pepper answers about
  who's who, what we teach, and what's on, specific to Nescot.

This is a working department tool, tuned for our network and hardware — see `CLAUDE.md` in this
repo for the full technical breakdown (architecture, ports, environment variables, and known rough
edges) if you're picking up development on it.

## Video of the original project

### April 2024 update
[![Pepper Dialogue](img/Pepper-prompt-2024-04.png)](https://youtu.be/1T3SLaut6wI?si=lggZ70EGl287Ke1G)

### Original release, June 2022
[![Pepper Dialogue](img/Pepper-prompt.png)](https://youtu.be/zip90jyv1i4)

## Running it

Our setup splits across four terminals, because NaoQi's Python 2 SDK, our dialogue logic, and the
Windows-side audio/control scripts each need a different environment:

1. **WSL, Python 2** (needs the `naoqi` SDK) — talks directly to the robot:
   ```
   python2 module_commandable.py --pip <pepper_ip>
   ```
2. **WSL, Python 3.8** — the dialogue engine:
   ```
   python3 dispatcher.py --prompt oaichat/openai.prompt
   ```
3. **Windows PowerShell, Python 3.13** — streams mic audio to WSL:
   ```
   py -3.13 mic_streamer.py
   ```
4. **Windows PowerShell, Python 3.13** — the PS5 movement control panel:
   ```
   py -3.13 pepper_control.py
   ```

Start them in that order — module 1 needs to be up before module 2 connects. Pepper's IP is DHCP,
so check its current IP (press the chest button) before starting terminal 1.

Configuration lives in `.env` (API keys, tablet wifi credentials — never commit this file) and
`dialogue.env` (the persona/prompt text Pepper uses). See `CLAUDE.md` for the full list of
environment variables and network ports this depends on.

## License

This project is released under the MIT license. Please refer to [LICENSE.md](LICENSE.md) for license details.

Parts of the source code have specific license formulations. Please see the file headers for details.

## Publications

Erik Billing, Julia Rosén, and Maurice Lamb. 2023. [Language Models for Human-Robot Interaction](doc/Billing_etal_2023-Language_models_for_HRI.pdf). In Companion of the 2023 ACM/IEEE International Conference on Human-Robot Interaction (HRI '23 Companion), March 13–16, 2023, Stockholm, Sweden. ACM, New York, NY, USA, 2 pages. https://doi.org/10.1145/3568294.3580040.

## Acknowledgments

This fork is maintained by the Computing department at Nescot College, Epsom, building on the
original PepperChat project:

* Mikael Lebram @ University of Skövde, Sweden - for implementing the OpenAI ChatGPT based speech recognition system.
* Erik Billing @ University of Skövde, Sweden - for implementing the OpenAI GPT-3 dialogue system.
* Igor Lirussi @ Cognitive Learning and Robotics Laboratory at Boğaziçi University, Istanbul - for providing an [AIML-based dialogue system](https://github.com/igor-lirussi/Dialogue-Pepper-Robot) on which this project is built.
* Johannes Bramauer @ Vienna University of Technology - for the [PepperSpeechRecognition](https://github.com/JBramauer/pepperspeechrecognition)
* Anthony Zang (Uberi) and his [SpeechRecognition](https://github.com/Uberi/speech_recognition)
