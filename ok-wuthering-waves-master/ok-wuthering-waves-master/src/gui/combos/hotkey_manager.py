"""全局快捷键管理器：Win32 RegisterHotKey + Qt nativeEvent 捕获 + 冲突探测。

- id 从 1000 起分配，避开 StartCard(999) / DebugTab(1,2)。
- 系统占用检测 = 试注册（RegisterHotKey 失败即被占用，含 Win+D 等系统热键）。
- 通过 QApplication.nativeEventFilter 捕获 WM_HOTKEY。
"""

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal
from PySide6.QtWidgets import QApplication

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

_MOD_MAP = {
    'CTRL': MOD_CONTROL,
    'CONTROL': MOD_CONTROL,
    'ALT': MOD_ALT,
    'SHIFT': MOD_SHIFT,
    'WIN': MOD_WIN,
    'META': MOD_WIN,
}

_VK_MAP = {
    '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
    '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    'SPACE': 0x20, 'TAB': 0x09, 'ENTER': 0x0D, 'RETURN': 0x0D,
    'ESC': 0x1B, 'ESCAPE': 0x1B,
    'LEFT': 0x25, 'UP': 0x26, 'RIGHT': 0x27, 'DOWN': 0x28,
    'HOME': 0x24, 'END': 0x23, 'PAGEUP': 0x21, 'PAGEDOWN': 0x22,
    'DELETE': 0x2E, 'DEL': 0x2E, 'INSERT': 0x2D, 'BACKSPACE': 0x08,
    'CAPSLOCK': 0x14, 'NUMLOCK': 0x90, 'SCROLLLOCK': 0x91,
    'PLUS': 0xBB, 'MINUS': 0xBD, 'COMMA': 0xBC, 'PERIOD': 0xBE,
    'SLASH': 0xBF, 'BACKSLASH': 0xDC, 'SEMICOLON': 0xBA, 'QUOTE': 0xDE,
    'LBRACKET': 0xDB, 'RBRACKET': 0xDD, 'GRAVE': 0xC0,
}


def parse_hotkey(hotkey: str):
    """'Ctrl+1' / 'Alt+X' -> (modifiers, vk)；非法返回 (None, None)。"""
    if not hotkey:
        return None, None
    parts = [p.strip() for p in hotkey.split('+')]
    if not parts:
        return None, None
    mods = 0
    for part in parts[:-1]:
        m = _MOD_MAP.get(part.upper())
        if m is None:
            return None, None
        mods |= m
    key = parts[-1].upper()
    if len(key) == 1 and key.isalpha():
        vk = ord(key)
    elif len(key) == 1 and key.isdigit():
        vk = 0x30 + int(key)
    elif key.startswith('F') and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x6F + int(key[1:])
    else:
        vk = _VK_MAP.get(key)
    if vk is None:
        return None, None
    return mods, vk


def normalize_hotkey(hotkey: str) -> str:
    """标准化显示：'ctrl+1' -> 'Ctrl+1'；非法返回原串。"""
    mods, vk = parse_hotkey(hotkey)
    if vk is None:
        return hotkey
    names = []
    for name, flag in (('Ctrl', MOD_CONTROL), ('Alt', MOD_ALT),
                       ('Shift', MOD_SHIFT), ('Win', MOD_WIN)):
        if mods & flag:
            names.append(name)
    if 0x30 <= vk <= 0x39:
        names.append(str(vk - 0x30))
    elif 0x41 <= vk <= 0x5A:
        names.append(chr(vk))
    elif 0x70 <= vk <= 0x87:
        names.append(f'F{vk - 0x6F}')
    else:
        for name, code in _VK_MAP.items():
            if code == vk:
                names.append(name.title())
                break
        else:
            return hotkey
    return '+'.join(names)


class _HotkeySignals(QObject):
    """独立信号载体（QAbstractNativeEventFilter 不是 QObject）。"""
    hotkey_triggered = Signal(str)   # combo_id
    hotkey_lost = Signal(str)        # combo_id


class HotkeyManager(QAbstractNativeEventFilter):
    """全局热键注册 / 触发 / 冲突探测。"""

    def __init__(self, parent=None):
        super().__init__()
        self.signals = _HotkeySignals(parent)
        self._next_id = 1000
        self._by_combo_id = {}   # combo_id -> (hotkey_str, hk_id)
        self._by_hk_id = {}      # hk_id -> combo_id
        self._filter_installed = False

    def _install_filter(self):
        if not self._filter_installed:
            QApplication.instance().installNativeEventFilter(self)
            self._filter_installed = True

    def register(self, combo_id: str, hotkey: str) -> str:
        """注册热键；返回空串表示成功，否则返回冲突原因。"""
        self.unregister(combo_id)
        mods, vk = parse_hotkey(hotkey)
        if vk is None:
            return f'快捷键格式无效: {hotkey}'
        hk_id = self._next_id
        self._next_id += 1
        ok = ctypes.windll.user32.RegisterHotKey(None, hk_id, mods, vk)
        if not ok:
            return f'快捷键 {normalize_hotkey(hotkey)} 已被系统或其他程序占用'
        self._by_combo_id[combo_id] = (normalize_hotkey(hotkey), hk_id)
        self._by_hk_id[hk_id] = combo_id
        self._install_filter()
        return ''

    def unregister(self, combo_id: str):
        entry = self._by_combo_id.pop(combo_id, None)
        if entry is None:
            return
        _hk_id = entry[1]
        ctypes.windll.user32.UnregisterHotKey(None, _hk_id)
        self._by_hk_id.pop(_hk_id, None)

    def unregister_all(self):
        for combo_id in list(self._by_combo_id):
            self.unregister(combo_id)

    def is_available(self, hotkey: str) -> bool:
        """试注册探测是否被占用（注册后立即注销）。"""
        mods, vk = parse_hotkey(hotkey)
        if vk is None:
            return False
        hk_id = self._next_id
        self._next_id += 1
        ok = ctypes.windll.user32.RegisterHotKey(None, hk_id, mods, vk)
        if ok:
            ctypes.windll.user32.UnregisterHotKey(None, hk_id)
        return bool(ok)

    def registered_hotkeys(self) -> dict:
        """combo_id -> hotkey_str"""
        return {cid: entry[0] for cid, entry in self._by_combo_id.items()}

    def nativeEventFilter(self, event_type, message):
        if event_type == 'windows_generic_MSG' or event_type == 'windows_dispatcher_MSG':
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                hk_id = msg.wParam & 0xFFFF
                combo_id = self._by_hk_id.get(hk_id)
                if combo_id:
                    self.signals.hotkey_triggered.emit(combo_id)
                    return True, 0
        return False, 0


_hotkey_manager = None


def get_hotkey_manager() -> HotkeyManager:
    global _hotkey_manager
    if _hotkey_manager is None:
        _hotkey_manager = HotkeyManager()
    return _hotkey_manager
