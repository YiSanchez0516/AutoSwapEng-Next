# 翻转外语自动化助手（AutoSwapEng-Next）

[English](README.en.md) | 中文

基于 **电脑投屏 + PaddleOCR + PyAutoGUI** 的「翻转外语」练习辅助工具，支持单词选择、拼写、手写、听力等题型。

> 本项目的思路与初版来自 [**ZRedTea/AutoSwapEng**](https://github.com/ZRedTea/AutoSwapEng)（MIT License）。
> 本仓库是在原项目基础上的**彻底重写**：重做了窗口捕获、OCR 解析、答案决策、手写笔画和错误处理，并新增 OPPO 互联投屏适配。
> 原项目版权归 **ZRedTea** 所有，本项目与原项目作者无隶属关系。

## 功能

- **自动识别题型**：单词选择、看释义拼写、手写板、听力、学习卡片
- **自动识别卡包阶段**：学习卡片 / 答题 / 答错后的强化巩固；学习结算后自动进入强化
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

程序会自动识别当前处于 **学习卡片 / 答题 / 强化巩固** 哪个阶段，并在学习结算页自动点“进入强化”。

听力对话页的自动流程：**只点一次左扬声器播放，然后连续点击右下角箭头 3 次**（提交并进入下一题）。右波形是“听自己的录音”，中间话筒是录音，自动流程不会点击它们。如果听力页按钮位置有偏移，运行 `setup` 第 5 步校准“播放”和“右下箭头”两个位置即可。

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

## 词库（发行包已内置）

发行包自带从 **ECDICT** 生成的英汉词库：`data/vocab.json.gz`，约 **10.7 万词、30 万义项**，解压后约 12 MB，采用 ECDICT 的 MIT 协议（见 `data/LICENSE-ECDICT.txt`）。本地存在 `cache/vocab.json` 时优先使用本地词库。

程序按以下顺序获取释义：

1. 本地 `cache/vocab.json`（CET4/CET6/高中词表 + ECDICT，可由 `tools/build_vocab.py` 生成）
2. `data/vocab.json.gz`（发行包自带 ECDICT 词库）
3. **ECDICT** 离线词典（可自行配置，词条更全）
4. 有道 / Bing 在线词典（需联网）

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
set ECDICT_DB=D:\dict\stardict.db
python tools\build_vocab.py --out cache\vocab.json
python tools\verify_vocab.py --vocab cache\vocab.json
```

只使用 ECDICT 生成可再分发的词库：

```bat
python tools\build_vocab.py --ecdict-only --out data\vocab.json
```

`tools/verify_vocab.py` 会检查词条结构、已知单词（bridge/intense/built/caught/chosen 等）并与 ECDICT 抽样比对，报告写入 `logs/vocab-report.txt`。

把本地学习记录（`cache/study.json`、`cache/learned.json`）中校验通过的释义并入本地词库：

```bat
python tools\merge_app_cache.py
```

脚本会过滤 OCR 误读和拼接片段（如 `agree -> 同思`、`顾客主顾`），报告写入 `logs/vocab-merge-report.txt`。词表来源请遵循其各自许可证。

## 配置项

首次运行 `setup` 会生成 `config.json`（已在 `.gitignore` 中忽略）。常用字段：

| 字段 | 说明 |
|---|---|
| `window_title` | 投屏窗口标题片段，留空则自动识别 |
| `bbox` | 截图区域 `[x1, y1, x2, y2]`，屏幕物理像素 |
| `keyboard.bbox` | 拼写页屏幕键盘区域（可校准） |
| `spell_input` | 拼写输入框点击位置 `[x, y]` |
| `listen.play` / `listen.next` | 听力页“左扬声器播放”和“右下箭头提交/下一题”的屏幕坐标（`setup` 第 5 步校准） |
| `listen.auto_flow` | `true`：播放一次后连续点右下箭头；`false`：只播放，默认 `true` |
| `listen.play_wait` | 播放后等待秒数，默认 2.0 |
| `listen.arrow_clicks` / `listen.arrow_interval` | 右下箭头连点次数/间隔，默认 3 次 / 0.4 秒 |
| `auto_enter_reinforce` | 学习结算后是否自动进入强化阶段，默认 `true` |
| `pack_memory` | 跨运行记住当前卡包单词与错词，默认 `true` |
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

**听力页点击位置不对**

- 听力对话页底部：左扬声器（播放）、中间话筒（录音）、右波形（听自己的录音）、右下箭头（提交并下一题）
- 自动流程只点“左扬声器一次 + 右下箭头连续 3 次”，不会点录音和右波形
- 程序默认按截图比例点击；窗口有标题栏或缩放时，运行 `setup` 第 5 步校准“播放”和“右下箭头”
- 校准坐标只在当前窗口位置有效；窗口移动后需重新校准
- 想调整连点次数/间隔：修改 `listen.arrow_clicks`、`listen.arrow_interval`
- 只想播放、不自动下一题：把 `listen.auto_flow` 改为 `false`

**想复盘错题 / 单词识别错误**

- 每次运行的答题记录保存在 `logs/answers-*.jsonl`
- 包含卡包、阶段、进度、OCR 单词、选项、实际点击与判题结果，可直接发到 issue

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
  session.py         卡包阶段识别、学习单词与错词记忆
  runner.py          主循环
tools/
  build_vocab.py     生成本地词库
  verify_vocab.py    校验词库结构与释义
  merge_app_cache.py 合并本地学习记录中的可靠释义
  sim_cases.json     离线选择题测试用例
data/
  vocab.json.gz      发行包自带 ECDICT 词库
  vocab-meta.json    词库版本/数量/校验值
  LICENSE-ECDICT.txt ECDICT MIT 许可证
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
