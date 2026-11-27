"""
StatusOverlay —— 屏幕左下角悬浮状态框（L1 视觉重做版）。

布局（8pt 栅格；外边距 16，块间距 8，行内间距 4）：

    ┌────────────────────────────────────────┐
    │ SonicCore            [运行中]   14:23:05 │
    │ ⚡ 触发器 5          ▣ 当前任务 每日任务  │
    │ ────────────────────────────────────── │
    │ ⟲ 实时日志                    已运行 1h53m│
    │ 14:20  进入战斗                          │
    │ ▍14:21  错误: 截图失败                   │
    └────────────────────────────────────────┘

内容：
  - 应用名（左上，主题色，semibold）
  - 状态 pill（运行中 / 空闲，主题色描边 + 极淡填充）
  - 时钟（右上，HH:MM:SS，前置图标）
  - 触发器数量 / 当前任务（第二行，各带图标）
  - 实时滚动中文日志（最近 50 条；时间戳弱化，错误行左侧红条）

紧凑形态（只留应用名 + 任务 + 已运行）：

    ┌────────────────────────────────────────┐
    │ SonicCore   每日任务          已运行 1h53m│
    └────────────────────────────────────────┘

日志来源（原版 框架 没有 op_log 信号，由 okunified.compat 挂上）：
  - ``communicate.op_log``   ：游戏侧 self.op_log() 发来的操作流水
                              + 启动器自身事件
  - ``communicate.task``     ：一次性任务开始
  - ``communicate.task_done``：一次性任务完成
  - ``communicate.notification`` / ``capture_error``：错误与截图失败

交互：
  本窗口是**鼠标穿透**的（WindowTransparentForInput + WA_TransparentForMouseEvents），
  所以不能双击/点击。紧凑形态由「开发工具」卡片里的「紧凑模式」开关切换，
  状态持久化在 configs/home.json 的 overlay_compact 键。

透明度的三个 ALPHA 常量在下面；想整体调淡/调实只改这三个数。
"""
import html
import re
import time
from datetime import datetime

from PySide6.QtCore import (QEasingCurve, QPropertyAnimation, Qt, QTimer,
                            Signal)
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QSizePolicy, QTextEdit, QVBoxLayout, QWidget)

from ok import Logger, og
from ok.core.events import communicate

logger = Logger.get_logger(__name__)

# ── 8pt 栅格 ────────────────────────────────────────────────────────────
GRID = 8

PAGE_MARGIN = GRID * 2          # 16  容器内边距
BLOCK_SPACING = GRID            # 8   块与块之间
ROW_SPACING = GRID // 2         # 4   行内元素之间

RADIUS_OUTER = 12
RADIUS_INNER = 8

OVERLAY_WIDTH = 360
LOG_MAX_HEIGHT = 180

# 背景透明度（0-255，数字越小越透明）。
# 悬浮窗压在游戏画面上，太重会挡视野，所以默认走"接近透明"。
# 日志框叠在卡片上面，两层会叠加：实际遮光 ≈ 1-(1-卡片)(1-日志)。
CONTAINER_ALPHA = 50
LOG_ALPHA = 45
BORDER_ALPHA = 18

# ── 配色 / 字体 ─────────────────────────────────────────────────────────
FALLBACK_ACCENT = '#009faa'

LOG_TEXT_COLOR = '#ffffff'
TIME_TEXT_COLOR = 'rgba(255,255,255,110)'   # 时间戳弱化到 ~43%
ERROR_BAR_COLOR = '#ff5252'
ERROR_KEYWORDS = ('失败', '错误', '未确认', '拒绝', '超时', '异常', '无法')

# 图标不透明度（弱化，不抢视线）
ICON_OPACITY = 0.55

# 字体一律用 pt：随系统 DPI 自动缩放，不需要手算 devicePixelRatio。
FONT_TITLE = '11.5pt'
FONT_BODY = '9pt'
FONT_CAPTION = '8.5pt'
FONT_LOG = '9pt'

_PROCESS_START = time.monotonic()

# 日志行首的 "HH:MM" 时间戳（compat.op_log 发送时已带上）
_TIMESTAMP_RE = re.compile(r'^(\d{2}:\d{2})(\s+)(.*)$', re.S)


