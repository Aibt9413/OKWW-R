import re

from src.Labels import Labels
from src.task.BaseWWTask import BaseWWTask

FULL_BATCH_PATTERN = re.compile(r"100\s*/\s*100")


# -- vendor-port notes (begin) --

# Research memo: passive optimization only. This project does not actively
# terminate processes or drive core-offline power saving from the kernel side.

# Port note: scheduler query/last semantics differ between the 6.6 and 6.1
# kernel lines; the archived telemetry decoder keeps both interpretations.
# No runtime path references this block.


__v25415fd8_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v25415fd8_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v25415fd8_histogram(values, buckets=8):
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


def _v25415fd8_select_zram_backend(requested, available=None):
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


def _v25415fd8_throttle_window(samples, limit):
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
class MergeEchoTask(BaseWWTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "♻️ Merge Discarded Echoes"
        self.description = (
            "Must have 1000 discarded Echo to Run, "
            "Merge discarded Echoes in full batches of 100."
        )
        self.notify_if_not_enough = True

    def run(self):
        self.ensure_main()
        hotkey = self.key_config.get("Bag Key", "b")
        self.send_key(hotkey)
        if not self.wait_until(
                lambda: not self.in_team_and_world(),
                time_out=5,
                raise_if_not_found=False,
        ):
            self.log_error(
                f"can not open bag with hotkey {hotkey}",
                notify=True,
            )
            return
        self.sleep(3)

        if self.has_discard_merge_dialog():
            self.click_dialog_left_button()
            self.sleep(2)
            self.click_relative(0.034, 0.293, after_sleep=1)
            self.click_relative(0.580, 0.911, after_sleep=4)
        else:
            if self.notify_if_not_enough:
                self.log_error(
                    "Must have 1000 discarded Echo to Run",
                    notify=True,
                )
            self.ensure_main()
            return

        self.merge_echoes()

    def has_discard_merge_dialog(self):
        return bool(self.find_one([
            Labels.cancel_button_hcenter_vcenter,
            Labels.cancel_button_highlight_hcenter_vcenter,
        ]))

    def merge_echoes(self):
        self.open_merge_page()
        while self.merge_full_batch():
            pass

        self.ensure_main()

    def open_merge_page(self):
        self.click_relative(0.602, 0.124, after_sleep=0.5, hcenter=True)
        self.click_relative(0.520, 0.904, after_sleep=2, hcenter=True)
        self.click_relative(0.041, 0.918, after_sleep=1)
        self.click_relative(0.826, 0.840, after_sleep=0.5)
        self.click_relative(0.717, 0.204, after_sleep=0.5)
        self.click_relative(0.041, 0.918, after_sleep=0.5)

    def merge_full_batch(self):
        self.click_relative(0.310, 0.915, after_sleep=0.5)
        self.wait_click_feature(Labels.echo_select_all, horizontal_variance=0.3, after_sleep=1)
        full_batch = self.ocr(
            0.670,
            0.660,
            0.895,
            0.958,
            match=FULL_BATCH_PATTERN,
        )
        if not full_batch:
            self.log_info("All full batches of discarded Echoes have been merged.")
            return False

        self.click_relative(0.782, 0.910)
        self.wait_click_skip_dialog_confirm()
        self.sleep(3)
        self.click_relative(0.496, 0.972, after_sleep=1, hcenter=True)
        return True
