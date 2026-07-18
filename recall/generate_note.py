"""generate_note — Phase 0 baseline: transcript -> SOAP clinical note (Opus 4.8).

The generated note is the B0 baseline and the real-detection object.
The provided note (record["note"]) is NEVER modified — it is the gold
reference for the later injection harness.
"""

from __future__ import annotations

from .llm import call_text

PROMPT = """You are an ambient clinical scribe. Given the visit transcript below, write a clinical note in SOAP format (Subjective, Objective, Assessment and Plan) in markdown. Document only what the transcript supports; do not invent findings, vitals, or results that were not stated. Be complete but not redundant.
TRANSCRIPT: {transcript}"""


def generate_note(transcript: str) -> str:
    """Generate a SOAP-format clinical note from an ambient visit transcript."""
    return call_text(PROMPT.format(transcript=transcript), max_tokens=8000)
