"""One conversation with the agent - shared by the terminal (main.py) and the
porcupine mascot (mascot.py), so error handling lives in exactly one place.
"""

import itertools
import threading

from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from agent import activity_log, events
from agent.config import check_api_key
from agent.graph import build_graph

# Stop a single command after this many steps, so a confused agent
# can never loop forever (each tool call + model reply counts as steps).
MAX_STEPS = 90  # a backstop only: the agent itself stops gracefully after SOFT_STEP_LIMIT tool calls

# Gives every fresh conversation its own id: 1, 2, 3...
_thread_numbers = itertools.count(1)

# The laptop has ONE mouse, keyboard and screen. The porcupine's chat and the phone bot each have
# their own conversation, but only one request may run at a time - otherwise they would fight
# over the same windows. A second request is told "busy" instead of waiting.
_RUN_LOCK = threading.Lock()


def new_config(confirm_risky: bool | None = None) -> dict:
    """Settings for a new conversation. Same thread_id -> the agent remembers earlier commands.

    confirm_risky: True/False forces "ask before risky actions" on/off for this
    conversation; None follows the global setting in config.py.
    """
    configurable = {"thread_id": f"laptop-session-{next(_thread_numbers)}"}
    if confirm_risky is not None:
        configurable["confirm_risky"] = confirm_risky
    return {"configurable": configurable, "recursion_limit": MAX_STEPS}


class AgentSession:
    """Holds the compiled agent graph and the current conversation."""

    def __init__(self, confirm_risky: bool | None = None, source: str = "desktop") -> None:
        """source = who talks to this session ("desktop" or "phone"); it is attached to events and the log."""
        check_api_key()
        activity_log.attach()   # keep a diary in logs/activity.log
        self.source = source
        self.confirm_risky = confirm_risky
        self.graph = build_graph()
        self.config = new_config(confirm_risky)
        self.last_ok = True  # did the last run() finish without an error?

    def reset(self) -> None:
        """Start a fresh conversation (the agent forgets this chat, but not its saved memory)."""
        self.config = new_config(self.confirm_risky)

    def run(self, text: str, ask) -> str:
        """Run one command (see _run) and announce its start and end (for the log and the porcupine)."""
        if not _RUN_LOCK.acquire(blocking=False):      # another request already owns the laptop
            self.last_ok = False
            return "I'm busy with another request right now - please try again in a moment."
        try:
            events.emit("request_start", text=text, source=self.source)
            reply = self._run(text, ask)
            events.emit("request_end", text=reply, ok=self.last_ok, source=self.source)
            return reply
        finally:
            _RUN_LOCK.release()

    def _run(self, text: str, ask) -> str:
        """Run one command and return the agent's final reply as text.

        ask(question) -> answer   is called whenever the agent needs to ask the
        user something (the terminal uses input(), the mascot uses its bubble).

        This never raises: problems come back as a message, and the
        conversation is reset so the next command starts clean.
        """
        self.last_ok = True
        try:
            result = self.graph.invoke({"messages": [("user", text)]}, self.config)

            # If the agent called ask_user, the graph is paused and the result holds
            # an "__interrupt__" entry. Keep asking until the agent has what it needs.
            while "__interrupt__" in result:
                question = result["__interrupt__"][0].value
                answer = ask(question)
                # Command(resume=...) continues the paused graph with the user's answer
                result = self.graph.invoke(Command(resume=answer), self.config)

            return result["messages"][-1].text or "Done."

        except GraphRecursionError:
            self.last_ok = False
            self.config = new_config(self.confirm_risky)  # fresh conversation so half-done work can't confuse it
            return (f"I stopped after {MAX_STEPS} steps without finishing - I was going in "
                    "circles. Try rephrasing or doing it in smaller steps.")
        except Exception as error:
            self.last_ok = False
            # A crash can leave a conversation half-finished (a tool call with no
            # result), which the AI service rejects. A new thread avoids that.
            self.config = new_config(self.confirm_risky)
            return f"Something went wrong: {error}"
