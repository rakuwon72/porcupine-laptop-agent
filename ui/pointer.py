"""The pointer: a glowing ring + caption drawn around the control the agent is about to use.

It is a see-through, click-through window laid over the screen, so you can watch
exactly WHAT the agent is about to click or type into ("Clicking Compose") - and
notice at once if it aims at the wrong thing. It never blocks the real click.
"""

import math
import time
import tkinter as tk
from tkinter import font as tkfont

from ui import winutil
from ui.porcupine import KEY

RING = "#ff8a1f"          # the glowing ring
RING_SOFT = "#ffc27a"     # its halo
CAPTION_BG = "#fff8e7"
CAPTION_FG = "#4a3426"
CAPTION_BORDER = "#8a5a3a"

MARGIN = 10               # the ring sits this far outside the control
MIN_SIZE = 28             # tiny controls still get a visible ring
CAPTION_HEIGHT = 26
FRAME_MS = 33


class PointerOverlay:
    def __init__(self, root) -> None:
        self.root = root
        self.top = tk.Toplevel(root)
        self.top.withdraw()
        self.top.title("Porcupine pointer")
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.attributes("-transparentcolor", KEY)
        self.top.config(bg=KEY)
        self.canvas = tk.Canvas(self.top, bg=KEY, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        winutil.set_no_activate(self.top, True)       # never takes the keyboard
        winutil.set_click_through(self.top, True)     # clicks pass straight through it
        self.visible = False
        self._hide_at = 0.0
        self._started = 0.0
        self._geometry = None                         # (ring_w, ring_h, caption_text, caption_above)

    def show(self, rect: tuple[int, int, int, int], caption: str, seconds: float) -> None:
        """Draw the ring around `rect` (left, top, right, bottom in screen pixels)."""
        left, top, right, bottom = rect
        ring_w = max(right - left, MIN_SIZE) + 2 * MARGIN
        ring_h = max(bottom - top, MIN_SIZE) + 2 * MARGIN
        center_x, center_y = (left + right) // 2, (top + bottom) // 2

        caption_w = self.font.measure(caption) + 24
        above = center_y - ring_h // 2 - CAPTION_HEIGHT - 6 > 0      # room for the caption above?
        total_w = max(ring_w, caption_w) + 8
        total_h = ring_h + CAPTION_HEIGHT + 10

        x = center_x - total_w // 2
        y = (center_y - ring_h // 2 - CAPTION_HEIGHT - 6) if above else (center_y - ring_h // 2 - 2)
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = min(max(x, 0), max(screen_w - total_w, 0))
        y = min(max(y, 0), max(screen_h - total_h, 0))

        self._geometry = (ring_w, ring_h, caption, above, total_w, total_h, caption_w)
        self.top.geometry(f"{total_w}x{total_h}+{x}+{y}")
        self.top.deiconify()
        self.top.lift()
        self.top.attributes("-topmost", True)
        self.visible = True
        self._started = time.time()
        self._hide_at = self._started + seconds
        self._draw()

    def hide(self) -> None:
        self.visible = False
        self.top.withdraw()

    def _draw(self) -> None:
        """One animation frame: a pulsing ring and the caption pill."""
        if not self.visible:
            return
        now = time.time()
        if now >= self._hide_at:
            self.hide()
            return
        ring_w, ring_h, caption, above, total_w, total_h, caption_w = self._geometry
        c = self.canvas
        c.delete("all")

        pulse = 0.5 + 0.5 * math.sin((now - self._started) * 9)       # 0..1, about 1.4 beats a second
        ring_top = (CAPTION_HEIGHT + 6) if above else 2
        ring_left = (total_w - ring_w) // 2
        grow = 3 * pulse
        # soft halo, then the bright ring
        c.create_rectangle(ring_left - grow - 3, ring_top - grow - 3,
                           ring_left + ring_w + grow + 3, ring_top + ring_h + grow + 3,
                           outline=RING_SOFT, width=2)
        c.create_rectangle(ring_left - grow, ring_top - grow,
                           ring_left + ring_w + grow, ring_top + ring_h + grow,
                           outline=RING, width=3 + int(2 * pulse))

        # caption pill, attached above (or below) the ring
        pill_y = 2 if above else ring_top + ring_h + 8
        pill_x = (total_w - caption_w) // 2
        c.create_rectangle(pill_x, pill_y, pill_x + caption_w, pill_y + CAPTION_HEIGHT - 4,
                           fill=CAPTION_BG, outline=CAPTION_BORDER, width=2)
        c.create_text(total_w // 2, pill_y + (CAPTION_HEIGHT - 4) // 2, text=caption,
                      font=self.font, fill=CAPTION_FG)
        self.top.after(FRAME_MS, self._draw)
