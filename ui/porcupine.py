"""Draws and animates the porcupine on a Tk Canvas.

Everything is drawn from simple shapes (ovals, triangles, arcs), redrawn about
30 times a second. What it looks like depends on its STATE:

    IDLE       gentle bobbing, blinking, eyes follow your mouse
    LISTENING  eyes wide open, ears perked (you clicked it to talk)
    THINKING   looks up, thought dots float
    WORKING    quills bristle, little feet run, a sweat drop (a tool is running)
    HAPPY      happy ^ ^ eyes, hops, sparkles (finished)
    ERROR      sad brows, tear, shakes, quills droop (something failed)
    SLEEPY     curls up into a spiky ball, breathes slowly, "z"s float from its head

CURLING: the porcupine is not two drawings. A number called `curl` glides from
0 (standing) to 1 (ball) when it falls asleep, and back to 0 when it wakes.
Every part - body shape, quill positions, head size and place - is a blend
between "standing" and "ball" using that number, so it rolls up and unrolls
smoothly.
"""

import math
import random
import time
import tkinter as tk

# The canvas background is painted in this colour and made see-through,
# so only the porcupine itself is visible on your desktop.
KEY = "#fe00fe"

WIDTH, HEIGHT = 180, 140

# --- the states ---
IDLE, LISTENING, THINKING, WORKING, HAPPY, ERROR, SLEEPY = (
    "idle", "listening", "thinking", "working", "happy", "error", "sleepy")

# --- colours ---
QUILL_DARK = "#5e3d2b"
QUILL_LIGHT = "#c9a27a"
BODY = "#c89b6d"
OUTLINE = "#8a5a3a"
BELLY = "#f1d9b8"
HEAD = "#e6c79e"
PINK = "#f4a6a0"
DARK = "#2b1d1d"
SPARKLE = "#ffd23f"
TEAR = "#6fb7f0"
ZZZ = "#6f86b8"
ZZZ_SHADOW = "#2f3b5c"

# How far the quills stick out in each state (1.0 = normal)
BRISTLE = {IDLE: 1.0, LISTENING: 1.05, THINKING: 1.15, WORKING: 1.35,
           HAPPY: 1.1, ERROR: 0.6, SLEEPY: 1.0}

# --- the two body shapes we blend between: STANDING and BALL ---
STAND_BODY = (74, 84, 44, 32)     # centre x, centre y, radius x, radius y
BALL_BODY = (84, 88, 38, 38)
STAND_HEAD = (116, 78, 1.0)       # centre x, centre y, size
BALL_HEAD = (118, 112, 0.5)       # small face peeking out at the lower front of the ball

QUILLS = 22          # quills in the ball; the first 13 are the ones you see when standing
STANDING_QUILLS = 13


def _lerp(a, b, f):
    """Blend between a and b: f=0 gives a, f=1 gives b. Works on numbers and (x, y) points."""
    if isinstance(a, tuple):
        return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
    return a + (b - a) * f


