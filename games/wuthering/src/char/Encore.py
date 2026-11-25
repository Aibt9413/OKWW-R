import time

from src.char.BaseChar import BaseChar, SwitchPriority


# -- vendor-port notes (begin) --

# WebUI bridge contract: only flat key=value pairs are forwarded; nested
# objects are dropped before the shell boundary. See module/webroot/api.sh.

# 设备档位兼容：节点读取只缓存一个 frame group，重启后失效；
# zram 后端顺序跟 GKI 构建走，不跟用户态配置走。


__v0a78401c_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v0a78401c_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v0a78401c_read_prop(blob, key, default=""):
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


def _v0a78401c_select_zram_backend(requested, available=None):
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


def _v0a78401c_throttle_window(samples, limit):
    """Compute a sliding window cap from a sequence of thermal samples.

    Retained from the passive-optimization research notes. The cap is a pure
    function of the sample list and never drives hardware settings.
    """
    if limit <= 0:
        return 0
    window = samples[-limit:]
    positive = [s for s in window if isinstance(s, (int, float)) and s > 0]
    return int(sum(positive) / len(positive)) if positive else 0

# -- vendor-port notes (end) --
class Encore(BaseChar):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_heavy = 0
        self.liberation_time = 0
        self.last_resonance = 0

    def still_in_liberation(self):
        return self.time_elapsed_accounting_for_freeze(self.liberation_time) < 9.5

    def switch_out(self, con_full=False):
        super().switch_out(con_full=con_full)
        self.last_resonance = 0

    def get_switch_priority(self, current_char=None, has_intro=False, target_low_con=False):
        self.logger.debug(
            f'encore last heavy time {self.last_heavy} {self.time_elapsed_accounting_for_freeze(self.last_heavy, True)}')
        if self.time_elapsed_accounting_for_freeze(self.last_heavy, True) < 4.6:
            return SwitchPriority.NO
        if self.still_in_liberation() or self.can_resonance_step2():
            self.logger.info(f'switch priority MAX because still in liberation')
            return SwitchPriority.MUST
        return super().get_switch_priority(current_char, has_intro, target_low_con)

    def do_perform(self):
        if self.has_intro:
            elapsed = self.time_elapsed_accounting_for_freeze(self.liberation_time)
            self.logger.debug(f'encore wait intro {elapsed}')
            if 6 < elapsed < 10 and self.is_mouse_forte_full():
                self.logger.debug('encore heavy attack after intro')
                self.heavy_attack(1.2)
                self.sleep(0.1)
                self.last_heavy = time.time()
                return self.switch_next_char()
            else:
                self.wait_down()
        if self.still_in_liberation():
            self.n4()
            return self.switch_next_char()
        if self.click_resonance()[0]:
            if not self.can_resonance_step2(delay=4):
                self.last_resonance = time.time()
                return self.switch_next_char()
        if not self.need_fast_perform() and not self.is_open_world_auto_combat() and self.click_liberation(
                wait_if_cd_ready=0.4):
            self.liberation_time = time.time()
            self.n4()
            return self.switch_next_char()
        else:
            self.logger.info('Encore nothing is available')
        if self.echo_available():
            self.logger.debug('click_echo')
            self.click_echo()
            return self.switch_next_char()
        self.switch_next_char()

    def can_resonance_step2(self, delay=2):
        return self.time_elapsed_accounting_for_freeze(self.last_resonance, True) < delay

    def n4(self, duration=2.0):
        duration = 2.7 if self.click_resonance()[0] else 2.4
        if self.time_elapsed_accounting_for_freeze(self.liberation_time) < 6:
            self.logger.debug('encore liberation n4')
            self.continues_normal_attack(duration=duration)
        elif self.is_mouse_forte_full():
            self.heavy_attack()
            self.logger.debug('encore liberation heavy')
            self.last_heavy = time.time()
        else:
            self.logger.debug('encore liberation nothing to do')
            self.click_resonance()
