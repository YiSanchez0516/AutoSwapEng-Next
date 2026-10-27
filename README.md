# 翻转外语自动化助手（AutoSwapEng-Next）

[English](README.en.md) | 中文

基于 **电脑投屏 + PaddleOCR + PyAutoGUI** 的「翻转外语」练习辅助工具，支持单词选择、拼写、手写、听力等题型。

> 本项目的思路与初版来自 [**ZRedTea/AutoSwapEng**](https://github.com/ZRedTea/AutoSwapEng)（MIT License）。
> 本仓库是在原项目基础上的**彻底重写**：重做了窗口捕获、OCR 解析、答案决策、手写笔画和错误处理，并新增 OPPO 互联投屏适配。
> 原项目版权归 **ZRedTea** 所有，本项目与原项目作者无隶属关系。

## 功能

- **自动识别题型**：单词选择、看释义拼写、手写板、听力、学习卡片
- **单词选择**：本地词库 + ECDICT + 在线词典综合评分；识别红/绿判题底色，答错自动换选项
- **拼写**：中文释义反查英文候选；自动定位屏幕键盘并点击输入；候选答错自动重试
- **手写**：内置单笔画字母表，用 PyAutoGUI 在书写区画出单词；支持整词、逐字母、每字母一格
- **投屏适配**：自动识别 OPPO 互联 / O+ Connect / 跨屏互联 / scrcpy 等竖屏投屏窗口
- **安全保护**：误选桌面/横屏窗口会拒绝执行；黑屏检测；鼠标移到屏幕角落立即急停
- **可诊断**：崩溃写入 `logs/crash.log`；`doctor.bat` 一键生成环境/截图/OCR 报告

## 与原项目的区别

| | 原 AutoSwapEng | 本仓库 |
|---|---|---|
| 窗口定位 | 手动记录窗口坐标 | 自动识别投屏窗口，也支持拖拽框选 |
| 截图 | pyscreenshot | mss 高速截图 + DPI 适配 |
| OCR | PaddleOCR | PaddleOCR 2.9.1，局部放大补识别、标注图 |
| 题型 | 选择 / 拼写 / 听力 | 选择 / 拼写 / 手写 / 听力 / 学习卡 |
| 答案 | 模糊字符串匹配 | 本地词库 + ECDICT + 中文反查 + 在线词典 + 学习记忆 |
| 手写 | 无 | 单笔画字母表 + PyAutoGUI 绘制 |
| 稳定性 | 依赖坐标与固定比例 | 以 OCR 元素定位为主，含防连点、急停、崩溃日志、诊断工具 |
| 投屏 | 通用屏幕坐标 | OPPO 互联等窗口自动识别、黑屏/误选保护 |

## 环境要求

- Windows 10 / 11
- 电脑上运行手机投屏工具（推荐 **OPPO 互联** 的“手机投屏”，或 scrcpy / Escrcpy）
- 能正常显示「翻转外语」小程序的答题页面
- 首次安装会下载 Python 3.12、PaddlePaddle、PaddleOCR 和中文模型（约 500–800 MB）

## 安装

双击 **`install.bat`**，脚本会：

1. 检查/安装 Python 3.12
2. 创建 `.venv` 虚拟环境
3. 安装 PaddleOCR、PyAutoGUI、mss 等依赖
4. 首次运行 OCR 时自动下载中文识别模型（约 20 MB）

也可以手动执行：

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 使用

1. 打开 OPPO 互联的“手机投屏”，让翻转外语画面显示出来
2. 双击 **`run.bat`**
3. 首次使用选 `1`：
   - 直接回车：自动识别 OPPO 互联等投屏窗口
   - 或按 `d`：拖拽框选，**只框手机画面**（不要包含工具栏和黑边）
4. 选 `3` 抓屏 + OCR 诊断，确认能读清题目
5. 选 `2` 开始自动答题

常用命令：

```bat
run.bat setup                  :: 重新框选窗口/校准键盘与手写区
run.bat run --dry-run          :: 只识别不点击
run.bat run --mode spell       :: 只做拼写题
run.bat ocr --image captures\live.png   :: 对已有截图做 OCR
run.bat doctor                 :: 生成诊断报告
```

运行中把鼠标猛地移到屏幕左上角即可急停。

## OPPO 互联适配说明

- 自动识别标题包含 `OPPO`、`O+ Connect`、`互联`、`跨屏`、`投屏`、`手机投屏`、`OnePlus`、`一加`、`realme` 等关键词的**竖屏窗口**
- OPPO 互联的横屏控制面板不会被误选
- 如果窗口标题不含上述关键词：
  - 打开 `setup`，按宽高比和 `★` / `△` 标记选择
  - 或直接按 `d` 拖拽框选手机画面
- 如果截图是黑屏：在 OPPO 互联设置中关闭“高清画质 / 硬件加速 / 隐私保护”，或改用 scrcpy 投屏
- 若窗口包含工具栏/侧边栏，建议只框选手机画面，滑动和点击会更准确

## 词库（可选，但推荐）

程序按以下顺序获取释义：

1. 本地 `cache/vocab.json`（CET4/CET6/高中词表，需自行生成）
2. **ECDICT** 离线词典（强烈推荐）
3. 有道 / Bing 在线词典（需联网）

### 配置 ECDICT

1. 从 [ECDICT Releases](https://github.com/skywind3000/ECDICT/releases) 下载 `ecdict-sqlite-28.zip` 并解压得到 `stardict.db`
2. 把 `stardict.db` 放到项目下的 `ecdict\` 目录，或在 `config.json` 中填写绝对路径：

```json
"solver": {
  "ecdict": "D:/dict/stardict.db",
  "online": true
}
```

没有 ECDICT 也能运行，只是选择题和拼写候选会更依赖在线词典。

### 生成本地词库（可选）

准备 CET4/CET6/高中词表 JSONL（`CET4_3.json`、`CET6_3.json`、`GaoZhong_2.json`），放到：

```
vocab_tmp/cet4/CET4_3.json
vocab_tmp/cet6/CET6_3.json
vocab_tmp/gaozhong/GaoZhong_2.json
```

然后运行：

```bat
.venv\Scripts\python.exe tools\build_vocab.py
```

会生成 `cache/vocab.json`。词表来源请遵循其各自许可证。

## 配置项

首次运行 `setup` 会生成 `config.json`（已在 `.gitignore` 中忽略）。常用字段：

| 字段 | 说明 |
|---|---|
| `window_title` | 投屏窗口标题片段，留空则自动识别 |
| `bbox` | 截图区域 `[x1, y1, x2, y2]`，屏幕物理像素 |
| `keyboard.bbox` | 拼写页屏幕键盘区域（可校准） |
| `spell_input` | 拼写输入框点击位置 `[x, y]` |
| `write_canvas` | 手写板区域 `[x1, y1, x2, y2]` |
| `handwriting.mode` | `word` 整词连写 / `letter` 逐字母 |
| `handwriting.letter_boxes` | 大于 1 时把书写区横向等分成 N 格，每格写一个字母 |
| `type_method` | `tap` 点击屏幕键盘 / `type` 直接用电脑键盘输入 |
| `solver.ecdict` | ECDICT 数据库路径 |
| `ocr.min_score` | OCR 置信度阈值 |

可参考 [`config.example.json`](config.example.json)。

## 常见问题

**双击后闪退**

- 请使用 `run.bat` 启动，不要直接双击 `main.py`（虽然 `main.py` 会自动切换到 `.venv`）
- 查看 `logs\crash.log`
- 运行 `doctor.bat`，把 `logs\doctor.txt` 发到 issue

**截图黑屏**

- 关闭 OPPO 互联的“高清画质 / 硬件加速 / 隐私保护”
- 或改用 scrcpy / Escrcpy

**识别不到投屏窗口**

- 打开 OPPO 互联的“手机投屏”后再运行
- 在 `setup` 中按 `d` 直接框选手机画面

**手写识别不准**

- 先用 `run.bat preview --word hello` 预览笔画
- 如果是每字母一格，把 `handwriting.letter_boxes` 设为格子数
- 调整 `write_canvas` 只覆盖可书写区域

**拼写输入位置不对**

- 重新运行 `setup` 第 4 步，把鼠标放到输入框上记录坐标
- 或改用 `type_method: "type"` 直接键入

## 目录结构

```
main.py              命令行入口 / 交互菜单
fzauto/
  screen.py          窗口识别、截图、黑屏检测
  ocr.py             PaddleOCR 封装与调试标注
  ui.py              界面元素解析与题型判断
  words.py           词库、ECDICT、在线词典、中文反查
  solver.py          选择题评分与拼写候选
  strokes.py         单笔画字母表
  actions.py         点击、滑动、键盘输入、手写
  runner.py          主循环
tools/
  build_vocab.py     生成本地词库
  sim_cases.json     离线选择题测试用例
install.bat/.ps1     安装脚本
run.bat              启动脚本
doctor.bat           诊断脚本
```

## 免责声明

- 本项目仅用于**个人学习辅助与技术研究**，请遵守「翻转外语」、学校及相关服务条款。
- 请勿用于代写、作弊或其他违反规定的用途，使用风险由使用者自行承担。
- 程序不收集、不上传账号信息；截图、日志、词库缓存均保存在本地。
- 第三方词库（ECDICT 等）遵循其各自许可证。

## 许可证与致谢

本项目使用 [MIT License](LICENSE)。

- 原项目：[ZRedTea/AutoSwapEng](https://github.com/ZRedTea/AutoSwapEng) — 思路与初版实现
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) — 文字识别
- [ECDICT](https://github.com/skywind3000/ECDICT) — 离线英汉词典
- [PyAutoGUI](https://github.com/asweigart/pyautogui)、[mss](https://github.com/BoboTiG/python-mss)、[PyGetWindow](https://github.com/asweigart/pygetwindow)
