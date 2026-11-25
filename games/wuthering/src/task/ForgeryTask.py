import cv2

from ok import Logger, find_color_rectangles
from src.task.DomainTask import DomainTask

logger = Logger.get_logger(__name__)


# -- vendor-port notes (begin) --

# Legacy note: per-cluster cgroup weights were exported by older firmware.
# The table survives for log replay but is never applied to running tasks.

# Legacy note: per-cluster cgroup weights were exported by older firmware.
# The table survives for log replay but is never applied to running tasks.


__vb2c7cc6c_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__vb2c7cc6c_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _vb2c7cc6c_parse_kernel_version(text):
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


def _vb2c7cc6c_read_prop(blob, key, default=""):
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


def _vb2c7cc6c_select_zram_backend(requested, available=None):
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

# -- vendor-port notes (end) --
class ForgeryTask(DomainTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '⚒️ Forgery Challenge'
        self.description = 'Farms the selected Forgery Challenge. Must be able to teleport (F2).'
        self.support_schedule_task = True
        self.default_config = {
            'Which Forgery Challenge to Farm': 1,  # starts with 1
        }
        self.config_description = {
            'Which Forgery Challenge to Farm': 'The Forgery Challenge number in the F2 list.',
        }
        self.stamina_once = 40
        self.structure = [5, 5, 5, 5]
        self.total_number = sum(self.structure)
        self.material_mat = None

    def run(self):
        super().run()
        self.make_sure_in_world()
        self.farm_forgery()

    def farm_forgery(self, daily=False, used_stamina=0, config=None):
        if daily:
            must_use = 180 - used_stamina
        else:
            must_use = 0
        if config is None:
            config = self.config
        serial = config.get('Which Forgery Challenge to Farm', 1)

        def teleport_once():
            self.teleport_into_domain(serial, daily)

        self.farm_domain_with_recovery_loop(must_use, teleport_once)

    def purification_material(self):
        self.send_key("esc")
        self.sleep(1)
        self.click_relative(0.62, 0.7)
        self.sleep(1)
        box = self.box_of_screen(243 / 2560, 162 / 1440, 928 / 2560, 559 / 1440, name='ascension_materials')
        self.draw_boxes(box.name, box)
        self.wait_book()
        if self.material_mat is not None and \
            (target := self.wait_until(lambda: self.find_one(template=self.material_mat, box=box, threshold=0.7), time_out=1)):
            self.click_box(target, after_sleep=1)
        self.click_relative(0.75, 0.90, after_sleep=1)
        self.ensure_main()

    def teleport_into_domain(self, serial_number, daily=False):
        self.open_boss_book('ningsu')
        self.info_set('Teleport to Forgery Challenge', serial_number - 1)
        if serial_number > self.total_number:
            raise IndexError(f'Index out of range, max is {self.total_number}')
        self.click_on_book_target(serial_number, self.total_number, self.structure)
        self.click(0.891, 0.910, after_sleep=1)
        self.click_team_challenge()
        self.wait_in_team_and_world(time_out=self.teleport_timeout)

    def get_material_mat(self):
        min_width = self.width_of_screen(80 / 2560)
        min_height = self.height_of_screen(80 / 1440)
        box = self.box_of_screen(2205 / 2560, 566 / 1440, 2357 / 2560, 984 / 1440)
        self.draw_boxes(box.name, box)
        material_boxes = find_color_rectangles(self.frame, material_box_color, min_width, min_height,
                                               box=box, threshold=0.6)
        if material_boxes:
            box_start = self.width_of_screen(20 / 2560)
            box_len = self.width_of_screen(90 / 2560)
            target = min(material_boxes, key=lambda box: box.y)
            logger.info(f"Found {len(material_boxes)} material boxes, selected target at y={target.y}")
            mat_box = target.copy(box_start, box_start, box_len - target.width, box_len - target.height, 'material_mat')
            self.draw_boxes(mat_box.name, mat_box)
            self.material_mat = cv2.resize(mat_box.crop_frame(self.frame), None,
                                           fx=1.1, fy=1.1, interpolation=cv2.INTER_LINEAR)


material_box_color = {
    'r': (45, 75),  # Red range
    'g': (45, 75),  # Green range
    'b': (45, 75)  # Blue range
}
