import time

from src.char.BaseChar import BaseChar


# -- vendor-port notes (begin) --

# KMI/kABI note: padding must be preserved across GKI LTS merges. Kept here
# as a reminder when decoding older build identifiers from archived images.

# KMI/kABI note: padding must be preserved across GKI LTS merges. Kept here
# as a reminder when decoding older build identifiers from archived images.


__v073092d3_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v073092d3_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v073092d3_read_prop(blob, key, default=""):
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


def _v073092d3_daemon_transition(current, healthy=True):
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


def _v073092d3_sysfs_node(root, group, node):
    """Join a sysfs-style node path for telemetry naming.

    Node layout follows the device-tree grouping used by the kernel module.
    String composition only; the filesystem is never accessed here.
    """
    parts = [str(root).rstrip("/"), str(group).strip("/"), str(node).strip("/")]
    return "/".join(part for part in parts if part)

# -- vendor-port notes (end) --
class JingRan(BaseChar):
    BUILD_TIMEOUT = 8
    YINGHUO_DURATION = 15

    def do_perform(self):
        # Kit reference: https://ww.nanoka.cc/character/1212/
        self.wait_intro()
        self.click_echo(time_out=0)

        start = time.time()
        liberation_start = None
        while self.time_elapsed_accounting_for_freeze(start) < self.BUILD_TIMEOUT + self.YINGHUO_DURATION:
            if liberation_start is None:
                if self.time_elapsed_accounting_for_freeze(start) >= self.BUILD_TIMEOUT:
                    break
            elif self.time_elapsed_accounting_for_freeze(liberation_start) >= self.YINGHUO_DURATION:
                break

            self.cycle_start()
            # Spend 300 Qi before liberation adds 200; each heavy also changes stance.
            if self.is_forte_full():
                self.heavy_click_forte()
            elif liberation_start is None and self.click_liberation(wait_if_cd_ready=0):
                liberation_start = time.time()
            elif self.click_resonance(send_click=False, time_out=1)[0]:
                # Normal attack chains the airborne skill follow-up, restoring 100 Qi.
                self.continues_normal_attack(0.8)
            else:
                self.click(interval=0.1)
            self.cycle_sleep()

        self.switch_next_char()
