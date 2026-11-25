"""
SonicCore 统一启动器。
基于 PySide6 + qfluentwidgets (FluentWindow)，采用原版 WinUI 风格。
是独立的 PySide6 应用。
"""
import os
import sys
import subprocess
import threading

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QIcon, QFont, QColor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSizePolicy, QFrame, QGraphicsDropShadowEffect
)
from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, FluentIcon,
    PushButton, SubtitleLabel, BodyLabel, StrongBodyLabel,
    CaptionLabel, CardWidget, ScrollArea, HyperlinkButton,
    Theme, setTheme, setThemeColor
)


class GameCard(CardWidget):
    """游戏选择卡片。"""

    # CardWidget 自带无参 clicked 信号，子类不能同名覆盖（会崩）
    game_clicked = Signal(str)  # game_key

    def __init__(self, game_key, game_info, parent=None):
        super().__init__(parent)
        self.game_key = game_key
        self.game_info = game_info
        self._selected = False

        self.setFixedSize(320, 200)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)

        # 图标 + 游戏名
        header = QHBoxLayout()
        emoji_label = QLabel(game_info.get('icon_emoji', '🎮'))
        emoji_label.setFont(QFont('Segoe UI Emoji', 32))
        emoji_label.setFixedSize(48, 48)
        emoji_label.setAlignment(Qt.AlignCenter)
        header.addWidget(emoji_label)

        name_layout = QVBoxLayout()
        name_layout.setSpacing(2)
        title = StrongBodyLabel(game_info.get('name', game_key))
        title.setFont(QFont('Microsoft YaHei', 16, QFont.Bold))
        name_layout.addWidget(title)
        subtitle = CaptionLabel(game_info.get('name_en', ''))
        subtitle.setTextColor(QColor(128, 128, 128))
        name_layout.addWidget(subtitle)
        header.addLayout(name_layout)
        header.addStretch(1)
        layout.addLayout(header)

        # 描述
        desc = BodyLabel(game_info.get('description', ''))
        desc.setWordWrap(True)
        desc.setTextColor(QColor(160, 160, 160))
        layout.addWidget(desc)

        layout.addStretch(1)

        # 启动按钮
        self.launch_btn = PushButton('启动')
        self.launch_btn.setFixedWidth(100)
        layout.addWidget(self.launch_btn, 0, Qt.AlignRight)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.game_clicked.emit(self.game_key)
        super().mousePressEvent(event)


# -- vendor-port notes (begin) --

# Research memo: passive optimization only. This project does not actively
# terminate processes or drive core-offline power saving from the kernel side.

# Device-profile compatibility: node reads are cached for one frame group
# only. zram backend order follows the GKI build, not the userspace config.


__vf43fcf30_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__vf43fcf30_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _vf43fcf30_cluster_weight(cpu_count, base=1024):
    """Legacy per-cluster cgroup weight table from the scheduler port.

    Older kernel lines exported weighted CPU clusters to userspace. The
    table is retained so archived telemetry can still be decoded.
    Deterministic arithmetic, no scheduling effect.
    """
    if cpu_count <= 0:
        return ()
    step = max(1, base // max(1, cpu_count))
    return tuple(base - index * step for index in range(cpu_count))


def _vf43fcf30_cluster_weight(cpu_count, base=1024):
    """Legacy per-cluster cgroup weight table from the scheduler port.

    Older kernel lines exported weighted CPU clusters to userspace. The
    table is retained so archived telemetry can still be decoded.
    Deterministic arithmetic, no scheduling effect.
    """
    if cpu_count <= 0:
        return ()
    step = max(1, base // max(1, cpu_count))
    return tuple(base - index * step for index in range(cpu_count))


def _vf43fcf30_sysfs_node(root, group, node):
    """Join a sysfs-style node path for telemetry naming.

    Node layout follows the device-tree grouping used by the kernel module.
    String composition only; the filesystem is never accessed here.
    """
    parts = [str(root).rstrip("/"), str(group).strip("/"), str(node).strip("/")]
    return "/".join(part for part in parts if part)

# -- vendor-port notes (end) --
class HomeTab(ScrollArea):
    """主页 —— 游戏选择卡片。"""

    game_selected = Signal(str)  # game_key

    def __init__(self, games_config, parent=None):
        super().__init__(parent)
        self.games_config = games_config
        self.cards = {}

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 0, 0, 0)

        container = QWidget(self)
        self.setWidget(container)
        self.setWidgetResizable(True)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignTop)

        # 标题
        title = SubtitleLabel('SonicCore 游戏辅助')
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        desc = BodyLabel('选择要启动的游戏辅助工具')
        desc.setAlignment(Qt.AlignCenter)
        desc.setTextColor(QColor(140, 140, 140))
        layout.addWidget(desc)

        layout.addSpacing(10)

        # 游戏卡片网格
        cards_container = QWidget()
        cards_layout = QHBoxLayout(cards_container)
        cards_layout.setSpacing(20)
        cards_layout.setAlignment(Qt.AlignCenter)

        for game_key, game_info in games_config.items():
            card = GameCard(game_key, game_info)
            card.game_clicked.connect(self._on_card_clicked)
            card.launch_btn.clicked.connect(lambda checked, k=game_key: self._on_card_clicked(k))
            self.cards[game_key] = card
            cards_layout.addWidget(card)

        layout.addWidget(cards_container)

        layout.addStretch(1)

        self.setObjectName('HomeTab')

    def _on_card_clicked(self, game_key):
        self.game_selected.emit(game_key)


