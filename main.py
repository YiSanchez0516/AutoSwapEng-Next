#!/usr/bin/env python3
"""翻转外语自动化助手 —— 电脑投屏 + PaddleOCR + PyAutoGUI.

用法:
    python main.py                     交互菜单
    python main.py setup               框选投屏窗口/校准键盘与手写区
    python main.py shot                抓屏 + OCR 诊断
    python main.py run                 自动答题
    python main.py run --dry-run       只识别不操作
    python main.py run --mode spell    只做拼写题
    python main.py test                离线测试答案引擎
    python main.py preview --word hello  预览手写笔画
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
SIM_CASES = ROOT / "tools" / "sim_cases.json"


def _relaunch_in_venv() -> None:
    """双击 main.py 时用系统 Python 启动会缺 PaddleOCR, 自动切到项目 .venv."""
    if os.environ.get("FZ_VENV") == "1" or not VENV_PY.exists():
        return
    try:
        if Path(sys.executable).resolve() == VENV_PY.resolve():
            return
    except OSError:
        pass
    env = os.environ.copy()
    env["FZ_VENV"] = "1"
    code = subprocess.call(
        [str(VENV_PY), str(ROOT / "main.py"), *sys.argv[1:]],
        cwd=str(ROOT), env=env,
    )
    raise SystemExit(code)


if __name__ == "__main__":
    _relaunch_in_venv()

try:
    from fzauto.config import CONFIG_FILE, CAPTURE_DIR, Config, ensure_dirs
    from fzauto.screen import (Capture, Rect, enable_dpi_awareness, find_mirror_window,
                               is_blank_image, is_mirror_candidate, is_probably_desktop,
                               list_windows, select_region_drag, blank_hint)
except Exception as _import_error:  # 依赖缺失时不要一闪而过
    print(f"依赖导入失败: {_import_error}")
    print("请先双击 install.bat 安装运行环境")
    try:
        if sys.stdin and sys.stdin.isatty():
            input("按回车键退出...")
    except (EOFError, KeyboardInterrupt):
        pass
    raise


def main() -> None:
    enable_dpi_awareness()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ensure_dirs()

    argv = _normalize_argv(sys.argv[1:])
    parser = argparse.ArgumentParser(
        description="翻转外语自动化助手 (选择/拼写/手写/听力)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--window", help="投屏窗口标题片段")
    parser.add_argument("--bbox", help="截图区域 x1,y1,x2,y2")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="框选窗口并校准")
    sub.add_parser("shot", help="抓屏并 OCR")
    ocr_cmd = sub.add_parser("ocr", help="对已有截图做 OCR (调试用)")
    ocr_cmd.add_argument("--image", required=True, help="图片路径")
    sub.add_parser("windows", help="列出可见窗口")
    sub.add_parser("config", help="显示当前配置")
    sub.add_parser("doctor", help="环境与 OPPO 投屏诊断")

    run = sub.add_parser("run", help="开始自动答题")
    run.add_argument("--mode", default="auto",
                     choices=["auto", "choice", "spell", "write", "listen", "study"])
    run.add_argument("--dry-run", action="store_true", help="只识别不操作")
    run.add_argument("--max", type=int, default=None, help="最多处理多少屏")
    run.add_argument("--debug", action="store_true", help="每步保存标注截图")
    run.add_argument("--log-ocr", action="store_true", help="打印全部 OCR 结果")

    sub.add_parser("test", help="离线测试选择题与反查")

    preview = sub.add_parser("preview", help="预览手写笔画")
    preview.add_argument("--word", default="hello")
    preview.add_argument("--grid", action="store_true", help="输出字母表")

    args = parser.parse_args(argv)

    cfg = Config.load()
    override_config(cfg, args)

    command = args.command
    if command is None:
        command = menu(cfg)
    if command in ("exit", None):
        return

    if command == "setup":
        setup(cfg)
    elif command == "shot":
        shot(cfg)
    elif command == "ocr":
        from PIL import Image
        image = Image.open(args.image).convert("RGB")
        _report_ocr(cfg, image, Path(args.image).stem)
    elif command == "windows":
        show_windows()
    elif command == "config":
        print(json.dumps(cfg.data, ensure_ascii=False, indent=2))
    elif command == "doctor":
        doctor(cfg)
    elif command == "run":
        from fzauto.runner import Runner
        Runner(cfg, mode=getattr(args, "mode", "auto"),
               dry_run=getattr(args, "dry_run", False),
               max_steps=getattr(args, "max", None),
               debug=getattr(args, "debug", False)).run()
    elif command == "test":
        run_tests(cfg)
    elif command == "preview":
        preview_strokes(getattr(args, "word", "hello"), getattr(args, "grid", False))
    else:
        parser.print_help()


def _normalize_argv(argv: list[str]) -> list[str]:
    """允许 --window/--bbox 写在子命令后面 (argparse 只认子命令前的全局参数)."""
    commands = {"setup", "shot", "ocr", "windows", "config", "run", "test", "preview"}
    if not any(token in commands for token in argv):
        return argv
    globals_: list[str] = []
    rest: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in ("--window", "--bbox") and index + 1 < len(argv):
            globals_.extend([token, argv[index + 1]])
            index += 2
            continue
        if token.startswith("--window=") or token.startswith("--bbox="):
            globals_.append(token)
            index += 1
            continue
        rest.append(token)
        index += 1
    return globals_ + rest


def override_config(cfg: Config, args) -> None:
    if getattr(args, "window", None):
        cfg.set("window_title", args.window)
    if getattr(args, "bbox", None):
        values = [int(item) for item in args.bbox.replace("，", ",").split(",")]
        if len(values) == 4:
            cfg.set("bbox", values)
            cfg.set("window_title", "")
    if getattr(args, "log_ocr", False):
        cfg.set("log_ocr", True)


def menu(cfg: Config) -> str:
    print("""
