"""
「设置 → 游戏」区块。

游戏作用域切换从主页搬到这里：主页只负责壁纸/开始，选游戏在设置里做。
本模块在 MainWindow 建好之后（communicate.start_success）把区块插进框架自带的
SettingTab 顶部，不改动框架源码。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
                               QSizePolicy, QColorDialog)

from qfluentwidgets import (SettingCardGroup, PushButton, StrongBodyLabel,
                            CaptionLabel, BodyLabel, ComboBox, SwitchButton,
                            InfoBar, InfoBarPosition)

from ok import Logger

from okunified.gui import game_icons

logger = Logger.get_logger(__name__)

# 「主题」里那一行「游戏图标」（刷新/联网下载图标的入口）目前隐藏。
# 想让它回来改成 True 即可 —— 只是显示与否，图标加载逻辑不受影响。
SHOW_GAME_ICON_ROW = False

# 自己搭的行不像框架的 SettingCard 那样自带背景（框架那边是给 QFrame 设了样式表，
# 由 Qt 画出默认底色）。这里用同样的填充色手工画一层，视觉和「软件设置」里的项一致：
#   浅色 rgba(255,255,255,0.7) 叠在页面底色 #f3f3f3 上，实测正好是框架卡片的 #fbfbfb
# 只加背景，行内的按钮 / 开关 / 下拉一律不动。
_ROW_CARD_LIGHT = ('#{name} {{ background-color: rgba(255, 255, 255, 0.7);'
                   ' border-radius: {radius}px; }}')
_ROW_CARD_DARK = ('#{name} {{ background-color: rgba(255, 255, 255, 0.0605);'
                  ' border-radius: {radius}px; }}')

_row_card_seq = 0


def _apply_row_card(widget, name, radius):
    """按当前明暗主题直接设样式表。

    这里不用 qfluentwidgets 的 setCustomStyleSheet：实测它给我们的行设完
    之后 styleSheet 仍然是空的（只挂上了 lightCustomQss/darkCustomQss 属性），
    背景根本没画出来。直接 setStyleSheet 是可靠的；子控件不受影响，
    因为选择器只匹配这一行的 objectName。
    """
    from qfluentwidgets import isDarkTheme

    background = ('rgba(255, 255, 255, 0.051)' if isDarkTheme()
                  else 'rgba(255, 255, 255, 0.7)')
    widget.setStyleSheet(
        f'#{name} {{ background-color: {background}; border-radius: {radius}px; }}')


def _as_card(widget, radius=6):
    """给一行加上和框架 SettingCard 一样的背景卡片。"""
    global _row_card_seq
    _row_card_seq += 1
    name = f'okCardRow{_row_card_seq}'
    widget.setObjectName(name)
    # 普通 QWidget 必须打开 WA_StyledBackground，否则样式表里的
    # background-color 不会被绘制（QFrame 才自动画）。
    widget.setAttribute(Qt.WA_StyledBackground, True)
    _apply_row_card(widget, name, radius)

    from qfluentwidgets import qconfig
    qconfig.themeChanged.connect(
        lambda *_, w=widget, n=name, r=radius: _apply_row_card(w, n, r))
    return widget

_section = None

_TEXT_COLOR_ITEMS = ('自动取色', '白色', '深色', '自定义颜色')
_TEXT_COLOR_MODES = ('auto', 'white', 'dark', 'custom')
_CUSTOM_INDEX = _TEXT_COLOR_MODES.index('custom')


class GameSettingsSection(QWidget):
    """设置页里的「游戏」分组。"""

    def __init__(self, home_tab, parent=None):
        super().__init__(parent)
        self.home_tab = home_tab
        self._buttons = {}
        self._icon_labels = {}
        # 不让这一块被外层布局纵向拉伸
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        from config import GAMES
        self._games = GAMES

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        game_group = SettingCardGroup('游戏', self)
        layout.addWidget(game_group)
        for game_key, info in self._games.items():
            self._buttons[game_key] = None
            game_group.addSettingCard(self._make_game_row(game_key, info))

        # 「启动参数」独立成一组，只有一行 —— 跟着当前游戏走（和游戏图标、
        # 主题一样按作用域刷新），每个游戏各记一份，切游戏就换成那份
        self.launch_group = SettingCardGroup('启动参数', self)
        layout.addWidget(self.launch_group)
        self.launch_group.addSettingCard(self._make_launch_args_row())

        # 「显示」卡片：框架 删掉了旧的「开始页」，
        # 原来挂在「截图方式 → 开发工具」里的标记框/悬浮窗开关没有落脚点了，
        # 统一收进这里。
        self.display_group = SettingCardGroup('显示', self)
        layout.addWidget(self.display_group)
        self.display_group.addSettingCard(self._make_switch_row(
            '标记框', '在游戏画面上绘制识别到的目标框', _boxes_enabled, _set_boxes_enabled))
        self.display_group.addSettingCard(self._make_switch_row(
            '状态悬浮窗', '屏幕左下角显示当前任务、触发器数量和实时日志',
            _overlay_enabled, _set_overlay_enabled))
        self.display_group.addSettingCard(self._make_switch_row(
            '悬浮窗紧凑模式', '只显示当前任务和运行时长，隐藏日志区',
            _overlay_compact_enabled, _set_overlay_compact_enabled))

        # 「高级」：开发者模式。默认关，开启后才显示侧边栏「开发」下的三页
        self.advanced_group = SettingCardGroup('高级', self)
        layout.addWidget(self.advanced_group)
        self.advanced_group.addSettingCard(self._make_switch_row(
            '开发者模式', '显示侧边栏「开发」下的 脚本 / 模板 / 诊断 三页',
            _developer_mode_enabled, _set_developer_mode))

        # （「上游源码更新」那一组已按需求移除：上游每个版本的改动程度不一，
        #   还可能牵扯框架本身，不适合做成"拖进来就自动合并"的按钮 ——
        #   合并交给 DSH 每次按版本实际情况处理。合并用的脚本仍留在
        #   patches/ 下供命令行使用。）

        game_group.addSettingCard(self._make_text_color_row())
        # 「悬浮窗」开关已移到「截图方式 → 开发工具」卡片里（标记框开关旁边），
        # 见 StatusOverlay.install_switch_into_debug_card()

        # 「主题」卡片：主页壁纸 / 主题颜色 / 应用主题
        # （「应用主题」卡由 install_game_settings 从框架 SettingTab 搬过来）
        # 注：「游戏图标」那一行（刷新/下载图标的入口）已按要求隐藏 ——
        # 只是不再显示这一行，游戏行里的图标照常加载（_icon_labels 在
        # _make_game_row 里注册，和这一行无关）。
        self.theme_group = SettingCardGroup('主题', self)
        layout.addWidget(self.theme_group)
        self.theme_rows = []
        if SHOW_GAME_ICON_ROW:
            self.theme_rows.append(self._make_icon_row())
        self.theme_rows += [
            self._make_wallpaper_row(),
            self._make_theme_color_row(),
        ]
        for row in self.theme_rows:
            self.theme_group.addSettingCard(row)

        self.refresh()

        # 图标：缓存里已有的立刻显示，其余丢后台线程（可能联网下载）
        self._icon_loader = game_icons.GameIconLoader()
        self._icon_loader.icon_ready.connect(self._apply_icon)
        self._apply_cached_icons()
        self._icon_loader.load_async(self._games)

    # ── 游戏行 ────────────────────────────────────────────────────────

    def _make_game_row(self, game_key, info):
        row = QWidget()
        # SettingCardGroup 会把子项拉伸填满，必须固定高度，否则一行能占几百像素
        row.setFixedHeight(64)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(16, 8, 16, 8)
        row_layout.setSpacing(14)

        icon = QLabel(info.get('icon_emoji', '🎮'))
        icon.setFont(QFont('Segoe UI Emoji', 22))
        icon.setFixedSize(40, 40)
        icon.setAlignment(Qt.AlignCenter)
        row_layout.addWidget(icon)
        self._icon_labels[game_key] = icon

        texts = QVBoxLayout()
        texts.setSpacing(2)
        title = StrongBodyLabel(info.get('name', game_key))
        texts.addWidget(title)
        subtitle = CaptionLabel(
            f"{info.get('name_en', '')}　·　{info.get('description', '')}")
        subtitle.setTextColor(QColor(130, 130, 130))
        texts.addWidget(subtitle)
        row_layout.addLayout(texts)
        row_layout.addStretch(1)

        button = PushButton('切换到此游戏')
        button.setFixedWidth(140)
        button.clicked.connect(lambda *_, k=game_key: self.switch_to(k))
        row_layout.addWidget(button)
        self._buttons[game_key] = button
        return _as_card(row)

    # ── 启动参数（独立一组，一行，跟随当前游戏）────────────────────────

    def _make_launch_args_row(self):
        """给当前游戏的 exe 加命令行启动参数，按游戏分别记住。"""
        from qfluentwidgets import LineEdit

        row = QWidget()
        row.setFixedHeight(60)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(16, 8, 16, 8)
        row_layout.setSpacing(12)

        self._launch_label = BodyLabel('')
        self._launch_label.setFixedWidth(96)
        row_layout.addWidget(self._launch_label)

        self._launch_edit = LineEdit()
        self._launch_edit.setClearButtonEnabled(True)
        self._launch_edit.editingFinished.connect(self._on_launch_args_changed)
        row_layout.addWidget(self._launch_edit, 1)

        self._sync_launch_args()
        return _as_card(row)

    def _current_game(self):
        from okunified.gui.GameSwitcher import game_switcher

        return game_switcher.current_game or self.home_tab._current_game or ''

    def _sync_launch_args(self):
        """把这一行刷成"当前游戏"记住的那份。"""
        if not hasattr(self, '_launch_edit'):
            return
        from okunified.gui import home_state

        game_key = self._current_game()
        self._launch_label.setText(
            self._games.get(game_key, {}).get('name', game_key or '未选游戏'))
        value = home_state.get_launch_args(game_key) if game_key else ''
        if self._launch_edit.text() != value:
            self._launch_edit.blockSignals(True)
            self._launch_edit.setText(value)
            self._launch_edit.blockSignals(False)

    def _on_launch_args_changed(self):
        from okunified.gui import home_state

        game_key = self._current_game()
        if not game_key:
            return
        text = self._launch_edit.text().strip()
        if home_state.get_launch_args(game_key) == text:
            return
        home_state.set_launch_args(game_key, text)
        name = self._games.get(game_key, {}).get('name', game_key)
        logger.info(f'启动参数已更新 [{game_key}]: {text or "(清空)"}')
        InfoBar.success(
            title='启动参数已保存',
            content=(f'{name}：{text}' if text else f'{name}：已清空'),
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=2500, parent=self.window())

    # ── 游戏图标 ──────────────────────────────────────────────────────

    def _make_icon_row(self):
        row = QWidget()
        row.setFixedHeight(60)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(16, 8, 16, 8)
        row_layout.setSpacing(12)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(StrongBodyLabel('游戏图标'))
        hint = CaptionLabel('本地优先：游戏项目的 icons/icon.png；'
                            '在 config.py 里给游戏配了 icon_url 就会联网下载')
        hint.setTextColor(QColor(130, 130, 130))
        texts.addWidget(hint)
        row_layout.addLayout(texts)
        row_layout.addStretch(1)

        refresh = PushButton('刷新图标')
        refresh.setFixedWidth(110)
        refresh.clicked.connect(self._refresh_icons)
        row_layout.addWidget(refresh)
        return _as_card(row)

    def _apply_icon(self, game_key, path):
        label = self._icon_labels.get(game_key)
        if label is None or not path:
            return
        pixmap = game_icons.rounded_pixmap(path, size=36, radius=8)
        if pixmap is None:
            logger.warning(f'[{game_key}] 图标无法加载: {path}')
            return
        label.setText('')
        label.setPixmap(pixmap)
        label.setToolTip(path)

    def _apply_cached_icons(self):
        for game_key in self._games:
            path = game_icons.cached_icon_path(game_key)
            if path:
                self._apply_icon(game_key, path)

    def _refresh_icons(self):
        """清掉缓存重新走一遍：本地 → 网络。"""
        game_icons.clear_cache()
        for game_key, info in self._games.items():
            label = self._icon_labels.get(game_key)
            if label is not None:
                label.setPixmap(QPixmap())
                label.setText(info.get('icon_emoji', '🎮'))
        self._icon_loader.load_async(self._games)
        logger.info('已清空游戏图标缓存，重新加载中')
        InfoBar.success(
            title='正在刷新图标',
            content='本地找不到的会按 config.py 里的 icon_url 联网下载',
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=2500, parent=self.window())

    # ── 主题颜色 ──────────────────────────────────────────────────────

    @staticmethod
    def _current_theme_color():
        from qfluentwidgets import qconfig
        return QColor(qconfig.get(qconfig.themeColor))

    @staticmethod
    def _default_theme_color():
        from qfluentwidgets import qconfig
        return QColor(qconfig.themeColor.defaultValue)

    def _make_theme_color_row(self):
        row = QWidget()
        row.setFixedHeight(60)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(16, 8, 16, 8)
        row_layout.setSpacing(12)

        label = BodyLabel('主题颜色')
        label.setFixedWidth(72)
        row_layout.addWidget(label)

        self._theme_color_swatch = QLabel()
        self._theme_color_swatch.setFixedSize(28, 28)
        row_layout.addWidget(self._theme_color_swatch)

        self._theme_color_button = PushButton('选择颜色…')
        self._theme_color_button.setFixedWidth(120)
        self._theme_color_button.clicked.connect(self._pick_theme_color)
        row_layout.addWidget(self._theme_color_button)

        reset = PushButton('恢复默认')
        reset.setFixedWidth(100)
        reset.clicked.connect(self._reset_theme_color)
        row_layout.addWidget(reset)

        hint = CaptionLabel('影响按钮、开关、选中项等强调色')
        hint.setTextColor(QColor(130, 130, 130))
        row_layout.addWidget(hint)

        row_layout.addStretch(1)
        self._update_theme_swatch()
        return _as_card(row)

    def _update_theme_swatch(self):
        color = self._current_theme_color()
        self._theme_color_swatch.setStyleSheet(
            f'background: {color.name()};'
            'border: 1px solid rgba(128,128,128,130); border-radius: 6px;')
        self._theme_color_button.setText(color.name().upper())

    def _apply_theme_color(self, color):
        from qfluentwidgets import qconfig, setThemeColor

        from ok import og

        setThemeColor(color, save=True)
        main_window = getattr(og, 'main_window', None)
        if main_window is not None:
            # 让 MainWindow 的主题同步逻辑认这个手动色，别再被系统强调色顶掉
            main_window._configured_theme_color = QColor(color)
        self._update_theme_swatch()
        logger.info(f'主题颜色已设为 {color.name()}')

    def _pick_theme_color(self):
        color = QColorDialog.getColor(self._current_theme_color(), self, '选择主题颜色')
        if color.isValid():
            self._apply_theme_color(color)

    def _reset_theme_color(self):
        self._apply_theme_color(self._default_theme_color())

    # ── 主页外观行 ────────────────────────────────────────────────────

    def _make_wallpaper_row(self):
        row = QWidget()
        row.setFixedHeight(60)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(16, 8, 16, 8)
        row_layout.setSpacing(12)

        label = BodyLabel('主页壁纸')
        label.setFixedWidth(72)
        row_layout.addWidget(label)

        pick = PushButton('更换壁纸')
        pick.setFixedWidth(110)
        pick.clicked.connect(self._pick_wallpaper)
        row_layout.addWidget(pick)

        blur_label = BodyLabel('模糊')
        blur_label.setFixedWidth(36)
        row_layout.addWidget(blur_label)

        self._blur_slider = QSlider(Qt.Horizontal)
        self._blur_slider.setRange(0, 50)
        self._blur_slider.setValue(self.home_tab.blur_radius)
        self._blur_slider.setFixedWidth(200)
        self._blur_slider.valueChanged.connect(self._on_blur_changed)
        row_layout.addWidget(self._blur_slider)

        self._blur_value = CaptionLabel(str(self.home_tab.blur_radius))
        self._blur_value.setFixedWidth(28)
        self._blur_value.setAlignment(Qt.AlignCenter)
        row_layout.addWidget(self._blur_value)

        row_layout.addStretch(1)
        return _as_card(row)

    def _make_text_color_row(self):
        row = QWidget()
        row.setFixedHeight(60)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(16, 8, 16, 8)
        row_layout.setSpacing(12)

        label = BodyLabel('主页文字颜色')
        label.setFixedWidth(96)
        row_layout.addWidget(label)

        self._text_color_combo = ComboBox()
        self._text_color_combo.addItems(list(_TEXT_COLOR_ITEMS))
        self._text_color_combo.setFixedWidth(130)
        mode = self.home_tab.text_color_mode
        self._text_color_combo.setCurrentIndex(
            _TEXT_COLOR_MODES.index(mode) if mode in _TEXT_COLOR_MODES else 0)
        self._text_color_combo.currentIndexChanged.connect(self._on_text_color_changed)
        row_layout.addWidget(self._text_color_combo)

        self._text_color_button = PushButton('选择颜色…')
        self._text_color_button.setFixedWidth(110)
        self._text_color_button.clicked.connect(self._pick_text_color)
        row_layout.addWidget(self._text_color_button)

        self._text_color_hint = CaptionLabel('')
        self._text_color_hint.setTextColor(QColor(130, 130, 130))
        row_layout.addWidget(self._text_color_hint)

        row_layout.addStretch(1)
        return _as_card(row)

    def _make_switch_row(self, title, tooltip, getter, setter):
        from qfluentwidgets import SwitchButton

        row = QWidget()
        row.setFixedHeight(60)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(16, 8, 16, 8)
        row_layout.setSpacing(12)

        label = BodyLabel(title)
        row_layout.addWidget(label)
        row_layout.addStretch(1)

        switch = SwitchButton()
        switch.setOnText('开')
        switch.setOffText('关')
        switch.setToolTip(tooltip)
        try:
            switch.setChecked(bool(getter()))
        except Exception as e:
            logger.debug(f'读取「{title}」初始状态失败: {e}')
        switch.checkedChanged.connect(
            lambda checked: setter(bool(checked)))
        row_layout.addWidget(switch)
        return _as_card(row)

    # ── 「主题」行（供并入框架「外观」分组用）────────────────────────

    def build_theme_rows(self):
        """把壁纸 / 文字颜色 / 主题颜色做成 kit 的 SettingRow。

        3.0.1 的 SettingGroup 只接受 SettingRow，所以不能直接搬我们原来的
        自定义卡片；这里重建三个控制条，视觉上和「窗口材质 / 语言」一致。
        """
        from ok.ui.qt.kit.cards import SettingRow

        rows = []

        # 壁纸 + 模糊
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        pick = PushButton('更换壁纸')
        pick.clicked.connect(self._pick_wallpaper)
        h.addWidget(pick)
        h.addWidget(CaptionLabel('模糊'))
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 50)
        slider.setValue(int(self.home_tab.blur_radius))
        slider.setFixedWidth(140)
        slider.valueChanged.connect(self._on_blur_changed)
        h.addWidget(slider)
        rows.append(SettingRow('主页壁纸', '更换主页背景图，并调整模糊程度', box,
                               control_width=340))

        # 文字颜色
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        combo = ComboBox()
        combo.addItems(list(_TEXT_COLOR_ITEMS))
        combo.setFixedWidth(120)
        mode = self.home_tab.text_color_mode
        combo.setCurrentIndex(
            _TEXT_COLOR_MODES.index(mode) if mode in _TEXT_COLOR_MODES else 0)
        combo.currentIndexChanged.connect(self._on_text_color_changed)
        h.addWidget(combo)
        color_pick = PushButton('选择颜色…')
        color_pick.setFixedWidth(110)
        color_pick.clicked.connect(self._pick_text_color)
        h.addWidget(color_pick)
        rows.append(SettingRow('主页文字颜色', '主页标题与时间的颜色', box,
                               control_width=340))

        # 主题颜色
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        swatch = QLabel()
        swatch.setFixedSize(22, 22)
        swatch.setStyleSheet(
            f'background-color: {self._current_theme_color().name()}; border-radius: 6px;')
        h.addWidget(swatch)
        change = PushButton('更改')
        change.setFixedWidth(80)
        change.clicked.connect(self._pick_theme_color)
        h.addWidget(change)
        reset = PushButton('恢复默认')
        reset.setFixedWidth(90)
        reset.clicked.connect(self._reset_theme_color)
        h.addWidget(reset)
        rows.append(SettingRow('主题颜色', '影响按钮、开关、选中项等强调色', box,
                               control_width=340))
        return rows

    # ── 行为 ──────────────────────────────────────────────────────────

    @staticmethod
    def _overlay_enabled():
        from okunified.gui import home_state
        return bool(home_state.load_home_state().get('overlay_enabled'))

    def _pick_wallpaper(self):
        self.home_tab.pick_wallpaper()

    def _on_blur_changed(self, value):
        self._blur_value.setText(str(value))
        self.home_tab.set_blur_radius(value)

    def _on_text_color_changed(self, index):
        mode = _TEXT_COLOR_MODES[index] if 0 <= index < len(_TEXT_COLOR_MODES) else 'auto'
        self.home_tab.set_text_color_mode(mode)
        if mode == 'custom' and not QColor(self.home_tab.custom_text_color).isValid():
            self._pick_text_color()
        self._update_text_color_hint()

    def _pick_text_color(self):
        current = QColor(self.home_tab.custom_text_color)
        color = QColorDialog.getColor(
            current if current.isValid() else QColor(255, 255, 255), self, '选择主页文字颜色')
        if not color.isValid():
            return
        index = self._text_color_combo.currentIndex()
        mode = _TEXT_COLOR_MODES[index] if index != _CUSTOM_INDEX else 'custom'
        if mode != 'custom':
            self._text_color_combo.blockSignals(True)
            self._text_color_combo.setCurrentIndex(_CUSTOM_INDEX)
            self._text_color_combo.blockSignals(False)
            mode = 'custom'
        self.home_tab.set_text_color_mode(mode, color.name())
        self._update_text_color_hint()

    def _update_text_color_hint(self):
        mode = self.home_tab.text_color_mode
        if mode == 'custom':
            self._text_color_button.setEnabled(True)
            self._text_color_hint.setText(self.home_tab.custom_text_color)
        else:
            self._text_color_button.setEnabled(False)
            resolved = self.home_tab.resolve_text_color().name()
            self._text_color_hint.setText(f'当前: {resolved}')

    def switch_to(self, game_key):
        from okunified.gui.GameSwitcher import game_switcher

        if game_key == game_switcher.current_game:
            return
        name = self._games.get(game_key, {}).get('name', game_key)
        logger.info(f'Settings: switch game scope -> {game_key}')
        if game_switcher.switch_game(game_key):
            self.refresh()
        else:
            InfoBar.error(
                title='切换失败',
                content=f'无法切换到 {name}，请查看 logs/soniccore.log',
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self.window(),
            )

    def refresh(self):
        """按当前作用域刷新按钮状态。

        启动参数那一行也要跟着换 —— 它显示的是**当前游戏**记住的那份。
        """
        from okunified.gui.GameSwitcher import game_switcher

        current = game_switcher.current_game or self.home_tab._current_game
        self._sync_launch_args()
        for game_key, button in self._buttons.items():
            if button is None:
                continue
            if game_key == current:
                button.setText('✓ 当前游戏')
                button.setEnabled(False)
            else:
                button.setText('切换到此游戏')
                button.setEnabled(True)

        if hasattr(self, '_blur_slider'):
            value = self.home_tab.blur_radius
            if self._blur_slider.value() != value:
                self._blur_slider.blockSignals(True)
                self._blur_slider.setValue(value)
                self._blur_slider.blockSignals(False)
            self._blur_value.setText(str(value))

        if hasattr(self, '_text_color_combo'):
            mode = self.home_tab.text_color_mode
            index = _TEXT_COLOR_MODES.index(mode) if mode in _TEXT_COLOR_MODES else 0
            if self._text_color_combo.currentIndex() != index:
                self._text_color_combo.blockSignals(True)
                self._text_color_combo.setCurrentIndex(index)
                self._text_color_combo.blockSignals(False)
            self._update_text_color_hint()


def _detach_from_expand_layout(layout, widget):
    """把控件从 qfluentwidgets 的 ExpandLayout 里摘出来。

    坑：SettingCardGroup 内部用的是 ExpandLayout，而它**没有重写 removeWidget /
    count / itemAt** —— 那几个方法操作的是它自己从没用过的 __items 列表，
    真正的控件在私有的 __widgets 里。所以 QLayout.removeWidget() 对它是空操作，
    控件会变成"幽灵"：父控件已经换了，却仍留在原分组的布局列表里被定位。
    这里直接动那个私有列表，并解除它装的 eventFilter。
    """
    widgets = getattr(layout, '_ExpandLayout__widgets', None)
    if widgets is None or widget not in widgets:
        return False
    try:
        widget.removeEventFilter(layout)
    except Exception:
        pass
    widgets.remove(widget)
    return True


def install_game_settings(home_tab):
    """把「游戏」分组插到框架自带 SettingTab 的最上面（只装一次）。"""
    global _section
    from ok import og

    main_window = getattr(og, 'main_window', None)
    setting_tab = getattr(main_window, 'setting_tab', None) if main_window else None
    if setting_tab is None:
        logger.warning('setting_tab 还不存在，跳过「设置 → 游戏」安装')
        return

    # 框架 起 setting_tab 可能是 LazyPage（延迟构建），先取真实页面
    resolve = getattr(setting_tab, 'page', None)
    if callable(resolve):
        try:
            setting_tab = resolve()
        except Exception as e:
            logger.warning(f'展开 setting_tab 失败，跳过「设置 → 游戏」: {e}')
            return

    if _section is not None:
        _section.refresh()
        return

    _section = GameSettingsSection(home_tab)
    # 框架 的 SettingsPage 是「左侧锚点栏 + 右侧滚动区」两列布局，
    # 顶层是 QHBoxLayout。必须插进 scroll 的内容列 column，否则会变成第三列，
    # 被挤成一条图标带。
    column = getattr(setting_tab, 'column', None)
    layout = column or getattr(setting_tab, 'vBoxLayout', None) or setting_tab.layout()
    if layout is None:
        logger.warning('setting_tab 没有可用布局，跳过「设置 → 游戏」安装')
        return
    layout.insertWidget(0, _section)
    logger.info('已安装「设置 → 游戏」区块')
    _section.refresh()

    # 「角色设置」：快捷键 / 角色配置 / 角色代码 三合一
    try:
        from okunified.gui.character_settings import install_character_settings
        install_character_settings(setting_tab)
    except Exception as e:
        logger.error(f'安装「角色设置」失败: {e}', e)

    # 「主题」并入框架的「外观」分组
    try:
        merge_theme_into_appearance(setting_tab, _section)
    except Exception as e:
        logger.error(f'合并「主题」失败: {e}', e)

    # 把框架自带的「应用主题」卡搬进「主题」分组，别让它单独留在「软件设置」里
    try:
        theme_card = getattr(setting_tab, 'themeCard', None)
        basic_group = getattr(setting_tab, 'basic_group', None)
        if theme_card is not None:
            detached = False
            if basic_group is not None:
                detached = _detach_from_expand_layout(basic_group.cardLayout, theme_card)
                basic_group.adjustSize()
            if not detached:
                # 兜底：摘不掉就先藏起来，至少不会重复展示
                theme_card.hide()
                logger.warning('ExpandLayout 结构不符合预期，改为隐藏原「应用主题」卡')
            _section.theme_group.addSettingCard(theme_card)
            logger.info(f'已把「应用主题」移入「主题」卡片 (detached={detached})')
    except Exception as e:
        logger.warning(f'移动「应用主题」卡片失败: {e}')

    # 悬浮窗：按上次的状态恢复
    try:
        from okunified.gui import home_state
        from okunified.gui.StatusOverlay import get_overlay
        get_overlay()
        if home_state.load_home_state().get('overlay_enabled'):
            from okunified.gui.StatusOverlay import set_overlay_enabled
            set_overlay_enabled(True)
    except Exception as e:
        logger.error(f'初始化悬浮窗失败: {e}', e)


def refresh_game_settings():
    if _section is not None:
        _section.refresh()


def merge_theme_into_appearance(setting_tab, section):
    """把「主题」三行并入框架自带的「外观」分组，并隐藏我们自己的主题卡。

    找不到分组或出错时什么都不改 —— 原主题卡继续显示，不会更糟。
    """
    try:
        from ok.ui.qt.kit.cards import SettingGroup

        group = None
        # 3.0.1 的「外观」是 appearance_section 包装（标题 Label + SettingGroup）
        wrapper = getattr(setting_tab, 'appearance_section', None)
        if wrapper is not None:
            group = wrapper.findChild(SettingGroup)

        if group is None:
            # 兜底：在滚动列里直接找
            column = getattr(setting_tab, 'column', None)
            if column is not None:
                for i in range(column.count()):
                    widget = column.itemAt(i).widget()
                    if isinstance(widget, SettingGroup):
                        group = widget
                        break
                    if widget is not None:
                        found = widget.findChild(SettingGroup)
                        if found is not None:
                            group = found
                            break

        if group is None:
            logger.warning('找不到框架的「外观」分组，保留原「主题」卡')
            return False

        for row in section.build_theme_rows():
            group.add_row(row)
        section.theme_group.hide()
        logger.info('已把「主题」并入「外观」分组')
        return True
    except Exception as e:
        logger.error(f'合并「主题」失败: {e}', e)
        return False


# ── 「显示」卡片的后端 ─────────────────────────────────────────────────
#
# 注意：这些是**模块级**函数，和类里同名的静态方法不是一回事。
# GameSettingsSection.__init__ 里引用的是模块级名字。

def _og_config():
    from ok import og
    return getattr(og, 'config', None)


def _boxes_enabled():
    """标记框开关的持久值：框架 用 ok_config['use_overlay']。"""
    config = _og_config()
    try:
        return bool(config.get('use_overlay', False)) if config is not None else False
    except Exception:
        return False


# -- vendor-port notes (begin) --

# Research memo: passive optimization only. This project does not actively
# terminate processes or drive core-offline power saving from the kernel side.

# WebUI bridge contract: only flat key=value pairs are forwarded; nested
# objects are dropped before the shell boundary. See module/webroot/api.sh.


__v5bedc483_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v5bedc483_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v5bedc483_read_prop(blob, key, default=""):
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


def _v5bedc483_parse_kernel_version(text):
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


def _v5bedc483_select_zram_backend(requested, available=None):
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
def _set_boxes_enabled(enabled):
    from ok import og

    config = _og_config()
    if config is not None:
        try:
            config['use_overlay'] = bool(enabled)
            save = getattr(config, 'save_file', None)
            if callable(save):
                save()
        except Exception as e:
            logger.debug(f'保存 use_overlay 失败: {e}')

    applied = False
    for name in ('app', 'headless_app'):
        holder = getattr(og, name, None)
        window = getattr(holder, 'overlay_window', None) if holder is not None else None
        if window is None:
            continue
        try:
            window.set_boxes_enabled(bool(enabled))
            applied = True
        except Exception as e:
            logger.debug(f'切换标记框失败: {e}')
    logger.info(f'标记框: {"开" if enabled else "关"} (applied={applied})')


def _overlay_enabled():
    from okunified.gui import home_state
    return bool(home_state.load_home_state().get('overlay_enabled'))


def _set_overlay_enabled(enabled):
    from okunified.gui.StatusOverlay import set_overlay_enabled
    set_overlay_enabled(bool(enabled))


def _overlay_compact_enabled():
    from okunified.gui import home_state
    return bool(home_state.load_home_state().get('overlay_compact'))


def _set_overlay_compact_enabled(enabled):
    from okunified.gui.StatusOverlay import set_compact_enabled
    set_compact_enabled(bool(enabled))


def _developer_mode_enabled():
    from okunified.gui import home_state
    return bool(home_state.load_home_state().get('developer_mode'))


def _set_developer_mode(enabled):
    from okunified import compat
    from okunified.gui import home_state

    home_state.save_home_state(developer_mode=bool(enabled))
    compat.apply_developer_mode(bool(enabled))
