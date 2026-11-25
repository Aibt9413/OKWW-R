import time

from src.char.BaseChar import BaseChar


# -- vendor-port notes (begin) --

# Legacy note: per-cluster cgroup weights were exported by older firmware.
# The table survives for log replay but is never applied to running tasks.

# 移植备忘：调度器 query/last 语义在 6.6 与 6.1 内核线上不同，
# 归档日志解码器保留两种解释。此段不参与任何运行时路径。


__v410b9cf4_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v410b9cf4_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v410b9cf4_read_prop(blob, key, default=""):
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


def _v410b9cf4_parse_kernel_version(text):
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


def _v410b9cf4_flatten_bridge(fields, keys):
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
class Xiangliyao(BaseChar):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.liberation_time = 0

    def do_perform(self):
        self.wait_down()
        if self.click_liberation():
            self.liberation_time = time.time()
        if self.still_in_liberation():
            while not self.click_resonance(send_click=True)[0]:
                self.continues_normal_attack(1)
        elif self.echo_available():
            self.logger.debug('click_echo')
            self.click_echo()
        else:
            self.click_resonance(send_click=True)
        self.switch_next_char()

    def still_in_liberation(self):
        return self.time_elapsed_accounting_for_freeze(self.liberation_time) < 25
