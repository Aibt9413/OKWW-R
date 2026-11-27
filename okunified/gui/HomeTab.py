"""
SonicCore 主页 Tab。

视觉参考 上游参考项目 的 HomePage：
模糊壁纸铺底 + 左上标题 + 右上时钟 + 底部操作栏 + 右下"开始"。

关于文字取色（重要）：
qfluentwidgets 的 TitleLabel / BodyLabel 都继承 FluentLabelBase，颜色由
``setTextColor(light, dark)`` 通过 setCustomStyleSheet 管理，并且 _init() 里
连了 ``qconfig.themeChanged → _applyThemeColor()``。
所以**不能用 setStyleSheet('color: ...')**——主题一变就被覆盖回默认色
（浅色主题默认黑字），这正是之前"浅色壁纸上是黑字"的原因。
这里统一走 setTextColor()，并且 light/dark 给同一个值，主题切换就不会变色。
"""
import os

from PySide6.QtCore import Qt, QTimer, QRectF, QEvent
from PySide6.QtGui import (QPixmap, QColor, QPainter, QPainterPath, QLinearGradient,
                           QBrush, QFont)
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
                               QGraphicsScene, QGraphicsPixmapItem, QGraphicsBlurEffect,
                               QGraphicsDropShadowEffect, QLabel)

from qfluentwidgets import (NavigationItemPosition, FluentIcon, PushButton,
                            PrimaryPushButton, TitleLabel, BodyLabel)

from ok import Logger
from ok.core.events import communicate
from ok.ui.qt.widget.CustomTab import CustomTab

from okunified.gui import home_state

logger = Logger.get_logger(__name__)

CORNER_RADIUS = 12


class _HomeLabel(QLabel):
    """主页顶部的大字标签。

    不使用 qfluentwidgets 的 TitleLabel：它的字号由库自带样式表控制，
    而 ``FluentLabelBase.setTextColor()`` 会用 ``setCustomStyleSheet()``
    整体替换控件样式表，外部设置的 font-size 会被反复冲掉（实测无效）。

    这里直接用 QLabel + 写死的像素字号，颜色由 setTextColor() 自己维护。
    """

    def __init__(self, text='', pixel_size=40, parent=None):
        super().__init__(text, parent)
        self._pixel_size = pixel_size
        self._text_color = QColor('#ffffff')

        font = QFont(self.font())
        font.setPixelSize(pixel_size)
        font.setBold(True)
        self.setFont(font)

        self._refresh_style()
        try:
            from qfluentwidgets import qconfig
            qconfig.themeChanged.connect(self._refresh_style)
        except Exception:
            pass

    def setTextColor(self, light=None, dark=None):
        if light is not None:
            self._text_color = QColor(light)
        self._refresh_style()

    def _refresh_style(self, *_args):
        self.setStyleSheet(
            f"color: {self._text_color.name()};"
            f" font-size: {self._pixel_size}px;"
            f" font-weight: 700;"
            f" background: transparent;")
# 壁纸右侧与窗口右边缘的间距
WALLPAPER_RIGHT_GAP = 16

# 自动取色时用的两个候选色
AUTO_LIGHT_TEXT = QColor(0xFF, 0xFF, 0xFF)
AUTO_DARK_TEXT = QColor(0x1F, 0x1F, 0x1F)
# 顶部这块区域的平均亮度高于该阈值就用深色字，否则白字
AUTO_LUMINANCE_THRESHOLD = 0.62

_GLASS_BUTTON_QSS = """
PushButton {
    background-color: rgba(0, 0, 0, 0.30);
    color: white;
    border: 1px solid rgba(255, 255, 255, 0.30);
    border-radius: 8px;
    padding: 6px 16px;
}
PushButton:hover { background-color: rgba(0, 0, 0, 0.44); }
PushButton:pressed { background-color: rgba(0, 0, 0, 0.58); }
"""

_home_tab = None


def get_home_tab():
    """返回当前 HomeTab 实例（可能还没创建）。"""
    return _home_tab


