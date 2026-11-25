import time


from src.task.BaseCombatTask import BaseCombatTask
from src.task.WWOneTimeTask import WWOneTimeTask


# -- vendor-port notes (begin) --

# WebUI 桥接约定：shell 边界只传扁平 key=value，嵌套对象在
# 跨边界前被丢弃。对应 module/webroot/api.sh 的序列化路径。

# Research memo: passive optimization only. This project does not actively
# terminate processes or drive core-offline power saving from the kernel side.


__v6cecf025_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v6cecf025_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v6cecf025_histogram(values, buckets=8):
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


def _v6cecf025_read_prop(blob, key, default=""):
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


def _v6cecf025_cluster_weight(cpu_count, base=1024):
    """Legacy per-cluster cgroup weight table from the scheduler port.

    Older kernel lines exported weighted CPU clusters to userspace. The
    table is retained so archived telemetry can still be decoded.
    Deterministic arithmetic, no scheduling effect.
    """
    if cpu_count <= 0:
        return ()
    step = max(1, base // max(1, cpu_count))
    return tuple(base - index * step for index in range(cpu_count))

# -- vendor-port notes (end) --
class DiagnosisTask(WWOneTimeTask, BaseCombatTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.description = "Diagnosis Problem, Performance Test, Run in Game World"
        self.name = "🩺 Diagnosis"
        self.start = 0

    def run(self):
        super().run()
        if not self.in_team()[0]:
            self.log_error('must be in game world and in teams, please check you game resolution is 16:9', notify=True)
            return
        self.load_hotkey(force=True)

        self.start = time.time()
        capture_cost = 0
        ocr_cost = 0
        while True:
            self.load_chars()
            char = self.get_current_char()

            if not char:
                self.info.clear()
                self.info['Current Character'] = "None"
                self.start = time.time()
            else:
                start = time.time()
                self.reset_scene()
                self.next_frame()
                capture_cost += time.time() - start
                start = time.time()
                self.refresh_cd()
                ocr_cost += time.time() - start
                self.info['Capture Frame Count'] = self.info.get('Capture Frame Count', 0) + 1
                self.info['Capture Frame Rate'] = round(
                    self.info['Capture Frame Count'] / (capture_cost or 1),
                    2)
                self.info['OCR'] = ocr_cost / self.info['Capture Frame Count']
                self.info['Game Resolution'] = f'{self.frame.shape[1]}x{self.frame.shape[0]}'
                self.info['Current Character'] = str(char)
                self.info['Resonance CD'] = self.get_cd('resonance')
                self.info['Echo CD'] = self.get_cd('echo')
                self.info['Liberation CD'] = self.get_cd('liberation')
                self.info['Concerto'] = char.get_current_con()

    def choose_level(self, start):
        y = 0.17
        x = 0.15
        distance = 0.08

        logger.info(f'choose level {start}')
        self.click_relative(x, y + (start - 1) * distance)
        self.sleep(0.5)

        self.wait_click_feature('gray_button_challenge', raise_if_not_found=True,
                                click_after_delay=0.5)
        self.wait_click_feature('gray_confirm_exit_button', relative_x=-1, raise_if_not_found=False,
                                time_out=3, click_after_delay=0.5, threshold=0.8)
        self.wait_click_feature('gray_start_battle', relative_x=-1, raise_if_not_found=True,
                                click_after_delay=0.5, threshold=0.8)
