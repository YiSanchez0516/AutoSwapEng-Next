"""鼠标/键盘动作: 点击、滑动、屏幕键盘输入、手写笔画."""

from __future__ import annotations

import time

from .config import Config
from .screen import Rect
from .strokes import word_strokes
from .ui import Keyboard, Line


class Controller:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._pg = None
        self.caps_on = False

    @property
    def pg(self):
        if self._pg is None:
            import pyautogui
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.02
            self._pg = pyautogui
            # 启动时鼠标若停在屏幕角落, PyAutoGUI 会立刻判定为急停, 先移开
            x, y = pyautogui.position()
            width, height = pyautogui.size()
            if x <= 2 or y <= 2 or x >= width - 2 or y >= height - 2:
                # 不能用 pyautogui.moveTo, 它在急停状态下会直接抛异常
                import ctypes
                ctypes.windll.user32.SetCursorPos(width // 2, height // 2)
        return self._pg

    # ---------- 基础动作 ----------
    def click(self, x: int, y: int, settle: float | None = None) -> None:
        self.pg.moveTo(int(x), int(y), duration=0.05)
        self.pg.click()
        time.sleep(self.cfg.get("delays.click", 0.03))
        if settle:
            time.sleep(settle)

    def click_line(self, line: Line, settle: float | None = None) -> None:
        self.click(line.cx, line.cy, settle)

    def click_ratio(self, rect: Rect, fx: float, fy: float) -> None:
        x, y = rect.point(fx, fy)
        self.click(x, y)

    def swipe(self, rect: Rect, fx1: float, fy1: float, fx2: float, fy2: float,
              duration: float = 0.28) -> None:
        x1, y1 = rect.point(fx1, fy1)
        x2, y2 = rect.point(fx2, fy2)
        self.pg.moveTo(x1, y1)
        self.pg.dragTo(x2, y2, duration=duration, button="left")
        time.sleep(self.cfg.get("delays.after_swipe", 0.9))

    def tap_center(self, rect: Rect) -> None:
        x, y = rect.center
        self.click(x, y)

    # ---------- 屏幕键盘 ----------
    def clear_input(self, keyboard: Keyboard) -> None:
        if keyboard.clear:
            self.click(*keyboard.clear)
            return
        if keyboard.delete:
            for _ in range(18):
                self.click(*keyboard.delete)
            return
        for _ in range(18):
            self.pg.press("backspace")
            time.sleep(0.01)

    def type_on_keyboard(self, word: str, keyboard: Keyboard) -> None:
        self.caps_on = False
        for char in word:
            if char.isupper():
                self._toggle_caps(keyboard)
                self._tap_key(char.lower(), keyboard)
                self._toggle_caps(keyboard)
            elif char.isalpha():
                self._tap_key(char.lower(), keyboard)
            elif char == " " and keyboard.space:
                self.click(*keyboard.space)
            elif char in "-'’":
                self._tap_key(char, keyboard)
            time.sleep(self.cfg.get("delays.click", 0.03))

    def _tap_key(self, char: str, keyboard: Keyboard) -> None:
        point = keyboard.keys.get(char)
        if point is not None:
            self.click(*point)

    def _toggle_caps(self, keyboard: Keyboard) -> None:
        if keyboard.caps:
            self.click(*keyboard.caps)
            self.caps_on = not self.caps_on

    def type_with_pc_keyboard(self, word: str) -> None:
        self.pg.write(word, interval=0.06)

    # ---------- 手写 ----------
    def handwrite(self, word: str, canvas: Rect) -> int:
        boxes = int(self.cfg.get("handwriting.letter_boxes", 0) or 0)
        if boxes > 1:
            # 每个字母一个格子: 把画布横向等分
            chars = [char for char in word if char != " "]
            cell_width = canvas.width / boxes
            count = 0
            for index, char in enumerate(chars[:boxes]):
                cell = Rect(
                    int(canvas.x1 + cell_width * index), canvas.y1,
                    int(canvas.x1 + cell_width * (index + 1)), canvas.y2,
                )
                strokes = word_strokes(char, cell.width, cell.height,
                                       margin_x=0.18, margin_y=0.12)
                count += self._draw_strokes(strokes, cell)
                time.sleep(0.5)
            return count
        mode = str(self.cfg.get("handwriting.mode", "word"))
        if mode == "letter":
            # 逐字母写: 适合每个字母有独立书写框/需要中间识别的场景
            count = 0
            for char in word:
                if char == " ":
                    continue
                strokes = word_strokes(
                    char, canvas.width, canvas.height,
                    margin_x=0.10, margin_y=0.10,
                )
                count += self._draw_strokes(strokes, canvas)
                time.sleep(0.7)
            return count
        strokes = word_strokes(
            word, canvas.width, canvas.height,
            margin_x=0.08, margin_y=0.12,
            letter_gap=float(self.cfg.get("handwriting.letter_gap", 0.12)),
        )
        return self._draw_strokes(strokes, canvas)

    def _draw_strokes(self, strokes: list[list[tuple[float, float]]], canvas: Rect) -> int:
        base_delay = float(self.cfg.get("handwriting.speed", 0.004))
        for stroke in strokes:
            x0 = canvas.x1 + stroke[0][0]
            y0 = canvas.y1 + stroke[0][1]
            self.pg.moveTo(x0, y0)
            self.pg.mouseDown()
            for x, y in stroke[1:]:
                target_x, target_y = canvas.x1 + x, canvas.y1 + y
                current_x, current_y = self.pg.position()
                distance = abs(target_x - current_x) + abs(target_y - current_y)
                duration = max(base_delay, min(0.06, distance / 5000))
                self.pg.moveTo(target_x, target_y, duration=duration)
            self.pg.mouseUp()
            time.sleep(0.05)
        return len(strokes)

    def draw_debug_strokes(self, word: str, canvas: Rect) -> None:
        """慢速演示一遍笔画, 方便确认手写区域是否正确."""
        self.handwrite(word, canvas)
