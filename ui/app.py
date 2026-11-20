"""The mascot application: wires the porcupine, the chat window and the agent together.

Flow of one message:
  you type in the chat and press Enter
  -> the agent runs in a BACKGROUND THREAD (so the porcupine never freezes)
  -> the agent announces what it is doing (agent/events.py) -> porcupine changes mood,
     the chat shows a status line ("Opening the site...")
  -> the reply is added to the chat, the porcupine hops happily, and the typing box
     is ready again - just keep typing.

If the agent asks YOU something, the question appears in the chat as a message and
your next message is taken as the answer.

Threads: Tk (the screen) may only be touched by the main thread. The worker
thread therefore never touches the UI - it just drops messages into a queue,
and the main thread picks them up every 100 ms (_poll).
"""

import json
import queue
import threading
import time
import tkinter as tk

from agent import controller, events
from agent.config import POINT_AT_CONTROLS, POINT_DELAY_SECONDS, PORCUPINE_FOLLOWS, ROOT_DIR
from agent.phone_bridge import PHONE_PREFIX
from ui import winutil
from ui.chat import ChatPanel
from ui.pointer import PointerOverlay
from ui.porcupine import (ERROR, HAPPY, HEIGHT, IDLE, KEY, LISTENING, SLEEPY, THINKING,
                          WIDTH, WORKING, Porcupine)

POSITION_FILE = ROOT_DIR / "memory" / "ui_position.json"   # remembers where you left the porcupine
SLEEP_AFTER = 10        # seconds of nothing before it curls up and goes to sleep
TYPING_AWAKE = 3        # it looks attentive for this many seconds after each key you press
REPLY_MOOD_TIME = 3.5   # seconds the happy / sad mood lasts after a reply
FRAME_MS = 33           # ~30 animation frames per second

# What the chat says while each tool runs
TOOL_STATUS = {
    "open_app": "Opening the app",
    "open_website": "Opening the site",
    "do_app_action": "Working in the app",
    "do_site_action": "Working on the page",
    "sign_in": "Signing in",
    "read_page": "Reading the page",
    "list_controls": "Looking around",
    "ui_click": "Clicking",
    "ui_type": "Typing",
    "ui_press": "Pressing keys",
    "search_files": "Searching your files",
    "open_path": "Opening the file",
    "remember": "Remembering that",
    "forget": "Forgetting that",
    "learn_website": "Learning this website",
    "save_learned_action": "Saving what I learned",
    "show_recording": "Reviewing my steps",
    "search_web": "Searching the web",
    "fill_form_from_profile": "Filling in the form",
    "list_profile_fields": "Checking your profile",
    "send_to_phone": "Sending to your phone",
    "start_teaching": "Getting ready to watch you",
    "finish_teaching": "Saving what I saw",
    "cancel_teaching": "Stopping",
    "forget_learned": "Forgetting that",
}


