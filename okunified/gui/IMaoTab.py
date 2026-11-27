"""
IMaoTab —— 「地图工具」页（SC 自建完整控制面板）。

架构：SonicCore 直接启动 IMAO 的 CoreHost（WGC 采集 / YOLO 定位 / ImGui 叠加层），
并通过命名管道成为它的唯一控制端。IMAO 的 WinUI 界面**完全不启动** —— 所有控制
（探索启停、窗口选择、路线规划、点位筛选、设置、诊断）都在本页用 SC 的 Qt 控件完成。

为什么不用 SetParent / owner 嵌入 WinUI：
  WinUI 3 窗口被 reparent 会崩溃于 Microsoft.UI.Windowing.dll（0xe0464645），
  owner 方案仍是两个窗口。直接接管 CoreHost 管道才是一窗口 + 完整控制的解法。

协议：见 imao_core_client.py（换行分隔 JSON，version=1，status 事件每 200ms）。

安全（不让它成为入口）：
  - 归档 hash fail-closed + 全量文件校验（清单外可执行拒绝）
  - 随机独占临时目录 + 干净环境 + 精确进程管理
"""
import hashlib
import json
import os
import shutil
import tempfile
import uuid
import zipfile

from PySide6.QtCore import QTimer, Qt, QUrl, QThread, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (BodyLabel, CaptionLabel, PrimaryPushButton, PushButton,
                            StrongBodyLabel, TitleLabel, CardWidget, SwitchButton,
                            ComboBox)

from ok import Logger
from ok.ui.qt.widget.CustomTab import CustomTab

logger = Logger.get_logger(__name__)

IMAO_UPSTREAM = 'https://github.com/kahvia-d/IMAO'
IMAO_ZIP_NAME = 'IMao-windows-x64.zip'
IMAO_EXPECTED_ZIP_SHA256 = (
    '249b6e99bc5f05b472062df29554a34632b795c0437727e7e529bfa994dfc60d'
)
_SENSITIVE_ENV_KEYS = (
    'GITHUB_TOKEN', 'GH_TOKEN', 'PAT', 'API_KEY', 'SECRET', 'PASSWORD',
    'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'WORKBUDDY_TOKEN', 'PYTHONPATH',
)
_EXECUTABLE_EXTS = ('.exe', '.dll', '.ocx', '.sys', '.com', '.scr',
                    '.pyd', '.node', '.bat', '.cmd', '.ps1', '.vbs', '.jar')

# 默认配置（IMAO RuntimeConfiguration.ToPayload 的等价字段）
DEFAULT_CONFIG = {
    'captureWay': 1, 'overlayPresentMode': 1, 'performanceProfile': 1,
    'captureMaxFps': 20, 'ocrUpdateCycle': 150, 'mapUpdateCycle': 80,
    'minMapUpdateCycle': 80, 'mapEnabled': True, 'minMapEnabled': True,
    'savedPointsEnabled': True, 'statusBarEnabled': False,
    'mapStatusBarEnabled': False, 'statusBallEnabled': False,
    'autoReplanEnabled': False, 'gapFillModeEnabled': False,
    'nearestCompletionKey': 90, 'manualRouteKey': 81,
    'currentTargetGuideKey': 119, 'guideSkipKey': 71,
    'guidePreviousImageKey': 33, 'guideNextImageKey': 34,
    'toggleEnabledKey': 120, 'gamepadEnabled': False,
    'completionRangePixels': 15, 'guideRangePixels': 15,
    'farmRangePixels': 30, 'markerMergeOverlapPercent': 50,
    'toolsScalePercent': 50, 'handPaletteScalePercent': 50,  # 弱化工具悬浮按钮
}

_STATE_TEXT = {
    'idle': '空闲', 'starting': '启动中', 'loading': '加载资源中',
    'ready': '就绪', 'waitingForGame': '等待游戏窗口',
    'startingOverlay': '启动叠加层', 'running': '运行中',
    'stopping': '停止中', 'fault': '故障',
    'unknown': '未识别', 'waiting': '等待中', 'active': '已激活',
    'searching': '搜索中', 'located': '已定位', 'lost': '定位丢失',
    'noWindow': '无窗口', 'paused': '已暂停',
}

_SETTING_LABELS = {
    'mapEnabled': '大地图叠加',
    'minMapEnabled': '小地图叠加',
    'savedPointsEnabled': '显示已存点位',
    'statusBarEnabled': '状态栏',
    'autoReplanEnabled': '自动重规划路线',
}

