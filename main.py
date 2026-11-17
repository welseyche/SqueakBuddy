"""
SqueakBuddy — a cute lil guy that types while you type.

Windows only (uses pynput for a system-wide keyboard listener, and a
Windows-specific API call to enable click-through).

States:
    idle    -> shown once IDLE_TIMEOUT_S has passed with no keystrokes
    waiting -> shown in the gap between KEY_HOLD_S and IDLE_TIMEOUT_S
               (i.e. you recently typed, but aren't mid-keystroke)
    typing  -> flashes on for KEY_HOLD_S every time you press a key,
               alternating between two frames each press

Setup:
    pip install -r requirements.txt

PNG frames (transparent background) are in frames/:
    idle.png
    waiting.png
    typing_1.png
    typing_2.png

Run:
    python main.py
"""

import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QLabel

from pynput import keyboard

# ---------------------------------------------------------------------------
# Config — mess around with these
# ---------------------------------------------------------------------------
FRAME_DIR = Path(__file__).parent / "frames"
IDLE_IMG = FRAME_DIR / "idle.png"
WAITING_IMG = FRAME_DIR / "waiting.png"
TYPING_IMGS = [FRAME_DIR / "typing_1.png", FRAME_DIR / "typing_2.png"]

AVATAR_SIZE = 256          # px, the avatar is scaled to this (width & height) — bigger now
CORNER = "bottom-right"    # "bottom-right", "bottom-left", "top-right", "top-left"
MARGIN = 0                # px gap from the screen edge

KEY_HOLD_S = 0.15          # how long a key-press frame stays up before dropping to "waiting"
IDLE_TIMEOUT_S = 0.5       # seconds of no keystrokes before switching to full idle

CHECK_INTERVAL_MS = 50     # how often we re-check which frame should be showing

CLICK_THROUGH = True       # let mouse clicks pass through the avatar to whatever's beneath

BOUNCE_HEIGHT = 14         # px, how high it hops up on each keystroke
BOUNCE_DURATION_MS = 260   # how long the hop-and-settle takes


# ---------------------------------------------------------------------------
def load_pixmap(path: Path) -> QPixmap | None:
    if not path.exists():
        return None
    pix = QPixmap(str(path))
    if pix.isNull():
        return None
    return pix.scaled(AVATAR_SIZE, AVATAR_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class KeySignal(QObject):
    """Bridges pynput's background thread to Qt's main/GUI thread safely."""
    typed = Signal()


class Avatar(QLabel):
    def __init__(self):
        super().__init__()

        self.idle_pix = load_pixmap(IDLE_IMG)
        self.waiting_pix = load_pixmap(WAITING_IMG)
        self.typing_pix = [load_pixmap(p) for p in TYPING_IMGS]

        missing = []
        if self.idle_pix is None:
            missing.append(IDLE_IMG)
        if self.waiting_pix is None:
            missing.append(WAITING_IMG)
        for p, img in zip(TYPING_IMGS, self.typing_pix):
            if img is None:
                missing.append(p)
        if missing:
            raise RuntimeError(
                "Missing or unreadable frame image(s):\n"
                + "\n".join(f"  {p}" for p in missing)
            )

        self.last_keystroke = 0.0
        self.typing_toggle = 0
        self.state = "idle"

        self._setup_window()
        self._position_window()
        self.base_pos = self.pos()
        self.bounce_anim = QPropertyAnimation(self, b"pos")

        self.check_timer = QTimer(self)
        self.check_timer.timeout.connect(self._check_state)
        self.check_timer.start(CHECK_INTERVAL_MS)

        self._set_state("idle")

    def _setup_window(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool  # keeps it off the taskbar / alt-tab list
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.resize(AVATAR_SIZE, AVATAR_SIZE)

    def _position_window(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x, y = MARGIN, MARGIN
        if "right" in CORNER:
            x = screen.width() - AVATAR_SIZE - MARGIN
        if "bottom" in CORNER:
            y = screen.height() - AVATAR_SIZE - MARGIN
        self.move(x, y)

    def _set_state(self, state: str):
        self.state = state
        if state == "idle":
            self.setPixmap(self.idle_pix)
        elif state == "waiting":
            self.setPixmap(self.waiting_pix)
        elif state == "typing":
            self.setPixmap(self.typing_pix[self.typing_toggle])

    def _check_state(self):
        elapsed = time.time() - self.last_keystroke
        if elapsed < KEY_HOLD_S:
            target = "typing"
        elif elapsed < IDLE_TIMEOUT_S:
            target = "waiting"
        else:
            target = "idle"
        if target != self.state:
            self._set_state(target)

    def _bounce(self):
        self.bounce_anim.stop()
        self.bounce_anim.setDuration(BOUNCE_DURATION_MS)
        self.bounce_anim.setStartValue(QPoint(self.base_pos.x(), self.base_pos.y() - BOUNCE_HEIGHT))
        self.bounce_anim.setEndValue(self.base_pos)
        self.bounce_anim.setEasingCurve(QEasingCurve.OutBounce)
        self.bounce_anim.start()

    def on_key_event(self):
        self.last_keystroke = time.time()
        self.typing_toggle = 1 - self.typing_toggle
        self._set_state("typing")  # flash the new frame immediately, don't wait for the timer
        self._bounce()

    def showEvent(self, event):
        super().showEvent(event)
        if CLICK_THROUGH:
            self._enable_click_through()

    def _enable_click_through(self):
        """Windows-only: lets mouse clicks pass through this window."""
        try:
            import ctypes
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
            )
        except Exception as e:
            print(f"Click-through not enabled: {e}")


def main():
    app = QApplication(sys.argv)
    avatar = Avatar()
    avatar.show()

    signal = KeySignal()
    signal.typed.connect(avatar.on_key_event)

    def on_press(_key):
        signal.typed.emit()

    listener = keyboard.Listener(on_press=on_press)
    listener.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()