========== 翻转外语自动化助手 ==========
  1. 首次设置 / 重新框选投屏窗口
  2. 开始自动答题 (自动识别题型)
  3. 抓屏 + OCR 诊断
  4. 预览手写笔画
  5. 离线测试答案引擎
  6. 查看当前配置
  7. 环境 / OPPO 互联投屏诊断
  0. 退出
========================================""")
    choice = input("请选择: ").strip()
    return {
        "1": "setup", "2": "run", "3": "shot", "4": "preview",
        "5": "test", "6": "config", "7": "doctor", "0": "exit",
    }.get(choice, "exit")


def _window_mark(title: str, rect: Rect) -> str:
    if is_mirror_candidate(title):
        return "★"
    if rect.width <= rect.height * 1.05 and rect.height >= 500:
        return "△"  # 竖屏但标题没关键词, 也可能是投屏窗口
    return " "


def _window_priority(item: tuple[str, Rect]) -> tuple[int, int]:
    title, rect = item
    rank = {"★": 0, "△": 1}.get(_window_mark(title, rect), 2)
    return rank, -(rect.width * rect.height)


def setup(cfg: Config) -> None:
    print("\n[1/4] 选择 OPPO 互联 / 投屏窗口")
    windows = list_windows()
    scored = sorted(windows, key=_window_priority)
    for index, (title, rect) in enumerate(scored[:15], 1):
        mark = _window_mark(title, rect)
        ratio = rect.width / max(1, rect.height)
        print(f"  {index:>2}.{mark} {title[:38]:<38} "
              f"{rect.width}x{rect.height} 宽高比 {ratio:.2f}")
    print("  回车 = 自动识别手机投屏窗口")
    print("  d    = 手动拖拽框选 (推荐: 只框手机画面, 不含工具栏和黑边)")
    answer = input("输入序号 / d / 回车: ").strip().lower()

    chosen = False
    if answer == "":
        found = find_mirror_window()
        if found is not None:
            title, rect = found
            cfg.set("window_title", title)
            cfg.set("bbox", rect.as_list())
            print(f"自动识别: {title}")
            chosen = True
        elif cfg.bbox and not is_probably_desktop(Rect(*cfg.bbox)):
            print(f"沿用上次区域: {cfg.bbox}")
            chosen = True
        else:
            answer = "d"
    if not chosen and answer == "d":
        rect = select_region_drag("拖动框选 OPPO 互联里的手机画面, 按 Esc 取消")
        if rect is None:
            print("已取消")
            return
        cfg.set("window_title", "")
        cfg.set("bbox", rect.as_list())
    elif not chosen:
        try:
            title, rect = scored[int(answer) - 1]
        except (ValueError, IndexError):
            print("序号无效")
            return
        cfg.set("window_title", title)
        cfg.set("bbox", rect.as_list())
        print(f"已选择: {title}")

    cfg.save()
    try:
        image, rect = Capture(cfg).grab()
        path = CAPTURE_DIR / "setup.png"
        image.save(path)
        print(f"截图测试成功: {path}  ({rect.width}x{rect.height})")
    except Exception as exc:
        print(f"截图失败: {exc}")
        return

    print("\n[2/4] 拼写题屏幕键盘 (可跳过)")
    print("  如果拼写页有独立键盘, 拖拽框选键盘区域; 直接回车跳过")
    if input("框选键盘? [y/N]: ").strip().lower() == "y":
        kb = select_region_drag("拖动框选拼写页的字母键盘区域, 按 Esc 取消")
        if kb is not None:
            cfg.set("keyboard.bbox", kb.as_list())
            cfg.save()
            print(f"键盘区域: {kb.as_list()}")

    print("\n[3/4] 手写板区域 (可跳过)")
    print("  手写题出现时, 拖拽框选真正可以写字的空白区域")
    if input("框选手写区? [y/N]: ").strip().lower() == "y":
        canvas = select_region_drag("拖动框选手写板区域, 按 Esc 取消")
        if canvas is not None:
            cfg.set("write_canvas", canvas.as_list())
            cfg.save()
            print(f"手写区域: {canvas.as_list()}")

    print("\n[4/4] 拼写输入框位置 (可跳过)")
    print("  打开一道拼写题, 把鼠标放到输入框上, 3 秒后自动记录")
    if input("记录输入框位置? [y/N]: ").strip().lower() == "y":
        try:
            import pyautogui
            for count in (3, 2, 1):
                print(f"  {count} 秒后记录鼠标位置...")
                time.sleep(1)
            x, y = pyautogui.position()
            cfg.set("spell_input", [int(x), int(y)])
            cfg.save()
            print(f"输入框位置: ({x}, {y})")
        except Exception as exc:
            print(f"记录失败: {exc}")

    print(f"\n配置已保存: {CONFIG_FILE}")
    print("下一步: python main.py shot 检查 OCR 是否能读清题目, 再运行 python main.py run")


def shot(cfg: Config) -> None:
    try:
        image, rect = Capture(cfg).grab()
    except RuntimeError as exc:
        print(exc)
        return
    plain = CAPTURE_DIR / "shot.png"
    image.save(plain)
    print(f"截图: {plain}  ({rect.width}x{rect.height})")
    _report_ocr(cfg, image, "shot")


def _report_ocr(cfg: Config, image, name: str) -> None:
    from fzauto.ocr import OcrEngine, draw_debug
    from fzauto.ui import Scene

    engine = OcrEngine(cfg)
    if not engine.available():
        print("未安装 PaddleOCR, 只保存了截图")
        return
    lines = engine.read(image)
    print(f"识别到 {len(lines)} 行:")
    for index, line in enumerate(lines):
        print(f"  {index:>2} ({line.x1:>4},{line.y1:>4})-({line.x2:>4},{line.y2:>4}) "
              f"{line.score:.2f}  {line.text}")
    scene = Scene(lines, image.width, image.height, cfg)
    state = scene.detect()
    print(f"题型判断: {state.kind}  单词={state.word}  提示={state.prompt}")
    if state.options:
        from fzauto.runner import Runner
        colors = {opt.letter: Runner._row_color(image, opt.line) for opt in state.options}
        print(f"选项底色: {colors}")
    debug = CAPTURE_DIR / f"{name}-debug.png"
    draw_debug(image, lines, debug)
    print(f"标注图: {debug}")


def show_windows() -> None:
    for index, (title, rect) in enumerate(list_windows(), 1):
        ratio = rect.width / max(1, rect.height)
        mark = _window_mark(title, rect)
        print(f"{index:>2}.{mark} {title[:42]:<42} {rect.as_list()} "
              f"宽高比 {ratio:.2f}")


def doctor(cfg: Config) -> None:
    """把环境、窗口、截图、OCR 结果汇总, 便于定位闪退/黑屏问题."""
    report: list[str] = []

    def emit(text: str = "") -> None:
        print(text)
        report.append(text)

    emit("========== 翻转外语助手 诊断报告 ==========")
    emit(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    emit(f"Python: {sys.version.split()[0]}  {sys.executable}")
    emit(f"项目: {ROOT}")
    emit(f"配置文件: {CONFIG_FILE}  {'存在' if CONFIG_FILE.exists() else '不存在'}")
    try:
        import paddle
        emit(f"paddlepaddle: {paddle.__version__}")
    except Exception:
        pass
    try:
        import paddleocr
        emit(f"paddleocr: {getattr(paddleocr, '__version__', '未知')}")
    except Exception as exc:
        emit(f"paddleocr: 未安装或导入失败 ({exc})")

    emit("")
    emit("--- 可选的投屏窗口 (★ 为疑似手机投屏) ---")
    windows = list_windows()
    scored = sorted(windows, key=_window_priority)
    for index, (title, rect) in enumerate(scored[:20], 1):
        ratio = rect.width / max(1, rect.height)
        mark = _window_mark(title, rect)
        emit(f"{index:>2}.{mark} {title[:40]:<40} {rect.as_list()} 宽高比 {ratio:.2f}")

    found = find_mirror_window()
    emit("")
    emit(f"自动识别投屏窗口: {found[0] if found else '未找到'}")
    emit(f"当前配置窗口: {cfg.get('window_title') or '(按区域截图)'}  bbox={cfg.bbox}")
    if cfg.bbox and is_probably_desktop(Rect(*cfg.bbox)):
        emit("警告: 当前区域像是整个桌面, 请重新运行 setup 只框手机画面")

    emit("")
    emit("--- 截图测试 ---")
    try:
        capture = Capture(cfg)
        image, rect = capture.grab(validate=False)
        path = CAPTURE_DIR / "doctor.png"
        image.save(path)
        emit(f"截图: {path}  {rect.width}x{rect.height}  {rect.as_list()}")
        blank = is_blank_image(image)
        emit(f"是否黑屏/纯色: {'是' if blank else '否'}")
        if blank:
            emit(blank_hint())
            emit("请关闭 OPPO 互联的硬件加速/高清画质, 或改用 scrcpy 投屏")
        else:
            from fzauto.ocr import OcrEngine
            from fzauto.ui import Scene
            engine = OcrEngine(cfg)
            if engine.available():
                emit("OCR 识别结果:")
                lines = engine.read(image)
                for index, line in enumerate(lines[:20]):
                    emit(f"  {index:>2} {line.text}")
                state = Scene(lines, rect.width, rect.height, cfg).detect()
                emit(f"题型判断: {state.kind} 单词={state.word} 提示={state.prompt}")
            else:
                emit("PaddleOCR 未安装")
    except Exception as exc:
        emit(f"截图/识别失败: {exc}")
        emit(traceback.format_exc())
    emit("")
    emit("========== 报告结束 ==========")

    path = ROOT / "logs" / "doctor.txt"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(report), encoding="utf-8")
        print(f"\n报告已保存: {path}")
    except OSError:
        pass


def preview_strokes(word: str, grid: bool) -> None:
    from fzauto import strokes

    if grid:
        path = strokes.render_grid(CAPTURE_DIR / "strokes-grid.png")
        print(f"字母表预览: {path}")
    path = strokes.render_preview(word, CAPTURE_DIR / f"write-{word or 'word'}.png")
    print(f"手写预览: {path}")


def run_tests(cfg: Config) -> None:
    from fzauto.solver import Solver
    from fzauto.ui import Option
    from fzauto.words import Lexicon, split_segments

    lex = Lexicon(cfg)
    solver = Solver(lex)
    print(f"本地词库: {len(lex)} 词, 学习记录: {len(lex.study)}, 已记住: {len(lex.learned)}")

    if SIM_CASES.exists():
        cases = json.loads(SIM_CASES.read_text(encoding="utf-8"))
        correct = 0
        for case in cases:
            options = [
                Option(chr(65 + i), text,
                       type("L", (), {"text": text, "cx": 0, "cy": 0})())
                for i, text in enumerate(case["options"])
            ]
            ranked = solver.choose_choices(case["word"], options)
            got = ranked[0][0] if ranked else "-"
            ok = got == case["answer"].upper()
            correct += ok
            print(f"  [{'OK' if ok else 'NG'}] {case['word']:<14} -> {got} "
                  f"(期望 {case['answer']}) {ranked[0][1] if ranked else ''}")
        print(f"选择题准确率: {correct}/{len(cases)} = {correct / len(cases) * 100:.0f}%")

    samples = list(lex.learned.items())[:40]
    if samples:
        top1 = top3 = 0
        print("\n反查测试 (中文释义 -> 单词):")
        for word, text in samples:
            segments = split_segments(text)
            ranked = lex.reverse_lookup(segments, limit=5)
            words = [item[0] for item in ranked]
            hit1 = words[:1] == [word]
            hit3 = word in words[:3]
            top1 += hit1
            top3 += hit3
            mark = "OK" if hit1 else ("T3" if hit3 else "NG")
            print(f"  [{mark}] {text[:20]:<20} -> {words[:3]}")
        print(f"反查命中率: Top1 {top1}/{len(samples)}, Top3 {top3}/{len(samples)}")


def _write_crash(text: str) -> Path:
    path = ROOT / "logs" / "crash.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
            handle.write(text)
            handle.write("\n")
    except OSError:
        pass
    return path


def _pause_if_double_clicked() -> None:
    """双击运行时让窗口停住, 不要一闪而过."""
    try:
        if sys.stdin and sys.stdin.isatty():
            input("\n按回车键退出...")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中断")
    except SystemExit as exc:
        code = exc.code
        if code in (None, 0):
            raise
        if isinstance(code, str):
            print(code)
            code = 1
        _pause_if_double_clicked()
        raise SystemExit(code)
    except BaseException:
        trace = traceback.format_exc()
        print(trace)
        path = _write_crash(trace)
        print(f"程序异常退出, 详情已写入: {path}")
        _pause_if_double_clicked()