class Porcupine:
    def __init__(self, parent) -> None:
        self.canvas = tk.Canvas(parent, width=WIDTH, height=HEIGHT, bg=KEY,
                                highlightthickness=0, cursor="hand2")
        self.state = IDLE
        self.state_start = time.time()
        self.t0 = time.time()
        self.hover = False               # is the mouse over the porcupine?
        self.curl = 0.0                  # 0 = standing, 1 = curled into a ball
        self.recording = False           # True while it is watching you (teach by showing): shows a REC badge
        self._last_frame = time.time()
        self._blink_until = 0.0
        self._next_blink = time.time() + 2.0
        self.canvas.bind("<Enter>", lambda e: setattr(self, "hover", True))
        self.canvas.bind("<Leave>", lambda e: setattr(self, "hover", False))

    def set_state(self, state: str) -> None:
        """Switch mood. The animation clock for the new state restarts."""
        if state != self.state:
            self.state = state
            self.state_start = time.time()

    # ------------------------------------------------------------ where are the eyes looking?
    def _look(self) -> tuple[float, float]:
        """Eye offset (dx, dy) in pixels - follows the mouse pointer."""
        if self.state == THINKING:
            return 2.6, -3.0                       # staring up at its thoughts
        px, py = self.canvas.winfo_pointerxy()
        eye_x = self.canvas.winfo_rootx() + 117    # roughly between the eyes
        eye_y = self.canvas.winfo_rooty() + 80
        dx, dy = px - eye_x, py - eye_y
        distance = math.hypot(dx, dy)
        if distance < 1:
            return 0.0, 0.0
        strength = min(1.0, distance / 180) * 2.8  # nearer pointer = smaller look
        return dx / distance * strength, dy / distance * strength

    # ------------------------------------------------------------ one animation frame
    def draw(self) -> None:
        c = self.canvas
        c.delete("all")
        now = time.time()
        dt = min(now - self._last_frame, 0.1)   # time since the last frame (capped)
        self._last_frame = now
        t = now - self.t0                 # seconds since start (drives all the wobbling)
        age = now - self.state_start      # seconds since the current state began
        s = self.state

        # ---- curl: glide towards "ball" while sleepy, back to "standing" otherwise ----
        target = 1.0 if s == SLEEPY else 0.0
        self.curl += (target - self.curl) * min(1.0, dt * 3.2)
        if abs(target - self.curl) < 0.003:
            self.curl = target
        k = self.curl
        k2 = k * k * (3 - 2 * k)          # "smoothstep": gentle start and end

        # ---- body movement ----
        if s == WORKING:
            bob = math.sin(t * 14) * 1.6              # quick little bounce while busy
        else:
            bob = math.sin(t * 2.4) * 2.0 * (1 - k2)  # (a ball does not bob, it breathes)
        hop = -abs(math.sin(age * 6)) * 16 if (s == HAPPY and age < 1.2) else 0
        shake = math.sin(age * 45) * 3 if (s == ERROR and age < 0.8) else 0
        ox, oy = shake, bob + hop + 8                 # +8 leaves room for the hop
        breath = 1 + 0.035 * math.sin(t * 1.3) * k2   # slow breathing when curled up

        bristle = BRISTLE[s] * (1.12 if (self.hover and s != SLEEPY) else 1.0)

        # ---- the body shape: a blend between the standing ellipse and the ball ----
        bx = _lerp(STAND_BODY[0], BALL_BODY[0], k2)
        by = _lerp(STAND_BODY[1], BALL_BODY[1], k2)
        brx = _lerp(STAND_BODY[2], BALL_BODY[2], k2) * breath
        bry = _lerp(STAND_BODY[3], BALL_BODY[3], k2) * breath

        # ---- the head: smaller and tucked into the front of the ball when curled ----
        hcx = _lerp(STAND_HEAD[0], BALL_HEAD[0], k2)
        hcy = _lerp(STAND_HEAD[1], BALL_HEAD[1], k2)
        hs = _lerp(STAND_HEAD[2], BALL_HEAD[2], k2)

        # ---- tiny drawing helpers that apply the movement offsets ----
        def oval(cx, cy, rx, ry, **kw):
            return c.create_oval(cx - rx + ox, cy - ry + oy, cx + rx + ox, cy + ry + oy, **kw)

        def poly(points, **kw):
            flat = [v for x, y in points for v in (x + ox, y + oy)]
            return c.create_polygon(flat, **kw)

        def line(x1, y1, x2, y2, **kw):
            return c.create_line(x1 + ox, y1 + oy, x2 + ox, y2 + oy, **kw)

        def arc(cx, cy, rx, ry, start, extent, **kw):
            return c.create_arc(cx - rx + ox, cy - ry + oy, cx + rx + ox, cy + ry + oy,
                                start=start, extent=extent, **kw)

        # Same helpers for HEAD parts: positions are written for the big standing head
        # (centre 116,78) and automatically moved/scaled to wherever the head is now.
        def hx(x): return hcx + (x - STAND_HEAD[0]) * hs
        def hy(y): return hcy + (y - STAND_HEAD[1]) * hs

        def h_oval(x, y, rx, ry, **kw):
            return oval(hx(x), hy(y), rx * hs, ry * hs, **kw)

        def h_line(x1, y1, x2, y2, **kw):
            kw["width"] = max(1.5, kw.get("width", 2) * hs)
            return line(hx(x1), hy(y1), hx(x2), hy(y2), **kw)

        def h_arc(x, y, rx, ry, start, extent, **kw):
            kw["width"] = max(1.5, kw.get("width", 2) * hs)
            return arc(hx(x), hy(y), rx * hs, ry * hs, start, extent, **kw)

        def h_poly(points, **kw):
            return poly([(hx(x), hy(y)) for x, y in points], **kw)

        # ---- 1) the quills (drawn first, so the body covers their roots) ----
        for i in range(QUILLS):
            ball_angle = 205 - i * (360 / QUILLS)                         # evenly round the ball
            stand_angle = (205 - i * (170 / (STANDING_QUILLS - 1))
                           if i < STANDING_QUILLS else ball_angle)        # along the back
            theta = math.radians(_lerp(stand_angle, ball_angle, k2))
            base = (bx + brx * math.cos(theta), by - bry * math.sin(theta))
            # direction pointing straight out of the body, and the sideways direction
            nx, ny = math.cos(theta) / brx, -math.sin(theta) / bry
            length_n = math.hypot(nx, ny)
            nx, ny = nx / length_n, ny / length_n
            tx, ty = -ny, nx
            # the 9 extra quills of the ball grow out as it curls up
            grow = 1.0 if i < STANDING_QUILLS else k2
            length = (17 + 5 * math.sin(i * 1.9)) * bristle * grow
            wiggle = math.sin(t * 3 + i) * (0.6 if s == SLEEPY else 2.2)
            tip = (base[0] + nx * length + tx * wiggle, base[1] + ny * length + ty * wiggle)
            half = 5.5
            left = (base[0] - tx * half - nx * 4, base[1] - ty * half - ny * 4)
            right = (base[0] + tx * half - nx * 4, base[1] + ty * half - ny * 4)
            poly([left, tip, right], fill=QUILL_DARK, outline=QUILL_DARK)
            poly([_lerp(left, tip, 0.6), tip, _lerp(right, tip, 0.6)],
                 fill=QUILL_LIGHT, outline=QUILL_LIGHT)               # pale tip

        # ---- 2) feet (they run while working; hidden behind the body when curled) ----
        run = math.sin(t * 14) * 3 if s == WORKING else 0
        oval(54, 115 - max(run, 0), 9, 5, fill=OUTLINE, outline=OUTLINE)
        oval(94, 115 - max(-run, 0), 9, 5, fill=OUTLINE, outline=OUTLINE)

        # ---- 3) body and belly ----
        oval(bx, by, brx, bry, fill=BODY, outline=OUTLINE, width=2)
        belly_scale = 1 - k2                                          # the tummy is tucked away
        if belly_scale > 0.08:
            oval(_lerp(80, bx, k2), _lerp(98, by + 10, k2), 28 * belly_scale, 16 * belly_scale,
                 fill=BELLY, outline=BELLY)

        # ---- 4) ears, head, snout, nose ----
        ear_lift = -3 if s == LISTENING else 0                        # ears perk up
        h_oval(103, 58 + ear_lift, 7, 7, fill=BODY, outline=OUTLINE, width=2)
        h_oval(103, 58 + ear_lift, 3.5, 3.5, fill=PINK, outline=PINK)
        h_oval(129, 58 + ear_lift, 6.5, 6.5, fill=BODY, outline=OUTLINE, width=2)
        h_oval(129, 58 + ear_lift, 3, 3, fill=PINK, outline=PINK)
        h_oval(116, 78, 25, 22, fill=HEAD, outline=OUTLINE, width=2)
        h_oval(130, 89, 12, 8, fill=BELLY, outline=OUTLINE, width=1)
        h_oval(139, 86, 4.5, 3.5, fill=DARK, outline=DARK)
        h_oval(101, 90, 5.5, 3.5, fill=PINK, outline=PINK)            # rosy cheek

        # ---- 5) eyes ----
        if now >= self._next_blink:                                   # schedule a blink
            self._blink_until = now + 0.14
            self._next_blink = now + random.uniform(2.5, 5.5)
        blinking = now < self._blink_until
        look_x, look_y = self._look()

        for eye_x in (108, 126):
            eye_y = 74
            if s == HAPPY:                                            # ^ ^
                h_arc(eye_x, eye_y + 2, 6, 6, 0, 180, style="arc", outline=DARK, width=3)
            elif s == SLEEPY:                                         # closed, curved
                h_arc(eye_x, eye_y - 3, 6, 6, 180, 180, style="arc", outline=DARK, width=3)
            elif blinking:
                h_line(eye_x - 5, eye_y + 1, eye_x + 5, eye_y + 1, fill=DARK, width=3)
            else:
                rx, ry = (5.5, 7.5) if s == LISTENING else ((5, 4.8) if s == WORKING else (5, 6))
                h_oval(eye_x, eye_y, rx, ry, fill=DARK, outline=DARK)
                # pupils/highlights follow the mouse (look_x/y are plain pixels)
                oval(hx(eye_x - 1.6) + look_x * hs, hy(eye_y - 2.4) + look_y * hs, 1.9 * hs, 1.9 * hs,
                     fill="white", outline="white")
                if s == LISTENING:
                    oval(hx(eye_x + 2) + look_x * hs, hy(eye_y + 3) + look_y * hs, 1 * hs, 1 * hs,
                         fill="white", outline="white")

        if s == ERROR:                                                # sad eyebrows + a tear
            h_line(98, 66, 113, 60, fill=DARK, width=2.5)
            h_line(121, 60, 136, 66, fill=DARK, width=2.5)
            drop_y = 82 + (age * 22) % 12
            h_poly([(103, drop_y - 5), (100, drop_y + 1), (106, drop_y + 1)], fill=TEAR, outline=TEAR)
            h_oval(103, drop_y + 2, 3.2, 3.2, fill=TEAR, outline=TEAR)

        # ---- 6) mouth ----
        if s == HAPPY:
            h_arc(130, 94, 7, 6, 190, 160, style="chord", fill="#c0504d", outline=DARK, width=2)
        elif s == ERROR:
            h_arc(130, 101, 6, 4, 20, 140, style="arc", outline=DARK, width=2)
        elif s == SLEEPY:                                             # a tiny breathing "o"
            h_oval(130, 97, 2.5, 2.5 + math.sin(t * 1.3) * 1.2, fill=DARK, outline=DARK)
        elif s == THINKING:
            h_line(125, 97, 135, 96, fill=DARK, width=2)
        else:
            h_arc(130, 94, 6, 4, 200, 140, style="arc", outline=DARK, width=2)

        # ---- 7) extras that belong to a mood ----
        if s == THINKING:                                             # floating thought dots
            for n, (dx, dy, base_r) in enumerate([(142, 40, 3), (151, 29, 4.5), (163, 15, 7)]):
                pulse = 0.75 + 0.25 * math.sin(t * 4 - n * 1.1)
                c.create_oval(dx - base_r * pulse, dy - base_r * pulse + oy,
                              dx + base_r * pulse, dy + base_r * pulse + oy,
                              fill="white", outline=OUTLINE)
        elif s == WORKING:                                            # sweat drop
            sweat_y = 56 + (t * 24) % 10
            poly([(94, sweat_y - 5), (91, sweat_y + 1), (97, sweat_y + 1)], fill=TEAR, outline=TEAR)
            oval(94, sweat_y + 2, 3, 3, fill=TEAR, outline=TEAR)
        elif s == HAPPY and age < 2.5:                                # sparkles
            for n, (sx, sy) in enumerate([(88, 34), (150, 48), (66, 24)]):
                r = 4 + 5 * abs(math.sin(age * 5 + n * 1.3))
                poly([(sx, sy - r), (sx + r * .3, sy - r * .3), (sx + r, sy), (sx + r * .3, sy + r * .3),
                      (sx, sy + r), (sx - r * .3, sy + r * .3), (sx - r, sy), (sx - r * .3, sy - r * .3)],
                     fill=SPARKLE, outline="#e0a800")

        # REC badge: a blinking red dot, so you always SEE when it is watching you
        if self.recording:
            blink_on = int(now * 2) % 2 == 0
            c.create_oval(6, 6, 22, 22, fill="#e53935" if blink_on else "#7a1f1f", outline="white", width=2)
            c.create_text(30, 14, text="REC", anchor="w", font=("Segoe UI", 10, "bold"), fill="#e53935")

        # Sleeping "z z Z" rising from the head. They appear as the ball forms.
        if s == SLEEPY and k > 0.45:
            for n in range(3):
                phase = (t * 15 + n * 20) % 60                        # 0 -> 60: how far it has floated up
                zx = hx(138) + n * 9 + math.sin(t * 2 + n) * 3        # a gentle sideways drift
                zy = hy(52) - phase
                size = 9 + n * 3 + phase / 12                         # they grow as they rise
                for text_color, shift in ((ZZZ_SHADOW, 1), (ZZZ, 0)): # shadow first, then the letter
                    c.create_text(zx + shift, zy + shift + oy, text="zZz"[n],
                                  font=("Segoe UI", int(size), "bold"), fill=text_color)
