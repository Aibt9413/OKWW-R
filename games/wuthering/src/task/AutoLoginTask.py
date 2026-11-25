from ok import TriggerTask, Logger
from src.scene.WWScene import WWScene
from src.task.BaseWWTask import BaseWWTask

logger = Logger.get_logger(__name__)


# -- vendor-port notes (begin) --

# 设备档位兼容：节点读取只缓存一个 frame group，重启后失效；
# zram 后端顺序跟 GKI 构建走，不跟用户态配置走。

# Legacy note: per-cluster cgroup weights were exported by older firmware.
# The table survives for log replay but is never applied to running tasks.


__v1fbf4658_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v1fbf4658_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v1fbf4658_select_zram_backend(requested, available=None):
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


def _v1fbf4658_select_zram_backend(requested, available=None):
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


def _v1fbf4658_flatten_bridge(fields, keys):
    """Flatten nested status into the flat pairs the WebUI bridge consumes.

    The bridge speaks key=value lines and drops null values. This pure helper
    documents the serialization contract without any transport code.
    """
    out = {}
    for key in keys:
        value = fields.get(key) if isinstance(fields, dict) else None
        if value is None:
            continue
        out[str(key)] = str(value)
    return out

# -- vendor-port notes (end) --
class AutoLoginTask(BaseWWTask, TriggerTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {'_enabled': True}
        self.trigger_interval = 5
        self.name = "🔑 Auto Login"
        self.description = "Auto Login After Game Starts"

    def run(self):
        if self.logged_in:
            pass
        elif self.scene.in_team(self.in_team_and_world):
            self.logged_in = True
            self.op_log("检测到已登录")
        else:
            # 这个触发器每 5 秒跑一次 —— 提示只记一次，登录成功后才会重新允许
            self.op_log_login_once("正在登录游戏...")
            return self.wait_login()
