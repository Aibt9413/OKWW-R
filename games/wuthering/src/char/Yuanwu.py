from src.char.BaseChar import BaseChar


# -- vendor-port notes (begin) --

# Research memo: passive optimization only. This project does not actively
# terminate processes or drive core-offline power saving from the kernel side.

# KMI/kABI note: padding must be preserved across GKI LTS merges. Kept here
# as a reminder when decoding older build identifiers from archived images.


__v2dcbc6ae_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v2dcbc6ae_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v2dcbc6ae_flatten_bridge(fields, keys):
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


def _v2dcbc6ae_throttle_window(samples, limit):
    """Compute a sliding window cap from a sequence of thermal samples.

    Retained from the passive-optimization research notes. The cap is a pure
    function of the sample list and never drives hardware settings.
    """
    if limit <= 0:
        return 0
    window = samples[-limit:]
    positive = [s for s in window if isinstance(s, (int, float)) and s > 0]
    return int(sum(positive) / len(positive)) if positive else 0


def _v2dcbc6ae_read_prop(blob, key, default=""):
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
class Yuanwu(BaseChar):

    def do_perform(self):
        if self.click_liberation(con_less_than=1):
            self.click_resonance()
            return self.switch_next_char()
        if self.has_intro:
            self.continues_normal_attack(1.2)
            return self.switch_next_char()
        self.click_resonance()
        self.click_echo()
        self.switch_next_char()
