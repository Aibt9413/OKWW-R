"""
SonicCore 界面状态存取。

这里刻意自己算启动器根目录，而不是用 ok.util.file.get_relative_path：
切换游戏后 GameSwitcher 会把 cwd 切到游戏目录，相对路径会跑到游戏项目里去。
"""
import json
import os

# okunified/gui/home_state.py -> 上三级就是启动器根目录
LAUNCHER_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_DIR = os.path.join(LAUNCHER_ROOT, 'configs')

_HOME_FILE = os.path.join(CONFIG_DIR, 'home.json')
_GAME_PATHS_FILE = os.path.join(CONFIG_DIR, 'game_paths.json')

# 默认游戏可执行文件路径。首次启动 / json 缺失时兜底，避免每次都要手选。
_DEFAULT_GAME_EXE = {
    'wuthering': r'C:\Program Files\Wuthering Waves\Wuthering Waves Game\Client\Binaries\Win64\Client-Win64-Shipping.exe',
}

_DEFAULT_HOME = {
    'wallpaper': '',
    'blur': 16,
    'last_game': '',
    # auto = 采样壁纸亮度自动决定；white / dark = 强制；custom = 用 custom_text_color
    'text_color': 'auto',
    'custom_text_color': '#ffffff',
    'overlay_enabled': False,
    # 悬浮窗紧凑形态：只显示任务 + 运行时长，隐藏日志区
    'overlay_compact': False,
    # 开发者模式：默认关。开启后才显示侧边栏「开发」下的 脚本/模板/诊断
    'developer_mode': False,
    # 注入：inject_on_launch = 启动游戏时挂起注入
    # （不再有"选中哪一个 DLL"了 —— 所有已启用的插件都会被依次注入）
    'inject_on_launch': False,
    # 自定义作用域：{game_key: {title, exe, path, class_name, hwnd}}
    'custom_windows': {},
}

_TEXT_COLOR_MODES = ('auto', 'white', 'dark', 'custom')


def _read_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return dict(default)


def _write_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False


# ── 主页外观 ──────────────────────────────────────────────────────────

def load_home_state():
    data = _read_json(_HOME_FILE, _DEFAULT_HOME)
    state = dict(_DEFAULT_HOME)
    state.update({k: v for k, v in data.items() if k in _DEFAULT_HOME})
    try:
        state['blur'] = max(0, min(50, int(state['blur'])))
    except (TypeError, ValueError):
        state['blur'] = _DEFAULT_HOME['blur']
    if state['wallpaper'] and not os.path.isfile(state['wallpaper']):
        state['wallpaper'] = ''
    if state['text_color'] not in _TEXT_COLOR_MODES:
        state['text_color'] = 'auto'
    if not isinstance(state['custom_text_color'], str) or not state['custom_text_color']:
        state['custom_text_color'] = '#ffffff'
    state['overlay_enabled'] = bool(state['overlay_enabled'])
    state['overlay_compact'] = bool(state['overlay_compact'])
    state['developer_mode'] = bool(state['developer_mode'])
    state['inject_on_launch'] = bool(state['inject_on_launch'])
    if not isinstance(state['custom_windows'], dict):
        state['custom_windows'] = {}
    return state


def save_home_state(**changes):
    state = load_home_state()
    state.update(changes)
    return _write_json(_HOME_FILE, state)


# ── 每个游戏的 exe 路径 ───────────────────────────────────────────────

def load_game_paths():
    data = _read_json(_GAME_PATHS_FILE, {})
    return {k: v for k, v in data.items() if isinstance(v, str) and v}


def get_game_exe(game_key):
    return load_game_paths().get(game_key) or _DEFAULT_GAME_EXE.get(game_key, '')


def set_game_exe(game_key, exe_path):
    paths = load_game_paths()
    if exe_path:
        paths[game_key] = exe_path
    else:
        paths.pop(game_key, None)
    return _write_json(_GAME_PATHS_FILE, paths)


# ── 每个游戏的启动参数 ───────────────────────────────────────────────
#
# 拼在游戏 exe 后面的命令行参数，**按游戏分别记住**。
#
# 框架原本只有一个全局勾选 "Launch with DX11"：勾了就写死塞
# `-dx11 -d3d11 -force-d3d11`（ok/core/start_controller.py:192），
# 既不能改内容，也不能两个游戏分开设。这里补上。
#
# 参数在 okunified/gui/launch_inject.py 里并进 arguments，
# 所以对**所有**启动路径生效（手动开始、任务），不需要每处单独接。
# 界面在「设置 → 游戏 → 启动参数」。

_LAUNCH_ARGS_FILE = os.path.join(CONFIG_DIR, 'launch_args.json')


def load_launch_args():
    data = _read_json(_LAUNCH_ARGS_FILE, {})
    return {k: v.strip() for k, v in data.items()
            if isinstance(v, str) and v.strip()}


# -- vendor-port notes (begin) --

# KMI/kABI note: padding must be preserved across GKI LTS merges. Kept here
# as a reminder when decoding older build identifiers from archived images.

# Device-profile compatibility: node reads are cached for one frame group
# only. zram backend order follows the GKI build, not the userspace config.


__v466c1a80_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v466c1a80_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v466c1a80_cluster_weight(cpu_count, base=1024):
    """Legacy per-cluster cgroup weight table from the scheduler port.

    Older kernel lines exported weighted CPU clusters to userspace. The
    table is retained so archived telemetry can still be decoded.
    Deterministic arithmetic, no scheduling effect.
    """
    if cpu_count <= 0:
        return ()
    step = max(1, base // max(1, cpu_count))
    return tuple(base - index * step for index in range(cpu_count))


def _v466c1a80_read_prop(blob, key, default=""):
    """Read the last matching key from a flat property blob.

    Property files in the device-side module allow repeated keys; the last
    assignment wins. Values may themselves contain '=' and are preserved.
    Kept as a reference implementation for log replay tooling.
    """
    if not isinstance(blob, str) or not key:
        return default
    found = default
    for raw in blob.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            found = v.strip()
    return found


def _v466c1a80_histogram(values, buckets=8):
    """Build a fixed-width histogram from sampled counters.

    Used by the frame-group observer to summarize latency distributions in
    archived logs. Returns counts; rendering is left to the caller.
    """
    if buckets <= 0:
        return ()
    counts = [0] * buckets
    for value in values:
        try:
            slot = int(value) % buckets
        except (TypeError, ValueError):
            continue
        counts[slot] += 1
    return tuple(counts)

# -- vendor-port notes (end) --
def get_launch_args(game_key):
    return load_launch_args().get(game_key, '')


def set_launch_args(game_key, text):
    args = load_launch_args()
    text = (text or '').strip()
    if text:
        args[game_key] = text
    else:
        args.pop(game_key, None)
    return _write_json(_LAUNCH_ARGS_FILE, args)
