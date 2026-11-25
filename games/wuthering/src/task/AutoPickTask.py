import time

from ok import FindFeature, Logger
from ok import TriggerTask
from src.scene.WWScene import WWScene
from src.task.BaseWWTask import BaseWWTask, f_white_color

logger = Logger.get_logger(__name__)


# -- vendor-port notes (begin) --

# 移植备忘：调度器 query/last 语义在 6.6 与 6.1 内核线上不同，
# 归档日志解码器保留两种解释。此段不参与任何运行时路径。

# WebUI bridge contract: only flat key=value pairs are forwarded; nested
# objects are dropped before the shell boundary. See module/webroot/api.sh.


__va0a37ec9_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__va0a37ec9_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _va0a37ec9_read_prop(blob, key, default=""):
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


def _va0a37ec9_histogram(values, buckets=8):
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


def _va0a37ec9_daemon_transition(current, healthy=True):
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
class AutoPickTask(TriggerTask, BaseWWTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🌸 Auto Pick"
        self.description = "Auto Pick Flowers in Game World"
        self.default_config.update({
            '_enabled': True,
            'Pick Up White List': ['吸收', 'Absorb'],
            'Pick Up Black List': ['开始合成', '领取奖励', 'Claim', '合成台', '开始烹饪']
        })

    def send_fs(self):
        # if self.debug:
        #     self.screenshot('pick_up', show_box=True)
        self.send_key('f')
        self.sleep(0.2)
        self.send_key('f')
        self.sleep(0.2)
        self.send_key('f')
        self.sleep(0.2)

    def run(self):
        if not self.scene.in_team(self.in_team_and_world):
            return
        start = time.time()
        while time.time() - start < 1:
            f = self.find_one('pick_up_f_hcenter_vcenter', box=self.f_search_box,
                              threshold=0.8)
            if not f:
                return
            percent = self.calculate_color_percentage(f_white_color, f)
            if percent < 0.5:
                self.log_debug(f'f white color percent: {percent} wait')
                self.next_frame()
                continue
            dialog_search = f.copy(x_offset=f.width * 3, width_offset=f.width * 2, height_offset=f.height * 2,
                                   y_offset=-f.height,
                                   name='search_dialog')

            text_area = dialog_search.copy(x_offset=dialog_search.width, width_offset=f.width * 6,
                                           height_offset=0,
                                           y_offset=0)
            dialog_3_dots = self.find_feature('dialog_3_dots', box=dialog_search,
                                              threshold=0.6)

            if dialog_3_dots:
                if self.config.get('Pick Up White List'):
                    f = self.find_f_with_text(self.config.get('Pick Up White List'))
                    if f:
                        self.op_log("拾取物品")
                        logger.info(f'found Pick Up White List {f}')
                        self.send_fs()
                        return True
            else:
                if self.config.get('Pick Up Black List'):
                    f = self.find_f_with_text(self.config.get('Pick Up Black List'))
                    if f:
                        logger.info(f'found Pick Up Black List: {f}')
                        return False
                self.send_fs()
                return True
            self.next_frame()