class MascotApp:
    def __init__(self, session, notice: str = "", phone=None) -> None:
        """
        session  the agent conversation for the porcupine's own chat
        notice   a line shown at the top of the chat (e.g. "Phone control is ON: ...")
        phone    the running phone bot (phone/launcher.py), or None if it is off
        """
        self.session = session
        self.phone = phone
        self.inbox: queue.Queue = queue.Queue()     # worker thread -> screen
        self.answers: queue.Queue = queue.Queue()   # screen -> worker thread (answers to questions)
        self.busy = False                           # is the agent working right now?
        self.pending_question = False               # is the agent waiting for YOUR answer?
        self.last_activity = time.time()
        self.last_key = 0.0                         # when you last pressed a key in the chat
        self.mood_until = 0.0                       # when a temporary mood (happy/sad) ends
        self.status_text = ""
        self.home = None                            # where the porcupine stands when it is NOT pointing at something
        self._glide_id = 0                          # lets a newer glide cancel an older one

        winutil.enable_dpi_awareness()              # real pixels, so the pointer ring lands exactly on target
        # How long the agent pauses on each control so you can see the pointer (0 = no pause)
        controller.POINT_DELAY = POINT_DELAY_SECONDS if POINT_AT_CONTROLS else 0.0

        # ---- the porcupine's window: borderless, see-through, always on top ----
        self.root = tk.Tk()
        self.root.title("Porcupine")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", KEY)
        self.root.config(bg=KEY)
        self.view = Porcupine(self.root)
        self.view.canvas.pack()
        winutil.set_no_activate(self.root, True)    # clicking it never steals focus from other apps

        self._place_window()
        self.chat = ChatPanel(self.root, self.anchor, on_send=self._on_user_message,
                              on_new_chat=self._new_conversation, on_activity=self._typing)
        self.pointer = PointerOverlay(self.root)
        if notice:
            self.chat.add_agent(notice)               # e.g. whether phone control is on

        # ---- mouse: click = open/close the chat, drag = move, right-click = menu ----
        canvas = self.view.canvas
        canvas.bind("<ButtonPress-1>", self._press)
        canvas.bind("<B1-Motion>", self._drag)
        canvas.bind("<ButtonRelease-1>", self._release)
        canvas.bind("<Button-3>", self._menu)

        # ---- right-click menu ----
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label=f"Phone control: {'ON' if phone else 'off'}", state="disabled")
        self.menu.add_separator()
        self.menu.add_command(label="New conversation", command=self._new_conversation)
        self.menu.add_separator()
        self.menu.add_command(label="Quit", command=self.root.destroy)

        # ---- listen to what the agent is doing ----
        events.subscribe(self._on_agent_event)       # called from the worker thread

        self.root.after(FRAME_MS, self._animate)
        self.root.after(100, self._poll)
        self.root.after(2000, self._keep_on_top)

    # ================================================================ window position
    def _place_window(self) -> None:
        """Start where it was last left, or in the bottom-right corner."""
        x = self.root.winfo_screenwidth() - WIDTH - 30
        y = self.root.winfo_screenheight() - HEIGHT - 90
        try:
            saved = json.loads(POSITION_FILE.read_text(encoding="utf-8"))
            # only use the saved spot if it is still on screen
            if 0 <= saved["x"] <= self.root.winfo_screenwidth() - 60 and 0 <= saved["y"] <= self.root.winfo_screenheight() - 60:
                x, y = saved["x"], saved["y"]
        except (OSError, ValueError, KeyError):
            pass
        self.root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")

    def _save_position(self) -> None:
        try:
            POSITION_FILE.parent.mkdir(exist_ok=True)
            POSITION_FILE.write_text(json.dumps({"x": self.root.winfo_x(), "y": self.root.winfo_y()}),
                                     encoding="utf-8")
        except OSError:
            pass

    def anchor(self) -> tuple[int, int, int, int]:
        """Where the porcupine is on screen (the chat uses this to sit below it)."""
        return self.root.winfo_x(), self.root.winfo_y(), WIDTH, HEIGHT

    def _keep_on_top(self) -> None:
        """Other apps sometimes push themselves above us; pop back up every 2 seconds."""
        self.root.attributes("-topmost", True)
        if self.chat.is_open:
            self.chat.top.attributes("-topmost", True)
        self.root.after(2000, self._keep_on_top)

    # ================================================================ mouse handling
    def _press(self, event) -> None:
        self._press_at = (event.x_root, event.y_root)
        self._start_pos = (self.root.winfo_x(), self.root.winfo_y())
        self._dragged = False
        self._touch()

    def _drag(self, event) -> None:
        dx, dy = event.x_root - self._press_at[0], event.y_root - self._press_at[1]
        if abs(dx) + abs(dy) > 4:           # a real drag, not a click with a shaky hand
            self._dragged = True
        if self._dragged:
            self.root.geometry(f"+{self._start_pos[0] + dx}+{self._start_pos[1] + dy}")
            self.chat.reposition()          # the chat follows

    def _release(self, event) -> None:
        if self._dragged:
            self._save_position()
        else:
            self.chat.toggle()              # click the porcupine = open / close the chat

    def _menu(self, event) -> None:
        self.menu.tk_popup(event.x_root, event.y_root)
        self.menu.grab_release()

    def _touch(self) -> None:
        """Note that something happened (wakes the porcupine up)."""
        self.last_activity = time.time()

    def _typing(self) -> None:
        """You pressed a key in the chat box."""
        self.last_key = time.time()
        self._touch()

    # ================================================================ chat actions
    def _on_user_message(self, text: str) -> None:
        """You pressed Enter in the chat box."""
        self.chat.add_user(text)
        if self.pending_question:
            # The agent asked something earlier - this message is the answer
            self.pending_question = False
            self._start_working("Thinking")
            self.answers.put(text)
        else:
            self._start_working("Thinking")
            threading.Thread(target=self._work, args=(text,), daemon=True).start()

    def _new_conversation(self) -> None:
        """Clear the chat and start the agent's conversation afresh."""
        if self.busy or self.pending_question:
            self.chat.add_agent("I'm in the middle of something - let me finish first.")
            return
        if hasattr(self.session, "reset"):
            self.session.reset()
        self.chat.reset_history()

    def _start_working(self, status: str) -> None:
        """The agent is running: show the status, and let the agent's own clicks pass through us."""
        self.busy = True
        self.status_text = status
        self.view.set_state(THINKING)
        self.chat.set_busy(True)
        self.chat.set_status(status)
        winutil.set_click_through(self.root, True)
        self.chat.set_click_through(True)
        self._touch()

    def _stop_working(self) -> None:
        self.busy = False
        winutil.set_click_through(self.root, False)
        self.chat.set_click_through(False)
        self.chat.set_busy(False)
        self.chat.set_status("")
        self.pointer.hide()
        if self.home is not None:                   # the porcupine walks back to where it was
            self._glide_to(*self.home)
            self.home = None

    # ================================================================ pointing
    def _point_at(self, rect, caption: str) -> None:
        """The agent is about to use a control: ring it, and walk the porcupine over next to it."""
        if POINT_AT_CONTROLS:
            self.pointer.show(rect, caption, seconds=POINT_DELAY_SECONDS + 0.6)
        if PORCUPINE_FOLLOWS:
            if self.home is None:
                self.home = (self.root.winfo_x(), self.root.winfo_y())
            left, top, right, bottom = rect
            screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            x = left - WIDTH - 14                    # stand to the LEFT of the control (it faces right)
            if x < 0:
                x = right + 14                       # no room on the left: stand to the right
            y = (top + bottom) // 2 - HEIGHT // 2
            self._glide_to(min(max(x, 0), screen_w - WIDTH), min(max(y, 0), screen_h - HEIGHT))

    def _glide_to(self, x: int, y: int, ms: int = 320) -> None:
        """Slide the porcupine to (x, y) smoothly, taking the chat along."""
        start_x, start_y = self.root.winfo_x(), self.root.winfo_y()
        steps = max(1, ms // FRAME_MS)
        self._glide_id += 1
        my_id = self._glide_id

        def step(i: int) -> None:
            if my_id != self._glide_id:              # a newer glide took over
                return
            ease = 1 - (1 - i / steps) ** 3          # fast start, gentle stop
            self.root.geometry(f"+{int(start_x + (x - start_x) * ease)}+{int(start_y + (y - start_y) * ease)}")
            self.chat.reposition()
            if i < steps:
                self.root.after(FRAME_MS, step, i + 1)

        step(1)

    # ================================================================ the worker thread
    def _work(self, text: str) -> None:
        """Runs in the background: call the agent and post its reply (or error)."""
        reply = self.session.run(text, ask=self._ask_from_worker)
        self.inbox.put(("reply", {"text": reply, "ok": self.session.last_ok}))

    def _ask_from_worker(self, question: str) -> str:
        """The agent has a question: send it to the screen, then WAIT for the answer."""
        self.inbox.put(("ask", {"question": question}))
        return self.answers.get()

    def _on_agent_event(self, kind: str, info: dict) -> None:
        """Called by agent/events.py from the worker thread - just queue it."""
        self.inbox.put((kind, info))

    # ================================================================ screen updates (main thread)
    def _poll(self) -> None:
        """Every 100 ms: handle everything the worker thread has sent us."""
        try:
            while True:
                kind, info = self.inbox.get_nowait()
                self._handle(kind, info)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _handle(self, kind: str, info: dict) -> None:
        if kind == "thinking" and self.busy:
            self.status_text = "Thinking"
            self.view.set_state(THINKING)
        elif kind == "tool" and self.busy:
            self.status_text = TOOL_STATUS.get(info["name"], f"Using {info['name']}")
            self.view.set_state(WORKING)
        elif kind == "point" and self.busy:
            self._point_at(info["rect"], info["caption"])
        elif kind == "request_start" and info.get("source") == "phone":
            # A request arrived from the phone: show it, and make the porcupine work for it.
            # (The chat is locked meanwhile, so you cannot start a second job on the same laptop.)
            self.chat.add_user("[phone] " + info["text"].replace(PHONE_PREFIX, "", 1))
            self._start_working("Working on a request from your phone")
        elif kind == "request_end" and info.get("source") == "phone":
            self._stop_working()
            self.chat.add_agent("[to phone] " + info["text"], error=not info["ok"])
            self.view.set_state(HAPPY if info["ok"] else ERROR)
            self.mood_until = time.time() + REPLY_MOOD_TIME
            self._touch()
        elif kind == "teach_start":
            self.view.recording = True           # show the REC badge
        elif kind == "teach_stop":
            self.view.recording = False
        elif kind == "ask":
            # The agent has a question for you: show it in the chat; your next message answers it
            self._stop_working()
            self.pending_question = True
            self.chat.add_agent(info["question"])
            self.view.set_state(LISTENING)
            self._touch()
            self._show_chat()
        elif kind == "reply":
            self._stop_working()
            self.chat.add_agent(info["text"], error=not info["ok"])
            self.view.set_state(HAPPY if info["ok"] else ERROR)
            self.mood_until = time.time() + REPLY_MOOD_TIME
            self._touch()
            self._show_chat()

    def _show_chat(self) -> None:
        """Make sure the chat is visible with the cursor in the typing box, ready for your reply."""
        if self.chat.is_open:
            self.chat.focus_input()
        else:
            self.chat.open()                 # (open() also puts the cursor in the box)

    def _animate(self) -> None:
        """~30 times a second: draw one frame, and handle timed mood changes."""
        now = time.time()
        # temporary moods end by themselves
        if self.view.state in (HAPPY, ERROR) and now > self.mood_until:
            self.view.set_state(IDLE)

        # attentive while you type, calm otherwise, asleep when ignored for a while
        if not self.busy and self.view.state in (IDLE, LISTENING, SLEEPY):
            if now - self.last_key < TYPING_AWAKE:
                self.view.set_state(LISTENING)
            elif now - self.last_activity > SLEEP_AFTER:
                self.view.set_state(SLEEPY)
            else:
                self.view.set_state(IDLE)

        # animated "..." after the status words
        if self.busy:
            self.chat.set_status(self.status_text + "." * (int(now * 2.5) % 4))
        self.view.draw()
        self.root.after(FRAME_MS, self._animate)

    def run(self) -> None:
        self.root.mainloop()
