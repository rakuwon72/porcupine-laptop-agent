"""Terminal version: type a command, the agent does it.

Run with:  python main.py
(For the little porcupine on your screen, run:  python mascot.py)
"""

from agent import events
from agent.session import AgentSession


def print_tool_events(kind: str, info: dict) -> None:
    """Show each tool the agent uses, so you can follow what it is doing."""
    if kind == "tool":
        print(f"  [tool] {info['name']}({info['args']})")


def main() -> None:
    events.subscribe(print_tool_events)
    session = AgentSession()  # exits with a clear message if the API key is missing

    print("Laptop agent ready. Type a command (or 'exit' to quit).\n")
    while True:
        text = input("You: ").strip()
        if text.lower() in ("exit", "quit"):
            break
        if text:
            # ask = what to do when the agent has a question: show it and read your answer
            reply = session.run(text, ask=lambda question: input(f"\nAgent asks: {question}\nYou: "))
            print(f"\nAgent: {reply}\n")


if __name__ == "__main__":
    main()