# IMAO 点位类别（来自 Assets/KuroMap/filter-items.json）
# WinUI 正常启动会发 setItems(add=用户启用的类别)，我们接管 CoreHost 后必须自己发。
# 第三项 = 默认是否显示（用户偏好：只显示采集/探索/副本/道具，隐藏敌人/BOSS/强敌/NPC）
IMAO_ITEM_CATEGORIES = (
    ('Kuro Map Sync - 大地图-采集物', '采集物', False),
    ('Kuro Map Sync - 大地图-敌人', '敌人', False),
    ('Kuro Map Sync - 大地图-BOSS', 'BOSS', False),
    ('Kuro Map Sync - 大地图-强敌', '强敌', False),
    ('Kuro Map Sync - 大地图-NPC', 'NPC', False),
    ('Kuro Map Sync - 大地图-地图探索', '地图探索', True),
    ('Kuro Map Sync - 大地图-副本挑战', '副本挑战', True),
    ('Kuro Map Sync - 大地图-收集道具', '收集道具', True),
)


# ── 安全 / 工具 ────────────────────────────────────────────────────────

def _payload_imao_zip():
    here = os.path.dirname(os.path.abspath(__file__))
    base = os.path.dirname(os.path.dirname(here))   # _internal
    root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    for p in (os.path.join(base, 'imao', IMAO_ZIP_NAME),
              os.path.join(root, 'imao', IMAO_ZIP_NAME)):
        if os.path.isfile(p):
            return p
    return None


def _make_resource_snapshot(base, zip_path):
    """生成指向本次解压目录的资源快照 JSON，解决"图标全是圆圈"。

    IMAO 的图标/地图/瓦片路径来自资源快照 JSON（mapIconRoot 等），
    而用户 AppData 里的快照指向**旧临时目录**（SFX 每次解压到新随机目录），
    导致图标加载失败 → 显示默认圆圈。这里按本次 base 重写所有路径。
    """
    import json
    snap_path = os.path.join(base, 'sc-snapshot.json')
    assets = os.path.join(base, 'Assets')
    template = None
    # 优先复用 IMAO 已有的快照模板（保留完整包清单/版本/baselineId）
    try:
        snaps = os.path.join(os.environ.get('LOCALAPPDATA', ''),
                             'IMao-WinUI', 'ResourceUpdates', 'snapshots')
        if os.path.isdir(snaps):
            for f in sorted(os.listdir(snaps), reverse=True):
                if f.endswith('.json'):
                    p = os.path.join(snaps, f)
                    with open(p, encoding='utf-8') as fh:
                        candidate = json.load(fh)
                    if candidate.get('formatVersion') == 1 and \
                            candidate.get('packages'):
                        template = candidate
                        break
    except Exception as e:
        logger.debug('读取快照模板失败: ' + str(e))

    if template is None:
        # 兜底：最小快照（只有 map-data / map-icons）
        template = {
            'formatVersion': 1, 'snapshotId': 'bundled', 'sequence': 0,
            'baselineId': 'map-baseline-1', 'minAppVersion': '',
            'maxAppVersion': None, 'bundled': True,
            'packages': [
                {'id': 'map-data', 'version': '2026.10.30.1',
                 'kind': 'map-data', 'sha256': '', 'files': []},
                {'id': 'map-icons', 'version': '2026.10.7.1',
                 'kind': 'map-icons', 'sha256': '', 'files': []},
            ],
        }

    doc = dict(template)
    doc['baselineRoot'] = assets
    doc['mapDataRoot'] = os.path.join(assets, 'KuroMap')
    doc['mapIconRoot'] = os.path.join(assets, 'KuroMapIcons')
    doc['mapFeatureRoot'] = ''
    # 重映射每个 package 的 directory 到本次解压目录
    tile_root = os.path.join(assets, 'FeaturesDatas', 'KuroTilePacks')
    for pkg in doc.get('packages', []):
        kind = pkg.get('kind')
        if kind == 'map-data':
            pkg['directory'] = doc['mapDataRoot']
        elif kind == 'map-icons':
            pkg['directory'] = doc['mapIconRoot']
        elif kind == 'map-features':
            pkg['directory'] = os.path.join(assets, 'FeaturesDatas')
        elif kind == 'tile':
            # 包名形如 avinoleum-kurotiles → 目录 avinoleum
            name = pkg.get('id', '').replace('-kurotiles', '')
            pkg['directory'] = os.path.join(tile_root, name)
        pkg['sha256'] = ''
        pkg['files'] = []

    try:
        with open(snap_path, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, ensure_ascii=False)
        logger.info('已生成资源快照: ' + snap_path)
        return snap_path
    except Exception as e:
        logger.warning('生成资源快照失败: ' + str(e))
        return None


def _load_item_id_map(zip_path):
    """从 IMAO 包内 filter-items.json 读取 类别 → [item_id...] 映射。

    CoreHost 的 setItems(add=...) 要的是**具体 item_id**（DrawItemBase::
    AddItemDataFromJson(itemId)），不是类别名 —— 这是 0 标记的根因。
    """
    import json
    try:
        with zipfile.ZipFile(zip_path) as zf:
            data = json.loads(zf.read('Assets/KuroMap/filter-items.json'))
        return {cat: list(ids.keys()) for cat, ids in data.items()}
    except Exception as e:
        logger.debug('读取 IMAO 点位类别失败: ' + str(e))
        return {}


