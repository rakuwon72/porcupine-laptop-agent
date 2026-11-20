"""A pretend agent, so you can play with the porcupine WITHOUT an API key.

Run:  python mascot.py --demo
Try:  "hello"            -> thinks, uses a tool, replies
      "ask me something" -> it asks YOU a question first
      "fail"             -> shows the sad / error mood
      "long"             -> a long reply, to see the scrollbar
"""

import time

from agent import events


class DemoSession:
    last_ok = True

    def reset(self) -> None:
        pass

    def run(self, text: str, ask) -> str:
        self.last_ok = True
        events.emit("thinking")
        if text.lower().startswith("quick"):          # a fast reply, handy for testing
            time.sleep(0.4)
            return f"(demo) quick reply to: {text}"
        time.sleep(1.5)

        if "ask" in text.lower():
            answer = ask("Which website should I open?")
            events.emit("thinking")
            time.sleep(1.0)
            text = f"{text} (you answered: {answer})"

        for tool in ("open_website", "read_page", "ui_type"):
            events.emit("tool", name=tool, args={})
            if tool == "ui_type":
                # Pretend to point at a button in the middle of the screen, to show the pointer
                import ctypes
                width, height = ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
                left, top = width // 2 - 110, height // 2 - 20
                events.emit("point", rect=(left, top, left + 220, top + 40), caption="Typing into Search box")
            time.sleep(1.4)
        events.emit("thinking")
        time.sleep(1.0)

        if "fail" in text.lower():
            self.last_ok = False
            return "Something went wrong: this is only a demo error. Don't worry!"
        if "long" in text.lower():
            return "\n".join(f"{n}. This is line number {n} of a long demo reply." for n in range(1, 30))
        return f"(demo) You said: {text}\n\nWith a real API key I would do this for real."
