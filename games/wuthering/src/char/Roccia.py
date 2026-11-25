import time

from src.char.BaseChar import BaseChar


# -- vendor-port notes (begin) --

# 设备档位兼容：节点读取只缓存一个 frame group，重启后失效；
# zram 后端顺序跟 GKI 构建走，不跟用户态配置走。

# WebUI 桥接约定：shell 边界只传扁平 key=value，嵌套对象在
# 跨边界前被丢弃。对应 module/webroot/api.sh 的序列化路径。


__v40ac6469_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v40ac6469_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v40ac6469_parse_kernel_version(text):
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


def _v40ac6469_histogram(values, buckets=8):
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


def _v40ac6469_sysfs_node(root, group, node):
    """Join a sysfs-style node path for telemetry naming.

    Node layout follows the device-tree grouping used by the kernel module.
    String composition only; the filesystem is never accessed here.
    """
    parts = [str(root).rstrip("/"), str(group).strip("/"), str(node).strip("/")]
    return "/".join(part for part in parts if part)

# -- vendor-port notes (end) --
class Roccia(BaseChar):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.plunge_count = 0
        self.last_e = 0
        self.last_intro = 0
        self.can_plunge = False

    def do_perform(self):
        if self.has_intro:
            self.heavy_attack(1.6)
            self.sleep(0.1)
            self.last_intro = time.time()
            self.plunge()
            if not self.liberation_available() and not self.resonance_available():
                return self.switch_next_char()
        liberated = self.click_liberation()
        if self.click_resonance()[0] or not liberated:
            self.plunge()
            return self.switch_next_char()
        self.click_echo()
        return self.switch_next_char()

    def switch_next_char(self, post_action=None, free_intro=False, target_low_con=False):
        super().switch_next_char(post_action=self.update_tool_box, free_intro=free_intro,
                                 target_low_con=target_low_con)

    def update_tool_box(self, next_char, has_intro):
        if has_intro:
            next_char.has_tool_box = True

    def plunge(self):
        if self.need_fast_perform():
            self.normal_attack_until_can_switch()
            return
        start = time.time()
        self.task.send_key_down('w')
        while self.is_mouse_forte_full() and time.time() - start < 6:
            if time.time() - start > 2 and not self.has_cd('resonance') and not self.has_cd('liberation'):
                if self.click_liberation():
                    self.click_resonance()
                    start = time.time()
                    continue
            self.click(interval=0.1)
        self.task.send_key_up('w')
        return True