def format_duration(seconds):
    """秒 → '1h 53m 26s'。不足一小时就不显示 h，不足一分钟就不显示 m。"""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f'{hours}h {minutes}m {secs}s'
    if minutes:
        return f'{minutes}m {secs}s'
    return f'{secs}s'


def uptime_text():
    return f'已运行 {format_duration(time.monotonic() - _PROCESS_START)}'


def onetime_task(executor):
    """当前在跑的**一次性任务**；触发器任务不算。"""
    task = getattr(executor, 'current_task', None)
    if task is None:
        return None
    onetime = getattr(executor, 'onetime_tasks', None)
    if onetime is not None:
        return task if task in onetime else None
    try:
        from ok import TriggerTask

        return None if isinstance(task, TriggerTask) else task
    except Exception:
        return task


def theme_color():
    """强调色 = 「设置 → 主题颜色」。"""
    try:
        from qfluentwidgets import qconfig

        color = qconfig.get(qconfig.themeColor)
        if isinstance(color, QColor) and color.isValid():
            return color
    except Exception:
        pass
    return QColor(FALLBACK_ACCENT)


def font_family_css():
    """主题字体栈，拼成 CSS 的 font-family 值。"""
    families = None
    try:
        from qfluentwidgets import qconfig

        families = qconfig.get(qconfig.fontFamilies)
    except Exception:
        pass
    if not families:
        families = ['Segoe UI', 'Microsoft YaHei']
    return ', '.join(f"'{name}'" for name in families)


def _rgba(color, alpha):
    return f'rgba({color.red()},{color.green()},{color.blue()},{alpha})'


def _boost(color, amount):
    """往白色提亮（保留色相），只用于文字。"""
    return QColor(
        round(color.red() + (255 - color.red()) * amount),
        round(color.green() + (255 - color.green()) * amount),
        round(color.blue() + (255 - color.blue()) * amount))


ACCENT_TEXT_BOOST = 0.32

_overlay = None


def get_overlay():
    """懒加载单例。"""
    global _overlay
    if _overlay is None:
        _overlay = StatusOverlay()
    return _overlay


def _emit(message):
    from okunified import compat
    compat.op_log(message)


def _app_name():
    """左上角显示的应用名，唯一来源是 GameSwitcher.WINDOW_TITLE。"""
    try:
        from okunified.gui.GameSwitcher import WINDOW_TITLE

        return WINDOW_TITLE
    except Exception:
        return 'SonicCore'


def _icon(name, size=14):
    """取一个 Fluent 图标控件；取不到就返回 None（不影响布局）。"""
    try:
        from qfluentwidgets import FluentIcon, IconWidget

        icon = getattr(FluentIcon, name, None)
        if icon is None:
            return None
        widget = IconWidget(icon)
        widget.setFixedSize(size, size)
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(ICON_OPACITY)
        widget.setGraphicsEffect(effect)
        return widget
    except Exception as e:
        logger.debug(f'取图标 {name} 失败: {e}')
        return None


