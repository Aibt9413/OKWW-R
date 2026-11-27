"""
自定义作用域：手动绑定任意正在运行的窗口。

框架自带的窗口选择（「截图方式」页）只能列出"符合游戏配置的 exe / 窗口类"的窗口。
有些游戏（比如原神，启动链里还有 miHoYo Launcher）匹配不上，或者你想让启动器
去操作一个完全不相干的窗口，这时就需要一个"自定义作用域"：
把当前所有可见窗口列出来，你点哪个就绑哪个。

绑定的内容写进 device_manager：
    windows_capture_config['title' / 'exe' / 'hwnd_class']
    config['selected_hwnd' / 'selected_exe' / 'pc_full_path']
并按游戏记到 configs/home.json，切走再切回来仍然生效。
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem)

from qfluentwidgets import (MessageBoxBase, SubtitleLabel, StrongBodyLabel, CaptionLabel,
                            BodyLabel, PushButton, PrimaryPushButton, LineEdit)

from ok import Logger

logger = Logger.get_logger(__name__)


# ── 枚举 ──────────────────────────────────────────────────────────────

def list_windows(keyword=''):
    """列出当前所有可见的顶层窗口。

    注意：这里用的是 find_all_visible_windows（宽松），窗口被最小化也能列出来。
    但 框架 的 find_hwnd 有尺寸检查（width/height <= 10 直接跳过），
    最小化的窗口 GetClientRect 是 0x0，**采集不到画面**。
    所以下面会标出 minimized / usable，避免选了却不知道为什么没反应。
    """
    from ok.util.window import find_all_visible_windows

    try:
        import win32gui
    except ImportError:
        win32gui = None

    windows = []
    try:
        raw = find_all_visible_windows()
    except Exception as e:
        logger.error(f'枚举窗口失败: {e}', e)
        return windows

    keyword = (keyword or '').strip().lower()
    for entry in raw:
        hwnd, title, exe_name, exe_path = (list(entry) + ['', '', '', ''])[:4]
        class_name = ''
        rect = (0, 0, 0, 0)
        minimized = False
        if win32gui is not None:
            try:
                class_name = win32gui.GetClassName(hwnd)
                rect = win32gui.GetWindowRect(hwnd)
                minimized = bool(win32gui.IsIconic(hwnd))
            except Exception:
                pass
        width, height = max(0, rect[2] - rect[0]), max(0, rect[3] - rect[1])
        # 和 find_hwnd 的判定保持一致：<= 10 就会被跳过
        usable = (not minimized) and width > 10 and height > 10
        item = {
            'hwnd': hwnd,
            'title': title,
            'exe': exe_name,
            'path': exe_path,
            'class_name': class_name,
            'size': (width, height),
            'minimized': minimized,
            'usable': usable,
        }
        if keyword and keyword not in f'{title} {exe_name} {class_name}'.lower():
            continue
        windows.append(item)

    # 可用的排前面
    windows.sort(key=lambda w: (not w['usable'], not w['exe'],
                                (w['title'] or '').lower()))
    return windows


def ensure_window_usable(hwnd):
    """窗口被最小化的话尝试还原。返回 (是否可用, 说明)。

    实测：原神的反作弊会屏蔽外部窗口操作 —— ShowWindow / ShowWindowAsync /
    SetForegroundWindow 全部返回 0、IsIconic 依旧是 True。
    所以这里会**实际复查**，不能只看调用返回值就声称还原成功。
    """
    import time

    try:
        import win32con
        import win32gui
    except ImportError:
        return True, ''

    try:
        if not win32gui.IsWindow(hwnd):
            return False, '窗口已经不存在了'
        if not win32gui.IsIconic(hwnd):
            return True, ''
    except Exception as e:
        logger.warning(f'查询窗口状态失败: {e}')
        return True, ''

    def restored():
        try:
            return not win32gui.IsIconic(hwnd)
        except Exception:
            return True

    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.3)
        if restored():
            logger.info(f'窗口 {hwnd} 之前最小化，已还原')
            return True, '窗口之前是最小化的，已自动还原'
    except Exception as e:
        logger.warning(f'ShowWindow 还原失败: {e}')

    try:
        import ctypes
        ctypes.windll.user32.ShowWindowAsync(hwnd, win32con.SW_RESTORE)
        time.sleep(0.5)
        if restored():
            logger.info(f'窗口 {hwnd} 之前最小化，已异步还原')
            return True, '窗口之前是最小化的，已自动还原'
    except Exception as e:
        logger.warning(f'ShowWindowAsync 还原失败: {e}')

    logger.error(f'窗口 {hwnd} 处于最小化状态，且无法从外部还原'
                 '（原神的反作弊会屏蔽外部窗口操作）。'
                 '请手动在任务栏点开游戏窗口，再重试。')
    return False, '窗口是最小化的，而且无法自动还原 —— 请手动把游戏窗口还原'


# ── 绑定 ──────────────────────────────────────────────────────────────

def current_binding():
    """当前绑定，返回一段可读文字。"""
    from ok import og
    from okunified.gui import home_state
    from okunified.gui.GameSwitcher import game_switcher

    # ⚠ 只认我们自己在「选择窗口…」里记下的绑定，**不能**读
    # device_manager.config['selected_hwnd'] —— 框架会自己把它设成
    # "当前首选窗口"的 hwnd（DeviceManager.py:460 的 select_hwnd），
    # 那样就会把框架自动匹配出来的窗口误报成"你手动绑定的"。
    game_key = game_switcher.current_game or ''
    bound = (home_state.load_home_state().get('custom_windows') or {}).get(game_key)
    if not bound:
        return '未手动绑定（按游戏配置的 exe / 窗口类自动匹配）'

    parts = []
    if bound.get('title'):
        parts.append(f'标题: {bound["title"]}')
    if bound.get('exe'):
        parts.append(f'exe: {bound["exe"]}')
    hwnd = int(bound.get('hwnd') or 0)
    if hwnd:
        parts.append(f'hwnd: {hwnd}')

    # 如果这个窗口当前是最小化的，直接说清楚为什么连不上
    if hwnd:
        try:
            import win32gui
            if win32gui.IsWindow(hwnd) and win32gui.IsIconic(hwnd):
                parts.append('⚠ 窗口已最小化，请还原窗口后重试')
        except Exception:
            pass
    return '　'.join(parts)


def bind_window(window, game_key=None):
    """把选中的窗口绑成采集目标。"""
    from ok import og
    from okunified.gui import home_state

    manager = getattr(og, 'device_manager', None)
    if manager is None:
        return False, 'device_manager 还没准备好'

    capture_config = manager.windows_capture_config
    if capture_config is None:
        return False, '当前没有 windows 采集配置'

    # 最小化的窗口采集不到画面，顺手还原它
    _, restore_note = ensure_window_usable(window.get('hwnd'))

    capture_config['title'] = window.get('title') or None
    if window.get('exe'):
        capture_config['exe'] = [window['exe']]
    if window.get('class_name'):
        capture_config['hwnd_class'] = window['class_name']

    manager.config['selected_hwnd'] = int(window.get('hwnd') or 0)
    manager.config['selected_exe'] = window.get('exe') or ''
    # 注意：**不要**写 config['pc_full_path']。
    # 那是"游戏启动路径"，StartController 会拿它去 execute；
    # 自定义作用域只负责"采集哪个窗口"，写进去会让启动器去启动被绑定窗口的进程
    # —— 之前就出过把 python.exe 当游戏启动的事故。
    try:
        manager.config.save_file()
    except Exception as e:
        logger.warning(f'保存设备选择失败: {e}')

    # 按游戏记住，切走再切回来还生效
    if game_key is None:
        from okunified.gui.GameSwitcher import game_switcher
        game_key = game_switcher.current_game
    if game_key:
        state = home_state.load_home_state()
        custom = dict(state.get('custom_windows') or {})
        custom[game_key] = {
            'title': window.get('title') or '',
            'exe': window.get('exe') or '',
            'path': window.get('path') or '',
            'class_name': window.get('class_name') or '',
            'hwnd': int(window.get('hwnd') or 0),
        }
        home_state.save_home_state(custom_windows=custom)

    logger.info(f'自定义作用域已绑定: {window.get("title")!r} '
                f'exe={window.get("exe")} hwnd={window.get("hwnd")}')

    try:
        manager.refresh()
    except Exception as e:
        logger.warning(f'刷新设备失败: {e}')
    message = f'已绑定到「{window.get("title")}」'
    if restore_note:
        message += f'（{restore_note}）'
    return True, message


def apply_custom_window(game_key):
    """切换游戏后恢复该游戏记住的自定义窗口。"""
    from okunified.gui import home_state

    window = (home_state.load_home_state().get('custom_windows') or {}).get(game_key)
    if not window:
        return False
    from ok import og
    manager = getattr(og, 'device_manager', None)
    if manager is None or manager.windows_capture_config is None:
        return False

    capture_config = manager.windows_capture_config
    if window.get('title'):
        capture_config['title'] = window['title']
    if window.get('exe'):
        capture_config['exe'] = [window['exe']]
    if window.get('class_name'):
        capture_config['hwnd_class'] = window['class_name']
    manager.config['selected_hwnd'] = int(window.get('hwnd') or 0)
    manager.config['selected_exe'] = window.get('exe') or ''
    # 同样不碰 pc_full_path（那是游戏启动路径）
    logger.info(f'已恢复自定义作用域 [{game_key}]: {window.get("title")!r}')
    return True


def clear_custom_window(game_key=None):
    from okunified.gui import home_state

    state = home_state.load_home_state()
    custom = dict(state.get('custom_windows') or {})
    if game_key:
        custom.pop(game_key, None)
    else:
        custom.clear()
    home_state.save_home_state(custom_windows=custom)

    from ok import og
    manager = getattr(og, 'device_manager', None)
    if manager is not None:
        manager.config['selected_hwnd'] = 0
        manager.config['selected_exe'] = ''
        try:
            manager.config.save_file()
        except Exception:
            pass

    # ⚠ 还要把 bind_window 改过的采集配置还原回去。
    # bind_window 直接改的是 device_manager.windows_capture_config
    # （就是 og.config['windows']）里的 title / exe / hwnd_class，
    # 只清 home.json 和 selected_hwnd 是不够的 —— 不还原的话，
    # 「恢复默认匹配」之后本次会话里启动器还会继续去找那个被绑的窗口
    # （比如绑到了启动器自己的窗口，它就会一直盯着 python.exe）。
    _restore_default_matching(game_key)
    return True, '已恢复默认匹配'


def _restore_default_matching(game_key):
    """把 windows 采集配置重新按当前游戏生成一遍，抵消 bind_window 的改动。"""
    from config import GAMES
    from okunified.gui.GameSwitcher import game_switcher

    game_key = game_key or game_switcher.current_game
    if not game_key:
        return False
    game_config = game_switcher.load_game_config(game_key)
    if not game_config:
        return False
    try:
        game_switcher._apply_config(GAMES.get(game_key, {}), game_config)
        game_switcher._rebuild_device_manager()
        logger.info(f'已还原 [{game_key}] 的默认窗口匹配规则')
        return True
    except Exception as e:
        logger.warning(f'还原默认匹配失败: {e}')
        return False


# ── 对话框 ────────────────────────────────────────────────────────────

class WindowPickerDialog(MessageBoxBase):
    """列出所有可见窗口，点一个就绑它。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.picked = None

        self.titleLabel = SubtitleLabel('选择窗口（自定义作用域）', self)
        self.viewLayout.addWidget(self.titleLabel)

        hint = CaptionLabel('列出当前所有可见窗口，不受游戏配置的 exe / 窗口类限制。'
                            '双击或选中后点「绑定此窗口」。')
        hint.setTextColor(QColor(130, 130, 130), QColor(130, 130, 130))
        self.viewLayout.addWidget(hint)

        top = QHBoxLayout()
        self.search = LineEdit()
        self.search.setPlaceholderText('按标题 / 进程名 / 窗口类过滤…')
        self.search.textChanged.connect(lambda *_: self.reload())
        top.addWidget(self.search, 1)
        refresh = PushButton('刷新')
        refresh.setFixedWidth(80)
        refresh.clicked.connect(self.reload)
        top.addWidget(refresh)
        self.viewLayout.addLayout(top)

        self.list = QListWidget(self)
        self.list.setMinimumHeight(360)
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        self.viewLayout.addWidget(self.list)

        self.current_label = CaptionLabel(f'当前绑定: {current_binding()}')
        self.current_label.setTextColor(QColor(130, 130, 130), QColor(130, 130, 130))
        self.viewLayout.addWidget(self.current_label)

        clear = PushButton('清除绑定')
        clear.clicked.connect(self._clear)
        self.viewLayout.addWidget(clear)

        self.yesButton.setText('绑定此窗口')
        self.cancelButton.setText('取消')
        self.widget.setMinimumWidth(760)
        self.reload()

    def reload(self):
        windows = list_windows(self.search.text())
        self.list.clear()
        unusable = 0
        for window in windows:
            size = window['size']
            if window['minimized']:
                flag = '⚠ 已最小化 —— 采集不到画面（框架 会当作窗口不存在）'
                unusable += 1
            elif not window['usable']:
                flag = f'⚠ 窗口太小 ({size[0]}x{size[1]}) —— 采集不到画面'
                unusable += 1
            else:
                flag = '可采集'
            text = (f"{window['title']}\n"
                    f"    {window['exe'] or '?'}　·　{window['class_name'] or '?'}"
                    f"　·　{size[0]}x{size[1]}　·　hwnd {window['hwnd']}\n"
                    f"    {flag}")
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, window)
            self.list.addItem(item)
        logger.info(f'自定义作用域：列出 {len(windows)} 个窗口，'
                    f'其中 {unusable} 个不可采集')

    def _selected(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def accept(self):
        """覆盖基类的 accept —— MessageBoxBase 的「确定」按钮走的是
        `__onYesButtonClicked → validate() → self.accept()`。
        之前我把处理逻辑写成 `_accept`，结果点按钮只是把对话框关掉、
        根本没绑定，表现就是"选了窗口但没生效"。"""
        window = self._selected()
        if window is None:
            self.current_label.setText('⚠ 请先在上面的列表里选中一个窗口')
            self.current_label.setTextColor(QColor(220, 80, 80), QColor(220, 80, 80))
            return  # 不关对话框

        ok, message = bind_window(window)
        if not ok:
            self.current_label.setText(f'⚠ {message}')
            self.current_label.setTextColor(QColor(220, 80, 80), QColor(220, 80, 80))
            logger.warning(f'自定义作用域绑定失败: {message}')
            return

        self.picked = window
        # 已绑定，但如果窗口不可采集（最小化），要明确告诉用户怎么办
        if not window.get('usable') or '无法自动还原' in message:
            self.current_label.setText(f'⚠ {message}')
            self.current_label.setTextColor(QColor(220, 80, 80), QColor(220, 80, 80))
            logger.warning(f'自定义作用域已绑定，但窗口不可采集: {message}')
        else:
            self.current_label.setText(f'当前绑定: {current_binding()}')
        super().accept()

    def _clear(self):
        clear_custom_window()
        self.current_label.setText(f'当前绑定: {current_binding()}')
        self.current_label.setTextColor(QColor(130, 130, 130), QColor(130, 130, 130))


def pick_window(parent=None):
    from ok import og

    window = parent
    if window is None:
        main_window = getattr(og, 'main_window', None)
        window = main_window.window() if main_window is not None else None
    dialog = WindowPickerDialog(window)
    if dialog.exec() and dialog.picked:
        return dialog.picked
    return None


# ── 挂到「截图方式」页顶部 ────────────────────────────────────────────

_card = None


def install_start_tab_card(main_window, home_tab=None):
    """把「自定义作用域」并进框架的「选择窗口」卡片底部。"""
    global _card
    if _card is not None:
        return

    start_tab = getattr(main_window, 'start_tab', None)
    if start_tab is None:
        logger.warning('找不到 start_tab，跳过自定义作用域控件')
        return

    # 并进框架的「选择窗口」卡片底部，而不是自己单开一张卡插在页首。
    # 它本来就是"窗口选择"的另一种方式，混在一起才顺；
    # 也不挂说明文字了 —— 按钮名已经说明一切，注意事项放 tooltip。
    container = getattr(start_tab, 'device_container', None)
    if container is None or getattr(container, 'widget', None) is None:
        logger.warning('找不到「选择窗口」卡片，跳过自定义作用域控件')
        return
    layout = container.widget.layout()
    if layout is None:
        logger.warning('「选择窗口」卡片没有布局，跳过自定义作用域控件')
        return

    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)

    status = BodyLabel(f'当前绑定: {current_binding()}')
    status.setToolTip('识别不到游戏窗口时，可以在这里手动绑定任意正在运行的窗口')
    row.addWidget(status)
    row.addStretch(1)

    button = PrimaryPushButton('选择窗口…')
    button.setFixedWidth(110)
    button.setToolTip(
        '手动绑定任意正在运行的窗口（不受游戏 exe / 窗口类限制）\n'
        '⚠ 游戏请用「窗口化」或「无边框窗口」运行：独占全屏下你一切出去，'
        'Windows 会把游戏窗口最小化，采集不到画面（表现为"一直已断开"），'
        '而且原神的反作弊会屏蔽外部还原窗口，只能自己手动还原')

    def on_click():
        picked = pick_window(main_window.window())
        status.setText(f'当前绑定: {current_binding()}')
        if picked:
            logger.info(f'自定义作用域: 已选中 {picked["title"]!r}')

    button.clicked.connect(on_click)
    row.addWidget(button)

    clear = PushButton('恢复默认匹配')
    clear.setFixedWidth(110)
    clear.setToolTip('清除手动绑定，回到按游戏配置（exe / 窗口类）自动匹配')

    def on_clear():
        clear_custom_window()
        status.setText(f'当前绑定: {current_binding()}')

    clear.clicked.connect(on_clear)
    row.addWidget(clear)

    layout.addLayout(row)
    _card = row
    logger.info('已把「自定义作用域」并入「选择窗口」卡片底部')


