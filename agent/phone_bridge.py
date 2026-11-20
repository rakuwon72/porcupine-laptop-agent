"""The link between the agent and the phone: lets the agent hand a FILE to the phone.

The phone bot (phone/bot.py) calls begin() before a request and end() afterwards.
While a request from the phone is running, the agent's send_to_phone tool puts
files into the "outbox"; the bot sends them once the answer is ready.
If no phone request is running, the tool just says so - it cannot send anything.

Safety rules for files (so the phone can never pull arbitrary things off the laptop):
  - the file must be inside the allowed folders (FILE_ROOTS in agent/config.py)
  - only documents / images / media / zip files - never programs or scripts
  - at most MAX_BYTES (Telegram bots can send up to 50 MB)
"""

from pathlib import Path

from langchain_core.tools import tool

from agent.files import SAFE_EXTENSIONS, is_allowed

MAX_BYTES = 45 * 1024 * 1024

# Added in front of every request that comes from the phone, so the agent knows to describe
# results in words (the user can't see the screen) and to use send_to_phone for files.
PHONE_PREFIX = "(From the user's phone - they cannot see the laptop screen.) "

_outbox: list[tuple[str, str]] | None = None     # (path, caption) of files to send; None = no phone request running


def begin() -> None:
    """A request from the phone starts: open the outbox."""
    global _outbox
    _outbox = []


def end() -> list[tuple[str, str]]:
    """The request is finished: close the outbox and return the files that were queued."""
    global _outbox
    files, _outbox = (_outbox or []), None
    return files


@tool
def send_to_phone(path: str, caption: str = "") -> str:
    """Send a file from this laptop to the user's phone (only works for requests that came from the phone).

    path:    full path of the file (find it first with search_files).
    caption: optional short text shown with the file.
    Only documents, images, media and zip files inside the allowed folders can be sent.
    """
    if _outbox is None:
        return "No phone is connected for this request, so I can't send a file. Tell the user where the file is."
    target = Path(path)
    if not target.is_file():
        return f"'{path}' is not a file. Use search_files to find the right path."
    if not is_allowed(target):
        return "That file is outside the folders I'm allowed to use, so I can't send it."
    if target.suffix.lower() not in SAFE_EXTENSIONS:
        return f"I only send documents, images, media and zip files - not '{target.suffix}' files."
    if target.stat().st_size > MAX_BYTES:
        return "That file is too big to send (limit 45 MB)."
    _outbox.append((str(target), caption))
    return f"Queued {target.name} - it will arrive on the phone together with my answer."


# graph.py adds these to the agent's tool list
PHONE_TOOLS = [send_to_phone]
