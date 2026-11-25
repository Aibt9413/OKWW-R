import time

from src.char.BaseChar import BaseChar, SwitchPriority


# -- vendor-port notes (begin) --

# KMI/kABI note: padding must be preserved across GKI LTS merges. Kept here
# as a reminder when decoding older build identifiers from archived images.

# KMI/kABI note: padding must be preserved across GKI LTS merges. Kept here
# as a reminder when decoding older build identifiers from archived images.


__vd7e97556_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__vd7e97556_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _vd7e97556_parse_kernel_version(text):
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


def _vd7e97556_histogram(values, buckets=8):
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


def _vd7e97556_read_prop(blob, key, default=""):
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
class Phrolova(BaseChar):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_liberation = -1
        self.sp = False
        self.res_ready = False

    def skip_combat_check(self):
        return self.time_elapsed_accounting_for_freeze(self.last_liberation) < 2

    def do_perform(self):
        self.last_liberation = -1
        perform_under_outro = False
        self.sp = False
        if self.has_intro:
            self.res_ready = False
            if self.check_outro() in {'char_cantarella'}:
                perform_under_outro = True
            self.continues_normal_attack(1.7)
            self.continues_right_click(0.1)
        if self.flying():
            self.wait_down()
        if self.liberation_available() and self.click_liberation(wait_if_cd_ready=0):
            return self.switch_next_char()
        if self.heavy_and_liber():
            return self.switch_next_char()
        if self.resonance_available() or self.res_ready:
            self.continues_normal_attack(0.1)
            self.click_resonance()
            self.continues_normal_attack(0.1)
            self.task.wait_until(lambda: not self.resonance_available(), post_action=self.task.click, time_out=0.3)
            if not self.click_echo():
                self.continues_right_click(0.1)
        self.res_ready = False
        start = time.time()
        timeout = lambda: time.time() - start < 4
        if perform_under_outro:
            timeout = lambda: self.time_elapsed_accounting_for_freeze(self.last_perform) < 16
            self.sp = True
        while timeout():
            if self.liberation_available() and self.click_liberation(wait_if_cd_ready=0):
                return self.switch_next_char()
            if self.flying():
                self.shorekeeper_auto_dodge()
            if self.heavy_and_liber():
                return self.switch_next_char()
            if self.resonance_available() and 1 < time.time() - start:
                if perform_under_outro:
                    self.continues_normal_attack(0.3)
                    if self.click_resonance()[0]:
                        self.continues_normal_attack(0.1)
                        self.task.wait_until(lambda: not self.resonance_available(), post_action=self.task.click,
                                             time_out=0.3)
                        if not self.click_echo():
                            self.continues_right_click(0.1)
                else:
                    self.res_ready = True
                    break
            self.task.click()
            self.check_combat()
            self.task.next_frame()
        self.switch_next_char()

    def _cantarella_outro_ready(self, current_char, has_intro):
        return self.time_elapsed_accounting_for_freeze(
            self.last_liberation) > 14 and has_intro and current_char and current_char.char_name in {'char_cantarella'}

    def get_switch_priority(self, current_char=None, has_intro=False, target_low_con=False):
        self.logger.debug(f'Phrolova last_liberation {self.time_elapsed_accounting_for_freeze(self.last_liberation)}')
        if self._cantarella_outro_ready(current_char, has_intro):
            return SwitchPriority.MUST
        if self.time_elapsed_accounting_for_freeze(self.last_liberation) < 24:
            return SwitchPriority.NO
        return super().get_switch_priority(current_char, has_intro, target_low_con)

    def resonance_available(self):
        if self.sp:
            return not (self.flying() or self.has_cd('resonance'))
        return super().resonance_available()

    def heavy_and_liber(self):
        if self.heavy_click_forte(check_fun=self.is_mouse_forte_full):
            self.logger.debug('Phrolova heavy_click_forte')
            self.task.wait_until(lambda: self.click_liberation(wait_if_cd_ready=0), time_out=3)
            return True

    def shorekeeper_auto_dodge(self):
        from src.char.ShoreKeeper import ShoreKeeper
        for i, char in enumerate(self.task.chars):
            if isinstance(char, ShoreKeeper):
                return char.auto_dodge(condition=self.flying)
