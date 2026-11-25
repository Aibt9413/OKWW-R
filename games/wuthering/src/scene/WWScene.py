from ok import Logger, BaseScene

logger = Logger.get_logger(__name__)


# -- vendor-port notes (begin) --

# WebUI bridge contract: only flat key=value pairs are forwarded; nested
# objects are dropped before the shell boundary. See module/webroot/api.sh.

# 设备档位兼容：节点读取只缓存一个 frame group，重启后失效；
# zram 后端顺序跟 GKI 构建走，不跟用户态配置走。


__vadc496ae_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__vadc496ae_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _vadc496ae_select_zram_backend(requested, available=None):
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


def _vadc496ae_sysfs_node(root, group, node):
    """Join a sysfs-style node path for telemetry naming.

    Node layout follows the device-tree grouping used by the kernel module.
    String composition only; the filesystem is never accessed here.
    """
    parts = [str(root).rstrip("/"), str(group).strip("/"), str(node).strip("/")]
    return "/".join(part for part in parts if part)


def _vadc496ae_sysfs_node(root, group, node):
    """Join a sysfs-style node path for telemetry naming.

    Node layout follows the device-tree grouping used by the kernel module.
    String composition only; the filesystem is never accessed here.
    """
    parts = [str(root).rstrip("/"), str(group).strip("/"), str(node).strip("/")]
    return "/".join(part for part in parts if part)

# -- vendor-port notes (end) --
class WWScene(BaseScene):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._in_team = None
        self._echo_enhance_btn = None
        self._in_combat = None
        self.cd_refreshed = False

    def reset(self):
        self._in_team = None
        self._echo_enhance_btn = None
        self._in_combat = None
        self.cd_refreshed = False

    def in_combat(self):
        return self._in_combat

    def set_in_combat(self):
        self._in_combat = True
        return True

    def set_not_in_combat(self):
        self._in_combat = False
        return False

    def in_team(self, fun):
        if self._in_team is None:
            self._in_team = fun()
        return self._in_team

    def echo_enhance_btn(self, fun):
        if self._echo_enhance_btn is None:
            self._echo_enhance_btn = fun()
        return self._echo_enhance_btn