def _blur_pixmap(src: QPixmap, radius: float) -> QPixmap:
    """高斯模糊 —— 用 QGraphicsBlurEffect 原生渲染。"""
    if src.isNull() or radius <= 0:
        return src
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(src)
    blur = QGraphicsBlurEffect()
    blur.setBlurRadius(radius)
    blur.setBlurHints(QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(blur)
    scene.addItem(item)
    out = QPixmap(src.size())
    out.fill(Qt.transparent)
    painter = QPainter(out)
    scene.render(painter, QRectF(out.rect()), QRectF(src.rect()))
    painter.end()
    return out


class _WallpaperLabel(QLabel):
    """铺满父窗口的壁纸（圆角 + 底部压暗）。"""

    # 放大一点再裁，避免模糊在边缘被截断出现暗边
    _OVERSCAN = 1.12

    def __init__(self, parent):
        super().__init__(parent)
        self._source = QPixmap()
        self._blur = 0
        self._cache_key = None

    def set_wallpaper(self, path, blur):
        if path and os.path.isfile(path):
            pixmap = QPixmap(path)
        else:
            pixmap = QPixmap()
        if pixmap.isNull() and path:
            logger.warning(f'无法读取壁纸: {path}')
        self._source = pixmap
        self._blur = blur
        self._cache_key = None
        self._rebuild()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rebuild()

    def _rebuild(self):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        key = (w, h, self._blur)
        if key == self._cache_key:
            return
        self._cache_key = key

        if self._source.isNull():
            # 没设壁纸时的兜底渐变，保证白字仍然可读
            out = QPixmap(w, h)
            out.fill(Qt.transparent)
            painter = QPainter(out)
            painter.setRenderHints(QPainter.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), CORNER_RADIUS, CORNER_RADIUS)
            gradient = QLinearGradient(0, 0, w, h)
            gradient.setColorAt(0.0, QColor(0x4A, 0x6B, 0x9A))
            gradient.setColorAt(1.0, QColor(0x1E, 0x2A, 0x3C))
            painter.fillPath(path, QBrush(gradient))
            painter.end()
            self.setPixmap(out)
            self.update()
            return

        tw = int(w * self._OVERSCAN)
        th = int(h * self._OVERSCAN)
        scaled = self._source.scaled(tw, th, Qt.KeepAspectRatioByExpanding,
                                     Qt.SmoothTransformation)
        if self._blur > 0:
            scaled = _blur_pixmap(scaled, self._blur)

        out = QPixmap(w, h)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)

        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), CORNER_RADIUS, CORNER_RADIUS)
        painter.setClipPath(path)

        sx = max(0, (scaled.width() - w) // 2)
        sy = max(0, (scaled.height() - h) // 2)
        painter.drawPixmap(0, 0, w, h, scaled, sx, sy, w, h)

        # 顶部轻微压暗：
        #   1. 白色文字在任何壁纸（含纯白）上都能看清，不用靠描边；
        #   2. 自动取色采样的是这张成品图，压暗后基准天然偏"该用白字"，
        #      只有接近纯白的壁纸才会翻成深色字。
        top_scrim = QLinearGradient(0, 0, 0, h * 0.26)
        top_scrim.setColorAt(0.0, QColor(0, 0, 0, 96))
        top_scrim.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillPath(path, QBrush(top_scrim))

        # 底部压暗，保证浅色壁纸上的白色按钮也看得清
        scrim = QLinearGradient(0, h * 0.55, 0, h)
        scrim.setColorAt(0.0, QColor(0, 0, 0, 0))
        scrim.setColorAt(1.0, QColor(0, 0, 0, 120))
        painter.fillPath(path, QBrush(scrim))
        painter.end()

        self.setPixmap(out)

    def top_band_luminance(self, ratio=0.22):
        """顶部文字区域的平均亮度（0~1），用于自动取色。"""
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return 0.0
        image = pixmap.toImage()
        width, height = image.width(), image.height()
        if width <= 0 or height <= 0:
            return 0.0

        y_max = max(1, int(height * ratio))
        step_x = max(1, width // 64)
        step_y = max(1, y_max // 24)

        total = 0.0
        count = 0
        for y in range(0, y_max, step_y):
            for x in range(0, width, step_x):
                color = image.pixelColor(x, y)
                total += (0.299 * color.red()
                          + 0.587 * color.green()
                          + 0.114 * color.blue()) / 255.0
                count += 1
        return total / count if count else 0.0


class HomeTab(CustomTab):
    """SonicCore 主页 —— 壁纸落地页。"""

    def __init__(self):
        global _home_tab
        super().__init__()
        _home_tab = self

        state = home_state.load_home_state()
        self._wallpaper_path = state['wallpaper']
        self._blur = state['blur']
        self._text_color_mode = state['text_color']
        self._custom_text_color = state['custom_text_color']
        self._applied_color = None
        self._current_game = None

        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)

        # 壁纸层（子控件，压在内容下面）
        self._bg = _WallpaperLabel(self.view)
        self._bg.lower()
        self._bg.set_wallpaper(self._wallpaper_path, self._blur)
        # Tab 的内层 view 由 ScrollArea 自己调整大小，时机晚于本控件的 resizeEvent，
        # 所以直接盯住 view 的 Resize 事件，保证壁纸始终铺满。
        self.view.installEventFilter(self)

        self._build_top_bar()
        self._build_game_label()
        self.vBoxLayout.addStretch(1)
        self._build_bottom_bar()

        # 单游戏：3.0.1 下没有 GameSwitcher 在跑，_current_game 会一直是空，
        # 导致「游戏路径」判定"未选择游戏"而直接跳去设置页。这里给个默认值。
        self.update_current_game(
            home_state.load_home_state().get('last_game') or 'wuthering')

        self._tick_clock()
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)

        communicate.executor_paused.connect(self._on_paused)
        communicate.start_success.connect(self._install_settings)

        # 特色功能 / 设置区块 / 侧边栏整理：不依赖 start_success 的时序
        # （信号可能在 HomeTab 连上之前就发完了，导致这些功能整个不出现）。
        # 在 QApplication 已存在的构造阶段起轮询，反复调用 _install_settings
        # （各安装函数都是幂等的），直到 MainWindow / LazyPage / 连接弹窗都就绪。
        try:
            self._feature_tries = [50]
            self._feature_timer = QTimer(self)
            self._feature_timer.timeout.connect(self._try_install_features)
            self._feature_timer.start(300)
        except Exception as e:
            logger.debug(f'启动功能轮询失败: {e}')

        self._apply_text_colors()

    def _try_install_features(self):
        try:
            # 各 install_* 都是幂等的；装到「增强功能区块」出现即视为完成，
            # 立刻停止轮询，避免反复执行 _install_settings 产生日志噪音、
            # 以及重复 insertWidget 打乱侧边栏顺序。
            from ok import og
            from qfluentwidgets import SwitchButton
            from PySide6.QtWidgets import QFrame
            mw = getattr(og, 'main_window', None)
            popover = getattr(getattr(mw, 'run_bar', None), 'popover', None)
            done = (popover is not None and
                    popover.findChild(QFrame, 'okUnifiedFeatureBlock') is not None)
            if not done:
                self._install_settings()
                # 重新检查一次
                popover = getattr(getattr(getattr(og, 'main_window', None), 'run_bar', None), 'popover', None)
                done = (popover is not None and
                        popover.findChild(QFrame, 'okUnifiedFeatureBlock') is not None)
            if done:
                self._feature_timer.stop()
                return
        except Exception as e:
            logger.debug(f'轮询安装功能异常: {e}')
        self._feature_tries[0] -= 1
        if self._feature_tries[0] <= 0:
            self._feature_timer.stop()
            logger.warning('功能安装轮询超时：连接弹窗增强区块始终未就绪')

    # ── 构建界面 ──────────────────────────────────────────────────────

    def _build_top_bar(self):
        from config import config

        top_bar = QWidget()
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(32, 20, 32, 0)
        top_layout.setSpacing(10)

        self.title_label = _HomeLabel('SonicCore', 40)
        self._add_shadow(self.title_label)
        top_layout.addWidget(self.title_label)

        # 直接显示版本号本身，不再前面拼 "v" ——
        # 版本号是 alpha0.1.3 这种自带前缀的写法，拼起来会变成 "valpha0.1.3"
        self.version_label = BodyLabel(config.get('version', '') or '')
        self.version_label.setFont(self._font(self.version_label, 13))
        self._add_shadow(self.version_label)
        top_layout.addWidget(self.version_label, 0, Qt.AlignBottom)
        top_layout.addStretch(1)

        self.clock_label = _HomeLabel('', 36)
        self._add_shadow(self.clock_label)
        top_layout.addWidget(self.clock_label)

        self.vBoxLayout.addWidget(top_bar)

    def _build_game_label(self):
        self.game_label = BodyLabel('尚未选择游戏 —— 请到「设置 → 游戏」中选择')
        self.game_label.setFont(self._font(self.game_label, 15))
        self._add_shadow(self.game_label)
        game_row = QHBoxLayout()
        game_row.setContentsMargins(34, 6, 32, 0)
        game_row.addWidget(self.game_label)
        game_row.addStretch(1)
        self.vBoxLayout.addLayout(game_row)

    def _build_bottom_bar(self):
        bottom = QWidget()
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(32, 16, 32, 20)
        bottom_layout.setSpacing(12)

        for text, slot in (
            ('更换壁纸', self.pick_wallpaper),
            ('游戏路径', self.pick_game_path),
            ('设置', self.goto_settings),
        ):
            button = PushButton(text)
            button.setFixedHeight(36)
            button.setStyleSheet(_GLASS_BUTTON_QSS)
            button.clicked.connect(slot)
            bottom_layout.addWidget(button)
            if text == '游戏路径':
                self.path_button = button

        bottom_layout.addStretch(1)

        self.start_button = PrimaryPushButton(FluentIcon.PLAY, '开始')
        self.start_button.setFixedSize(140, 44)
        self.start_button.clicked.connect(self.toggle_start)
        bottom_layout.addWidget(self.start_button)

        self.vBoxLayout.addWidget(bottom)

    @staticmethod
    def _font(widget, pixel_size, bold=False):
        font = QFont(widget.font())
        font.setPixelSize(pixel_size)
        font.setBold(bold)
        return font

    @staticmethod
    def _add_shadow(widget):
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(12)
        shadow.setColor(QColor(40, 40, 40, 190))
        shadow.setOffset(0, 2)
        widget.setGraphicsEffect(shadow)

    # ── 基础属性 ──────────────────────────────────────────────────────

    @property
    def name(self):
        return "主页"

    @property
    def icon(self):
        # 框架 的 nav_icon() 只认「内置图标名 / QIcon / Icon 枚举」。
        # 返回 FluentIcon 会走它自己的 .icon()，渲染成 qfluentwidgets 主题色的
        # QIcon（表现为粉色高亮），和侧边栏其余图标风格不一致。
        return "grid"

    @property
    def position(self):
        return NavigationItemPosition.TOP

    @property
    def add_after_default_tabs(self):
        return False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_background()

    def eventFilter(self, obj, event):
        if obj is self.view and event.type() == QEvent.Resize:
            self._sync_background()
        return super().eventFilter(obj, event)

    def _sync_background(self):
        # 右侧留一点间距，壁纸不贴死窗口右边缘
        width = max(0, self.view.width() - WALLPAPER_RIGHT_GAP)
        self._bg.setGeometry(0, 0, width, self.view.height())
        # 壁纸尺寸变了 → 自动取色结果可能也变
        if self._text_color_mode == 'auto':
            self._apply_text_colors()

    # ── 文字取色 ──────────────────────────────────────────────────────

    @property
    def text_color_mode(self):
        return self._text_color_mode

    @property
    def custom_text_color(self):
        return self._custom_text_color

    def resolve_text_color(self):
        mode = self._text_color_mode
        if mode == 'white':
            return QColor(AUTO_LIGHT_TEXT)
        if mode == 'dark':
            return QColor(AUTO_DARK_TEXT)
        if mode == 'custom':
            color = QColor(self._custom_text_color)
            return color if color.isValid() else QColor(AUTO_LIGHT_TEXT)
        luminance = self._bg.top_band_luminance()
        return QColor(AUTO_DARK_TEXT if luminance > AUTO_LUMINANCE_THRESHOLD
                      else AUTO_LIGHT_TEXT)

    def _apply_text_colors(self):
        color = self.resolve_text_color()
        if color == self._applied_color:
            return
        self._applied_color = color

        secondary = QColor(color)
        secondary.setAlpha(210)
        # light / dark 给同一个值：FluentLabelBase 在主题切换时会用这两个值回写，
        # 只要它们一致，切主题就不会把颜色改掉。
        for label in (self.title_label, self.clock_label):
            label.setTextColor(color, color)
        # setTextColor() 会整体替换控件样式表，字号规则必须在它之后重新补上
        self._apply_title_sizes()
        self.version_label.setTextColor(secondary, secondary)
        self.game_label.setTextColor(secondary, secondary)

    def _apply_title_sizes(self, *_args):
        """字号必须写成样式表规则。

        qfluentwidgets 的 FluentLabelBase.setTextColor() 用 setCustomStyleSheet()
        **整体替换**控件样式表，所以 setFont()/先前的 font-size 都会被打回去。
        每次设完颜色（或主题切换后）都要把字号规则重新补一遍。
        """
        if not getattr(self, '_title_size_hooked', False):
            self._title_size_hooked = True
            try:
                from qfluentwidgets import qconfig
                # 标签自己的主题回调比我们早注册，所以这里能最后执行
                qconfig.themeChanged.connect(self._apply_title_sizes)
            except Exception:
                pass

        for label, size in ((self.title_label, 40), (self.clock_label, 36)):
            sheet = label.styleSheet()
            rule = f'FluentLabelBase{{font-size:{size}px; font-weight:700;}}'
            if rule not in sheet:
                label.setStyleSheet(sheet + rule)
        if not getattr(self, '_title_size_logged', False):
            self._title_size_logged = True
            logger.info(f'主页字号已应用: title={self.title_label.font().pixelSize()} '
                        f'clock={self.clock_label.font().pixelSize()} '
                        f'titleHintH={self.title_label.sizeHint().height()}')

    def set_text_color_mode(self, mode, custom_color=None):
        """供「设置」调用。mode: auto / white / dark / custom"""
        if mode not in home_state._TEXT_COLOR_MODES:
            mode = 'auto'
        self._text_color_mode = mode
        if custom_color:
            self._custom_text_color = custom_color
        home_state.save_home_state(text_color=mode,
                                   custom_text_color=self._custom_text_color)
        self._applied_color = None
        self._apply_text_colors()
        logger.info(f'主页文字取色: {mode} {self._custom_text_color} '
                    f'→ {self.resolve_text_color().name()}')

    # ── 时钟 / 开始按钮 ───────────────────────────────────────────────

    def _tick_clock(self):
        from datetime import datetime
        self.clock_label.setText(datetime.now().strftime('%H:%M'))

    def _on_paused(self, paused):
        self.start_button.setText('开始' if paused else '暂停')
        self.start_button.setIcon(FluentIcon.PLAY if paused else FluentIcon.PAUSE)

    def toggle_start(self):
        from ok import og
        executor = getattr(og, 'executor', None)
        if executor is None:
            return
        if executor.paused:
            logger.info('Home page: start executor')
            og.app.start_controller.start()
        else:
            logger.info('Home page: pause executor')
            executor.pause()

    def goto_settings(self):
        from ok import og

        main_window = getattr(og, 'main_window', None)
        if main_window is None:
            return
        # 2.0.6 是 switchTo()，3.0.1 改成了 switch_to()（且会自己展开 LazyPage）
        switch = getattr(main_window, 'switch_to', None) or getattr(
            main_window, 'switchTo', None)
        if switch is None:
            return
        setting_tab = getattr(main_window, 'setting_tab', None)
        if setting_tab is not None:
            switch(setting_tab)

    # ── 壁纸 / 游戏路径 ───────────────────────────────────────────────

    def pick_wallpaper(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择壁纸', '', '图片 (*.png *.jpg *.jpeg *.bmp *.webp)')
        if not path:
            return
        self.apply_wallpaper(path)

    def apply_wallpaper(self, path):
        self._wallpaper_path = path
        home_state.save_home_state(wallpaper=path)
        self._bg.set_wallpaper(path, self._blur)
        self._applied_color = None
        self._apply_text_colors()
        logger.info(f'壁纸已更新: {path}')

    def set_blur_radius(self, radius):
        self._blur = max(0, min(50, int(radius)))
        home_state.save_home_state(blur=self._blur)
        self._bg.set_wallpaper(self._wallpaper_path, self._blur)
        self._applied_color = None
        self._apply_text_colors()

    @property
    def blur_radius(self):
        return self._blur

    def pick_game_path(self):
        """设置当前所选游戏的可执行文件。没选游戏就不让改。"""
        from config import GAMES
        from qfluentwidgets import InfoBar, InfoBarPosition

        game_key = self._current_game
        if not game_key:
            InfoBar.warning(
                title='还没有选择游戏',
                content='请先到「设置 → 游戏」里选择一个游戏，再设置它的可执行文件',
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=4000, parent=self.window())
            self.goto_settings()
            return

        info = GAMES.get(game_key, {})
        exes = info.get('exe') or []
        pattern = ' '.join('*.exe' for _ in exes) or '*.exe'
        current = home_state.get_game_exe(game_key)
        start_dir = os.path.dirname(current) if current else info.get('path', '')
        path, _ = QFileDialog.getOpenFileName(
            self, f"选择 {info.get('name', game_key)} 的可执行文件", start_dir,
            f'游戏程序 ({pattern});;所有文件 (*.exe)')
        if not path:
            return
        home_state.set_game_exe(game_key, path)
        self._apply_game_exe(path)
        self.update_current_game(game_key)
        logger.info(f'游戏路径已更新 [{game_key}]: {path}')

    @staticmethod
    def _apply_game_exe(exe_path):
        from ok import og
        manager = getattr(og, 'device_manager', None)
        if manager is None:
            return
        try:
            manager.config['pc_full_path'] = exe_path
            manager.config.save_file()
        except Exception as e:
            logger.warning(f'写入游戏路径失败: {e}')

    # ── 游戏状态 ──────────────────────────────────────────────────────

    def update_current_game(self, game_key):
        from config import GAMES
        self._current_game = game_key
        home_state.save_home_state(last_game=game_key or '')
        if not game_key:
            self.game_label.setText('尚未选择游戏 —— 请到「设置 → 游戏」中选择')
            if hasattr(self, 'path_button'):
                self.path_button.setToolTip('请先在「设置 → 游戏」中选择一个游戏')
            return
        info = GAMES.get(game_key, {})
        exe = home_state.get_game_exe(game_key)
        text = f"当前游戏：{info.get('name', game_key)}　{info.get('name_en', '')}"
        if exe:
            text += f"　·　{os.path.basename(exe)}"
        self.game_label.setText(text)
        if hasattr(self, 'path_button'):
            self.path_button.setToolTip(
                f"设置「{info.get('name', game_key)}」的可执行文件"
                + (f'\n当前: {exe}' if exe else '\n当前: 未设置（点一下选择）'))

    # ── 设置页集成 ────────────────────────────────────────────────────

    def _install_settings(self, *_):
        try:
            from okunified.gui.game_settings import install_game_settings
            install_game_settings(self)
        except Exception as e:
            logger.error(f'安装「设置 → 游戏」失败: {e}', e)

        # 藏掉 框架 顶部那条重复的「启动游戏」运行栏
        try:
            from PySide6.QtCore import QTimer
            from okunified import compat as _compat
            # 此时 QApplication 已存在，再同步一次主题（启动早期那次可能还是 no-op）
            _compat._sync_widget_theme()
            # 开发者模式：默认关 → 隐藏「开发」下的 脚本/模板/诊断
            from okunified.gui import home_state as _hs
            _compat.apply_developer_mode(
                bool(_hs.load_home_state().get('developer_mode', False)))
            QTimer.singleShot(400, _compat.hide_run_bar)
            QTimer.singleShot(700, _compat.arrange_navigation)
            # 3.0.1 会在稍后恢复上次的窗口几何，夹两次更稳
            QTimer.singleShot(900, _compat.fit_main_window)
            QTimer.singleShot(1800, _compat.fit_main_window)
        except Exception as e:
            logger.debug(f'安排隐藏运行栏失败: {e}')

        # 窗口总标题固定为 SonicCore（框架会拼上版本号，这里覆盖掉）
        try:
            from okunified.gui.GameSwitcher import force_window_title, WINDOW_TITLE
            if force_window_title():
                logger.info(f'窗口标题固定为 {WINDOW_TITLE}')
        except Exception as e:
            logger.error(f'固定窗口标题失败: {e}', e)

        # 悬浮窗/紧凑模式开关 + 自定义作用域按钮：
        # 3.0.1 的「截图方式页」已改成运行栏的连接弹窗，旧 start_tab 不存在。
        try:
            from ok import og
            from okunified import compat as _compat
            main_window = getattr(og, 'main_window', None)
            if main_window is not None and getattr(main_window, 'run_bar', None) is not None:
                _compat.install_connection_features()
            elif main_window is not None:
                # 旧框架兜底：2.0.6 的 start_tab
                start_tab = getattr(main_window, 'start_tab', None)
                if start_tab is not None:
                    from okunified.gui.window_picker import install_start_tab_card
                    from okunified.gui.StatusOverlay import install_switch_into_debug_card
                    install_start_tab_card(main_window, self)
                    install_switch_into_debug_card(start_tab)
        except Exception as e:
            logger.error(f'安装特色功能（悬浮窗/作用域）失败: {e}', e)
