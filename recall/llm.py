"""Shared Anthropic client + robust JSON handling for the RECALL pipeline.

All LLM calls in this session use Opus 4.8 (claude-opus-4-8) and prompt for
JSON-only output; parse_json_loose strips prose/fences before json.loads.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import anthropic

MODEL = os.environ.get("RECALL_MODEL", "claude-opus-4-8")

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from .env at the repo root (no external dep)."""
    env_path = _REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        os.environ.setdefault(key, value)


_load_dotenv()

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env/.env
    return _client


# Aggregate usage across all calls this process makes (thread-safe enough for
# counters; verified via usage_summary() at end of runs).
USAGE = {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0, "calls": 0}


def usage_summary() -> str:
    total_in = USAGE["input"] + USAGE["cache_read"] + USAGE["cache_write"]
    hit_pct = (USAGE["cache_read"] / total_in * 100) if total_in else 0.0
    return (
        f"{USAGE['calls']} calls · input {USAGE['input']:,} uncached "
        f"+ {USAGE['cache_write']:,} cache-written + {USAGE['cache_read']:,} cache-read "
        f"({hit_pct:.0f}% of input from cache) · output {USAGE['output']:,}"
    )


def _build_content(prompt) -> list[dict] | str:
    """str -> passthrough. list of {"text", "cache"?} -> content blocks with
    cache_control breakpoints on blocks flagged cache=True (prefix caching:
    put stable content first, varying content after the last breakpoint)."""
    if isinstance(prompt, str):
        return prompt
    content = []
    for block in prompt:
        item = {"type": "text", "text": block["text"]}
        if block.get("cache"):
            item["cache_control"] = {"type": "ephemeral"}
        content.append(item)
    return content


def call_text(
    prompt, max_tokens: int = 8000, model: str | None = None, _retried: bool = False
) -> str:
    """One-shot completion. `prompt` is a string OR a list of blocks
    [{"text": ..., "cache": True}] for prompt-caching (see _build_content).

    Adaptive-thinking tokens count toward max_tokens, so a truncated response
    is retried once at double the budget before giving up.
    """
    use_model = model or MODEL
    kwargs: dict = {}
    # Opus 4.8 runs WITHOUT thinking when the field is omitted — enable
    # adaptive thinking explicitly. Haiku 4.5 doesn't support adaptive
    # thinking (older generation) — omit the field there.
    if "haiku" not in use_model:
        kwargs["thinking"] = {"type": "adaptive"}
    response = client().messages.create(
        model=use_model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": _build_content(prompt)}],
        **kwargs,
    )
    USAGE["calls"] += 1
    USAGE["input"] += response.usage.input_tokens
    USAGE["cache_read"] += response.usage.cache_read_input_tokens or 0
    USAGE["cache_write"] += response.usage.cache_creation_input_tokens or 0
    USAGE["output"] += response.usage.output_tokens
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Model refused the request (stop_details={response.stop_details})")
    if response.stop_reason == "max_tokens":
        if not _retried and max_tokens < 32000:
            return call_text(prompt, max_tokens=max_tokens * 2, model=model, _retried=True)
        raise RuntimeError(f"Response truncated at max_tokens={max_tokens} even after retry")
    return "".join(b.text for b in response.content if b.type == "text").strip()


def parse_json_loose(text: str):
    """Parse JSON out of model output that may include prose or code fences."""
    text = text.strip()
    # Strip a markdown code fence if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost JSON array/object in the text.
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start, end = text.find(open_ch), text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"Could not parse JSON from model output:\n{text[:500]}")


def call_json(prompt, max_tokens: int = 16000, model: str | None = None):
    """JSON-only completion with one strict-reminder retry on parse failure.

    Accepts a string or a block list (see call_text); the retry reminder is
    appended after the cached prefix so retries still hit the cache.
    """
    raw = call_text(prompt, max_tokens=max_tokens, model=model)
    try:
        return parse_json_loose(raw)
    except ValueError:
        reminder = (
            "\n\nIMPORTANT: Your previous response was not valid JSON. "
            "Return ONLY the JSON value — no prose, no markdown fences."
        )
        if isinstance(prompt, str):
            retry_prompt = prompt + reminder
        else:
            retry_prompt = prompt + [{"text": reminder}]
        raw = call_text(retry_prompt, max_tokens=max_tokens, model=model)
        return parse_json_loose(raw)
