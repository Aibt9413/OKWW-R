"""角色设置：把「游戏快捷键 / 角色配置 / 角色代码」并成一张卡，放进设置里。

背景：这三项原来各占一个侧边栏页面（前两个由框架按 ``show_at_tab=True``
生成，第三个是自定义 Tab）。单游戏 + 新 UI 下侧边栏太长，所以合并到
「设置」里，用 TabStrip 分三栏。

依赖前提（已在 games/wuthering/config.py 里改好）：
  - key_config_option / char_config_option 的 show_at_tab = False
  - custom_tabs 里不再注册 src.gui.CharacterCodeTab
"""
from PySide6.QtWidgets import QLabel, QStackedWidget, QVBoxLayout, QWidget

from ok import Logger, og
from ok.ui.qt.kit.tabs import TabStrip

logger = Logger.get_logger(__name__)

_section = None

_TABS = (
    ('hotkey', '游戏快捷键'),
    ('config', '角色配置'),
    ('code', '角色代码'),
)


class CharacterSettingsSection(QWidget):
    """一张卡里放三栏：快捷键 / 角色配置 / 角色代码。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pages = {}
        self._built = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.tabs = TabStrip()
        for key, text in _TABS:
            self.tabs.add_tab(key, text)
        self.tabs.current_changed.connect(self._show)
        layout.addWidget(self.tabs)

        self.stack = QStackedWidget()
        self.stack.setMinimumHeight(380)
        layout.addWidget(self.stack)

        self._build()

    # ── 构建 ──────────────────────────────────────────────────────────

    def _build(self):
        if self._built:
            return
        self._built = True
        for key, _text in _TABS:
            try:
                page = getattr(self, f'_build_{key}')()
            except Exception as e:
                logger.error(f'构建「{key}」失败: {e}', e)
                page = self._fallback(str(e))
            self._pages[key] = page
            self.stack.addWidget(page)
        self.tabs.set_current(_TABS[0][0])
        self._show(_TABS[0][0])

    def _fallback(self, message):
        label = QLabel(f'该页面加载失败：{message}')
        label.setWordWrap(True)
        return label

    @staticmethod
    def _config_pair(name):
        """按名字取 (Config, ConfigOption)。

        注意：GlobalConfigTab 的第一个参数是**每个配置项的 Config 对象**，
        不是 og.global_config 这个全局管理器（那样会报 no attribute
        'has_user_config'）。框架自己也是从 get_all_visible_configs() 里配对的。
        """
        for tab_name, config_obj, option in og.global_config.get_all_visible_configs():
            if tab_name == name or getattr(option, 'name', None) == name:
                return config_obj, option
        return None, None

    def _make_config_page(self, name):
        from ok.ui.qt.settings.GlobalConfigTab import GlobalConfigTab

        config_obj, option = self._config_pair(name)
        if option is None:
            raise RuntimeError(f'找不到配置项 {name}')
        return GlobalConfigTab(config_obj, option)

    def _build_hotkey(self):
        return self._make_config_page('Game Hotkey')

    def _build_config(self):
        return self._make_config_page('Character Config')

    def _build_code(self):
        import importlib

        module = importlib.import_module('src.gui.CharacterCodeTab')
        tab = module.CharacterCodeTab()
        executor = getattr(og, 'executor', None)
        if executor is not None:
            tab.executor = executor
        return tab

    # ── 行为 ──────────────────────────────────────────────────────────

    def _show(self, key):
        page = self._pages.get(key)
        if page is not None:
            self.stack.setCurrentWidget(page)

    def refresh(self):
        for page in self._pages.values():
            refresh = getattr(page, 'refresh', None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    pass


def install_character_settings(setting_tab):
    """把「角色设置」插到设置页「游戏」区块下面。"""
    global _section

    if setting_tab is None:
        return None

    # 3.0.1 的 setting_tab 可能是 LazyPage
    resolve = getattr(setting_tab, 'page', None)
    if callable(resolve):
        try:
            setting_tab = resolve()
        except Exception as e:
            logger.warning(f'展开 setting_tab 失败: {e}')
            return None

    if _section is not None:
        _section.refresh()
        return _section

    column = getattr(setting_tab, 'column', None)
    layout = column or setting_tab.layout()
    if layout is None:
        logger.warning('设置页没有可用布局，跳过「角色设置」')
        return None

    try:
        section = CharacterSettingsSection()
    except Exception as e:
        logger.error(f'创建「角色设置」失败: {e}', e)
        return None

    # 0 是「游戏」区块，1 就是它后面
    layout.insertWidget(1, section)
    _section = section
    logger.info('已安装「设置 → 角色设置」区块')
    return section