class StatusOverlay(QWidget):
    """屏幕左下角悬浮状态框。"""

    visibility_changed = Signal(bool)

    MAX_LOG_LINES = 50
    FADE_MS = 120

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            # 鼠标完全穿透：悬浮窗只显示信息，不该抢走点击。
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedWidth(OVERLAY_WIDTH)
        self.setMinimumHeight(120)
        self.setMaximumHeight(350)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        self._log_lines = []
        self._fade_anim = None
        self._compact = is_compact_enabled()

        self._build()
        self._apply_compact()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(500)
        self._refresh_timer.timeout.connect(self._refresh)

        communicate.executor_paused.connect(self._on_state_changed)
        communicate.task.connect(self._on_task)
        communicate.task_done.connect(self._on_task_done)
        communicate.notification.connect(self._on_notification)
        communicate.capture_error.connect(self._on_capture_error)
        signal = getattr(communicate, 'op_log', None)
        if signal is not None:
            signal.connect(self.append_log)

        try:
            from qfluentwidgets import qconfig

            qconfig.themeColorChanged.connect(self._on_theme_color_changed)
        except Exception as e:
            logger.debug(f'监听主题色失败（不影响使用）: {e}')

        self._apply_style()
        self._position_bottom_left()

    # ── 构建 ──────────────────────────────────────────────────────────

    def _build(self):
        self._container = QWidget(self)
        self._container.setObjectName("overlayContainer")

        layout = QVBoxLayout(self._container)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN - 4,
                                  PAGE_MARGIN, PAGE_MARGIN - 4)
        layout.setSpacing(BLOCK_SPACING)

        # ── 第一行：应用名 + 状态 pill + 时钟 ──
        header = QHBoxLayout()
        header.setSpacing(ROW_SPACING * 2)

        self._app_label = QLabel(_app_name())
        self._app_label.setObjectName("overlayApp")
        header.addWidget(self._app_label)

        self._pill = QLabel("空闲")
        self._pill.setObjectName("overlayPill")
        self._pill.setAlignment(Qt.AlignCenter)
        header.addWidget(self._pill)

        header.addStretch(1)

        clock_icon = _icon('DATE_TIME')
        if clock_icon is not None:
            header.addWidget(clock_icon, 0, Qt.AlignVCenter)

        self._time_label = QLabel("")
        self._time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self._time_label)

        layout.addLayout(header)

        # ── 第二行：触发器数量 + 当前任务（紧凑形态隐藏）──
        self._meta_row = QWidget()
        meta = QHBoxLayout(self._meta_row)
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(ROW_SPACING)

        trigger_icon = _icon('SYNC')
        if trigger_icon is not None:
            meta.addWidget(trigger_icon, 0, Qt.AlignVCenter)

        self._trigger_label = QLabel("触发器 0")
        meta.addWidget(self._trigger_label)

        meta.addSpacing(BLOCK_SPACING * 2)

        task_icon = _icon('TAG')
        if task_icon is not None:
            meta.addWidget(task_icon, 0, Qt.AlignVCenter)

        self._task_label = QLabel("当前任务 空闲")
        meta.addWidget(self._task_label)

        meta.addStretch(1)
        layout.addWidget(self._meta_row)

        # ── 分隔线 ──
        self._separator = QWidget()
        self._separator.setFixedHeight(1)
        layout.addWidget(self._separator)

        # ── 日志标题行 ──
        self._log_header_row = QWidget()
        log_header = QHBoxLayout(self._log_header_row)
        log_header.setContentsMargins(0, 0, 0, 0)
        log_header.setSpacing(ROW_SPACING)

        log_icon = _icon('HISTORY', size=13)
        if log_icon is not None:
            log_header.addWidget(log_icon, 0, Qt.AlignVCenter)

        self._log_header = QLabel("实时日志")
        log_header.addWidget(self._log_header)
        log_header.addStretch(1)

        self._uptime_label = QLabel("")
        self._uptime_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        log_header.addWidget(self._uptime_label)

        layout.addWidget(self._log_header_row)

        # ── 日志正文 ──
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._log_text.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._log_text.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 文档自带 4px 边距，会让"滚到底"停在半行上 —— 去掉它，整行对齐
        self._log_text.document().setDocumentMargin(0)
        self._log_text.setMaximumHeight(LOG_MAX_HEIGHT)
        layout.addWidget(self._log_text)

        # ── 紧凑形态专用行（与上面互斥）──
        self._compact_row = QWidget()
        compact = QHBoxLayout(self._compact_row)
        compact.setContentsMargins(0, 0, 0, 0)
        compact.setSpacing(ROW_SPACING)

        self._compact_task = QLabel("空闲")
        compact.addWidget(self._compact_task)
        compact.addStretch(1)

        self._compact_uptime = QLabel("")
        self._compact_uptime.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        compact.addWidget(self._compact_uptime)
        layout.addWidget(self._compact_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._container)

        self._container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    def _apply_compact(self):
        """按 _compact 切换两种形态的可见性。"""
        expanded = not self._compact
        for widget in (self._meta_row, self._separator,
                       self._log_header_row, self._log_text):
            widget.setVisible(expanded)
        self._compact_row.setVisible(self._compact)
        if self._compact:
            self.setMinimumHeight(44)
            self.setMaximumHeight(90)
        else:
            self.setMinimumHeight(120)
            self.setMaximumHeight(350)
        self._position_bottom_left()

    def set_compact(self, compact):
        self._compact = bool(compact)
        self._apply_compact()
        self._refresh()
        return self._compact

    def _position_bottom_left(self):
        screen = self.screen()
        if screen:
            geo = screen.availableGeometry()
            self.adjustSize()
            self.move(geo.left() + 12, geo.bottom() - self.height() - 12)

    # ── 淡入淡出 ──────────────────────────────────────────────────────

    def _fade(self, start, end, on_done=None):
        try:
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(self.FADE_MS)
            anim.setStartValue(float(start))
            anim.setEndValue(float(end))
            anim.setEasingCurve(QEasingCurve.OutCubic)
            if on_done is not None:
                anim.finished.connect(on_done)
            self._fade_anim = anim
            anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        except Exception as e:
            logger.debug(f'淡入淡出失败（忽略）: {e}')
            if on_done is not None:
                on_done()

    # ── 显隐 ──────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_style()
        self._apply_compact()
        self._refresh()
        self._refresh_timer.start()
        # 先置 1：万一动画没跑起来，窗口仍然是可见的（不会被停在 0 透明度）
        self.setWindowOpacity(1.0)
        # 有些平台不支持 windowOpacity（会是 no-op），动画结束后再兜一次底
        self._fade(0.0, 1.0, on_done=lambda: self.setWindowOpacity(1.0))
        self.visibility_changed.emit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._refresh_timer.stop()
        self.visibility_changed.emit(False)

    # ── 日志 ──────────────────────────────────────────────────────────

    def _on_state_changed(self, *_args):
        self._refresh()

    def _on_task(self, task):
        if task is None or not getattr(task, 'running', False):
            return
        _emit(f"开始任务: {self._task_name(task)}")

    def _on_task_done(self, task):
        if task is None:
            return
        _emit(f"任务完成: {self._task_name(task)}")

    def _on_notification(self, message, title=None, error=False, tray=False,
                         show_tab=None, params=None, images=None):
        if not error or not message:
            return
        _emit(f"错误: {message}")

    def _on_capture_error(self):
        _emit("截图失败，请检查游戏窗口是否选中")

    @staticmethod
    def _task_name(task):
        return getattr(task, 'cn_name', None) or getattr(task, 'name', str(task))

    @staticmethod
    def _is_error(message):
        return any(word in message for word in ERROR_KEYWORDS)

    def _render_log(self):
        """日志渲染：时间戳弱化、正文白字、错误行左侧红条。

        QTextEdit 只有富文本能一行一色，所以拼 HTML；转义 + 保住空格。
        """
        parts = []
        for line in self._log_lines:
            safe = html.escape(line)
            # HTML 会把连续空格压成一个，这里补成 &nbsp; 保住排版
            safe = re.sub(r' {2,}', lambda m: '&nbsp;' * len(m.group(0)), safe)

            match = _TIMESTAMP_RE.match(safe)
            if match:
                stamp, gap, body = match.groups()
                gap = '&nbsp;' * len(gap)
                head = f'<span style="color:{TIME_TEXT_COLOR};">{stamp}</span>{gap}'
            else:
                body = safe
                head = ''

            if self._is_error(line):
                # 左侧红条用半格方块近似（QTextEdit 不支持 border-left）
                bar = f'<span style="color:{ERROR_BAR_COLOR};">▍</span>'
                body = f'<span style="color:{ERROR_BAR_COLOR};">{body}</span>'
            else:
                bar = ''
                body = f'<span style="color:{LOG_TEXT_COLOR};">{body}</span>'

            parts.append(f'{bar}{head}{body}')

        self._log_text.setHtml('<br>'.join(parts))
        scrollbar = self._log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def append_log(self, message):
        if not message:
            return
        self._log_lines.append(str(message))
        if len(self._log_lines) > self.MAX_LOG_LINES:
            self._log_lines = self._log_lines[-self.MAX_LOG_LINES:]
        self._render_log()

    def _refresh(self):
        try:
            now = datetime.now().strftime("%H:%M:%S")
            up = uptime_text()
            self._time_label.setText(now)
            self._uptime_label.setText(up)
            self._compact_uptime.setText(up)

            executor = getattr(og, 'executor', None)
            if executor is None:
                self._pill.setText("空闲")
                self._compact_task.setText("空闲")
                return

            task = onetime_task(executor)
            if task is not None and getattr(task, 'enabled', False):
                name = self._task_name(task)
                running = True
            elif not executor.paused:
                name = "运行中"
                running = True
            else:
                name = "空闲"
                running = False

            self._task_label.setText(f"当前任务 {name}")
            self._compact_task.setText(name)
            self._pill.setText("运行中" if running else "空闲")
            self._restyle_pill(running)

            count = executor.active_trigger_task_count()
            self._trigger_label.setText(f"触发器 {count}")
        except Exception as e:
            logger.debug(f"StatusOverlay refresh error: {e}")

    # ── 样式 ──────────────────────────────────────────────────────────

    def _on_theme_color_changed(self, _color=None):
        logger.info('主题色已变，悬浮窗跟着刷新')
        self._apply_style()
        self._render_log()

    def _restyle_pill(self, running):
        accent = theme_color()
        accent_text = _boost(accent, ACCENT_TEXT_BOOST)
        color = accent_text.name() if running else 'rgba(255,255,255,150)'
        fill = _rgba(accent, 46) if running else 'rgba(255,255,255,18)'
        border = _rgba(accent, 110) if running else 'rgba(255,255,255,40)'
        self._pill.setStyleSheet(
            f"color: {color}; background-color: {fill};"
            f" border: 1px solid {border}; border-radius: 7px;"
            f" padding: 1px 8px; font: 600 {FONT_CAPTION} {font_family_css()};")

    def _apply_style(self):
        """配色/字体：界面元素用主题色，日志正文白字、错误红字。"""
        accent = theme_color()
        fonts = font_family_css()
        accent_text = _boost(accent, ACCENT_TEXT_BOOST)

        palette = self._log_text.viewport().palette()
        palette.setColor(QPalette.ColorRole.Base,
                         QColor(80, 80, 80, LOG_ALPHA))
        palette.setColor(QPalette.ColorRole.Text, QColor(LOG_TEXT_COLOR))
        self._log_text.viewport().setPalette(palette)
        self._log_text.viewport().setAutoFillBackground(True)
        self._log_text.setStyleSheet(f"""
            background-color: rgba(80, 80, 80, {LOG_ALPHA});
            color: {LOG_TEXT_COLOR};
            border: none;
            border-radius: {RADIUS_INNER}px;
            font: 500 {FONT_LOG} {fonts};
            padding: {ROW_SPACING}px {ROW_SPACING + 2}px;
        """)

        # 外框：中性深色填充 + 主题色描边；顶部一点点主题色渐变
        self._container.setStyleSheet(f"""
            #overlayContainer {{
                background-color: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {_rgba(accent, CONTAINER_ALPHA + 22)},
                    stop:0.35 rgba(50, 50, 60, {CONTAINER_ALPHA}),
                    stop:1 rgba(50, 50, 60, {CONTAINER_ALPHA}));
                border: 1px solid {_rgba(accent, 70)};
                border-radius: {RADIUS_OUTER}px;
            }}
        """)

        self._app_label.setStyleSheet(
            f"color: {accent_text.name()};"
            f"font: 600 {FONT_TITLE} {fonts}; padding: 0;")
        self._time_label.setStyleSheet(
            f"color: rgba(255,255,255,190);"
            f"font: 500 {FONT_BODY} {fonts}; padding: 0;")
        self._trigger_label.setStyleSheet(
            f"color: rgba(255,255,255,205);"
            f"font: 500 {FONT_BODY} {fonts}; padding: 0;")
        self._task_label.setStyleSheet(
            f"color: rgba(255,255,255,235);"
            f"font: 500 {FONT_BODY} {fonts}; padding: 0;")
        self._separator.setStyleSheet(
            f"background-color: {_rgba(accent, 90)};")
        self._log_header.setStyleSheet(
            f"color: {_rgba(accent_text, 215)};"
            f"font: 600 {FONT_CAPTION} {fonts}; padding: 0;")
        self._uptime_label.setStyleSheet(
            f"color: rgba(255,255,255,160);"
            f"font: 500 {FONT_CAPTION} {fonts}; padding: 0;")
        self._compact_task.setStyleSheet(
            f"color: rgba(255,255,255,235);"
            f"font: 500 {FONT_BODY} {fonts}; padding: 0;")
        self._compact_uptime.setStyleSheet(
            f"color: rgba(255,255,255,160);"
            f"font: 500 {FONT_CAPTION} {fonts}; padding: 0;")

        running = self._pill.text() == "运行中"
        self._restyle_pill(running)


