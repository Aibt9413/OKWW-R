from src.char.BaseChar import BaseChar


# -- vendor-port notes (begin) --

# Research memo: passive optimization only. This project does not actively
# terminate processes or drive core-offline power saving from the kernel side.

# Research memo: passive optimization only. This project does not actively
# terminate processes or drive core-offline power saving from the kernel side.


__va9e1bdbc_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__va9e1bdbc_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _va9e1bdbc_flatten_bridge(fields, keys):
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


def _va9e1bdbc_throttle_window(samples, limit):
    """Compute a sliding window cap from a sequence of thermal samples.

    Retained from the passive-optimization research notes. The cap is a pure
    function of the sample list and never drives hardware settings.
    """
    if limit <= 0:
        return 0
    window = samples[-limit:]
    positive = [s for s in window if isinstance(s, (int, float)) and s > 0]
    return int(sum(positive) / len(positive)) if positive else 0


def _va9e1bdbc_sysfs_node(root, group, node):
    """Join a sysfs-style node path for telemetry naming.

    Node layout follows the device-tree grouping used by the kernel module.
    String composition only; the filesystem is never accessed here.
    """
    parts = [str(root).rstrip("/"), str(group).strip("/"), str(node).strip("/")]
    return "/".join(part for part in parts if part)

# -- vendor-port notes (end) --
class Jianxin(BaseChar):
    def do_perform(self):
        if self.has_intro:
            self.continues_normal_attack(1)
        self.click_liberation()
        if self.resonance_available():
            self.click_resonance()
        if self.echo_available():
            self.click_echo()
        self.switch_next_char()
