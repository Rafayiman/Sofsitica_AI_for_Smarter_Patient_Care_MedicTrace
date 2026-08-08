"""Groq API wrapper (config via .env.example).

Returns None when GROQ_API_KEY is unset so callers can degrade gracefully.
"""
import os

from dotenv import load_dotenv

load_dotenv()

MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

_client = None


def get_client():
    global _client
    if not os.getenv("GROQ_API_KEY"):
        return None
    if _client is None:
        from groq import Groq

        _client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _client


def chat(system: str, user: str, temperature: float = 0.1) -> str | None:
    client = get_client()
    if client is None:
        return None
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content
