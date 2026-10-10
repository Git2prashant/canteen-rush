"""The one shared helper. Every script and the app talk to Gemma 4 through this file.

It adds the safety nets you want on busy Wi-Fi with a free key:
  - a friendly error if your key is missing (it never prints the key)
  - a pause between calls
  - automatic retries when Google says "too many requests" (error 429)
  - an on-disk cache, so asking the same thing twice costs nothing
  - a rough count of your calls in the last 24 hours
"""

import hashlib
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Read the .env file (if there is one) so GEMINI_API_KEY is available.
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass  # python-dotenv is not installed; real environment variables still work


# Quiet a harmless warning the Google package prints on every run.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

# Windows consoles can crash on emoji or arrows in the model's answer. Print a "?" instead.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")


def _number(name, default):
    """Read a number from an environment variable. Use the default if it is missing or wrong."""
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


# Settings. You can change any of them in your .env file.
MODEL = os.environ.get("GEMMA_MODEL") or "gemma-4-26b-a4b-it"
MIN_SECONDS_BETWEEN_CALLS = _number("MIN_SECONDS_BETWEEN_CALLS", 4)
SOFT_LIMIT = int(_number("GEMMA_SOFT_LIMIT", 1000))
USE_CACHE = os.environ.get("GEMMA_CACHE", "1") != "0"
RETRY_WAITS = (10, 20, 40)  # seconds to wait before retry 1, 2 and 3
CACHE_DIR = ROOT / ".cache"

_client = None
_last_call_time = 0.0


class MissingKeyError(RuntimeError):
    """Raised when no API key can be found."""


def get_client():
    """Make the Gemini API client once and reuse it."""
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY", "").strip().strip("\"'")
        if not key or key == "paste-your-key-here":
            raise MissingKeyError(
                "No API key found. Fix: copy .env.example to .env, open .env, and put your "
                "key after GEMINI_API_KEY=. Get a free key at https://aistudio.google.com"
            )
        from google import genai

        _client = genai.Client(api_key=key)
    return _client


def _make_config(system, thinking):
    """Build the settings for one call: the rule for the model and thinking mode."""
    if not system and not thinking:
        return None
    from google.genai import types

    settings = {}
    if system:
        settings["system_instruction"] = system
    if thinking:
        settings["thinking_config"] = types.ThinkingConfig(thinking_level="high")
    return types.GenerateContentConfig(**settings)


# ---------- usage counter ----------

def calls_last_24h():
    """How many real calls we made in the last 24 hours (cache hits do not count)."""
    try:
        stamps = json.loads((CACHE_DIR / "usage.json").read_text())
    except (OSError, ValueError):
        return 0
    return len([t for t in stamps if time.time() - t < 86400])


def _record_call():
    now = time.time()
    path = CACHE_DIR / "usage.json"
    try:
        stamps = json.loads(path.read_text())
    except (OSError, ValueError):
        stamps = []
    stamps = [t for t in stamps if now - t < 86400] + [now]
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        path.write_text(json.dumps(stamps))
    except OSError:
        pass  # the counter is only a helper; never crash because of it
    if len(stamps) > SOFT_LIMIT:
        print(
            f"Heads up: you made {len(stamps)} calls in the last 24 hours. Your free allowance "
            "may run out soon. This is a rough guide, not the real limit. "
            "Check your real limits in Google AI Studio."
        )


# ---------- cache ----------
# Free limits are per Google Cloud project, so repeated calls waste them.
# If the same question was already answered, we reuse the saved answer.

def _cache_key(*parts):
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part if isinstance(part, bytes) else str(part).encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _cache_get(key):
    if not USE_CACHE:
        return None
    try:
        return json.loads((CACHE_DIR / f"{key}.json").read_text())["text"]
    except (OSError, ValueError, KeyError):
        return None


def _cache_put(key, text):
    if not USE_CACHE:
        return
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        (CACHE_DIR / f"{key}.json").write_text(json.dumps({"text": text}))
    except OSError:
        pass


# ---------- calling the API safely ----------

def _is_rate_limit(error):
    text = str(error).lower()
    return getattr(error, "code", None) == 429 or "429" in text or "resource_exhausted" in text


def _is_busy(error):
    """Google's side is overloaded or had a hiccup (500, 502, 503, 504). Trying again usually works."""
    text = str(error).lower()
    return getattr(error, "code", None) in (500, 502, 503, 504) or "unavailable" in text or "500 internal" in text


