"""Backend-only credentials supplied by Electron's .env loader or explicit environment."""
import os
import re


def load_key():
    value = os.getenv('AVALAI_API_KEY') or os.getenv('OPENAI_API_KEY') or ''
    if value and not re.fullmatch(r'[!-~]{8,4096}', value):
        raise RuntimeError('Invalid API credential format.')
    return value
