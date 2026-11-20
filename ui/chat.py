"""The small chat window that sits below the porcupine.

It is built ONCE and kept: a scrolling history (your messages on the right, the
agent's on the left), a status line ("Reading the page...") and a text box that is
always ready, so you can keep typing message after message without clicking.

It is its own borderless window, shaped like a rounded bubble with a tail
pointing at the porcupine (up, or down if there is no room below).
"""

import re
import tkinter as tk

from ui import winutil
from ui.porcupine import KEY

# --- look ---
CREAM = "#fff8e7"
BROWN = "#4a3426"
BORDER = "#8a5a3a"
GRAY = "#9a8a7a"
USER_BG = "#ffe2a8"       # your messages
AGENT_BG = "#ffffff"      # the agent's messages
ERROR_BG = "#ffd9d6"      # when something went wrong
FONT = ("Segoe UI", 10)

PAD = 12            # space between the window edge and its content
TAIL = 14           # height of the little pointer
RADIUS = 16         # roundness of the corners
CHAT_CHARS = 38     # width of the history, in characters
CHAT_LINES = 12     # height of the history, in lines
INPUT_CHARS = 30    # width of the typing box

WELCOME = "Hi! I'm your porcupine. Tell me what to do and I'll do it on your laptop."


def plain(text: str) -> str:
    """Strip markdown symbols (**bold**, `code`, # headings) that look ugly in a chat."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    return text.strip()


def rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    """Draw a rectangle with rounded corners (a smoothed polygon)."""
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
              x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, **kw)


class ChatPanel:
    def __init__(self, root, get_anchor, on_send, on_new_chat, on_activity) -> None:
        """
        get_anchor()    -> (x, y, width, height) of the porcupine on screen
        on_send(text)   called when you press Enter / Send
        on_new_chat()   called when you click "new chat"
        on_activity()   called on every key press (so the porcupine stays awake while you type)
        """
        self.root = root
        self.get_anchor = get_anchor
        self.on_send = on_send
        self.on_new_chat = on_new_chat
        self.on_activity = on_activity
        self.is_open = False
        self.busy = False
        self.sent_texts: list[str] = []     # what you sent, for the up-arrow key
        self._recall = 0

        # ---- the window: borderless, see-through corners, always on top ----
        self.top = tk.Toplevel(root)
        self.top.withdraw()
        self.top.title("Porcupine chat")
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.attributes("-transparentcolor", KEY)
        self.top.config(bg=KEY)
        self.canvas = tk.Canvas(self.top, bg=KEY, highlightthickness=0)
        self.canvas.pack()
        self.frame = tk.Frame(self.canvas, bg=CREAM)
        self._frame_window = self.canvas.create_window(0, 0, window=self.frame, anchor="nw")

        self._build_content()
        self.reset_history()

    # ================================================================ building the content (once)
    def _build_content(self) -> None:
        frame = self.frame

        # --- header: title on the left, "new chat" and close on the right ---
        header = tk.Frame(frame, bg=CREAM)
        header.pack(fill="x")
        tk.Label(header, text="Chat", bg=CREAM, fg=BROWN, font=("Segoe UI", 10, "bold")).pack(side="left")
        close = tk.Label(header, text="✕", bg=CREAM, fg=GRAY, font=("Segoe UI", 10, "bold"), cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.close())
        new_chat = tk.Label(header, text="new chat", bg=CREAM, fg=GRAY, font=("Segoe UI", 9, "underline"),
                            cursor="hand2")
        new_chat.pack(side="right", padx=(0, 10))
        new_chat.bind("<Button-1>", lambda e: self.on_new_chat())

        # --- the conversation (a read-only Text widget with coloured "bubbles") ---
        body = tk.Frame(frame, bg=CREAM)
        body.pack(fill="both", pady=(4, 0))
        self.history = tk.Text(body, width=CHAT_CHARS, height=CHAT_LINES, wrap="word", bg=CREAM, fg=BROWN,
                               font=FONT, relief="flat", highlightthickness=0, padx=2, pady=2, cursor="arrow")
        scrollbar = tk.Scrollbar(body, command=self.history.yview)
        self.history.config(yscrollcommand=scrollbar.set)
        self.history.pack(side="left")
        scrollbar.pack(side="right", fill="y")
        self.history.bind("<MouseWheel>", lambda e: self.history.yview_scroll(-1 * (e.delta // 120), "units"))
        # Your messages sit on the right, the agent's on the left
        self.history.tag_config("user", background=USER_BG, justify="right", lmargin1=36, lmargin2=36,
                                rmargin=6, spacing1=4, spacing3=4)
        self.history.tag_config("agent", background=AGENT_BG, justify="left", lmargin1=6, lmargin2=6,
                                rmargin=36, spacing1=4, spacing3=4)
        self.history.tag_config("error", background=ERROR_BG, justify="left", lmargin1=6, lmargin2=6,
                                rmargin=36, spacing1=4, spacing3=4)
        self.history.tag_config("gap", spacing1=0, spacing3=0, font=("Segoe UI", 3))

        # --- status line ("Reading the page...") - always present so the window size never jumps ---
        self.status = tk.Label(frame, text="", bg=CREAM, fg=GRAY, font=("Segoe UI", 9, "italic"), anchor="w")
        self.status.pack(fill="x", pady=(4, 0))

        # --- the typing box + Send button ---
        row = tk.Frame(frame, bg=CREAM)
        row.pack(fill="x", pady=(2, 0))
        self.entry = tk.Entry(row, width=INPUT_CHARS, font=FONT, relief="solid", bd=1, bg="white",
                              fg=BROWN, insertbackground=BROWN, disabledbackground="#eee")
        self.entry.pack(side="left", ipady=3)
        self.send_button = tk.Button(row, text="Send", font=("Segoe UI", 9, "bold"), bg="#e8c58f", fg=BROWN,
                                     relief="flat", padx=8, cursor="hand2", command=self._send)
        self.send_button.pack(side="left", padx=(6, 0))

        self.entry.bind("<Return>", lambda e: self._send())
        self.entry.bind("<Escape>", lambda e: self.close())
        self.entry.bind("<Up>", lambda e: self._recall_message(-1))
        self.entry.bind("<Down>", lambda e: self._recall_message(+1))
        self.entry.bind("<Key>", lambda e: self.on_activity())

    # ================================================================ the conversation
    def reset_history(self) -> None:
        """Empty the conversation and show the welcome message."""
        self.history.config(state="normal")
        self.history.delete("1.0", "end")
        self.history.config(state="disabled")
        self.add_agent(WELCOME)

    def _append(self, text: str, tag: str) -> None:
        self.history.config(state="normal")
        self.history.insert("end", plain(text) + "\n", tag)
        self.history.insert("end", "\n", "gap")          # a thin gap between messages
        self.history.config(state="disabled")
        self.history.see("end")                          # scroll to the newest message

    def add_user(self, text: str) -> None:
        self._append(text, "user")

    def add_agent(self, text: str, error: bool = False) -> None:
        self._append(text, "error" if error else "agent")

    def set_status(self, text: str) -> None:
        self.status.config(text=text)

    # ================================================================ sending
    def _send(self) -> None:
        text = self.entry.get().strip()
        if not text or self.busy:
            return
        self.entry.delete(0, "end")
        self.sent_texts.append(text)
        self._recall = len(self.sent_texts)
        self.on_send(text)

    def _recall_message(self, step: int) -> str:
        """Up / Down arrow: bring back what you typed earlier."""
        if self.sent_texts:
            self._recall = min(max(self._recall + step, 0), len(self.sent_texts))
            self.entry.delete(0, "end")
            if self._recall < len(self.sent_texts):
                self.entry.insert(0, self.sent_texts[self._recall])
        return "break"

    def set_busy(self, busy: bool) -> None:
        """While the agent works: the box is disabled, and the window never takes focus."""
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.entry.config(state=state)
        self.send_button.config(state=state)
        winutil.set_no_activate(self.top, busy)

    def focus_input(self) -> None:
        """Put the cursor in the typing box (even if another window is in front)."""
        if self.busy or not self.is_open:
            return
        winutil.force_foreground(self.top)
        self.top.focus_force()
        self.entry.focus_force()

    # ================================================================ showing / hiding / placing
    def open(self) -> None:
        self.layout()
        self.is_open = True
        self.top.deiconify()
        self.top.lift()
        self.top.attributes("-topmost", True)
        winutil.set_no_activate(self.top, self.busy)
        self.focus_input()

    def close(self) -> None:
        self.is_open = False
        self.top.withdraw()

    def toggle(self) -> None:
        self.close() if self.is_open else self.open()

    def layout(self) -> None:
        """Size the window around its content, draw the bubble shape, put it under the porcupine."""
        self.frame.update_idletasks()
        width = self.frame.winfo_reqwidth() + 2 * PAD
        body_h = self.frame.winfo_reqheight() + 2 * PAD
        height = body_h + TAIL

        ax, ay, aw, ah = self.get_anchor()
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        above = ay + ah - 8 + height > screen_h - 40        # not enough room below -> go above

        x = min(max(ax + aw // 2 - width // 2, 8), screen_w - width - 8)
        y = (ay + 10 - height) if above else (ay + ah - 8)
        y = max(y, 4)
        tail_x = min(max(ax + aw // 2 - x, RADIUS + 8), width - RADIUS - 8)

        self.canvas.config(width=width, height=height)
        self.canvas.delete("shape")
        top = 0 if above else TAIL                          # the body starts below the tail
        rounded_rect(self.canvas, 1, top + 1, width - 1, top + body_h - 1, RADIUS,
                     fill=CREAM, outline=BORDER, width=2, tags="shape")
        if above:   # tail on the bottom edge, pointing down
            tail = [tail_x - 9, body_h - 2, tail_x + 9, body_h - 2, tail_x, body_h + TAIL - 1]
            edge = (tail_x - 8, body_h - 1, tail_x + 8, body_h - 1)
        else:       # tail on the top edge, pointing up at the porcupine
            tail = [tail_x - 9, TAIL + 2, tail_x + 9, TAIL + 2, tail_x, 1]
            edge = (tail_x - 8, TAIL + 1, tail_x + 8, TAIL + 1)
        self.canvas.create_polygon(tail, fill=CREAM, outline=BORDER, width=2, tags="shape")
        self.canvas.create_line(*edge, fill=CREAM, width=3, tags="shape")   # hides the seam
        self.canvas.tag_lower("shape")
        self.canvas.coords(self._frame_window, PAD, top + PAD)

        self.top.geometry(f"{width}x{height}+{x}+{y}")

    def reposition(self) -> None:
        """Call after the porcupine moved, so the chat follows it."""
        if self.is_open:
            self.layout()

    def set_click_through(self, on: bool) -> None:
        winutil.set_click_through(self.top, on)
