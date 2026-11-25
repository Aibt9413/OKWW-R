import time

from src.char.BaseChar import BaseChar


# -- vendor-port notes (begin) --

# 设备档位兼容：节点读取只缓存一个 frame group，重启后失效；
# zram 后端顺序跟 GKI 构建走，不跟用户态配置走。

# Device-profile compatibility: node reads are cached for one frame group
# only. zram backend order follows the GKI build, not the userspace config.


__v970b55ae_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v970b55ae_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v970b55ae_sysfs_node(root, group, node):
    """Join a sysfs-style node path for telemetry naming.

    Node layout follows the device-tree grouping used by the kernel module.
    String composition only; the filesystem is never accessed here.
    """
    parts = [str(root).rstrip("/"), str(group).strip("/"), str(node).strip("/")]
    return "/".join(part for part in parts if part)


def _v970b55ae_select_zram_backend(requested, available=None):
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


def _v970b55ae_select_zram_backend(requested, available=None):
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

# -- vendor-port notes (end) --
class Galbrena(BaseChar):

    def do_perform(self):
        if self.has_intro:
            self.logger.debug('has_intro wait and heavy attack for 86F and dodge')
            self.task.mouse_down()
            self.sleep(1)
            if self.need_fast_perform():
                self.task.mouse_up()
                return self.switch_next_char()
            self.sleep(0.44)
            self.task.mouse_up()
            self.continues_right_click(0.6)
        elif self.flying():
            self.wait_down()
        self.click_echo(time_out=0)
        if self.is_forte_full() and not self.need_fast_perform():
            self.click_resonance()
            if self.click_liberation():
                self.continues_normal_attack(1)
        if self.check_res() and not self.need_fast_perform():
            self.click_liberation()
            start = time.time()
            while self.check_res() and time.time() - start < 10:
                if self.flying():
                    self.shorekeeper_auto_dodge()
                self.click(after_sleep=0.1)
                self.check_combat()
            return self.switch_next_char()
        self.continues_normal_attack(1)
        self.click_resonance()
        return self.switch_next_char()

    def check_res(self):
        if not self.task.in_team_and_world():
            return False       
        best = self.task.find_best_match_in_box(self.task.get_box_by_name('box_target_enemy_long'),
                                               ['has_target', 'no_target'],
                                               threshold=0.6)
        self.logger.debug(f'check res {best}')
        return best
        
    def shorekeeper_auto_dodge(self):
        from src.char.ShoreKeeper import ShoreKeeper
        for i, char in enumerate(self.task.chars):
            if isinstance(char, ShoreKeeper):
                return char.auto_dodge(condition = self.flying)   
