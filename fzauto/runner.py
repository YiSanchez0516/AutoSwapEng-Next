"""主循环: 截图 -> 识别 -> 判断题型 -> 作答."""

from __future__ import annotations

import re
import time
from collections import deque
from datetime import datetime

from PIL import Image

from .actions import Controller
from .config import CAPTURE_DIR, LOG_DIR, Config
from .ocr import OcrEngine, draw_debug
from .screen import Capture, Rect, activate_window
from .solver import Solver
from .ui import Keyboard, Line, Scene, SceneState
from .words import Lexicon


class Runner:
    def __init__(self, cfg: Config, mode: str = "auto", dry_run: bool = False,
                 max_steps: int | None = None, debug: bool = False):
        self.cfg = cfg
        self.mode = mode
        self.dry_run = dry_run
        self.debug = debug
        self.max_steps = max_steps or int(cfg.get("max_steps", 300))
        self.capture = Capture(cfg)
        self.ocr = OcrEngine(cfg)
        self.lex = Lexicon(cfg)
        self.solver = Solver(self.lex)
        self.controller = Controller(cfg)
        self.recent: deque[str] = deque(maxlen=60)
        self.attempts: dict[str, int] = {}
        self.last_word: str | None = None
        self.stale = 0
        self.counts = {"choice": 0, "spell": 0, "write": 0, "listen": 0, "study": 0}
        self._action_time: dict[str, float] = {}
        self.log_file = LOG_DIR / f"run-{datetime.now():%Y%m%d-%H%M%S}.log"

    # ---------- 日志 ----------
    def log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {message}"
        print(line, flush=True)
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass

    # ---------- 坐标 ----------
    @staticmethod
    def abs_point(rect: Rect, x: int, y: int) -> tuple[int, int]:
        return rect.x1 + int(x), rect.y1 + int(y)

    def abs_line(self, rect: Rect, line: Line) -> tuple[int, int]:
        return self.abs_point(rect, line.cx, line.cy)

    # ---------- 主流程 ----------
    def run(self) -> None:
        try:
            rect = self.capture.refresh(force=True)
            self.log(f"投屏区域: {rect.as_list()} ({rect.width}x{rect.height})")
        except RuntimeError as exc:
            raise SystemExit(str(exc))
        self.log(f"词库 {len(self.lex)} 词, 模式 {self.mode}"
                 + (", DRY-RUN" if self.dry_run else ""))
        if self.capture.note:
            self.log(self.capture.note)
        title = self.cfg.get("window_title") or ""
        if title and activate_window(title):
            self.log(f"已切换到投屏窗口: {title}")
            time.sleep(0.4)
        elif title:
            self.log("警告: 找不到投屏窗口, 请确认它没有被最小化")
        self._preload()
        capture_fails = 0
        for step in range(1, self.max_steps + 1):
            try:
                image, rect = self.capture.grab_stable(tries=3, gap=0.12)
                capture_fails = 0
            except Exception as exc:
                capture_fails += 1
                self.log(f"截图失败({capture_fails}/3): {exc}")
                if capture_fails >= 3:
                    raise SystemExit(str(exc))
                time.sleep(1.0)
                continue
            try:
                lines = self.ocr.read(image)
            except Exception as exc:
                self.log(f"OCR 识别失败: {exc}")
                time.sleep(0.8)
                continue
            scene = Scene(lines, rect.width, rect.height, self.cfg)
            state = scene.detect()
            state = self._apply_mode(scene, state)

            if self.cfg.get("log_ocr"):
                self._log_ocr(lines)

            key = f"{state.current}|{state.word or ''}|" + "|".join(state.prompt)
            if key == self.last_word:
                self.stale += 1
            else:
                self.stale = 0
                self.last_word = key

            progress = f"{state.current}/{state.total}" if state.total else "-"
            self.log(f"[{step}] {state.kind} 进度 {progress} "
                     f"词={state.word or '-'} 提示={'/'.join(state.prompt[:3]) or '-'}")
            if self.debug:
                draw_debug(image, lines, CAPTURE_DIR / f"debug-{step:03d}.png")

            if state.kind == "done":
                self.log("本卡包已完成, 结束")
                break

            if self.dry_run:
                self._dry_run(state)
                if step >= 3:
                    self.log("DRY-RUN 预览结束")
                    break
                time.sleep(0.6)
                continue

            try:
                if state.kind == "popup":
                    self.handle_popup(rect, scene, state)
                elif state.kind == "choice":
                    self.handle_choice(rect, scene, state, image)
                elif state.kind == "spell":
                    self.handle_spell(rect, scene, state)
                elif state.kind == "write":
                    self.handle_write(rect, scene, state)
                elif state.kind == "listen":
                    self.handle_listen(rect, scene, state)
                elif state.kind == "study":
                    self.handle_study(rect, scene, state)
                else:
                    self.handle_unknown(rect, scene, state)
            except Exception as exc:
                if type(exc).__name__ == "FailSafeException":
                    self.log("检测到鼠标移到屏幕角落, 已按急停退出")
                    break
                self.log(f"  处理出错: {exc}")
                time.sleep(0.8)

            if self.stale >= 8:
                self.log("画面长时间没有变化, 已停止 (可检查是否卡在弹窗)")
                break
            time.sleep(self.cfg.get("delays.between_steps", 0.25))

        self.lex.flush()
        self.log("运行结束, 统计: " + ", ".join(f"{k}={v}" for k, v in self.counts.items()))

    def _preload(self) -> None:
        if OcrEngine.available():
            self.log("正在加载 PaddleOCR 模型...")
            try:
                self.ocr._build()
                self.log("OCR 就绪")
            except Exception as exc:
                raise SystemExit(str(exc))
        else:
            raise SystemExit(
                "未检测到 PaddleOCR. 请先运行 install.ps1 安装依赖, "
                "或 python -m pip install paddlepaddle paddleocr"
            )

    def _log_ocr(self, lines: list[Line]) -> None:
        for index, line in enumerate(lines):
            self.log(f"    OCR {index:02d} ({line.x1},{line.y1})-({line.x2},{line.y2}) "
                     f"{line.score:.2f} {line.text}")

    def _dry_run(self, state: SceneState) -> None:
        if state.kind == "choice" and state.word:
            ranked = self.solver.choose_choices(state.word, state.options)
            self.log("   [预览] 选择: " + " > ".join(f"{a}({b})" for a, b in ranked[:3]))
        elif state.kind in ("spell", "write"):
            candidates = self.solver.spell_candidates(state.prompt, list(self.recent))
            self.log(f"   [预览] {'拼写' if state.kind == 'spell' else '手写'}: {candidates}")
        elif state.kind == "study":
            self.log("   [预览] 学习卡片")
            if state.word:
                self.recent.append(state.word.lower())

    # ---------- 题型处理 ----------
    def handle_popup(self, rect: Rect, scene: Scene, state: SceneState) -> None:
        button = scene.button("确定") or scene.button("继续") or scene.button("我知道了")
        if button:
            self.controller.click(*self.abs_line(rect, button), settle=0.6)
        else:
            self.controller.click_ratio(rect, 0.5, 0.72)
        time.sleep(0.6)

    def handle_choice(self, rect: Rect, scene: Scene, state: SceneState, image: Image.Image) -> None:
        options = state.options
        colors = {opt.letter: self._row_color(image, opt.line) for opt in options}
        word = state.word or self._recover_word(image)
        if not word:
            self.log("   没读到题目单词, 等待重试")
            time.sleep(0.5)
            return
        key = f"choice|{state.current}|{word}"
        attempted = self.attempts.get(key, 0)
        if any(color == "green" for color in colors.values()):
            if attempted > 0:
                self.counts["choice"] += 1
                green = next(letter for letter, color in colors.items() if color == "green")
                chosen = next((opt for opt in options if opt.letter == green), None)
                if chosen and word and self.solver.meaning_plausible(word, chosen.text):
                    self.lex.remember_learned(word, chosen.text)
            self.controller.swipe(rect, 0.5, 0.74, 0.5, 0.40)
            return
        red = [letter for letter, color in colors.items() if color == "red"]
        ranked = self.solver.choose_choices(word, options)
        ranked = [item for item in ranked if item[0] not in red]
        if attempted >= len(ranked):
            self.log("  所有选项都试过了, 直接下一题")
            self.controller.swipe(rect, 0.5, 0.74, 0.5, 0.40)
            return
        if time.time() - self._action_time.get(key, 0) < 1.2:
            # 判题动画还没结束, 不要连点
            time.sleep(0.35)
            return
        letter, note = ranked[attempted]
        target = next((opt for opt in options if opt.letter == letter), None)
        if target is None:
            return
        self.log(f"   选 {letter}: {note}  ({target.text})")
        self.controller.click(*self.abs_line(rect, target.line),
                              settle=self.cfg.get("delays.after_click", 0.7))
        self.attempts[key] = attempted + 1
        self._action_time[key] = time.time()
        self.recent.append(word.lower())

    def handle_study(self, rect: Rect, scene: Scene, state: SceneState) -> None:
        word = state.word
        if not word:
            self.controller.swipe(rect, 0.5, 0.74, 0.5, 0.40)
            return
        self.recent.append(word.lower())
        self.counts["study"] += 1
        self.log(f"   学习卡片: {word}")
        # 点开卡片看释义, 顺便记进词库供拼写题使用
        self.controller.click_ratio(rect, 0.5, 0.50)
        time.sleep(0.8)
        image, rect2 = self.capture.grab_stable(tries=2, gap=0.15)
        lines = self.ocr.read(image)
        scene2 = Scene(lines, rect2.width, rect2.height, self.cfg)
        segments = scene2.prompt_segments()
        segments = [seg for seg in segments if seg not in ("学习", "认识", "不认识")]
        if segments and word and self.solver.meaning_plausible(word, "；".join(segments)):
            self.lex.remember_study(word, "；".join(segments[:3]))
            self.log(f"   记住释义: {'；'.join(segments[:3])}")
        self.controller.swipe(rect2, 0.5, 0.74, 0.5, 0.40)

    def handle_spell(self, rect: Rect, scene: Scene, state: SceneState) -> None:
        keyboard = state.keyboard or scene.keyboard()
        candidates = self._candidates(state)
        if not candidates:
            self.log("   无法确定要拼写的单词, 跳过")
            self._skip(rect, scene)
            return
        if keyboard is None:
            self.log("   没找到屏幕键盘, 尝试直接键入")
        key = "spell|" + "|".join(state.prompt)[:40] + "|" + (state.word or "")
        if time.time() - self._action_time.get(key, 0) < 2.2:
            # 上一次提交后还在判题/翻页, 等画面变化
            time.sleep(0.5)
            return
        index = self.attempts.get(key, 0)
        if index >= min(3, len(candidates)):
            self.log("   候选都试过了, 跳过")
            self.attempts[key] = 0
            self._skip(rect, scene)
            return
        word = candidates[index]
        self.log(f"   拼写候选[{index + 1}/{len(candidates)}]: {word}")
        self.attempts[key] = index + 1

        input_point = self._spell_input_point(rect, keyboard)
        self.controller.click(*input_point, settle=0.25)
        if keyboard is not None and self.cfg.get("type_method", "tap") == "tap":
            self.controller.clear_input(keyboard)
            self.controller.type_on_keyboard(word, keyboard)
            button = scene.submit_line()
            if button:
                self.controller.click(*self.abs_line(rect, button))
            else:
                self.controller.pg.press("enter")
        else:
            self.controller.type_with_pc_keyboard(word)
            self.controller.pg.press("enter")
        self.counts["spell"] += 1
        self._action_time[key] = time.time()
        time.sleep(max(0.8, self.cfg.get("delays.after_click", 0.7)))

    def handle_write(self, rect: Rect, scene: Scene, state: SceneState) -> None:
        candidates = self._candidates(state)
        if not candidates:
            self.log("   无法确定要手写的单词, 跳过")
            self._skip(rect, scene)
            return
        key = "write|" + "|".join(state.prompt)[:40] + "|" + (state.word or "")
        if time.time() - self._action_time.get(key, 0) < 3.0:
            time.sleep(0.6)
            return
        index = self.attempts.get(key, 0)
        if index >= min(2, len(candidates)):
            self.log("   手写候选都试过了, 跳过")
            self.attempts[key] = 0
            self._skip(rect, scene)
            return
        word = candidates[index]
        self.attempts[key] = index + 1
        canvas = self._write_canvas(rect)
        self.log(f"   手写: {word}  区域 {canvas.as_list()}")
        clear = scene.button("清除") or scene.button("重写") or scene.button("清空")
        if clear:
            self.controller.click(*self.abs_line(rect, clear), settle=0.25)
        strokes = self.controller.handwrite(word, canvas)
        self.log(f"   完成 {strokes} 笔")
        self.counts["write"] += 1
        time.sleep(0.6)
        button = scene.submit_line()
        if button:
            self.controller.click(*self.abs_line(rect, button))
        self._action_time[key] = time.time()
        time.sleep(1.0)

    def handle_listen(self, rect: Rect, scene: Scene, state: SceneState) -> None:
        listen_word = state.word
        if listen_word:
            self.recent.append(listen_word.lower())
        if scene.has("当前卡包已完成"):
            button = scene.button("当前卡包已完成") or scene.submit_line()
            if button:
                self.controller.click(*self.abs_line(rect, button), settle=0.8)
            return
        if scene.has("内容会慢慢呈现") or scene.has("已播放"):
            # 原版比例: 播放按钮在左下方
            self.controller.click_ratio(rect, 0.2811, 0.8427)
            self.log("   已点击播放")
            time.sleep(1.2)
            return
        if scene.has("点击按钮") or scene.has("不能暂停"):
            # 录音按钮在右下角
            self.controller.click_ratio(rect, 0.9376, 0.9826)
            self.log("   已点击录音")
            time.sleep(2.5)
            return
        play = scene.button("播放")
        record = scene.button("录音") or scene.button("开始录音")
        stop = scene.button("停止") or scene.button("结束录音")
        confirm = scene.button("提交") or scene.button("确定") or scene.button("完成")
        if play:
            self.controller.click(*self.abs_line(rect, play), settle=2.4)
            self.log("   已点击播放")
            return
        if record:
            self.controller.click(*self.abs_line(rect, record), settle=4.0)
            self.log("   已点击录音")
            return
        if stop:
            self.controller.click(*self.abs_line(rect, stop), settle=0.8)
            return
        if confirm:
            self.controller.click(*self.abs_line(rect, confirm), settle=0.8)
            self.counts["listen"] += 1
            return
        self.controller.swipe(rect, 0.5, 0.74, 0.5, 0.40)

    def handle_unknown(self, rect: Rect, scene: Scene, state: SceneState) -> None:
        if len(scene.lines) < 3:
            # OCR 没读到内容时不要乱点, 等画面稳定
            time.sleep(0.8)
            return
        if self.stale < 2:
            time.sleep(0.6)
            return
        if self.stale in (2, 4):
            self.log("   页面未识别, 尝试点击中部")
            self.controller.click_ratio(rect, 0.5, 0.5)
        elif self.stale in (6, 7):
            self.log("   页面未识别, 尝试上滑")
            self.controller.swipe(rect, 0.5, 0.74, 0.5, 0.40)

    # ---------- 辅助 ----------
    def _apply_mode(self, scene: Scene, state: SceneState) -> SceneState:
        """手动指定题型时, 只在自动判断失败的情况下接管."""
        if self.mode == "auto" or state.kind in ("done", "popup", "choice"):
            return state
        if state.kind == self.mode:
            return state
        if state.kind not in ("unknown", "study"):
            return state
        if self.mode == "study":
            return state
        state.kind = self.mode
        if self.mode in ("spell", "write"):
            state.prompt = state.prompt or scene.prompt_segments()
            state.keyboard = state.keyboard or scene.keyboard()
        return state

    def _recover_word(self, image: Image.Image) -> str | None:
        """题目单词被漏读时, 放大题目区域再识别一次."""
        height, width = image.height, image.width
        box = (int(width * 0.06), int(height * 0.10),
               int(width * 0.94), int(height * 0.58))
        try:
            lines = self.ocr.read_zoom(image, box, scale=3)
        except Exception as exc:
            self.log(f"   补识别失败: {exc}")
            return None
        stop_words = {"n", "v", "adj", "adv", "prep", "pron", "conj", "vt", "vi",
                      "num", "art", "int", "aux", "the", "and"}
        best, best_height = None, 0
        for line in lines:
            text = line.text.strip()
            letters = re.sub(r"[^A-Za-z'’\- ]", "", text).strip()
            if len(letters) < 2 or letters.lower() in stop_words:
                continue
            if len(letters) < len(text.replace(" ", "")) * 0.6:
                continue
            if line.height > best_height:
                best, best_height = letters, line.height
        if best:
            self.log(f"   补识别单词: {best}")
        return best

    def _candidates(self, state: SceneState) -> list[str]:
        if state.word and re.fullmatch(r"[A-Za-z][A-Za-z'’\- ]{1,30}", state.word):
            if state.kind == "spell" and not state.prompt:
                return [state.word.lower()]
        words = self.solver.spell_candidates(state.prompt, list(self.recent), limit=4)
        if not words and state.word and state.kind in ("spell", "write"):
            words = [state.word.lower()]
        return words

    def _spell_input_point(self, rect: Rect, keyboard: Keyboard | None) -> tuple[int, int]:
        configured = self.cfg.get("spell_input")
        if configured and len(configured) == 2:
            return int(configured[0]), int(configured[1])
        if keyboard and keyboard.bbox:
            x = rect.x1 + keyboard.bbox.x1 + keyboard.bbox.width // 2
            y = rect.y1 + keyboard.bbox.y1 - int(rect.height * 0.07)
            return x, y
        return rect.point(0.5, 0.45)

    def _write_canvas(self, rect: Rect) -> Rect:
        configured = Rect.from_list(self.cfg.get("write_canvas"))
        if configured and rect.contains(*configured.center):
            return Rect(configured.x1 - rect.x1, configured.y1 - rect.y1,
                        configured.x2 - rect.x1, configured.y2 - rect.y1)
        return rect.crop_box(0.06, 0.26, 0.94, 0.56)

    def _skip(self, rect: Rect, scene: Scene) -> None:
        for word in ("跳过", "不会", "不认识", "下一题"):
            button = scene.button(word)
            if button:
                self.controller.click(*self.abs_line(rect, button))
                time.sleep(0.6)
                return
        self.controller.swipe(rect, 0.5, 0.74, 0.5, 0.40)

    @staticmethod
    def _row_color(image: Image.Image, line: Line) -> str | None:
        """选项行底色: 绿=正确, 红=错误."""
        y = min(max(line.cy, 0), image.height - 1)
        xs = range(int(image.width * 0.12), int(image.width * 0.88),
                   max(1, int(image.width * 0.05)))
        samples = [image.getpixel((x, y))[:3] for x in xs]
        if not samples:
            return None
        samples.sort(key=lambda rgb: sum(rgb))
        r, g, b = samples[len(samples) // 2]
        if g - r > 25 and g > 140:
            return "green"
        if r - g > 40 and r > 180:
            return "red"
        return None
