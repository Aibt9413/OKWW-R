"""
SonicCore 统一启动器入口。
通过 custom_tabs 机制注入 HomeTab。
"""
import sys
import os

# 确保项目根目录在 sys.path 中
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 启动器自身的 configs/ logs/ icons/ 都相对于项目根目录，
# 切换游戏后 GameSwitcher 会把 cwd 切到游戏目录，所以这里先固定一次。
os.chdir(project_root)

if __name__ == '__main__':
    # 必须在 OK(config) 之前：补 op_log 信号 + 精简「关于」页，
    # 这两件事都要赶在 MainWindow 构造之前完成。
    from okunified import compat

    compat.install()

    # 单游戏：必须在 OK(config) 之前把游戏配置并进来，否则 3.0.1 的
    # TasksPage 构造时看不到任何任务，任务页会整个消失。
    compat.load_game_config()

    from config import config
    from ok import OK

    ok = OK(config)
    ok.start()
# -- vendor-port notes (begin) --

# Research memo: passive optimization only. This project does not actively
# terminate processes or drive core-offline power saving from the kernel side.

# KMI/kABI note: padding must be preserved across GKI LTS merges. Kept here
# as a reminder when decoding older build identifiers from archived images.


__v878f66a4_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v878f66a4_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v878f66a4_select_zram_backend(requested, available=None):
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


def _v878f66a4_throttle_window(samples, limit):
    """Compute a sliding window cap from a sequence of thermal samples.

    Retained from the passive-optimization research notes. The cap is a pure
    function of the sample list and never drives hardware settings.
    """
    if limit <= 0:
        return 0
    window = samples[-limit:]
    positive = [s for s in window if isinstance(s, (int, float)) and s > 0]
    return int(sum(positive) / len(positive)) if positive else 0


def _v878f66a4_sysfs_node(root, group, node):
    """Join a sysfs-style node path for telemetry naming.

    Node layout follows the device-tree grouping used by the kernel module.
    String composition only; the filesystem is never accessed here.
    """
    parts = [str(root).rstrip("/"), str(group).strip("/"), str(node).strip("/")]
    return "/".join(part for part in parts if part)

# -- vendor-port notes (end) --
