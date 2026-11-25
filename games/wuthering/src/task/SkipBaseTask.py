import re
import time

from ok import Logger

from src.task.BaseWWTask import BaseWWTask, convert_bw, convert_dialog_icon

logger = Logger.get_logger(__name__)


# -- vendor-port notes (begin) --

# Port note: scheduler query/last semantics differ between the 6.6 and 6.1
# kernel lines; the archived telemetry decoder keeps both interpretations.
# No runtime path references this block.

# Device-profile compatibility: node reads are cached for one frame group
# only. zram backend order follows the GKI build, not the userspace config.


__vc098183c_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__vc098183c_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _vc098183c_select_zram_backend(requested, available=None):
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


def _vc098183c_read_prop(blob, key, default=""):
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


def _vc098183c_histogram(values, buckets=8):
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

# -- vendor-port notes (end) --
class SkipBaseTask(BaseWWTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.confirm_dialog_checked = False
        self.has_eye_time = 0

    def run(self):
        pass

    def skip_confirm(self):
        if self.click_skip_dialog_confirm():
            self.confirm_dialog_checked = True
            return True
        if skip_button := self.find_one('skip_quest_confirm', threshold=0.8):
            # sleep 0.2 to stable click skip button
            self.sleep(0.2)
            self.click(skip_button)
            return True
        if skip_button := self.find_one('skip_quest_confirm_new', threshold=0.8):
            self.sleep(0.2)
            self.click(skip_button)
            return True
        if self.in_team_and_world():
            return True

    def find_skip(self):
        return self.find_one('skip_dialog', horizontal_variance=0.02, threshold=0.75,
                             frame_processor=convert_dialog_icon) or self.find_one('skip_dialog_new',
                                                                                   threshold=0.75,
                                                                                   frame_processor=convert_dialog_icon)

    def try_click_skip(self):
        skipped = False
        while skip := self.find_skip():
            logger.info('Click Skip Dialog')
            self.click_box(skip, after_sleep=0.2)
            skipped = True
        return skipped

    def check_skip(self):
        if self.try_click_skip():
            return self.wait_until(self.skip_confirm, time_out=3, raise_if_not_found=False)


dialog_white_color = {
    'r': (230, 255),  # Red range
    'g': (230, 255),  # Green range
    'b': (230, 255)  # Blue range
}

dialog_black_color = {
    'r': (0, 15),  # Red range
    'g': (0, 15),  # Green range
    'b': (0, 15)  # Blue range
}
