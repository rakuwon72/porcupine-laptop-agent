"""Starts the porcupine mascot - and, if you set it up, phone control with it.

    python mascot.py          the real agent (needs your API key in .env) + phone control
    python mascot.py --demo   a pretend agent, to try the porcupine without a key (no phone control)

Double-click run_porcupine.bat to start it without a console window.
Phone control starts automatically when the porcupine starts (see phone.py for the one-time
setup, and PHONE_AUTOSTART=false in .env to turn that off).
"""

import sys
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import messagebox

LOG_FILE = Path(__file__).resolve().parent / "mascot_error.log"


def show_error(message: str) -> None:
    """Without a console window (pythonw) errors would be invisible, so use a pop-up."""
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Porcupine", message)
    root.destroy()


def main() -> None:
    try:
        phone = None
        if "--demo" in sys.argv:
            from ui.demo import DemoSession
            session = DemoSession()
            notice = "Demo mode: this is a pretend agent, and phone control is not started."
        else:
            from agent.session import AgentSession
            session = AgentSession()          # exits with a message if the API key is missing
            from phone.launcher import start_in_background
            try:
                phone, notice = start_in_background()   # phone control starts together with the porcupine
            except Exception as error:                  # a phone problem must never stop the porcupine itself
                phone, notice = None, f"Phone control could not start: {error}"

        from ui.app import MascotApp
        MascotApp(session, notice=notice, phone=phone).run()
        if phone:
            phone.stop()

    except SystemExit as stop:                # e.g. missing API key
        show_error(str(stop))
    except Exception:
        LOG_FILE.write_text(traceback.format_exc(), encoding="utf-8")
        show_error(f"The porcupine crashed. Details were saved in:\n{LOG_FILE}")


if __name__ == "__main__":
    main()
