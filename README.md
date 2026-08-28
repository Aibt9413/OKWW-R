# OKWW-R

基于 [ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) v3.6.6 的微量修改分支，在原有自动化框架上模仿了启动器界面。

> 本项目最初用于测试 AI 代码生成的质量，完成后作为独立分支发布。基于源码运行，未打包为安装程序。
  注意，非ok-wuthering-waves的官方版本，以及修改的代码质量极差，不建议使用。（应该没人会用我这一坨吧）
  精力有限，同时不是专业开发人员，不保证更新
  若有侵权，请联系。
## ⚠️ 以下是ok-ww团队免责声明

本软件为外部辅助工具，旨在自动化《鸣潮》的部分游戏流程。它完全通过模拟常规用户界面与游戏交互，遵循相关法律法规。本项目旨在简化用户的重复性操作，不会破坏游戏平衡或提供不公平优势，也绝不会修改任何游戏文件或数据。

本软件开源、免费，仅供个人学习与交流使用，请勿用于任何商业或营利性目的。开发者团队拥有本项目的最终解释权。因使用本软件而产生的任何问题，均与本项目及开发者无关。

请注意，根据库洛官方的《鸣潮》公平运营声明：
> 严禁利用任何第三方工具破坏游戏体验。
> 我们将严厉打击使用外挂、加速器、作弊软件、宏脚本等违规工具的行为，这些行为包括但不限于自动挂机、技能加速、无敌模式、瞬移、修改游戏数据等操作。
> 一经查证，我们将视违规情况和次数，采取包括但不限于扣除违规收益、冻结或永久封禁游戏账号等措施。

**使用本软件即表示您已阅读、理解并同意以上声明，并自愿承担一切潜在风险。**


## 🚀 快速开始


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
