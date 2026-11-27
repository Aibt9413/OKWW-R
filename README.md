# SonicCore

基于 [OKWW-R](https://github.com/Aibt9413/OKWW-R)（其上游为 [ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves)）的二改衍生分支。

> 本项目最初用于测试 AI 代码生成的质量。在 OKWW-R 的自动化框架基础上，改造了启动器界面，并增加了版权保护与发布相关能力：模型 DPAPI 不落盘加密、Rust SHA256 校验壳、进程名中性化、静态混淆（版权保护，不做动态反作弊对抗）、单 exe SFX 封装、管理员权限与纯英文路径校验、系统 Python 缺失提示。
>
> 保留 SonicCore 品牌，清空了上游工坊 / GitHub submodule URL，日志名中性化。

#注意：非 ok-wuthering-waves 官方版本，也不保证更新。
#精力有限，同时不是专业开发人员，不保证更新。
#若有侵权，请联系。

## ⚠️ 以下是 ok-ww 团队免责声明

本软件为外部辅助工具，旨在自动化《鸣潮》的部分游戏流程。它完全通过模拟常规用户界面与游戏交互，遵循相关法律法规。本项目旨在简化用户的重复性操作，不会破坏游戏平衡或提供不公平优势，也绝不会修改任何游戏文件或数据。

本软件开源、免费，仅供个人学习与交流使用，请勿用于任何商业或营利性目的。开发者团队拥有本项目的最终解释权。因使用本软件而产生的任何问题，均与本项目及开发者无关。

请注意，根据库洛官方的《鸣潮》公平运营声明：
> 严禁利用任何第三方工具破坏游戏体验。
> 我们将严厉打击使用外挂、加速器、作弊软件、宏脚本等违规工具的行为，这些行为包括但不限于自动挂机、技能加速、无敌模式、瞬移、修改游戏数据等操作。
> 一经查证，我们将视违规情况和次数，采取包括但不限于扣除违规收益、冻结或永久封禁游戏账号等措施。

**使用本软件即表示您已阅读、理解并同意以上声明，并自愿承担一切潜在风险。**

## 🚀 运行

发布物为单文件 `wwcore.exe`，需在**纯英文路径**下以**管理员身份**运行（UAC 弹窗点"是"）。

源码运行需 Python 3.12 与依赖（见 `requirements-lock.txt`）：

```bash
set PYTHONPATH=games\wuthering
python main.py
```

## 🔨 构建

```powershell
.\build_single.ps1
```

链路：静态混淆注入 → PyInstaller onedir → Rust SFX launcher（固化数据区 SHA256）→ 打包单 exe → 完整性校验。

前提：`C:\wwbuild\venv`（Python 环境）、Rust GNU 工具链、windres、PyInstaller。

## 📂 主要结构

```
soniccore/
├── main.py                 # 启动入口（compat.install → load_game_config → OK）
├── config.py               # 启动器配置（custom_tabs 注入 HomeTab）
├── configs/                # 任务 / 设备 / 路径配置
├── games/wuthering/        # 游戏任务、角色、资源、i18n
├── okunified/              # 兼容层、GUI（主页 / 设置 / 悬浮窗 / 作用域）
│   ├── compat.py           # 运行时补丁、侧边栏整理、连接弹窗功能注入
│   └── security/           # 模型 DPAPI 加密容器
├── launcher/               # Rust SFX 校验壳（SHA256 / 归档 / UAC / 路径校验）
└── tools/
    ├── obfuscate.py        # 静态混淆（--apply / --undo / --verify）
    └── pack_single.py      # 单文件打包与校验
```

## 🗺️ 附带组件：IMAO 地图工具

SonicCore 随包附带 [IMAO](https://github.com/kahvia-d/IMAO)（鸣潮地图叠加/导航工具）的官方发布包，作为**独立进程**由「地图工具」页启动。两者是**聚合关系**：SonicCore 不链接、不修改 IMAO 代码，也未将其纳入 PyInstaller/SFX 主程序。

IMAO 采用 **GPL-3.0** 许可证，版权归 kahvia-d 及其贡献者所有：

- 上游源码：https://github.com/kahvia-d/IMAO
- GPL-3.0 全文：https://www.gnu.org/licenses/gpl-3.0.html
- 随包附带的 IMAO 发布包保持原样，未做修改

SonicCore 自身代码不受 GPL 传染（聚合分发），但为尊重上游许可，在此明确标注其归属与许可证。

## 版权与归属

上游 [ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) 与 [OKWW-R](https://github.com/Aibt9413/OKWW-R) 的原有版权归各自作者所有。本项目仅在其上做二改衍生，保留原项目归属与免责声明。
