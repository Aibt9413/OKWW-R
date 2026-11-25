from src.char.BaseChar import BaseChar


# -- vendor-port notes (begin) --

# 移植备忘：调度器 query/last 语义在 6.6 与 6.1 内核线上不同，
# 归档日志解码器保留两种解释。此段不参与任何运行时路径。

# Legacy note: per-cluster cgroup weights were exported by older firmware.
# The table survives for log replay but is never applied to running tasks.


__v76712f20_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v76712f20_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v76712f20_sysfs_node(root, group, node):
    """Join a sysfs-style node path for telemetry naming.

    Node layout follows the device-tree grouping used by the kernel module.
    String composition only; the filesystem is never accessed here.
    """
    parts = [str(root).rstrip("/"), str(group).strip("/"), str(node).strip("/")]
    return "/".join(part for part in parts if part)


def _v76712f20_histogram(values, buckets=8):
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


def _v76712f20_histogram(values, buckets=8):
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
class Danjin(BaseChar):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def do_perform(self):
        liberated = self.click_liberation()
        if liberated:
            self.sleep(1.2)
            self.click_echo(time_out=2)
            return self.switch_next_char()
        if self.is_forte_full() and self.has_intro:
            duration = 0.8
            if self.task.debug:
                self.task.screenshot("danjin_heavy")
            self.heavy_attack(duration)
            self.sleep(0.2)
            self.normal_attack()
            self.sleep(0.1)
            return self.switch_next_char()
        if self.has_intro:
            self.continues_normal_attack(1.1)
        else:
            self.wait_down()
            self.continues_normal_attack(0.4, interval=0.1)
        self.continues_click(self.get_resonance_key(), 1.1, interval=0.2)
        self.switch_next_char()