def _call_api(do_call):
    """Run one API call with spacing and retries. `do_call` is a function that makes the call."""
    global _last_call_time
    for attempt in range(len(RETRY_WAITS) + 1):
        wait = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call_time)
        if wait > 0:
            time.sleep(wait)
        try:
            result = do_call()
            _record_call()
            return result
        except Exception as error:
            if not (_is_rate_limit(error) or _is_busy(error)):
                raise
            if attempt == len(RETRY_WAITS):
                raise RuntimeError(
                    "Google is busy or says too many requests, even after 3 retries. "
                    "Wait a few minutes, then try again."
                ) from error
            seconds = RETRY_WAITS[attempt]
            print(f"Google is busy or says too many requests. Waiting {seconds} seconds, then trying again...")
            time.sleep(seconds)
        finally:
            _last_call_time = time.monotonic()


def _text(response):
    return response.text or "(The model sent back no text. Try asking again.)"


def generate_raw(contents, config=None):
    """Make one call and return the full response object (the harness and script 05 use this)."""
    return _call_api(
        lambda: get_client().models.generate_content(model=MODEL, contents=contents, config=config)
    )


# ---------- the three helpers you will use ----------

def ask(prompt, system=None, thinking=False):
    """Ask Gemma a question and get text back. `system` is a rule for the model."""
    key = _cache_key(MODEL, system, prompt, thinking)
    saved = _cache_get(key)
    if saved is not None:
        return saved
    response = generate_raw(prompt, _make_config(system, thinking))
    text = _text(response)
    if response.text:
        _cache_put(key, text)
    return text


def ask_with_image(image_path, prompt, system=None):
    """Ask Gemma about a picture."""
    image_bytes = Path(image_path).read_bytes()
    key = _cache_key(MODEL, system, prompt, image_bytes)
    saved = _cache_get(key)
    if saved is not None:
        return saved

    def upload_and_ask():
        client = get_client()
        my_file = client.files.upload(file=str(image_path))  # send the picture to Google
        return client.models.generate_content(
            model=MODEL, contents=[my_file, prompt], config=_make_config(system, False)
        )

    response = _call_api(upload_and_ask)
    text = _text(response)
    if response.text:
        _cache_put(key, text)
    return text


class GemmaChat:
    """A chat that remembers earlier messages."""

    def __init__(self, system=None):
        self._chat = get_client().chats.create(model=MODEL, config=_make_config(system, False))

    def send_message(self, text):
        return _text(_call_api(lambda: self._chat.send_message(text)))


def make_chat(system=None):
    return GemmaChat(system)


# ---------- friendly errors ----------

def describe_error(error):
    """Turn a scary error into one line of simple advice."""
    if isinstance(error, MissingKeyError):
        return str(error)
    text = str(error)
    low = text.lower()
    if isinstance(error, ModuleNotFoundError):
        return "A package is missing. Fix: activate your virtual environment, then run: pip install -r requirements.txt"
    if _is_rate_limit(error):
        return "Too many requests. Wait a minute and try again. Do not share one key between people."
    if _is_busy(error):
        return "Google had a problem on its side. Wait a minute and try again."
    if "404" in low or "not found" in low:
        return f"Model not found. Check the model name (we use '{MODEL}') and GEMMA_MODEL in your .env."
    if "api key" in low or "api_key" in low or "401" in low or "403" in low or "permission" in low:
        return "Google did not accept your key. Make a fresh key in Google AI Studio and put it in .env."
    if any(word in low for word in ("timed out", "timeout", "connection", "getaddrinfo", "ssl")):
        return "Network problem. Check your Wi-Fi, or try a phone hotspot."
    return "Something went wrong: " + re.sub(r"AIza[0-9A-Za-z_-]{35}", "[key hidden]", text)[:300]


def _friendly_crash(kind, error, trace):
    """If a script crashes, print one line of advice instead of a wall of red text."""
    if issubclass(kind, KeyboardInterrupt) or os.environ.get("GEMMA_DEBUG") == "1":
        sys.__excepthook__(kind, error, trace)
    else:
        print("\nProblem:", describe_error(error))
        print("(For the full technical details, set GEMMA_DEBUG=1 and run again.)")


sys.excepthook = _friendly_crash
