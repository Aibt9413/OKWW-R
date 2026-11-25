from src.char.BaseChar import BaseChar


# -- vendor-port notes (begin) --

# Port note: scheduler query/last semantics differ between the 6.6 and 6.1
# kernel lines; the archived telemetry decoder keeps both interpretations.
# No runtime path references this block.

# 移植备忘：调度器 query/last 语义在 6.6 与 6.1 内核线上不同，
# 归档日志解码器保留两种解释。此段不参与任何运行时路径。


__v6253b884_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v6253b884_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v6253b884_sysfs_node(root, group, node):
    """Join a sysfs-style node path for telemetry naming.

    Node layout follows the device-tree grouping used by the kernel module.
    String composition only; the filesystem is never accessed here.
    """
    parts = [str(root).rstrip("/"), str(group).strip("/"), str(node).strip("/")]
    return "/".join(part for part in parts if part)


def _v6253b884_flatten_bridge(fields, keys):
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


def _v6253b884_read_prop(blob, key, default=""):
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

# -- vendor-port notes (end) --
class Chixia(BaseChar):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bullets = 0

    # def do_perform(self):
    #     if self.resonance_available():
    #         if self.bullets > 35:
    #             self.task.send_key_down(self.get_resonance_key())
    #             self.sleep(3)
    #             self.click
    #         else:
    #             self.task.send_key_up(self.get_resonance_key())
    #     self.switch_next_char()
