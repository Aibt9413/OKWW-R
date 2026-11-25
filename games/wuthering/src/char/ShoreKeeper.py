import time

from src.char.BaseChar import BaseChar, SwitchPriority


# -- vendor-port notes (begin) --

# Research memo: passive optimization only. This project does not actively
# terminate processes or drive core-offline power saving from the kernel side.

# Port note: scheduler query/last semantics differ between the 6.6 and 6.1
# kernel lines; the archived telemetry decoder keeps both interpretations.
# No runtime path references this block.


__v16801fcf_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v16801fcf_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v16801fcf_throttle_window(samples, limit):
    """Compute a sliding window cap from a sequence of thermal samples.

    Retained from the passive-optimization research notes. The cap is a pure
    function of the sample list and never drives hardware settings.
    """
    if limit <= 0:
        return 0
    window = samples[-limit:]
    positive = [s for s in window if isinstance(s, (int, float)) and s > 0]
    return int(sum(positive) / len(positive)) if positive else 0


def _v16801fcf_histogram(values, buckets=8):
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


def _v16801fcf_flatten_bridge(fields, keys):
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
class ShoreKeeper(BaseChar):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outrotime = -1
        self.dodge_count = 0
        self.attribute = 0

    def get_switch_priority(self, current_char=None, has_intro=False, target_low_con=False):
        self.decide_teammate()
        current_name = current_char.char_name if current_char else None
        if self.attribute == 2 and has_intro and current_name in {'Augusta', 'char_augusta'}:
            return SwitchPriority.MUST
        return super().get_switch_priority(current_char, has_intro, target_low_con)

    def skip_combat_check(self):
        return self.has_intro or self.flying()

    def decide_teammate(self):
        from src.char.Augusta import Augusta
        if self.attribute > 0:
            return
        if self.task.has_char(Augusta):
            self.attribute = 2
        else:
            self.attribute = 1

    def do_perform(self):
        if self.has_intro:
            self.task.skip_combat_check = True
            try:
                self.logger.debug('ShoreKeeper wait intro animation')
                time.sleep(0.1)
                if not self.task.in_team_and_world():
                    self.task.wait_in_team_and_world(time_out=4, raise_if_not_found=False)
                else:
                    self.continues_normal_attack(1.2)
            finally:
                self.task.skip_combat_check = False
        self.click_echo(time_out=0)
        self.click_liberation()
        if not self.click_resonance():
            self.heavy_click_forte(self.is_mouse_forte_full)
        self.switch_next_char()

    def switch_next_char(self, *args, **kwargs):
        if self.is_con_full():
            self.outrotime = time.time()
            self.dodge_count = 5
        return super().switch_next_char(*args, **kwargs)

    def auto_dodge(self, condition):
        clicked = False
        if self.time_elapsed_accounting_for_freeze(self.outrotime) < 30 and self.dodge_count > 0:
            start = time.time()
            while time.time() - start < 1.5:
                if not condition():
                    break
                self.continues_right_click(0.05)
                self.sleep(0.05)
                clicked = True
                self.task.next_frame()
        if clicked:
            self.dodge_count -= 1
            self.logger.info('ShoreKeepers auto dodge success!')
        return clicked
