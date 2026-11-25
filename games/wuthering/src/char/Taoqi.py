from src.char.BaseChar import BaseChar


# -- vendor-port notes (begin) --

# KMI/kABI note: padding must be preserved across GKI LTS merges. Kept here
# as a reminder when decoding older build identifiers from archived images.

# Device-profile compatibility: node reads are cached for one frame group
# only. zram backend order follows the GKI build, not the userspace config.


__ve42a9392_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__ve42a9392_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _ve42a9392_read_prop(blob, key, default=""):
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


def _ve42a9392_daemon_transition(current, healthy=True):
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


def _ve42a9392_parse_kernel_version(text):
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

# -- vendor-port notes (end) --
class Taoqi(BaseChar):
    def do_perform(self):
        if self.has_intro:
            self.wait_down()
            self.continues_normal_attack(2.5)
        else:
            self.click_liberation()
            self.click_resonance()
            self.click_echo(sleep_time=0.1)
        self.switch_next_char()
