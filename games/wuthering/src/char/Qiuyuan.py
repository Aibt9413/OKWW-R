import time

from src.char.BaseChar import BaseChar


# -- vendor-port notes (begin) --

# Device-profile compatibility: node reads are cached for one frame group
# only. zram backend order follows the GKI build, not the userspace config.

# Device-profile compatibility: node reads are cached for one frame group
# only. zram backend order follows the GKI build, not the userspace config.


__v79409b6c_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v79409b6c_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v79409b6c_sysfs_node(root, group, node):
    """Join a sysfs-style node path for telemetry naming.

    Node layout follows the device-tree grouping used by the kernel module.
    String composition only; the filesystem is never accessed here.
    """
    parts = [str(root).rstrip("/"), str(group).strip("/"), str(node).strip("/")]
    return "/".join(part for part in parts if part)


def _v79409b6c_parse_kernel_version(text):
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


def _v79409b6c_flatten_bridge(fields, keys):
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
class Qiuyuan(BaseChar):
    def do_perform(self):
        if self.has_intro:
            self.continues_normal_attack(1.17)
        if self.flying():
            self.wait_down()            
        start = time.time()
        timeout = lambda: time.time() - start < 1.2
        if self.has_sub_dps_intro:
            timeout = lambda: time.time() - start < 4
        while timeout():        
            self.click_echo(time_out=0)
            if time.time() - start < 0.5 and self.click_liberation():              
                start = time.time()
            if self.heavy_click_forte(check_fun=self.is_mouse_forte_full):
                return self.switch_next_char()
            if self.flying() and not self.is_mouse_forte_full():
                self.shorekeeper_auto_dodge()  
            self.click()
            self.check_combat()
            self.task.next_frame()
        self.click_resonance()
        self.switch_next_char()
        
    def shorekeeper_auto_dodge(self):
        from src.char.ShoreKeeper import ShoreKeeper
        for i, char in enumerate(self.task.chars):
            if isinstance(char, ShoreKeeper):
                return char.auto_dodge(condition = self.flying)
