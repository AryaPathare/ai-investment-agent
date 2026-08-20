"""Health check for the local development environment.

Run this FIRST whenever something breaks. It answers the question "is it my
config, is Groq down, or is it my code?" before you start debugging the wrong
layer.

Usage (from the project root):
    python -m scripts.check_setup

Exits 0 if everything works, 1 if anything fails.
"""

import sys
from pathlib import Path

# Allow running as a plain script (python scripts/check_setup.py) as well as a
# module, by making sure the project root is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PROJECT_ROOT, get_llm, get_settings  # noqa: E402


def main() -> int:
    print("Checking environment...\n")

    # --- 1. Does the .env file exist? --------------------------------------
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        print(f"FAIL  No .env file at {env_path}")
        print("      Fix: Copy-Item .env.example .env, then add your key.")
        return 1
    print(f"OK    .env found at {env_path}")

    # --- 2. Do the settings load and validate? -----------------------------
    try:
        settings = get_settings()
    except RuntimeError as exc:
        print(f"FAIL  Configuration invalid:\n{exc}")
        return 1

    # Safe to print: the API key is a SecretStr and renders as asterisks.
    print("OK    Settings loaded")
    print(f"        model       = {settings.groq_model}")
    print(f"        temperature = {settings.llm_temperature}")
    print(f"        timeout     = {settings.llm_timeout_seconds}s")
    print(f"        max_retries = {settings.llm_max_retries}")

    # --- 3. Can we actually reach the model? -------------------------------
    print("\n      Calling Groq (this is a real network request)...")
    try:
        response = get_llm().invoke("Reply with the single word: pong")
    except Exception as exc:  # noqa: BLE001 - this is a diagnostic, report anything
        print(f"FAIL  Could not reach the model: {type(exc).__name__}: {exc}")
        print("      Likely causes: bad/expired API key, no internet, Groq")
        print("      outage, or rate limit. Check https://console.groq.com")
        return 1

    print(f"OK    Model replied: {response.content.strip()!r}")
    print("\nEnvironment is healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
