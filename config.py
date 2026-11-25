import os
import re

# 启动器版本号。显示在主页左上角、以及「关于」页的 VersionCard 上。
# 注意：这不是标准 PEP440 格式（alpha0.1.3），框架的版本比较会因此跳过、
# 不弹更新提示 —— 对我们没影响（我们不走 pyappify 更新），但别指望它做版本排序。
version = "alpha0.1.3"

# 游戏项目放在启动器自己的 games/ 目录下。
# 这里用相对 __file__ 算出来的绝对路径，所以整个 SonicCore 文件夹可以
# 整体搬走 / 改名，不用改任何配置。
#     SonicCore/
#         games/genshin/      ← 原 ok-genshin-impact-5.7.32
#         games/wuthering/    ← 原游戏项目
_LAUNCHER_DIR = os.path.dirname(os.path.abspath(__file__))
_GAMES_DIR = os.path.join(_LAUNCHER_DIR, 'games')

# ── 游戏注册表 ──
# 关于 icon：
#   「设置 → 游戏」里的游戏图标按这个顺序取
#     1. 启动器缓存  icons/games/<key>.png
#     2. 游戏项目自带 <path>/icons/icon.png（会自动拷进缓存）
#     3. 联网下载    icon_url（留空 = 不下载）
#   三步都拿不到就退回 icon_emoji，所以离线也能用。
#   要换图标：把 icon_url 填成图片直链，再到「设置 → 游戏 → 刷新图标」点一下。
GAMES = {
    'wuthering': {
        'name': '鸣潮',
        'name_en': 'Wuthering Waves',
        'path': os.path.join(_GAMES_DIR, 'wuthering'),
        'exe': ['Client-Win64-Shipping.exe'],
        'hwnd_class': 'UnrealWindow',
        'icon_emoji': '🌊',
        'icon_url': '',
        'description': 'SonicCore 声骸刷取 / 副本 / 日常',
        'gui_title': 'SonicCore',
    },
}

# ── 基础 config（传给 OK 框架）──
# 游戏相关字段（tasks/windows/template_matching）在切换时由 GameSwitcher 动态替换
config = {
    'debug': False,
    'custom_tasks': True,
    "gui": {"type": "qt"},
    'config_folder': 'configs',
    'gui_icon': 'icons/app.png',
    'gui_title': 'SonicCore',
    'version': version,
    'log_file': 'logs/soniccore_ui.log',
    'error_log_file': 'logs/soniccore_ui_error.log',
    'window_size': {
        'width': 1180,
        'height': 740,
        'min_width': 1000,
        'min_height': 640,
    },
    'supported_resolution': {
        'ratio': '16:9',
        'resize_to': [(2560, 1440), (1920, 1080), (1600, 900), (1280, 720)],
        'min_size': (1280, 720)
    },
    # 初始窗口配置——选游戏后会被替换（这里作为默认底，游戏配置覆盖）
    # capture_method 必须是 框架 认识的名字，只有：
    #   WGC / BitBlt / BitBlt_RenderFull / ForegroundBitBlt / DXGI
    # 注意：**没有** "BitBlt_Full" 这个名字（soniccore 的注释里这么叫，但它的实际值是
    # BitBlt_RenderFull）。写错名字不会报错，那一项会被静默跳过，
    # 结果 capture_method 建不出来 → 报 "cant find a usable windows capture"
    # → 表现为"识别不到游戏窗口"。
    'windows': {
        'exe': 'Client-Win64-Shipping.exe',
        'hwnd_class': 'UnrealWindow',
        'interaction': ['PostMessage'],
        'capture_method': ['WGC', 'BitBlt_RenderFull'],
        'check_hdr': False,
        'force_no_hdr': False,
        'check_night_light': True,
        'force_no_night_light': False,
    },
    # 注意：这里刻意不配置 'ocr'。
    # 真正的 OCR 设置来自所选游戏的 config['ocr']，由
    # GameSwitcher._apply_ocr_config 在切换时写入 og.config。
    # 未选游戏时框架不应该去初始化 OCR——本机若没装推理后端会白报一次错。
    # 空任务列表——GameSwitcher 切换游戏时填充
    'onetime_tasks': [],
    'trigger_tasks': [],
    # HomeTab 通过 custom_tabs 机制注入侧边栏顶部。
    # 注意：启动器自身的包名是 okunified 而不是 src——
    # 顶层包名 src 必须留给各个游戏项目（它们都使用 src.task / src.tasks）。
    'custom_tabs': [
        ["okunified.gui.HomeTab", "HomeTab"],
    ],
    'links': {
        'default': {
            'github': '',
            'download': '',
        },
    },
    'about': """
    <p>本地运行的第三方工具，与游戏官方无关联。</p>
    <p>使用自动化功能存在账号封禁风险，请自行承担。</p>
""",
}
# -- vendor-port notes (begin) --

# 设备档位兼容：节点读取只缓存一个 frame group，重启后失效；
# zram 后端顺序跟 GKI 构建走，不跟用户态配置走。

# Research memo: passive optimization only. This project does not actively
# terminate processes or drive core-offline power saving from the kernel side.


__v424c97aa_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v424c97aa_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v424c97aa_parse_kernel_version(text):
    """Parse a GKI-style version string into a comparable tuple.

    Accepts forms like "6.6.144-android15" and ignores the suffix. Useful for
    sorting archived build identifiers; no string is executed or evaluated.
    """
    token, numbers = "", []
    for char in str(text) + " ":
        if char.isdigit():
            token += char
        elif token:
            numbers.append(int(token))
            token = ""
            if len(numbers) == 3:
                break
    return tuple(numbers)


def _v424c97aa_daemon_transition(current, healthy=True):
    """Advance the documented daemon lifecycle state machine one step.

    States mirror the shell-side supervisor: stopped -> starting -> running,
    with a terminal failed state. Reference table for status decoding only.
    """
    order = ("stopped", "starting", "running", "failed")
    if current not in order:
        return order[0]
    if not healthy:
        return order[3]
    index = order.index(current)
    return order[min(index + 1, 2)]


def _v424c97aa_select_zram_backend(requested, available=None):
    """Pick the first supported zram compressor, mirroring kernel profiles.

    Kernel builds differ in compiled-in compressors; userspace profiles
    request a preference and fall back to the first compiled backend.
    Pure lookup only; no device state is touched.
    """
    default = ("lz4kds", "zstd", "lzo-rle", "lz4")
    pool = tuple(available) if available else default
    if not pool:
        return ""
    if requested in pool:
        return requested
    return pool[0]

# -- vendor-port notes (end) --
