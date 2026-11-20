"""A plain-text diary of what the agent did: logs/activity.log

Each line: time, then what happened - your command, every tool the agent used
(with its arguments), and the final reply. Open the file any time to see
exactly what happened in a past command, or to check whether it changed anything.

Passwords never appear here: the agent never receives them (sign_in only gets
the site name), and the vault is separate.
"""

from datetime import datetime

from agent import events
from agent.config import ROOT_DIR
from agent.phone_bridge import PHONE_PREFIX

LOG_FILE = ROOT_DIR / "logs" / "activity.log"
MAX_BYTES = 1_000_000        # when the file gets bigger than this, the oldest half is dropped
MAX_LINE = 500               # long texts are shortened so the log stays readable
_attached = False


def _write(line: str) -> None:
    """Append one timestamped line (never let a logging problem break the agent)."""
    try:
        LOG_FILE.parent.mkdir(exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_BYTES:
            data = LOG_FILE.read_text(encoding="utf-8", errors="ignore")
            LOG_FILE.write_text(data[len(data) // 2:], encoding="utf-8")
        text = " ".join(line.split())               # one line per entry
        if len(text) > MAX_LINE:
            text = text[:MAX_LINE] + "..."
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {text}\n")
    except OSError:
        pass


def _on_event(kind: str, info: dict) -> None:
    if kind == "request_start":
        where = " (from phone)" if info.get("source") == "phone" else ""
        _write(f"COMMAND{where}: {info['text'].replace(PHONE_PREFIX, '', 1)}")
    elif kind == "tool":
        _write(f"  tool {info['name']} {info['args']}")
    elif kind == "request_end":
        _write(f"  {'REPLY' if info['ok'] else 'FAILED'}: {info['text']}")


def note(line: str) -> None:
    """Write a custom line (e.g. 'a stranger tried the phone bot') into the diary."""
    _write(line)


def attach() -> None:
    """Start recording (safe to call more than once)."""
    global _attached
    if not _attached:
        events.subscribe(_on_event)
        _attached = True