def _sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _safe_child_env():
    env = dict(os.environ)
    for k in list(env):
        if any(s in k.upper() for s in _SENSITIVE_ENV_KEYS):
            env.pop(k, None)
    return env


def _read_manifest(zip_path):
    import json
    local = os.path.join(os.path.dirname(zip_path), 'integrity.json')
    if os.path.isfile(local):
        try:
            with open(local, encoding='utf-8') as fh:
                data = json.load(fh)
            return {k.lower(): v.lower() for k, v in data.items() if len(v) == 64}
        except Exception as e:
            logger.debug('读取 integrity.json 失败: ' + str(e))
    return {}


def _verify_extracted(base, manifest):
    bad = []
    for rel, want in manifest.items():
        fp = os.path.join(base, rel.replace('/', os.sep))
        if not os.path.isfile(fp):
            bad.append('缺失: ' + rel)
        elif _sha256(fp) != want:
            bad.append('篡改: ' + rel)
    for dp, _dn, fn in os.walk(base):
        for name in fn:
            if not name.lower().endswith(_EXECUTABLE_EXTS):
                continue
            rel = os.path.relpath(os.path.join(dp, name), base).replace('\\', '/').lower()
            if rel not in manifest:
                bad.append('清单外可执行: ' + rel)
    return bad


class _ConnectWorker(QThread):
    """后台连接 IMAO CoreHost：hash + 解压 + 校验 + 握手，避免阻塞 GUI。

    解压 450MB（约 6 秒）+ 校验 335 个文件（约 1-2 秒）+ 管道连接，
    在 GUI 线程同步做会让界面"卡死"。这里放到工作线程，进度/结果用信号回传。
    """
    progress = Signal(str)
    finished_ok = Signal(object, object)   # (client, base)
    failed = Signal(str)
    core_status = Signal(dict)             # CoreHost status 事件 → 主线程

    def __init__(self, zip_path, config, item_switches, on_status=None, parent=None):
        super().__init__(parent)
        self.zip_path = zip_path
        self.config = dict(config)
        self.item_categories = [cid for cid, sw in item_switches.items()
                                if sw.isChecked()]
        self._client = None
        self._base = None

    def run(self):
        import os as _os
        try:
            self.progress.emit('正在校验程序包…')
            if _sha256(self.zip_path) != IMAO_EXPECTED_ZIP_SHA256:
                raise RuntimeError('程序包校验失败，已拒绝启动')
            manifest = _read_manifest(self.zip_path)
            if not manifest:
                raise RuntimeError('完整性清单缺失，拒绝启动')

            self.progress.emit('正在解压 IMAO（约 450MB，需几秒）…')
            self._base = _os.path.join(tempfile.gettempdir(),
                                       'sc_imao_' + uuid.uuid4().hex[:12])
            _os.makedirs(self._base, exist_ok=False)
            with zipfile.ZipFile(self.zip_path, 'r') as zf:
                zf.extractall(self._base)

            self.progress.emit('正在校验文件完整性…')
            bad = _verify_extracted(self._base, manifest)
            if bad:
                raise RuntimeError('文件校验失败（%d 项）: %s' % (
                    len(bad), ','.join(bad[:5])))

            self.progress.emit('正在准备资源快照…')
            snapshot = _make_resource_snapshot(self._base, self.zip_path)
            self.progress.emit('正在连接 CoreHost…')
            from okunified.gui.imao_core_client import CoreHostClient
            self._client = CoreHostClient(
                self._base, env=_safe_child_env(), resource_snapshot=snapshot)
            # 关键：CoreHost 的状态回调在它的读线程触发，绝不能直接操作 Qt GUI。
            # 用 Qt 信号切回主线程，由 IMaoTab._on_core_status 处理。
            self._client.on_status = self.core_status.emit
            if not self._client.start(timeout=10):
                raise RuntimeError('连接失败：' + self._client.last_error)
            self._client.configure(self.config)
            # IMAO 默认不显示任何点位；setItems 要的是具体 item_id 而非类别名
            id_map = _load_item_id_map(self.zip_path)
            item_ids = []
            for cat in self.item_categories:
                item_ids.extend(id_map.get(cat, []))
            ack = self._client.set_items(add=item_ids)
            logger.info('IMAO 点位类别已启用: %d 类/%d 个id, ack=%s' % (
                len(self.item_categories), len(item_ids),
                bool(ack and ack.get('accepted'))))
            # 清除可能残留的手绘草稿 —— 它会让地图上的蓝色工具悬浮按钮常驻
            try:
                self._client.route_planning('handCancel')
            except Exception:
                pass
            self.finished_ok.emit(self._client, self._base)
            self._client = None
            self._base = None
        except Exception as e:
            logger.error('连接 IMAO CoreHost 异常: ' + str(e))
            if self._client is not None:
                try:
                    self._client.stop()
                except Exception:
                    pass
            if self._base is not None:
                shutil.rmtree(self._base, ignore_errors=True)
            self.failed.emit(str(e))




