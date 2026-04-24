from __future__ import annotations

import os
import warnings
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any

try:
    from openai import OpenAI
except ModuleNotFoundError:
    OpenAI = None

try:
    import anthropic
except ModuleNotFoundError:
    anthropic = None

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        import google.generativeai as genai
except ModuleNotFoundError:
    genai = None


OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "auto").strip().lower() or "auto"


class LLMUnavailableError(RuntimeError):
    pass


def provider_status() -> dict[str, bool]:
    return {
        "openai": bool(OpenAI and os.getenv("OPENAI_API_KEY", "").strip()),
        "anthropic": bool(anthropic and os.getenv("ANTHROPIC_API_KEY", "").strip()),
        "gemini": bool(genai and os.getenv("GEMINI_API_KEY", "").strip()),
        "local": True,
    }


def default_provider_name() -> str:
    try:
        return resolve_provider(None)
    except LLMUnavailableError:
        return "local"


def resolve_provider(requested: str | None) -> str:
    desired = (requested or DEFAULT_PROVIDER or "auto").strip().lower()
    statuses = provider_status()

    if desired in {"local", "none"}:
        return "local"

    if desired and desired != "auto":
        if statuses.get(desired):
            return desired
        raise LLMUnavailableError(f"{desired.title()} is not configured.")

    for candidate in ("openai", "anthropic", "gemini"):
        if statuses.get(candidate):
            return candidate
    raise LLMUnavailableError("No external LLM provider is configured.")


def generate_text(
    prompt: str,
    provider: str | None = None,
    *,
    temperature: float = 0.2,
    max_tokens: int = 900,
) -> tuple[str, str]:
    resolved = resolve_provider(provider)
    if resolved == "local":
        raise LLMUnavailableError("Local provider does not generate external responses.")

    def _run() -> str:
        if resolved == "openai":
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", "").strip(), timeout=20.0)
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content or ""

        if resolved == "anthropic":
            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(), timeout=20.0)
            response = client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            parts = []
            for block in getattr(response, "content", []) or []:
                text = getattr(block, "text", "")
                if text:
                    parts.append(text)
            return "".join(parts)

        if resolved == "gemini":
            genai.configure(api_key=os.getenv("GEMINI_API_KEY", "").strip())
            model = genai.GenerativeModel(GEMINI_MODEL)
            response = model.generate_content(
                prompt,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                },
            )
            return getattr(response, "text", "") or ""

        raise LLMUnavailableError(f"Unsupported provider: {resolved}")

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run)
            return future.result(timeout=20), resolved
    except FuturesTimeout as exc:
        raise RuntimeError(f"{resolved.title()} request timed out.") from exc