# ── 开关（挂在「截图方式 → 开发工具」卡片里）────────────────────────────

def is_overlay_enabled():
    from okunified.gui import home_state

    return bool(home_state.load_home_state().get('overlay_enabled'))


def is_compact_enabled():
    from okunified.gui import home_state

    return bool(home_state.load_home_state().get('overlay_compact'))


def set_overlay_enabled(enabled):
    from okunified.gui import home_state

    overlay = get_overlay()
    if enabled:
        overlay.setWindowOpacity(0.0)
        overlay.show()
        overlay.raise_()
    else:
        overlay.hide()
    home_state.save_home_state(overlay_enabled=bool(enabled))
    return overlay.isVisible()


def set_compact_enabled(enabled):
    from okunified.gui import home_state

    overlay = get_overlay()
    overlay.set_compact(enabled)
    home_state.save_home_state(overlay_compact=bool(enabled))
    return overlay._compact


def install_switch_into_debug_card(start_tab):
    """把「悬浮窗」和「紧凑模式」两个开关插进框架「开发工具」卡片。

    框架那卡片本来就有个 overlay_switch（启用/禁用标记框，控制它自己画的
    检测框）；我们的悬浮窗是另一回事（状态/日志面板），所以并排、各自独立。
    """
    from qfluentwidgets import SwitchButton

    layout = getattr(start_tab, 'debug_layout', None)
    if layout is None:
        logger.warning('找不到 debug_layout，跳过悬浮窗开关')
        return None

    for i in range(layout.count()):
        widget = layout.itemAt(i).widget()
        if isinstance(widget, SwitchButton) and getattr(
                widget, '_ok_unified_overlay', False):
            return widget          # 已经插过了

    switch = SwitchButton()
    switch.setOnText('显示悬浮窗')
    switch.setOffText('隐藏悬浮窗')
    switch.setToolTip('屏幕左下角显示当前任务、触发器数量和实时中文日志')
    switch._ok_unified_overlay = True
    switch.setChecked(is_overlay_enabled())
    switch.checkedChanged.connect(_on_switch_toggled)

    # 末尾是框架 addStretch(1) 留下的弹簧，插在它前面 = 紧挨标记框开关
    insert_at = max(0, layout.count() - 1)
    layout.insertWidget(insert_at, switch)

    compact = SwitchButton()
    compact.setOnText('紧凑模式')
    compact.setOffText('紧凑模式')
    compact.setToolTip('只显示当前任务和运行时长，隐藏日志区')
    compact._ok_unified_overlay = True
    compact.setChecked(is_compact_enabled())
    compact.checkedChanged.connect(_on_compact_toggled)
    layout.insertWidget(insert_at + 1, compact)

    logger.info('已把「悬浮窗 / 紧凑模式」开关加入「开发工具」卡片')
    return switch


def _on_switch_toggled(checked):
    try:
        set_overlay_enabled(checked)
        logger.info(f'悬浮窗: {"开" if checked else "关"}')
    except Exception as e:
        logger.error(f'切换悬浮窗失败: {e}', e)


def _on_compact_toggled(checked):
    try:
        set_compact_enabled(checked)
        logger.info(f'紧凑模式: {"开" if checked else "关"}')
    except Exception as e:
        logger.error(f'切换紧凑模式失败: {e}', e)