class IMaoTab(CustomTab):
    """地图工具页：SC 自建控制面板 + 后台 CoreHost。"""

    def __init__(self, parent=None):
        super().__init__()
        self._client = None
        self._base = None
        self._config = dict(DEFAULT_CONFIG)
        self._status = {}
        self._connecting = False
        self._want_explore = False   # 用户是否请求了探索（用于自动重试等游戏窗口）
        self._retrying = False
        self._stay_noactivate = False  # 常驻不抢焦点模式
        self._last_overlay_state = None  # 悬浮窗同步去重
        self._item_id_map = {}           # 类别 → [item_id]，连接时从包内加载

        # 正常退出窗口时框架不会调用 dispose()，这里挂 aboutToQuit 保证
        # CoreHost 进程与临时目录一定被清理（否则残留黑窗口/进程）。
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self.dispose)
        except Exception:
            pass

        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.vBoxLayout.setContentsMargins(28, 24, 28, 28)
        self.vBoxLayout.setSpacing(16)

        title = TitleLabel('地图工具 · IMAO')
        self.vBoxLayout.addWidget(title)
        sub = CaptionLabel(
            'IMAO 的采集/定位/叠加层在后台运行，所有控制在下方完成。'
            '点位、路线、收集进度直接画在游戏画面上。'
            '⚠ 重要：鸣潮必须在最前面（游戏焦点）才会定位并标记点位 —— '
            '设置好后点「聚焦游戏」，SonicCore 会最小化让位给游戏。')
        sub.setWordWrap(True)
        self.vBoxLayout.addWidget(sub)

        # ── 1. 核心控制 ────────────────────────────────────────────────
        ctrl = CardWidget(self)
        cl = QVBoxLayout(ctrl)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(10)
        self._core_status = StrongBodyLabel('核心：未连接')
        self._core_status.setObjectName('imaoCoreStatus')
        cl.addWidget(self._core_status)
        self._detail_label = CaptionLabel('点击「连接核心」开始 · 需要游戏窗口已打开')
        self._detail_label.setWordWrap(True)
        cl.addWidget(self._detail_label)
        row = QHBoxLayout()
        self._connect_btn = PrimaryPushButton('连接核心', self)
        self._connect_btn.clicked.connect(self._on_connect)
        row.addWidget(self._connect_btn)
        self._explore_btn = PushButton('开始探索', self)
        self._explore_btn.clicked.connect(self._on_explore)
        self._explore_btn.setEnabled(False)
        row.addWidget(self._explore_btn)
        self._window_btn = PushButton('选择游戏窗口', self)
        self._window_btn.clicked.connect(self._on_select_window)
        self._window_btn.setEnabled(False)
        row.addWidget(self._window_btn)
        self._focus_btn = PushButton('聚焦游戏', self)
        self._focus_btn.clicked.connect(self._on_focus_game)
        self._focus_btn.setToolTip(
            'IMAO 要求游戏窗口在最前面才会定位并标记点位。\n'
            '点击此按钮会最小化 SonicCore，让游戏获得焦点；\n'
            '定位/叠加层继续工作，从任务栏点 SonicCore 即可返回。')
        self._focus_btn.setEnabled(False)
        row.addWidget(self._focus_btn)
        self._stay_btn = PushButton('常驻不抢焦点：关', self)
        self._stay_btn.clicked.connect(self._on_toggle_noactivate)
        self._stay_btn.setToolTip(
            '开启后本窗口不会抢走游戏焦点，可一边看面板一边让 IMAO 标记点位。\n'
            '按钮仍可正常点击；关闭则恢复普通窗口行为。')
        row.addWidget(self._stay_btn)
        self._disconnect_btn = PushButton('断开', self)
        self._disconnect_btn.clicked.connect(self._on_disconnect)
        self._disconnect_btn.setEnabled(False)
        row.addWidget(self._disconnect_btn)
        row.addStretch(1)
        cl.addLayout(row)
        self.vBoxLayout.addWidget(ctrl)

        # ── 2. 实时状态 ────────────────────────────────────────────────
        self._status_card = self._make_card('实时状态')
        self._status_labels = {}
        for key, label in (
            ('coreState', '核心状态'), ('gameState', '游戏状态'),
            ('localization', '定位状态'), ('gameFocused', '游戏焦点'),
            ('ocrBackend', 'OCR 后端'), ('frameMilliseconds', '帧耗时'),
            ('minimapMarkers', '小地图点位'), ('mapMarkers', '大地图点位'),
            ('resourcesReady', '资源就绪'),
        ):
            row = QHBoxLayout()
            row.addWidget(BodyLabel(label + '：'))
            v = BodyLabel('—')
            v.setObjectName('imaoStatus_' + key)
            row.addWidget(v, 1)
            self._status_labels[key] = v
            self._status_card.layout().addLayout(row)

        # ── 3. 路线导航 ────────────────────────────────────────────────
        route = self._make_card('路线导航')
        self._route_label = BodyLabel('尚未规划路线')
        self._route_label.setWordWrap(True)
        route.layout().addWidget(self._route_label)
        rrow = QHBoxLayout()
        for text, action in (('规划路线', 'plan'), ('撤销', 'undo'), ('清空', 'clear')):
            b = PushButton(text, self)
            b.clicked.connect(lambda _c=False, a=action: self._on_route(a))
            b.setEnabled(False)
            rrow.addWidget(b)
            setattr(self, '_route_' + action + '_btn', b)
        rrow.addStretch(1)
        route.layout().addLayout(rrow)

        # ── 4. 点位筛选（决定叠加层显示哪些点位） ──────────────────────
        filt = self._make_card('点位筛选 · 勾选要显示的类别')
        hint = CaptionLabel('IMAO 默认不显示任何点位，需在这里启用；勾选后立即生效。')
        hint.setWordWrap(True)
        filt.layout().addWidget(hint)
        self._item_switches = {}
        for cat_id, label, default_on in IMAO_ITEM_CATEGORIES:
            srow = QHBoxLayout()
            sw = SwitchButton()
            sw.setOnText('显示')
            sw.setOffText('隐藏')
            sw.setChecked(default_on)
            sw.checkedChanged.connect(
                lambda checked, c=cat_id: self._on_item_toggle(c, checked))
            self._item_switches[cat_id] = sw
            srow.addWidget(BodyLabel(label + '：'))
            srow.addWidget(sw)
            srow.addStretch(1)
            filt.layout().addLayout(srow)

        # ── 5. 叠加层设置 ──────────────────────────────────────────────
        settings = self._make_card('叠加层设置')
        self._switches = {}
        for key, label in _SETTING_LABELS.items():
            srow = QHBoxLayout()
            srow.addWidget(BodyLabel(label + '：'))
            sw = SwitchButton()
            sw.setOnText('开')
            sw.setOffText('关')
            sw.setChecked(bool(self._config.get(key)))
            sw.checkedChanged.connect(lambda checked, k=key: self._on_setting(k, checked))
            self._switches[key] = sw
            srow.addWidget(sw)
            srow.addStretch(1)
            settings.layout().addLayout(srow)
        fps = QHBoxLayout()
        fps.addWidget(BodyLabel('采集帧率：'))
        self._fps_combo = ComboBox()
        self._fps_combo.addItems(['10', '15', '20', '30', '60'])
        idx = self._fps_combo.findText(str(self._config.get('captureMaxFps', 20)))
        if idx >= 0:
            self._fps_combo.setCurrentIndex(idx)
        self._fps_combo.currentTextChanged.connect(self._on_fps_changed)
        fps.addWidget(self._fps_combo)
        fps.addStretch(1)
        settings.layout().addLayout(fps)

        # ── 5. 归属 ────────────────────────────────────────────────────
        self.add_card('归属与许可', self._build_license())

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(500)

    def _make_card(self, title_text):
        w = CardWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)
        lbl = StrongBodyLabel(title_text)
        lay.addWidget(lbl)
        self.vBoxLayout.addWidget(w)
        return w

    # ── 基础属性 ──────────────────────────────────────────────────────
    @property
    def name(self):
        return '地图工具'

    @property
    def icon(self):
        return 'globe'

    @property
    def add_after_default_tabs(self):
        return True

    def _build_license(self):
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(18, 12, 18, 12)
        lbl = BodyLabel(
            'IMAO 由 kahvia-d 及其贡献者开发，采用 GPL-3.0 许可证开源。'
            '本页仅将 IMAO 官方发布包作为独立进程附带并控制其后台核心，'
            'SonicCore 自身代码未被 IMAO 衍生，两者为聚合关系。')
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        row = QHBoxLayout()
        up = PushButton('IMAO 上游仓库', self)
        up.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(IMAO_UPSTREAM)))
        row.addWidget(up)
        gpl = PushButton('GPL-3.0 许可证', self)
        gpl.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl('https://www.gnu.org/licenses/gpl-3.0.html')))
        row.addWidget(gpl)
        row.addStretch(1)
        lay.addLayout(row)
        return w

    # ── 状态同步到 SC 悬浮窗 ──────────────────────────────────────────
    def _push_overlay(self, message):
        """向 SC 悬浮窗推一条日志（连接/断开/故障等低频事件才用）。"""
        try:
            from okunified.gui.StatusOverlay import get_overlay
            get_overlay().append_log(message)
        except Exception as e:
            logger.debug('同步 IMAO 状态到悬浮窗失败: ' + str(e))

    def _on_core_status(self, ev):
        """CoreHost 状态回调（工作线程 → 主线程信号）。

        只在**故障**时推一条到悬浮窗；定位状态/点位数每 200ms 都在变，
        推到日志流会严重刷屏。正常运行信息留在「地图工具」页的状态卡片里。
        """
        try:
            core = ev.get('coreState', '')
            if core == 'faulted' and self._last_overlay_state != 'faulted':
                self._last_overlay_state = 'faulted'
                self._push_overlay('IMAO 故障：' + (
                    ev.get('message') or '未知错误'))
            elif core != 'faulted' and self._last_overlay_state == 'faulted':
                self._last_overlay_state = None
        except Exception as e:
            logger.debug('处理 IMAO 状态失败: ' + str(e))

    # ── 状态刷新 ──────────────────────────────────────────────────────
    def _poll(self):
        if self._client is None:
            return
        if not self._client.is_running():
            self._on_core_lost()
            return
        st = self._client.status
        if not st:
            return
        self._status = st
        core = st.get('coreState', '')
        self._core_status.setText('核心：' + _STATE_TEXT.get(core, core or '连接中'))
        game = st.get('gameState', '')
        loc = st.get('localization', '')
        focused = st.get('gameFocused')
        ready = st.get('resourcesReady')
        # 直接显示 CoreHost 给出的 message/hint —— 这是定位失败的具体原因
        # （例如"未找到可用的游戏窗口"），比抽象状态更有用。
        msg = st.get('message') or ''
        hint = st.get('hint') or ''
        detail = '游戏：%s · 定位：%s · 焦点：%s' % (
            game, loc, '是' if focused else '否')
        if msg:
            detail += ' · ' + msg
        if hint:
            detail += ' · ' + hint
        # 焦点是 IMAO 定位的硬门槛：游戏不在前面就不会标记点位。
        # 这是用户最容易踩的坑，用醒目提示引导。
        if core == 'running' and not focused:
            detail = '⚠ 游戏未在最前面，IMAO 不会标记点位 —— 点「聚焦游戏」让位给游戏。\n' + detail
        self._detail_label.setText(detail)
        ocr = st.get('ocrBackend') or {}
        values = {
            'coreState': _STATE_TEXT.get(core, core),
            'gameState': _STATE_TEXT.get(game, game or '—'),
            'localization': _STATE_TEXT.get(loc, loc or '—'),
            'gameFocused': '是' if focused else '否',
            'ocrBackend': _STATE_TEXT.get(
                ocr.get('backend'), ocr.get('backend')) or '等待中',
            'frameMilliseconds': ('%.1f ms' % st['frameMilliseconds']) if st.get('frameMilliseconds') else '—',
            'minimapMarkers': st.get('minimapMarkers', '—'),
            'mapMarkers': st.get('mapMarkers', '—'),
            'resourcesReady': '是' if ready else '否',
        }
        for k, v in values.items():
            lbl = self._status_labels.get(k)
            if lbl is not None:
                lbl.setText(str(v))
        # CoreHost 的 start 是一次性的：失败后只把状态设为 waitingForGame，
        # 不会自动重试。若用户已请求探索但游戏窗口当时未就绪，这里持续重试，
        # 游戏窗口一出现就自动开始采集/定位（这是"查找中不标记点位"的根因修复）。
        core = st.get('coreState', '')
        if getattr(self, '_want_explore', False) and core == 'waitingForGame' \
                and not getattr(self, '_retrying', False):
            self._retrying = True
            QTimer.singleShot(1500, self._retry_explore)

        can_explore = core in ('ready', 'waitingForGame', 'running')
        self._explore_btn.setEnabled(can_explore)
        self._window_btn.setEnabled(can_explore)
        self._focus_btn.setEnabled(core == 'running')
        for key in ('plan', 'undo', 'clear'):
            getattr(self, '_route_' + key + '_btn').setEnabled(can_explore)
        # 按钮文本跟随真实状态，避免 CoreHost 自行变化后文本与行为脱节。
        # 注意：CoreHost 自己 stop/fault 也算探索结束，同步清掉重试意图。
        running = core == 'running'
        self._explore_btn.setText('停止探索' if running else '开始探索')
        if core in ('idle', 'stopping', 'fault'):
            self._want_explore = False

    def _retry_explore(self):
        self._retrying = False
        if not getattr(self, '_want_explore', False) or self._client is None:
            return
        if self._client.status.get('coreState') == 'waitingForGame':
            ack = self._client.start_capture()
            if ack and ack.get('accepted'):
                self._explore_btn.setText('停止探索')
                logger.info('IMAO 自动重试探索成功（游戏窗口已就绪）')

    def _on_core_lost(self):
        self._want_explore = False
        self._retrying = False
        self._last_overlay_state = None
        if self._client is None:
            return
        logger.warning('IMAO CoreHost 已退出')
        try:
            self._client.stop()
        except Exception:
            pass
        self._client = None
        if self._base:
            shutil.rmtree(self._base, ignore_errors=True)
            self._base = None
        self._core_status.setText('核心：未连接')
        self._detail_label.setText('核心已断开，点击「连接核心」重试')
        self._push_overlay('IMAO 已断开')
        self._connect_btn.setEnabled(True)
        self._explore_btn.setEnabled(False)
        self._window_btn.setEnabled(False)
        self._focus_btn.setEnabled(False)
        self._disconnect_btn.setEnabled(False)
        for key in ('plan', 'undo', 'clear'):
            getattr(self, '_route_' + key + '_btn').setEnabled(False)

    # ── 连接 / 断开 ───────────────────────────────────────────────────
    def _on_connect(self):
        if self._client is not None or self._connecting:
            return
        zip_path = _payload_imao_zip()
        if not zip_path or not os.path.isfile(zip_path):
            self._detail_label.setText('未找到 IMAO 程序包')
            return
        self._connecting = True
        self._connect_btn.setEnabled(False)
        self._detail_label.setText('正在校验程序包…')
        # 重活在后台线程做，GUI 保持响应（解压 450MB 约 6 秒）
        self._worker = _ConnectWorker(
            zip_path, self._config, self._item_switches, parent=self)
        self._worker.progress.connect(self._detail_label.setText)
        self._worker.finished_ok.connect(self._on_connect_done)
        self._worker.failed.connect(self._on_connect_failed)
        # 跨线程安全：读线程 emit → 主线程槽（避免 Qt6Gui 跨线程崩溃）
        self._worker.core_status.connect(self._on_core_status)
        self._worker.start()

    def _on_connect_done(self, client, base):
        self._client = client
        self._base = base
        zp = _payload_imao_zip()
        if zp:
            self._item_id_map = _load_item_id_map(zp)
        self._status = {}
        self._last_overlay_state = None
        self._connecting = False
        self._connect_btn.setEnabled(False)
        self._disconnect_btn.setEnabled(True)
        self._core_status.setText('核心：已连接')
        self._detail_label.setText('核心已就绪，可以开始探索')
        self._push_overlay('IMAO 已运行')
        logger.info('IMAO CoreHost 已就绪')

    def _on_connect_failed(self, message):
        self._connecting = False
        self._detail_label.setText('连接失败：' + message)
        self._connect_btn.setEnabled(True)   # 可重试

    def _on_disconnect(self):
        self._on_core_lost()
        self._core_status.setText('核心：未连接')
        self._connect_btn.setEnabled(True)
        self._detail_label.setText('已断开')

    # ── 操作 ──────────────────────────────────────────────────────────
    def _on_explore(self):
        if self._client is None:
            return
        core = self._client.status.get('coreState')
        if core == 'running':
            self._want_explore = False
            ack = self._client.stop_capture()
            if ack and ack.get('accepted'):
                self._explore_btn.setText('开始探索')
                logger.info('IMAO 已停止探索')
        else:
            self._want_explore = True
            ack = self._client.start_capture()
            if ack and ack.get('accepted'):
                self._explore_btn.setText('停止探索')
            else:
                # 游戏窗口未就绪：保持"等待游戏窗口"状态并持续重试，
                # 游戏一开就会自动开始采集（CoreHost 自己不会重试）。
                self._detail_label.setText(
                    '已请求探索，等待游戏窗口…（游戏打开后会自动开始，无需再点）')

    def _on_select_window(self):
        if self._client is None:
            return
        self._detail_label.setText(
            '游戏窗口由 CoreHost 自动发现（已识别到大地图）。'
            '关键：鸣潮必须在最前面才有焦点并标记点位 —— 点「聚焦游戏」让位。')

    def _on_toggle_noactivate(self):
        """切换「常驻不抢焦点」：给主窗口加/去 WS_EX_NOACTIVATE。

        开启后本窗口可见、按钮可点，但不会成为 foreground，游戏保持焦点，
        IMAO 就能持续定位并标记点位（App.cpp:479 的 isWindowFocused 门槛）。
        """
        self._stay_noactivate = not self._stay_noactivate
        ok = False
        try:
            from PySide6.QtWidgets import QApplication
            import ctypes
            app = QApplication.instance()
            mw = app.activeWindow() if app is not None else None
            if mw is None and app is not None:
                tops = [w for w in app.topLevelWidgets()
                        if w.isVisible() and w.windowType() == Qt.Window]
                mw = tops[0] if tops else None
            if mw is not None:
                hwnd = int(mw.winId())
                GWL_EXSTYLE = -20
                WS_EX_NOACTIVATE = 0x08000000
                u = ctypes.windll.user32
                style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
                if self._stay_noactivate:
                    u.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
                else:
                    u.SetWindowLongW(hwnd, GWL_EXSTYLE,
                                     style & ~WS_EX_NOACTIVATE)
                ok = True
        except Exception as e:
            logger.debug('切换 NOACTIVATE 失败: ' + str(e))
        self._stay_btn.setText(
            '常驻不抢焦点：' + ('开' if self._stay_noactivate and ok else '关'))
        if ok and self._stay_noactivate:
            self._detail_label.setText(
                '已开启常驻模式：本页可见且可操作，但不会抢游戏焦点。'
                '点游戏窗口让它成为前台，IMAO 即可标记点位。')

    def _on_focus_game(self):
        """最小化 SC 窗口并把焦点交还游戏 —— IMAO 定位/标记的硬门槛。"""
        try:
            from PySide6.QtWidgets import QApplication
            import win32gui
            import win32con

            app = QApplication.instance()
            mw = app.activeWindow() if app is not None else None
            # 找鸣潮客户端窗口（Client-Win64-Shipping.exe），按标题兜底
            targets = []
            def cb(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    t = win32gui.GetWindowText(hwnd)
                    if ('鸣潮' in t or 'Wuthering' in t or
                            'Client-Win64' in t):
                        targets.append(hwnd)
            win32gui.EnumWindows(cb, None)
            # 先最小化 SC 主窗口，让游戏成为前台
            if mw is not None:
                mw.showMinimized()
            for h in targets:
                try:
                    win32gui.ShowWindow(h, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(h)
                    break
                except Exception:
                    pass
            self._detail_label.setText(
                '已让位给游戏。IMAO 正在定位，点位/路线会画在游戏画面上；'
                '从任务栏点 SonicCore 可返回本页（返回后点「聚焦游戏」再次让位）。')
        except Exception as e:
            self._detail_label.setText('聚焦游戏失败：' + str(e))

    def _on_route(self, action):
        if self._client is None:
            return
        ack = self._client.route_planning(action)
        if ack and ack.get('accepted'):
            data = ack.get('data') or {}
            self._route_label.setText(str(data.get('message') or '路线已更新'))
        else:
            self._route_label.setText(
                '操作失败：' + ((ack or {}).get('message') or '无响应'))

    def _on_setting(self, key, checked):
        self._config[key] = bool(checked)
        if self._client is not None:
            self._client.configure({key: bool(checked)})

    def _on_item_toggle(self, category_id, checked):
        """点位类别勾选变化 → 实时 setItems 增减该类别的所有 item_id。"""
        if self._client is None:
            return
        ids = self._item_id_map.get(category_id, [])
        if not ids:
            return
        add = ids if checked else []
        remove = [] if checked else ids
        self._client.set_items(add=add, remove=remove)

    def _on_fps_changed(self, text):
        try:
            self._config['captureMaxFps'] = int(text)
        except ValueError:
            return
        if self._client is not None:
            self._client.configure({'captureMaxFps': int(text)})

    def dispose(self):
        try:
            self._timer.stop()
        except Exception:
            pass
        # 等待后台连接线程结束（正在解压时退出，避免残留临时目录）
        w = getattr(self, '_worker', None)
        if w is not None and w.isRunning():
            try:
                w.wait(3000)
            except Exception:
                pass
        # 退出时恢复窗口样式，避免 NOACTIVATE 影响用户其他操作
        if self._stay_noactivate:
            self._stay_noactivate = False
            try:
                import ctypes
                from PySide6.QtWidgets import QApplication
                app = QApplication.instance()
                mw = app.activeWindow() if app is not None else None
                if mw is None and app is not None:
                    tops = [w for w in app.topLevelWidgets()
                            if w.isVisible() and w.windowType() == Qt.Window]
                    mw = tops[0] if tops else None
                if mw is not None:
                    hwnd = int(mw.winId())
                    style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
                    ctypes.windll.user32.SetWindowLongW(
                        hwnd, -20, style & ~0x08000000)
            except Exception:
                pass
        if self._client is not None:
            try:
                self._client.stop()
            except Exception:
                pass
            self._client = None
        if self._base:
            shutil.rmtree(self._base, ignore_errors=True)
            self._base = None
        parent_dispose = getattr(super(), 'dispose', None)
        if callable(parent_dispose):
            parent_dispose()
