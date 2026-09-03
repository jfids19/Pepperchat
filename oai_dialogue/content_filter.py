# -*- coding: utf-8 -*-
"""Safety filter for Pepper's dialogue system.

Blocks obviously inappropriate spoken questions before they ever reach the
LLM, so nothing gets echoed back or elaborated on in a school setting. This
is a first-pass keyword/phrase filter, not a full moderation model — it's
meant to catch clearly inappropriate content, not every edge case.

To extend: add words to the relevant list below (single words are matched
as whole words only, so "class" won't match "ass"; phrases are matched as
substrings so word order/spacing matters).
"""

import re

PROFANITY = [
    "fuck", "fucking", "fucker", "shit", "bullshit", "bitch", "asshole",
    "bastard", "dick", "pussy", "cunt", "wanker", "twat", "slut", "whore",
]

SEXUAL = [
    "sex", "sexual", "porn", "pornography", "nude", "naked", "penis",
    "vagina", "masturbate", "masturbation", "rape", "molest", "molestation",
]

VIOLENCE_AND_WEAPONS = [
    "kill", "murder", "suicide", "bomb", "gun", "shoot", "shooting", "stab",
    "stabbing", "weapon", "terrorist", "terrorism",
]

DRUGS_AND_ALCOHOL = [
    "cocaine", "heroin", "meth", "marijuana", "weed", "vape", "vaping",
]

HATE_SPEECH = [
    "nigger", "nigga", "faggot", "retard", "retarded", "tranny", "chink",
    "spic", "kike",
]

# Multi-word phrases, matched as plain substrings (case-insensitive) since a
# word-boundary check on single words would miss these.
PHRASES = [
    "kill myself", "kill yourself", "hurt myself", "hurt someone",
    "self harm", "self-harm", "cut myself", "how to make a bomb",
    "how do i make a bomb", "how to make a gun",
]

_WORD_LIST = PROFANITY + SEXUAL + VIOLENCE_AND_WEAPONS + DRUGS_AND_ALCOHOL + HATE_SPEECH
_WORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _WORD_LIST) + r")\b",
    re.IGNORECASE,
)


def is_inappropriate(text):
    # type: (str) -> bool
    if not text:
        return False
    if _WORD_PATTERN.search(text):
        return True
    text_lower = text.lower()
    return any(phrase in text_lower for phrase in PHRASES)
