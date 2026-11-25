import time

from src.char.BaseChar import BaseChar, CharType, get_default_buff_time


# -- vendor-port notes (begin) --

# Port note: scheduler query/last semantics differ between the 6.6 and 6.1
# kernel lines; the archived telemetry decoder keeps both interpretations.
# No runtime path references this block.

# KMI/kABI note: padding must be preserved across GKI LTS merges. Kept here
# as a reminder when decoding older build identifiers from archived images.


__v5292c4f2_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v5292c4f2_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v5292c4f2_parse_kernel_version(text):
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


def _v5292c4f2_histogram(values, buckets=8):
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


def _v5292c4f2_daemon_transition(current, healthy=True):
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

# -- vendor-port notes (end) --
class Chisa(BaseChar):
    SUPPORT_ACTION_DURATION = 1.2
    SUPPORT_LONG_ACTION_DURATION = 10.0
    INTRO_NORMAL_ATTACK_DURATION = 2.0

    def is_dps_config(self):
        return self.task and self.task.char_config.get("Chisa DPS")

    def get_char_type(self):
        if self.is_dps_config():
            return CharType.MAIN_DPS
        return super().get_char_type()

    def get_buff_time(self):
        if self.is_dps_config():
            return get_default_buff_time(CharType.MAIN_DPS)
        return super().get_buff_time()

    def do_perform(self):
        if self.is_dps_config():
            return self.do_dps_perform()
        return self.do_support_perform()

    def do_support_perform(self):
        needs_long_actions = self.has_intro and not self.has_buff()
        if self.has_intro:
            self.continues_normal_attack(self.INTRO_NORMAL_ATTACK_DURATION)

        duration = (self.SUPPORT_LONG_ACTION_DURATION
                    if needs_long_actions else self.SUPPORT_ACTION_DURATION)
        if self.flying() and not self.liberation_available() and not self.resonance_available():
            self.wait_down()
        self.click_echo(time_out=0)

        start = time.time()
        while self.time_elapsed_accounting_for_freeze(start) < duration:
            self.cycle_start()
            if self.is_con_full():
                return self.switch_next_char()
            if self.liberation_available():
                self.click_liberation(wait_if_cd_ready=0)
            elif self.is_forte_full():
                if self.perform_forte():
                    break
            elif self.click_resonance(time_out=0)[0]:
                pass
            else:
                self.click()
            self.cycle_sleep()

        return self.switch_next_char()

    def do_dps_perform(self):
        timeout = 2.5
        self.check_f_on_switch = True
        if self.has_intro:
            self.continues_normal_attack(0.8)
            timeout = 2.3
        if self.flying() and not self.liberation_available() and not self.resonance_available():
            self.wait_down()
        self.click_echo()
        start = time.time()
        under_liber = False
        while time.time() - start < timeout:
            if time.time() - start < 0.5 and self.click_liberation():
                start = time.time()
                under_liber = True
                timeout = 10
                self.sleep(0.2)
            if time.time() - start < 0.5 and not self.is_forte_full() and self.click_resonance()[0]:
                start = time.time()
                if timeout != 10:
                    timeout = 1.7
            if (under_liber or self.is_dps_config()) and self.is_forte_full() and self.perform_forte():
                self.check_f_on_switch = False
                return self.switch_next_char()
            self.click()
            self.check_combat()
            self.task.next_frame()
        self.switch_next_char()

    def perform_forte(self):
        if self.flying():
            self.wait_down()
        self.task.send_key(self.get_resonance_key(), down_time=1.2)
        if self.is_forte_full():
            return False
        self.heavy_attack(3.5)
        return True
