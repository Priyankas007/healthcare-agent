# RECALL

Detects clinically important omissions in AI-generated clinical notes using the visit transcript and FHIR context.

Hackathon project for the [Synthetic Ambient FHIR Encounters](synthetic-ambient-fhir-25/) dataset (25 synthetic encounters).

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install anthropic
echo "ANTHROPIC_API_KEY=..." > .env
```

## Run

```bash
python run_checkpoint0.py   # baseline notes
python run_checkpoint1.py   # extract facts + check presence
python run_checkpoint2.py   # injection eval
python run_checkpoint3.py   # severity + surfacing
python run_checkpoint4.py   # patch + verify
python run_checkpoint6.py   # FHIR writeback demo
```

Results are written to `checkpoint_*.md`. See `TODOS.md` for status.
