"""Long-term memory: a short list of facts about the user, kept between sessions.

Examples of facts: "My physics course folder is D:\\Courses\\Physics",
"I prefer replies signed 'Alex'", "My college email is alex@example.edu".

How it works:
  - Facts live in memory/memory.json (a plain list you can open and edit yourself).
  - Every turn, graph.py pastes the facts into the system prompt, so Claude
    "remembers" them in every new session.
  - Claude saves/removes facts with the `remember` / `forget` tools (tools.py).

Because the facts are sent to Claude, NEVER store passwords or secrets here.
"""

import json
import re

from agent.config import ROOT_DIR

MEMORY_FILE = ROOT_DIR / "memory" / "memory.json"
MAX_FACTS = 100  # keeps the prompt small
MAX_FACT_LENGTH = 300

# Words that suggest a secret. Facts matching this are refused.
SECRET_PATTERN = re.compile(r"(pass(word|code)?|pwd|pin|otp|secret|api[ _-]?key|token)\s*(is|:|=)", re.IGNORECASE)


def load_facts() -> list[str]:
    """Read all saved facts (empty list if there are none yet)."""
    if not MEMORY_FILE.exists():
        return []
    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []  # a damaged file must never crash the agent


def _save(facts: list[str]) -> None:
    MEMORY_FILE.parent.mkdir(exist_ok=True)
    MEMORY_FILE.write_text(json.dumps(facts, indent=2, ensure_ascii=False), encoding="utf-8")


def add_fact(fact: str) -> str:
    """Save a new fact. Returns a message describing what happened."""
    fact = " ".join(fact.split())  # tidy whitespace
    if not fact:
        return "Nothing to remember."
    if SECRET_PATTERN.search(fact):
        return "Refused: that looks like a password or secret. Secrets belong in the vault, not memory."
    if len(fact) > MAX_FACT_LENGTH:
        return f"Too long (max {MAX_FACT_LENGTH} characters). Save a shorter version."

    facts = load_facts()
    if fact.lower() in (f.lower() for f in facts):
        return "Already remembered."
    if len(facts) >= MAX_FACTS:
        return "Memory is full. Forget something first."
    facts.append(fact)
    _save(facts)
    return f"Remembered: {fact}"


def remove_fact(text: str) -> str:
    """Delete every fact that contains `text` (ignoring case)."""
    facts = load_facts()
    kept = [f for f in facts if text.lower() not in f.lower()]
    removed = len(facts) - len(kept)
    if removed == 0:
        return "No saved fact matches that."
    _save(kept)
    return f"Forgot {removed} fact(s)."


def memory_summary() -> str:
    """Text for the system prompt: the saved facts as a bullet list."""
    facts = load_facts()
    if not facts:
        return "(nothing saved yet)"
    return "\n".join(f"- {fact}" for fact in facts)