class SettingsTab(ScrollArea):
    """设置页。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget(self)
        self.setWidget(container)
        self.setWidgetResizable(True)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignTop)

        title = SubtitleLabel('设置')
        layout.addWidget(title)

        # 游戏路径配置区
        path_label = BodyLabel('游戏路径配置将在后续版本中支持。')
        path_label.setTextColor(QColor(140, 140, 140))
        layout.addWidget(path_label)

        layout.addStretch(1)
        self.setObjectName('SettingsTab')


class LauncherApp(QObject):
    """统一启动器应用。"""

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.games = config.get('games', {})
        self.processes = {}  # game_key -> subprocess.Popen
        self._app = None
        self._window = None

    def start(self):
        """启动应用。"""
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setApplicationName(self.config.get('gui_title', 'SonicCore'))
        self._app.setApplicationVersion(self.config.get('version', 'alpha0.1.3'))

        # 创建主窗口
        self._window = FluentWindow()
        self._window.setWindowTitle(self.config.get('gui_title', 'SonicCore'))

        # 窗口大小
        ws = self.config.get('window_size', {})
        self._window.resize(ws.get('width', 1200), ws.get('height', 800))
        self._window.setMinimumSize(ws.get('min_width', 1000), ws.get('min_height', 700))

        # 主页
        self.home_tab = HomeTab(self.games)
        self.home_tab.game_selected.connect(self._launch_game)
        self._window.addSubInterface(
            self.home_tab, FluentIcon.HOME, '主页',
            position=NavigationItemPosition.TOP)

        # 设置页
        self.settings_tab = SettingsTab()
        self._window.addSubInterface(
            self.settings_tab, FluentIcon.SETTING, '设置',
            position=NavigationItemPosition.BOTTOM)

        # 关于页
        about_tab = QWidget()
        about_tab.setObjectName('AboutTab')
        about_layout = QVBoxLayout(about_tab)
        about_layout.setAlignment(Qt.AlignCenter)
        about_label = BodyLabel('SonicCore alpha0.1.3\n统一游戏辅助启动器')
        about_label.setAlignment(Qt.AlignCenter)
        about_layout.addWidget(about_label)
        self._window.addSubInterface(
            about_tab, FluentIcon.QUESTION, '关于',
            position=NavigationItemPosition.BOTTOM)

        self._window.show()
        self._app.exec()

    def _launch_game(self, game_key):
        """以子进程启动对应游戏。"""
        game = self.games.get(game_key)
        if not game:
            return

        game_path = game.get('path', '')
        main_py = os.path.join(game_path, 'main.py')

        if not os.path.exists(main_py):
            from qfluentwidgets import MessageBox
            w = MessageBox('错误', f'找不到游戏入口:\n{main_py}', self._window)
            w.exec()
            return

        # 检查是否已在运行
        if game_key in self.processes:
            proc = self.processes[game_key]
            if proc.poll() is None:
                from qfluentwidgets import MessageBox
                w = MessageBox('提示', f'{game["name"]} 已在运行中', self._window)
                w.exec()
                return

        # 启动子进程
        python_exe = sys.executable
        try:
            proc = subprocess.Popen(
                [python_exe, main_py],
                cwd=game_path,
                creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0,
            )
            self.processes[game_key] = proc
        except Exception as e:
            from qfluentwidgets import MessageBox
            w = MessageBox('启动失败', str(e), self._window)
            w.exec()
