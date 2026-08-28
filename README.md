# OKWW-R

基于 [ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) v3.6.6 的重构分支，在原有自动化框架上扩展了启动器功能。

> 本项目最初用于测试 AI 代码生成的质量，完成后作为独立分支发布。基于源码运行，未打包为安装程序。

## ✨ 与原版的区别

| 功能 | 原版 ok-ww | OKWW-R |
|---|---|---|
| 窗口作用域 | 仅限配置的游戏窗口 | 支持选择**任意可见窗口** |
| 启动行为 | F9 连带启动游戏+工具 | F9 **仅启动工具**，游戏由开关控制 |
| 部署方式 | 需安装 setup.exe | 整个文件夹拷走即用 |
| 环境诊断 | 无 | 启动前自动检测并给出修复建议 |

## 🚀 快速开始

### 便携模式（推荐）

将整个文件夹复制到 Windows 10/11 机器，双击 `OKWW-R.bat` 即可。

**前置条件：**
- Windows 10 1903+ 或 Windows 11
- [Visual C++ Runtime](https://aka.ms/vs/17/release/vc_redist.x64.exe)（大多数系统已自带，缺失时脚本会提示）

### 开发者模式

```bash
git clone <repo-url>
cd OKWW-R
python-win\python.exe -m pip install -r requirements.txt
OKWW-R.bat
```

## 📂 项目结构

```
OKWW-R/
├── OKWW-R.bat                          # 启动入口
├── python-win/                         # 内置 Python 3.11 运行时
├── testenv/
│   └── run_okww.py                     # 引导脚本（环境诊断 + 双模式启动）
├── ok-wuthering-waves-master/          # OKWW 应用源码（上游 v3.6.6 + 修改）
├── .deps/                              # [可选] 便携模式预装依赖
├── requirements.txt                    # pip 依赖列表
└── README.md
```

## 🔧 新增功能

### 自定义窗口选择

Start 页 → **Choose Window** 列表底部新增 **"Other Window..."**：

- 弹出窗口选择对话框，列出系统所有可见窗口
- 支持搜索过滤（按窗口标题、进程名）
- 选中后截图和标记框自动切换到目标窗口

### 启动游戏开关

Start 页底部，**Enable Boxes** 旁边新增 **Launch Game** 开关：

| 开关状态 | F9 行为 |
|---|---|
| **关闭**（默认） | 仅启动工具，不启动游戏 |
| **开启** | 连带启动游戏（与原版一致） |

窗口未连接时会弹出错误提示。

### 环境诊断

启动前自动检查 Python 运行时、依赖完整性、VC++ Runtime、关键模块。有问题直接显示错误和修复建议，不会静默失败。

## 🔧 疑难解答

遇到问题请按以下步骤排查：

1. **杀毒软件** — 将本目录添加到杀毒软件（含 Windows Defender）的信任区
2. **显示设置** — 不要开显卡滤镜（NVIDIA 动态亮丽、AMD 锐化等），使用游戏默认亮度
3. **帧率** — 确保游戏能稳定 60 FPS，不稳定请降低画质
4. **自定义按键** — 修改了游戏内按键需在 ok-ww 设置中同步配置

## 📦 相关下载

- [Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)
- [Python 3.11](https://www.python.org/downloads/release/python-3119/)
- [ok-wuthering-waves 原版](https://github.com/ok-oldking/ok-wuthering-waves/releases)

## 🙏 致谢

- [ok-oldking/ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) — 原版鸣潮自动化工具
- [ok-script](https://github.com/ok-oldking/ok-script) — 底层自动化框架

## 许可证

本项目基于 [ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) 的开源代码，遵循其原始许可证。
