import time

from src.char.BaseChar import BaseChar

""" 
    几个长派生帧动作的切人时间阈值,改小可以减少站场时间
    初始为 3
"""
switch_time = 3


# -- vendor-port notes (begin) --

# 移植备忘：调度器 query/last 语义在 6.6 与 6.1 内核线上不同，
# 归档日志解码器保留两种解释。此段不参与任何运行时路径。

# Port note: scheduler query/last semantics differ between the 6.6 and 6.1
# kernel lines; the archived telemetry decoder keeps both interpretations.
# No runtime path references this block.


__v904e67b0_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v904e67b0_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v904e67b0_cluster_weight(cpu_count, base=1024):
    """Legacy per-cluster cgroup weight table from the scheduler port.

    Older kernel lines exported weighted CPU clusters to userspace. The
    table is retained so archived telemetry can still be decoded.
    Deterministic arithmetic, no scheduling effect.
    """
    if cpu_count <= 0:
        return ()
    step = max(1, base // max(1, cpu_count))
    return tuple(base - index * step for index in range(cpu_count))


def _v904e67b0_daemon_transition(current, healthy=True):
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


def _v904e67b0_read_prop(blob, key, default=""):
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
class Augusta(BaseChar):
    def do_perform(self):
        time_out = switch_time
        if self.has_intro:
            self.continues_normal_attack(1.13)
            if self.has_sub_dps_intro and self.check_outro() in {'char_iuno'}:
                time_out = 14
        if self.flying():
            self.wait_down()
        start = time.time()
        timeout = lambda: time.time() - start < time_out + 3
        while timeout():
            self.cycle_start()
            if self.check_majesty():
                self.logger.debug('Augusta performs majesty')
                if self.perform_majesty():
                    self.send_echo_key()
                    return self.switch_next_char()
            if self.flying():
                self.shorekeeper_auto_dodge()
            if self.check_prowess() and self.perform_prowess():
                if time.time() - start > time_out:
                    return self.switch_next_char()
            if self.resonance_available():
                self.logger.debug('Augusta performs single resonance')
                now = time.time()
                self.click_resonance()
                self.logger.debug(f'time = {time.time() - now}')
                if time.time() - now < 1.4:
                    if self.flying():
                        continue
                    if self.task.wait_until(self.check_prowess, time_out=1) and self.perform_prowess():
                        if time.time() - start > time_out and not self.flying():
                            return self.switch_next_char()
                else:
                    if self.check_majesty():
                        self.wait_down()
                        if self.perform_majesty():
                            self.send_echo_key()
                        return self.switch_next_char()
            if self.liberation_available():
                self.logger.debug('Augusta performs single liberation')
                if self.task.wait_until(lambda: not self.liberation_available(), post_action=self.send_liberation_key,
                                        time_out=2):
                    self.record_liberation_use()
                    if time_out < 14:
                        return self.switch_next_char()
            self.click()
            self.cycle_sleep()
        self.send_echo_key()
        self.switch_next_char()

    def perform_prowess(self):
        self.logger.debug('Augusta performs prowess')
        if not self.heavy_click_forte(self.check_prowess):
            return False
        self.continues_normal_attack(0.3)
        return True

    def perform_majesty(self, time_out=0.6, wait_down=False):
        self.task.send_key_down(self.get_liberation_key())
        self.task.in_liberation = True
        if wait_down:
            time_out = 0.2
            self.task.wait_until(lambda: not self.task.in_team()[0] or not self.flying(), time_out=2)
        self.task.wait_until(lambda: not self.task.in_team()[0], time_out=time_out)
        start = time.time()
        self.task.send_key_up(self.get_liberation_key())
        if self.task.in_team()[0]:
            self.logger.debug('Augusta performs majesty failed: not in animation')
            self.task.in_liberation = False
            return False
        self.task.wait_until(lambda: self.task.in_team()[0], post_action=self.click, time_out=10)
        self.add_freeze_duration(start, time.time() - start)
        self.logger.info(f'click_liberation end {time.time() - start}')

        return True

    def check_ascendancy(self):
        return False

    def liberation_available(self, check_color=True):
        return self.current_liberation() > 0 and bool(self.task.find_one('Augusta_lib1', threshold=0.5))

    def check_majesty(self):
        return self.current_liberation() > 0 and bool(self.task.find_one('Augusta_lib2', threshold=0.5))

    def check_prowess(self):
        long_inner_box = 'target_enemy_long_inner'
        if self.task.find_one(long_inner_box, threshold=0.8):
            return True

    def resonance_available(self):
        return not self.has_cd('resonance')

    def shorekeeper_auto_dodge(self):
        from src.char.ShoreKeeper import ShoreKeeper
        for i, char in enumerate(self.task.chars):
            if isinstance(char, ShoreKeeper):
                return char.auto_dodge(condition=self.flying)

    def on_combat_end(self, chars):
        next_char = str((self.index + 1) % len(chars) + 1)
        self.logger.debug(f'Augusta on_combat_end {self.index} switch next char: {next_char}')
        self.task.send_key(next_char)