def create_scope_button(popover):
    """创建「选择窗口…（自定义作用域）」按钮，不负责插入布局。

    由 compat.install_connection_features 统一组装进「增强功能」区块，
    保证它和标记框 / 悬浮窗开关在同一块区域。
    """
    button = PrimaryPushButton('选择窗口…')
    button.setObjectName('okUnifiedScopeButton')
    button._ok_scope_btn = True
    button.setFixedWidth(96)
    button.setToolTip(
        '手动绑定任意正在运行的窗口（不受游戏 exe / 窗口类限制）\n'
        '⚠ 游戏请用「窗口化」或「无边框窗口」运行')

    def on_click():
        picked = pick_window(popover.window())
        if picked:
            logger.info(f'自定义作用域: 已选中 {picked["title"]!r}')
            try:
                popover.refresh()
            except Exception:
                pass

    button.clicked.connect(on_click)
    return button


def install_scope_into_popover(popover):
    """兼容旧调用：单独把作用域按钮插到窗口选择行（一般不再使用）。"""
    global _card
    layout = popover.layout()
    for i in range(layout.count()):
        item = layout.itemAt(i)
        w = item.widget() if item is not None else None
        if w is not None and getattr(w, '_ok_scope_btn', False):
            return w
    button = create_scope_button(popover)
    layout.addWidget(button)
    row = QHBoxLayout()
    row._ok_scope_popover = True
    _card = row
    return button
