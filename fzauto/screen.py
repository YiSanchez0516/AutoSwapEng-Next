"""屏幕捕获与窗口定位.

所有坐标均为屏幕物理像素, 与 PyAutoGUI 的鼠标坐标一致(启动时开启 DPI 感知).
"""

from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass
from pathlib import Path

import mss
from PIL import Image

from .config import Config


def enable_dpi_awareness() -> None:
    """必须在导入 pyautogui / 读取窗口坐标之前调用."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def virtual_screen() -> tuple[int, int, int, int]:
    """返回多显示器总区域 (left, top, right, bottom), 物理像素."""
    user32 = ctypes.windll.user32
    left = user32.GetSystemMetrics(76)
    top = user32.GetSystemMetrics(77)
    width = user32.GetSystemMetrics(78)
    height = user32.GetSystemMetrics(79)
    if width <= 0 or height <= 0:
        return 0, 0, 1920, 1080
    return left, top, left + width, top + height


@dataclass
class Rect:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def center(self) -> tuple[int, int]:
        return (self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2

    def point(self, fx: float, fy: float) -> tuple[int, int]:
        """按比例取点 (0~1)."""
        return int(self.x1 + self.width * fx), int(self.y1 + self.height * fy)

    def crop_box(self, fx1: float, fy1: float, fx2: float, fy2: float) -> "Rect":
        x1, y1 = self.point(fx1, fy1)
        x2, y2 = self.point(fx2, fy2)
        return Rect(x1, y1, x2, y2)

    def as_list(self) -> list[int]:
        return [self.x1, self.y1, self.x2, self.y2]

    @classmethod
    def from_list(cls, value) -> "Rect | None":
        if not value or len(value) != 4:
            return None
        return cls(*(int(v) for v in value))

    def contains(self, x: int, y: int) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def expand(self, fx: float, fy: float) -> "Rect":
        dx, dy = int(self.width * fx), int(self.height * fy)
        return Rect(self.x1 - dx, self.y1 - dy, self.x2 + dx, self.y2 + dy)


def list_windows() -> list[tuple[str, Rect]]:
    """列出可见窗口 (标题, 区域), 按面积从大到小."""
    try:
        import pygetwindow as gw
    except ImportError:
        return []
    result: list[tuple[str, Rect]] = []
    for window in gw.getAllWindows():
        title = (window.title or "").strip()
        if not title:
            continue
        try:
            rect = Rect(int(window.left), int(window.top),
                        int(window.left + window.width), int(window.top + window.height))
        except (TypeError, ValueError):
            continue
        if rect.width < 240 or rect.height < 320:
            continue
        if rect.y2 <= 0 or rect.x2 <= 0:
            continue
        result.append((title, rect))
    result.sort(key=lambda item: item[1].width * item[1].height, reverse=True)
    return result


def activate_window(title: str) -> bool:
    """把投屏窗口切到前台, 否则 PyAutoGUI 的点击可能落到别的窗口上."""
    if not title:
        return False
    title = title.strip().lower()
    try:
        import pygetwindow as gw
    except ImportError:
        return False
    best = None
    for window in gw.getAllWindows():
        window_title = (window.title or "").strip().lower()
        if title not in window_title:
            continue
        if window_title == title:
            best = window
            break
        if best is None:
            best = window
    if best is None:
        return False
    try:
        if best.isMinimized:
            best.restore()
        best.activate()
        return True
    except Exception:
        return False


def find_window(title: str) -> Rect | None:
    if not title:
        return None
    title = title.strip().lower()
    candidates = [
        (win_title, rect)
        for win_title, rect in list_windows()
        if title in win_title.lower()
    ]
    if not candidates:
        return None
    valid = [(title, rect) for title, rect in candidates
             if rect.width >= 240 and rect.height >= 320
             and rect.y2 > 0 and rect.x2 > 0]
    if not valid:
        return None
    # 同名窗口有多个时, 优先竖屏投屏窗口, 再按面积排序
    valid.sort(key=lambda item: (-mirror_score(item[0], item[1]),
                                 -(item[1].width * item[1].height)))
    for win_title, rect in valid:
        if win_title.strip().lower() == title:
            return rect
    return valid[0][1]


# OPPO 互联 / O+ Connect / 跨屏互联等投屏窗口的标题特征
MIRROR_KEYWORDS = (
    "oppo", "o+", "互联", "跨屏", "投屏", "oneplus", "一加",
    "realme", "coloros", "多屏协同", "屏幕镜像", "无线投屏",
    "scrcpy", "escrcpy", "手机投屏", "手机镜像",
)


def is_mirror_candidate(title: str) -> bool:
    lower = title.lower()
    return any(keyword.lower() in lower for keyword in MIRROR_KEYWORDS)


def mirror_score(title: str, rect: Rect) -> int:
    """越大越像手机投屏窗口; 只有标题命中关键词才算候选."""
    if not is_mirror_candidate(title):
        return 0
    score = 6
    ratio = rect.width / max(1, rect.height)
    if 0.30 <= ratio <= 0.80:
        score += 3
    elif 0.80 < ratio <= 1.0:
        score += 1
    if rect.height >= 700:
        score += 1
    return score


def find_mirror_window() -> tuple[str, Rect] | None:
    """没有指定标题时, 自动找 OPPO 互联等投屏窗口 (只认标题关键词)."""
    best: tuple[int, str, Rect] | None = None
    for title, rect in list_windows():
        # 只要竖屏窗口, 避免把 OPPO 互联的横屏控制面板当成手机画面
        if rect.width > rect.height * 1.05:
            continue
        score = mirror_score(title, rect)
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, title, rect)
    if best is None:
        return None
    return best[1], best[2]


def is_probably_desktop(rect: Rect) -> bool:
    """选中的是不是整个桌面/横屏大窗口 (而不是手机画面)."""
    left, top, right, bottom = virtual_screen()
    area = max(1, (right - left) * (bottom - top))
    return (rect.width * rect.height >= area * 0.85
            and rect.width > rect.height * 1.2)


def blank_hint() -> str:
    return (
        "截到的画面是黑屏/纯色。若使用 OPPO 互联, 请在设置里关闭"
        "“高清画质/硬件加速/隐私保护”后重试, 或改用 scrcpy/Escrcpy 投屏。"
    )


def is_blank_image(image: Image.Image) -> bool:
    """近似判断整帧是否纯黑/纯色 (无法 OCR 的画面)."""
    small = image.convert("L").resize((64, 48))
    pixels = list(small.getdata())
    if not pixels:
        return True
    low, high = min(pixels), max(pixels)
    return high - low < 10 and sum(pixels) / len(pixels) < 45


def select_region_drag(prompt: str = "拖动鼠标框选投屏窗口，按 Esc 取消") -> Rect | None:
    """全屏半透明遮罩, 让用户拖拽框选一块区域."""
    import tkinter as tk

    left, top, right, bottom = virtual_screen()
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.28)
    root.geometry(f"{right - left}x{bottom - top}+{left}+{top}")
    root.configure(bg="black")
    canvas = tk.Canvas(root, bg="black", highlightthickness=0, cursor="cross")
    canvas.pack(fill="both", expand=True)
    canvas.create_text(
        (right - left) // 2, 40, text=prompt, fill="white",
        font=("Microsoft YaHei", 18), anchor="n",
    )
    state: dict[str, int] = {}
    box_id: list[int] = []

    def on_press(event):
        state["x"], state["y"] = event.x, event.y
        if box_id:
            canvas.delete(box_id[0])
            box_id.clear()
        box_id.append(canvas.create_rectangle(event.x, event.y, event.x, event.y,
                                             outline="#4dd0e1", width=3))

    def on_drag(event):
        if box_id:
            canvas.coords(box_id[0], state["x"], state["y"], event.x, event.y)

    def on_release(event):
        x1, y1 = min(state["x"], event.x), min(state["y"], event.y)
        x2, y2 = max(state["x"], event.x), max(state["y"], event.y)
        state.update(x1=x1, y1=y1, x2=x2, y2=y2)
        root.destroy()

    def on_cancel(event=None):
        state.clear()
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_cancel)
    root.focus_force()
    root.mainloop()
    if not state:
        return None
    rect = Rect(left + state["x1"], top + state["y1"],
                left + state["x2"], top + state["y2"])
    if rect.width < 100 or rect.height < 100:
        return None
    return rect


class Capture:
    """按窗口或固定区域截图."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._sct = mss.mss()
        self._rect: Rect | None = None
        self._rect_from_window = False
        self._last_refresh = 0.0
        self.note = ""

    def refresh(self, force: bool = False, validate: bool = True) -> Rect:
        now = time.time()
        if not force and self._rect is not None and now - self._last_refresh < 3.0:
            return self._rect
        title = self.cfg.get("window_title") or ""
        rect = find_window(title) if title else None
        if rect is None and not title:
            # 没指定窗口时自动找 OPPO 互联等竖屏投屏窗口
            found = find_mirror_window()
            if found is not None:
                title, rect = found
                self.cfg.set("window_title", title)
                self.note = f"自动识别到投屏窗口: {title}"
        if rect is not None:
            self._rect = rect
            self._rect_from_window = True
            self.cfg.set("bbox", rect.as_list())
        else:
            saved = self.cfg.bbox
            if saved is None:
                raise RuntimeError(
                    "还没有设置投屏窗口区域。先运行: python main.py setup"
                )
            self._rect = Rect(*saved)
            self._rect_from_window = False
        if validate and is_probably_desktop(self._rect):
            # 误选了桌面/设置窗口: 自动改用识别到的手机投屏窗口
            found = find_mirror_window()
            if found is not None:
                title, rect = found
                self.cfg.set("window_title", title)
                self.cfg.set("bbox", rect.as_list())
                self._rect = rect
                self._rect_from_window = True
                self.note = f"原窗口不是手机画面, 已自动改用: {title}"
            else:
                raise RuntimeError(
                    "当前框选的是整个桌面/横屏大窗口, 不是手机投屏画面。"
                    "请重新运行 python main.py setup, 只框住 OPPO 互联里的手机画面"
                    " (不含左侧工具栏和黑边)。"
                )
        self._last_refresh = now
        return self._rect

    def grab(self, validate: bool = True) -> tuple[Image.Image, Rect]:
        rect = self.refresh(validate=validate)
        raw = self._sct.grab(
            {"left": rect.x1, "top": rect.y1, "width": rect.width, "height": rect.height}
        )
        image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        return image, rect

    def grab_stable(self, tries: int = 4, gap: float = 0.12) -> tuple[Image.Image, Rect]:
        """连拍直到两帧一致, 避开翻页/判题动画; 黑屏时给出明确提示."""
        previous: bytes | None = None
        image, rect = self.grab()
        for index in range(tries):
            current = image.tobytes()
            if is_blank_image(image):
                if index >= tries - 1:
                    raise RuntimeError(blank_hint())
                time.sleep(0.4)
                image, rect = self.grab()
                continue
            if previous is not None and current == previous:
                break
            previous = current
            time.sleep(gap)
            image, rect = self.grab()
        return image, rect

    def rect(self) -> Rect:
        return self.refresh()


def save_image(image: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path
