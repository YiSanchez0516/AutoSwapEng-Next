"""主循环: 截图 -> 识别 -> 判断题型 -> 作答."""

from __future__ import annotations

import json
import re
import time
from collections import deque
from datetime import datetime

from PIL import Image

from .actions import Controller
from .config import CAPTURE_DIR, LOG_DIR, Config
from .ocr import OcrEngine, draw_debug
from .screen import Capture, Rect, activate_window
from .session import PackSession
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
        self.session = PackSession.load() if cfg.get("pack_memory", True) else PackSession()
        self.recent.extend(self.session.words[-60:])
        self.attempts: dict[str, int] = {}
        self.last_word: str | None = None
        self.stale = 0
        self.counts = {"choice": 0, "spell": 0, "write": 0, "listen": 0, "study": 0}
        self._action_time: dict[str, float] = {}
        self.listen_state: dict[str, str] = {}
        self._arrow_rounds: dict[str, int] = {}
        self.stop_requested = False
        self.log_file = LOG_DIR / f"run-{datetime.now():%Y%m%d-%H%M%S}.log"
        self.answer_log = LOG_DIR / f"answers-{datetime.now():%Y%m%d}.jsonl"

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
            stage = self.session.observe(scene, state)

            if self.cfg.get("log_ocr"):
                self._log_ocr(lines)

            key = (f"{state.current}|{state.word or ''}|"
                   f"{hash(scene.compact) & 0xffff}|" + "|".join(state.prompt))
            if key == self.last_word:
                self.stale += 1
            else:
                self.stale = 0
                self.last_word = key

            progress = (f"{self.session.current}/{self.session.total}"
                        if self.session.total else "-")
            self.log(f"[{step}] {state.kind} 阶段={stage} 卡包={self.session.pack or '-'} "
                     f"进度={progress} 词={state.word or '-'} "
                     f"提示={'/'.join(state.prompt[:3]) or '-'}")
            if self.debug:
                draw_debug(image, lines, CAPTURE_DIR / f"debug-{step:03d}.png")

            if self.dry_run:
                self._dry_run(state)
                if step >= 3:
                    self.log("DRY-RUN 预览结束")
                    break
                time.sleep(0.6)
                continue

            if state.kind == "summary":
                self.handle_summary(rect, scene, state)
                if self.stop_requested:
                    break
                continue

            if state.kind == "done":
                self.session.finish()
                self.log("本卡包已完成, 结束")
                break

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

            if self.stop_requested:
                break
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

    def _log_answer(self, payload: dict) -> None:
        """把每题的选择/结果写入 answers-*.jsonl, 便于复盘错题."""
        data = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pack": self.session.pack,
            "stage": self.session.stage,
            "progress": f"{self.session.current}/{self.session.total}",
        }
        data.update(payload)
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with self.answer_log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(data, ensure_ascii=False) + "\n")
        except OSError:
            pass

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
        elif state.kind == "summary":
            self.log("   [预览] 学习结算页, 将自动进入强化")

    # ---------- 题型处理 ----------
    def handle_summary(self, rect: Rect, scene: Scene, state: SceneState) -> None:
        """学习结算页: 自动进入强化/巩固阶段."""
        key = f"summary|{self.session.pack}"
        button = scene.button("进入强化") or scene.button("开始强化")
        if button is None or not self.cfg.get("auto_enter_reinforce", True):
            self.log("   学习阶段完成, 未自动进入强化")
            self.stop_requested = True
            return
        if time.time() - self._action_time.get(key, 0) < 2.0:
            time.sleep(0.4)
            return
        self.log(f"   学习完成, 进入强化: {button.text}")
        self.controller.click(*self.abs_line(rect, button), settle=1.2)
        self._action_time[key] = time.time()
        self.session.mark_reinforce()

    def handle_popup(self, rect: Rect, scene: Scene, state: SceneState) -> None:
        text = scene.compact
        if "待强化单词" in text:
            self.session.mark_reinforce()
            self.log("   进入强化/巩固阶段")
            for keyword in ("开始强化", "进入强化", "开始", "确定"):
                button = scene.button(keyword)
                if button:
                    self.controller.click(*self.abs_line(rect, button), settle=1.0)
                    return
            self.controller.click_ratio(rect, 0.5, 0.88)
            time.sleep(1.0)
            return
        if "遇到错词不要怕" in text:
            button = scene.button("确定") or scene.button("继续") or scene.button("知道了")
            if button:
                self.controller.click(*self.abs_line(rect, button), settle=0.6)
            else:
                time.sleep(0.8)
            return
        button = (scene.button("开始强化") or scene.button("进入强化")
                  or scene.button("确定") or scene.button("继续")
                  or scene.button("我知道了"))
        if button:
            self.controller.click(*self.abs_line(rect, button), settle=0.6)
        else:
            self.controller.click_ratio(rect, 0.5, 0.72)
        time.sleep(0.6)

    def handle_choice(self, rect: Rect, scene: Scene, state: SceneState, image: Image.Image) -> None:
        options = state.options
        colors = {opt.letter: self._row_color(image, opt.line) for opt in options}
        raw_word = state.word or self._recover_word(image)
        word, corrected = (self.session.correct_word(raw_word) if raw_word else ("", False))
        if corrected:
            self.log(f"   按本卡包单词纠正: {raw_word} -> {word}")
        elif word and not self.lex.has_word(word):
            # 词库/词包都查不到, 再放大识别一次题目区域
            better = self._recover_word(image)
            if better and self.lex.has_word(better):
                self.log(f"   放大补识别: {word} -> {better}")
                raw_word, word = better, better
                word, corrected = self.session.correct_word(word)
        if not word:
            self.log("   没读到题目单词, 等待重试")
            time.sleep(0.5)
            return
        key = f"choice|{state.current}|{word}"
        attempted = self.attempts.get(key, 0)
        if any(color == "green" for color in colors.values()):
            green = next(letter for letter, color in colors.items() if color == "green")
            chosen = next((opt for opt in options if opt.letter == green), None)
            if attempted > 0:
                self.counts["choice"] += 1
                if chosen and self.solver.meaning_plausible(word, chosen.text):
                    self.lex.remember_learned(word, chosen.text)
                self._log_answer({
                    "event": "choice_result", "word": word, "result": "green",
                    "correct": green, "reply": chosen.text if chosen else "",
                })
            self.session.remove_wrong(word)
            self.controller.swipe(rect, 0.5, 0.74, 0.5, 0.40)
            return
        red = [letter for letter, color in colors.items() if color == "red"]
        if red:
            self.session.add_wrong(word)
        ranked = self.solver.choose_choices(word, options)
        ranked = [item for item in ranked if item[0] not in red]
        if attempted >= len(ranked):
            self.log("  所有选项都试过了, 直接下一题")
            self._log_answer({
                "event": "choice_result", "word": word, "result": "exhausted",
                "options": [{"letter": o.letter, "text": o.text} for o in options],
            })
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
        self._log_answer({
            "event": "choice_click", "word": word, "chosen": letter, "note": note,
            "options": [{"letter": o.letter, "text": o.text} for o in options],
        })
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
        self.session.add_word(word)
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
        raw_word = state.word or ""
        word, corrected = (self.session.correct_word(raw_word) if raw_word else ("", False))
        if corrected:
            self.log(f"   按本卡包单词纠正: {raw_word} -> {word}")
        if word:
            self.recent.append(word.lower())
        key = f"listen|{self.session.current}|{word}"
        if time.time() - self._action_time.get(key, 0) < 2.0:
            time.sleep(0.4)
            return

        if self._is_dialogue_page(scene):
            self._handle_dialogue(rect, scene, key)
            return

        if scene.has("当前卡包已完成"):
            point = self._listen_point("submit", rect)
            if point:
                self.controller.click(*point, settle=0.8)
            else:
                button = scene.submit_line()
                if button:
                    self.controller.click(*self.abs_line(rect, button), settle=0.8)
                else:
                    self.controller.click_ratio(rect, 0.3504, 0.9517)
            self.session.finish()
            self._action_time[key] = time.time()
            return

        if scene.has("内容会慢慢呈现") or scene.has("已播放"):
            if self.listen_state.get(key) == "played":
                time.sleep(1.0)
                return
            self._click_listen(rect, scene, key, "play", ("播放", "播放一遍"),
                               (0.2811, 0.8427))
            self.listen_state[key] = "played"
            self.log("   已点击播放")
            time.sleep(1.2)
            return

        if scene.has("点击按钮") or scene.has("不能暂停"):
            if self.listen_state.get(key) in ("recorded", "submitted"):
                time.sleep(1.0)
                return
            self._click_listen(rect, scene, key, "record", ("录音", "开始录音"),
                               (0.9376, 0.9826))
            self.listen_state[key] = "recorded"
            self.log("   已点击录音")
            time.sleep(2.5)
            return

        play = scene.button("播放")
        record = scene.button("录音") or scene.button("开始录音")
        stop = scene.button("停止") or scene.button("结束录音")
        confirm = scene.button("提交") or scene.button("确定") or scene.button("完成")
        if play and self.listen_state.get(key) != "played":
            self._click_listen(rect, scene, key, "play", ("播放",), (0.2811, 0.8427))
            self.listen_state[key] = "played"
            self.log("   已点击播放")
            return
        if record and self.listen_state.get(key) not in ("recorded", "submitted"):
            self._click_listen(rect, scene, key, "record", ("录音",), (0.9376, 0.9826))
            self.listen_state[key] = "recorded"
            self.log("   已点击录音")
            time.sleep(2.0)
            return
        if stop:
            self.controller.click(*self.abs_line(rect, stop), settle=0.8)
            self._action_time[key] = time.time()
            return
        if confirm:
            self._click_listen(rect, scene, key, "submit", ("提交",), (0.3504, 0.9517))
            self.listen_state[key] = "submitted"
            self.counts["listen"] += 1
            return
        self.controller.swipe(rect, 0.5, 0.74, 0.5, 0.40)

    @staticmethod
    def _is_dialogue_page(scene: Scene) -> bool:
        """短对话/听力页: 只有英文原文、中文翻译和底部三个圆形按钮."""
        text = scene.compact
        if "已播放" in text:
            return True
        return "短对话" in text or "长对话" in text

    def _handle_dialogue(self, rect: Rect, scene: Scene, key: str) -> None:
        """听力对话页: 左扬声器播放一次, 然后连续点右下角箭头提交并下一题.

        右波形是“听自己的录音”, 不点; 中间话筒也不需要点.
        """
        flow = bool(self.cfg.get("listen.auto_flow", True))
        phase = self.listen_state.get(key, "")
        if phase == "done":
            time.sleep(0.6)
            return
        if not phase:
            self._click_fixed(rect, key, "play", (0.271, 0.830), "播放")
            self.listen_state[key] = "played"
            time.sleep(float(self.cfg.get("listen.play_wait", 2.0) or 2.0))
            return
        if flow and phase == "played":
            changed = self._hammer_arrows(rect)
            if changed:
                # 已经进入下一题: 清掉旧状态, 下一轮会对新界面重新播放
                self.listen_state.pop(key, None)
                self._arrow_rounds.pop(key, None)
                self._action_time[key] = time.time()
                self.log("   听力: 检测到下一界面, 已停止连点")
                return
            rounds = self._arrow_rounds.get(key, 0) + 1
            limit = max(1, int(self.cfg.get("listen.arrow_rounds", 8) or 8))
            if rounds >= limit:
                self.listen_state[key] = "done"
                self._arrow_rounds.pop(key, None)
                self.log(f"   听力: 连点 {rounds} 轮仍未换题, 交给主循环处理")
            else:
                # 进度没变: 不放弃, 继续连点同一位置
                self._arrow_rounds[key] = rounds
                self.stale = 0
                self.log(f"   听力: 进度未变化(第 {rounds} 轮), 继续连点右下箭头")
                time.sleep(0.5)

    def _screen_signature(self, rect: Rect) -> bytes | None:
        try:
            image, _ = self.capture.grab()
        except Exception:
            return None
        width, height = image.width, image.height
        crop = image.crop((int(width * 0.05), int(height * 0.08),
                           int(width * 0.95), int(height * 0.75)))
        return crop.convert("L").resize((32, 48)).tobytes()

    @staticmethod
    def _signature_changed(before: bytes | None, after: bytes | None) -> bool:
        if not before or not after or len(before) != len(after):
            return False
        diff = sum(abs(a - b) for a, b in zip(before, after)) / len(before)
        return diff > 6.0

    def _hammer_arrows(self, rect: Rect) -> bool:
        """连点右下角箭头, 每点一次检测题目区域是否变化, 变化即停."""
        clicks = max(1, int(self.cfg.get("listen.arrow_clicks", 50) or 50))
        interval = float(self.cfg.get("listen.arrow_interval", 0.2) or 0.2)
        stop_on_change = bool(self.cfg.get("listen.stop_on_change", True))
        point = self._listen_point("next", rect) or rect.point(0.927, 0.910)
        self.log(f"   听力: 连点右下箭头, 本轮 {clicks} 次 {point}")
        baseline = self._screen_signature(rect)
        for index in range(clicks):
            self.controller.click(*point, settle=0)
            time.sleep(interval)
            if not stop_on_change:
                continue
            current = self._screen_signature(rect)
            if self._signature_changed(baseline, current):
                # 再等半秒确认一次, 避免“请先录音”之类提示气泡导致误判
                time.sleep(0.35)
                confirm = self._screen_signature(rect)
                if self._signature_changed(baseline, confirm):
                    self.log(f"   听力: 第 {index + 1} 次点击后界面已变化")
                    return True
                baseline = confirm or baseline
        return False

    def _click_fixed(self, rect: Rect, key: str, name: str,
                     fallback: tuple[float, float], label: str) -> None:
        point = self._listen_point(name, rect)
        if point:
            self.log(f"   听力: 点击{label}(校准) {point}")
            self.controller.click(*point, settle=0.5)
        else:
            target = rect.point(*fallback)
            self.log(f"   听力: 点击{label}(比例) {target}; "
                     f"若位置不对请运行 setup 第 5 步校准")
            self.controller.click(*target, settle=0.5)
        self._action_time[key] = time.time()

    def _listen_point(self, name: str, rect: Rect) -> tuple[int, int] | None:
        points = self.cfg.get("listen") or {}
        value = points.get(name) if isinstance(points, dict) else None
        if isinstance(value, (list, tuple)) and len(value) == 2:
            point = int(value[0]), int(value[1])
            if rect.contains(*point):
                return point
            self.log(f"   听力按钮 {name} 的校准位置不在当前窗口内, 改用自动识别")
        return None

    def _click_listen(self, rect: Rect, scene: Scene, key: str, name: str,
                      keywords: tuple[str, ...], fallback: tuple[float, float]) -> None:
        point = self._listen_point(name, rect)
        if point:
            self.log(f"   点击{name}(校准): {point}")
            self.controller.click(*point, settle=0.6)
        else:
            button = None
            for keyword in keywords:
                button = scene.button(keyword)
                if button:
                    break
            if button:
                target = self.abs_line(rect, button)
                self.log(f"   点击{name}(文字): {target}")
                self.controller.click(*target, settle=0.6)
            else:
                target = rect.point(*fallback)
                self.log(f"   点击{name}(比例): {target}  "
                         f"若位置不对请运行 setup 第 5 步校准")
                self.controller.click(*target, settle=0.6)
        self._action_time[key] = time.time()

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
        word = state.word
        if word and re.fullmatch(r"[A-Za-z][A-Za-z'’\- ]{1,30}", word):
            word, corrected = self.session.correct_word(word)
            if corrected:
                self.log(f"   按本卡包单词纠正: {state.word} -> {word}")
            if state.kind == "spell" and not state.prompt:
                return [word]
        words = self.solver.spell_candidates(state.prompt, list(self.recent), limit=4)
        if not words and word and state.kind in ("spell", "write"):
            words = [word]
        return words

    def _spell_input_point(self, rect: Rect, keyboard: Keyboard | None) -> tuple[int, int]:
        configured = self.cfg.get("spell_input")
        if configured and len(configured) == 2:
            point = int(configured[0]), int(configured[1])
            if rect.contains(*point):
                return point
            self.log("   拼写输入框的校准位置不在当前窗口内, 改用自动推断")
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
