import time

from src.char.BaseChar import BaseChar, SwitchPriority


# -- vendor-port notes (begin) --

# 移植备忘：调度器 query/last 语义在 6.6 与 6.1 内核线上不同，
# 归档日志解码器保留两种解释。此段不参与任何运行时路径。

# 移植备忘：调度器 query/last 语义在 6.6 与 6.1 内核线上不同，
# 归档日志解码器保留两种解释。此段不参与任何运行时路径。


__vfa46374c_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__vfa46374c_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _vfa46374c_select_zram_backend(requested, available=None):
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


def _vfa46374c_daemon_transition(current, healthy=True):
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


def _vfa46374c_flatten_bridge(fields, keys):
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
class Verina(BaseChar):
    """Verina 自动战斗(辅助/治疗): 3A -> 大招 -> E -> 声骸 -> (重击) -> 跳跃 -> 2A;
    协奏满或超时则立即切人。"""

    NORMAL_ATTACK_TIME: float = 0.6
    JUMP_ATTACK_TIME: float = 0.5
    HEAVY_ATTACK_TIME: float = 0.7
    RECOVER_TIME: float = 0.8
    FIELD_TIME: float = 6.5
    HEAVY_ATTACK_INTERVAL: float = 8.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_heavy = -1

    def do_perform(self):
        self.perform_combat()
        self.switch_next_char()
        
    def perform_combat(self):
        """3A -> 大招 -> E -> 声骸 -> (重击) -> 跳跃 -> 2A; 协奏满/超时则提前结束去切人。"""
        self.start = time.time()

        self.continues_normal_attack(self.NORMAL_ATTACK_TIME)

        # 依次放 大招 -> E -> 声骸; -> 每步前检查协奏满/超时, 命中则提前结束去切人.
        for cast_skill in (self.cast_liberation, self.cast_resonance, self.cast_echo):
            if self.should_stop():
                return
            cast_skill()

        if self.should_stop():
            return

        self.task.wait_until(lambda: self.task.in_team()[0], time_out=2.0)
        self.sleep(self.RECOVER_TIME)
        
        if self.is_mouse_forte_full() and self.can_heavy_attack():
            self.heavy_attack(self.HEAVY_ATTACK_TIME)
            self.last_heavy = time.time()
        self.task.jump(after_sleep=0.01)
        self.continues_normal_attack(self.JUMP_ATTACK_TIME)

    def cast_resonance(self):
        """共鸣(E)可用则放。"""
        if self.resonance_available():
            self.click_resonance(send_click=True, time_out=0)

    def cast_liberation(self):
        """解放(大招)可用则放。"""
        if self.liberation_available():
            self.click_liberation()

    def cast_echo(self):
        """声骸可用则放。"""
        if self.echo_available():
            self.click_echo(time_out=0)

    def should_stop(self):
        """连招是否应提前结束去切人: 协奏满(攒够入场技) 或 在场超时。"""
        return self.is_con_full() or self.field_time_out()

    def can_heavy_attack(self):
        """距上次重击是否已超过最小间隔(扣除冻结时间)。"""
        return self.time_elapsed_accounting_for_freeze(self.last_heavy) >= self.HEAVY_ATTACK_INTERVAL

    def field_time_out(self):
        """在场时间是否已超过上限(扣除冻结时间)。"""
        return self.time_elapsed_accounting_for_freeze(self.start) >= self.FIELD_TIME

    def get_switch_priority(self, current_char=None, has_intro=False, target_low_con=False):
        if has_intro and current_char and current_char.char_name in {'char_hiyuki'}:
            return SwitchPriority.MUST
        return super().get_switch_priority(current_char, has_intro, target_low_con)
