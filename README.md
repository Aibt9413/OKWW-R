# OKWW-R

基于 [ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) 的可移植重构版本，支持自定义窗口选择和独立启动工具。

## 快速开始

### 方式一：便携模式（推荐）

将整个文件夹复制到任意 Windows 10/11 机器，双击 `OKWW-R.bat` 即可运行。

**要求：**
- Windows 10 1903+ 或 Windows 11
- 预装 Visual C++ Runtime（大多数系统已自带）

### 方式二：开发者模式

```bash
# 1. 克隆仓库
git clone <your-repo-url>
cd OKWW-R

# 2. 使用自带 Python 安装依赖
python-win\python.exe -m pip install -r requirements.txt

# 3. 启动
OKWW-R.bat
```

## 目录结构

```
OKWW-R/
├── OKWW-R.bat                  # 启动入口
├── python-win/                 # Python 3.11 运行时
├── testenv/
│   └── run_okww.py             # 引导脚本（环境诊断 + 启动）
├── ok-wuthering-waves-master/  # OKWW 应用源码
│   └── ok-wuthering-waves-master/
├── .deps/                      # [可选] 便携模式依赖
├── requirements.txt            # pip 依赖列表
└── README.md
```

## 自定义功能

### 其他窗口选择

在 Start 页的 **Choose Window** 列表底部，点击 **"Other Window..."** 可选择系统中任意可见窗口作为截图目标。

### 启动游戏开关

Start 页底部新增 **"Launch Game"** 开关：
- **关闭（默认）**：按 F9 仅启动工具，不启动游戏
- **开启**：按 F9 会连带启动游戏

如果窗口未连接，会弹出错误提示。

## 环境诊断

启动脚本会自动检查：
- Python 运行时是否存在
- 依赖目录/包是否完整
- Visual C++ Runtime 是否安装
- 关键包是否可导入

如有问题，会显示具体错误和下载链接。

## 下载链接

- [Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)
- [Python 3.11](https://www.python.org/downloads/release/python-3119/)

## 许可证

本项目基于 [ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) 的开源代码。
