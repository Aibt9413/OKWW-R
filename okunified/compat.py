"""
运行时兼容层 —— 不改 site-packages 的前提下做两件事：

1. 给 框架 的事件总线补一个 ``op_log`` 信号。
   原版 框架 的 EventBus 里没有它，而悬浮窗
   （okunified/gui/StatusOverlay.py）靠它接收中文操作日志。

2. 精简「关于」页：
   - 去掉「应用更新」卡片（pyappify 更新检查在本项目里一直是坏的，
     每次启动都会报 "PyAppify does not support checking for updates"）
   - 去掉顶部卡片（VersionCard）上的 GitHub / Download / Discord 等按钮
   - 去掉「其他项目」卡片上的 GitHub / Download 按钮，改成整卡点击跳转

做法是构造后处理 + 少量 monkey-patch，框架源码一行都不动。
"""
from ok import Logger

logger = Logger.get_logger(__name__)

_installed = False


# ── op_log 信号 ───────────────────────────────────────────────────────

def op_log(message):
    """发一条操作日志到悬浮窗。信号不存在时静默忽略。"""
    from datetime import datetime

    from ok.core.events import communicate

    signal = getattr(communicate, 'op_log', None)
    if signal is None:
        return
    signal.emit(f"{datetime.now().strftime('%H:%M')}  {message}")


def default_op_log(message):
    """给"没有游戏侧 op_log"的任务兜底。

    少数任务不继承游戏自己的基础任务类，拿不到插桩进去的 op_log：
      - soniccore 的 MouseResetTask(TriggerTask)
      - soniccore 的 DiagnosisTask 用的是框架自带 ok.task.DiagnosisTask(BaseTask)
    这里在实例上补一个同样的接口，保证 task.op_log(...) 恒可用。
    """
    op_log(message)


def _install_op_log():
    from ok.core.events import EventBus, EventSignal, communicate

    if hasattr(communicate, 'op_log'):
        return
    forward = getattr(communicate, '_forward', None)
    signal = EventSignal('op_log', forward('op_log') if forward else None)
    setattr(communicate, 'op_log', signal)
    if 'op_log' not in EventBus._event_names:
        EventBus._event_names = EventBus._event_names + ('op_log',)
    logger.info('已把 op_log 信号挂到 communicate')


# ── 「关于」页精简 ────────────────────────────────────────────────────

def _patch_version_card():
    """VersionCard：去掉右侧那一排 GitHub / Download / Discord… 按钮。"""
    from ok.ui.qt.about.LinksBar import LinksBar
    from ok.ui.qt.about.VersionCard import VersionCard

    original = VersionCard.__init__
    if getattr(original, '_ok_unified_patched', False):
        return

    def patched(self, config, icon, title, version, debug, parent=None):
        original(self, config, icon, title, version, debug, parent)
        for bar in self.findChildren(LinksBar):
            layout = getattr(self, 'hBoxLayout', None)
            if layout is not None:
                layout.removeWidget(bar)
            bar.setParent(None)
            bar.deleteLater()
        logger.info('已移除「关于」顶部卡片的下载/GitHub 等按钮')

    patched._ok_unified_patched = True
    VersionCard.__init__ = patched


def _patch_project_card():
    """ProjectCard：去掉 GitHub / Download 按钮，整卡点击跳转。"""
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QDesktopServices

    from ok.ui.qt.about.ProjectCard import ProjectCard

    original = ProjectCard.__init__
    if getattr(original, '_ok_unified_patched', False):
        return

    def patched(self, name, url, website=None, parent=None):
        original(self, name, url, website, parent)
        for attr in ('github_button', 'download_button'):
            button = getattr(self, attr, None)
            if button is not None:
                layout = getattr(self, 'hBoxLayout', None)
                if layout is not None:
                    layout.removeWidget(button)
                button.setParent(None)
                button.deleteLater()
                setattr(self, attr, None)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(url)

    patched._ok_unified_patched = True
    ProjectCard.__init__ = patched

    original_release = ProjectCard.mouseReleaseEvent

    def patched_release(self, event):
        original_release(self, event)
        if event.button() == Qt.LeftButton and getattr(self, 'url', None):
            QDesktopServices.openUrl(QUrl(self.url))

    patched_release._ok_unified_patched = True
    ProjectCard.mouseReleaseEvent = patched_release


def _patch_about_tab():
    """AboutTab：连卡片一起摘掉「应用更新」。"""
    from ok.ui.qt.about.AboutTab import AboutTab

    original = AboutTab.__init__
    if getattr(original, '_ok_unified_patched', False):
        return

    def patched(self, config, pyappify_module=None, exit_event=None):
        original(self, config, pyappify_module, exit_event)
        _strip_update_card(self)

    patched._ok_unified_patched = True
    AboutTab.__init__ = patched


def _strip_update_card(about_tab):
    from ok.ui.qt.widget.Card import Card

    card = getattr(about_tab, 'update_card', None)
    if card is None:
        return
    # 先置空，MainWindow 后面会检查 about_tab.update_card is not None
    about_tab.update_card = None

    wrapper = card
    for _ in range(4):
        if wrapper is None or isinstance(wrapper, Card):
            break
        wrapper = wrapper.parentWidget()

    if isinstance(wrapper, Card):
        layout = getattr(about_tab, 'vBoxLayout', None)
        if layout is not None:
            layout.removeWidget(wrapper)
        wrapper.setParent(None)
        wrapper.deleteLater()
    logger.info('已移除「关于」页的应用更新卡片')


# ── 模板 json 的编码 ──────────────────────────────────────────────────

def _patch_feature_set_encoding():
    """修正 框架 读模板 json 时的编码问题。

    ``ok/feature/FeatureSet.py`` 的 ``load_json()`` 是这么写的：

        with open(coco_json, 'r') as file:      # ← 没指定 encoding
            data = json.load(file)

    不指定 encoding 就用系统默认编码，中文 Windows 上是 GBK。
    原神的 ``assets/result.json`` 含 UTF-8 中文，于是：

        UnicodeDecodeError: 'gbk' codec can't decode byte 0xae ...

    这个异常发生在 ``FeatureSet.process_data()``，也就是**第一次做模板匹配**时，
    结果 AutoPick / AutoCombat / AutoDialog / AutoLogin 全部抛异常停掉——
    表现就是"自动对话等功能不生效"。

    换成显式 utf-8 读取，行为与原来完全一致。
    """
    import json

    import ok.feature.FeatureSet as feature_set

    original = getattr(feature_set, 'load_json', None)
    if original is None or getattr(original, '_ok_unified_patched', False):
        return

    def load_json(coco_json):
        with open(coco_json, 'r', encoding='utf-8') as file:
            data = json.load(file)
            for image in data['images']:
                image['file_name'] = feature_set.un_fk_label_studio_path(
                    image['file_name'])
            return data

    load_json._ok_unified_patched = True
    feature_set.load_json = load_json
    logger.info('已修正 FeatureSet.load_json 编码：改为显式 utf-8 '
                '（原本用系统默认 GBK 读模板 json，含中文就会崩）')


# ── 框架默认日志名 ────────────────────────────────────────────────────

def _patch_logger_name():
    """把框架的默认日志名从 ``框架`` 换成 ``SonicCore``。

    ``ok/util/logger.py::config_logger(config, name='框架')`` 用 name
    拼日志文件名，而 ``TaskExecutor`` 调用时只传了 config，于是日志永远叫
    ``logs/soniccore*.log``。这里接管默认值。

    注意 TaskExecutor 可能是 ``from ... import config_logger`` 直接绑定的，
    所以两处都要改。
    """
    import ok.util.logger as logger_module

    original = logger_module.config_logger
    if getattr(original, '_soniccore_patched', False):
        return

    def patched(config=None, name='SonicCore'):
        return original(config, name)

    patched._soniccore_patched = True
    logger_module.config_logger = patched

    try:
        import ok.task.TaskExecutor as task_executor
        if getattr(task_executor, 'config_logger', None) is original:
            task_executor.config_logger = patched
    except Exception as e:
        logger.debug(f'TaskExecutor.config_logger 改写跳过: {e}')

    logger.info('已把框架默认日志名改为 SonicCore')


# ── ONNX Runtime：自动补 DirectML ─────────────────────────────────────

def _patch_ort_dml():
    """让所有只传 CPU 的 InferenceSession 自动带上 DirectML。

    onnxocr 里是写死的 ``providers = ['CPUExecutionProvider']``，OCR 因此
    一直跑 CPU。这里包装 InferenceSession：遇到没指定 DML 的调用就插到最前，
    DML 建不起来（个别算子不支持）再回退到原 providers。
    """
    import onnxruntime as ort

    available = ort.get_available_providers()
    if 'DmlExecutionProvider' not in available:
        logger.info('未安装 DirectML provider，ONNX 继续用 CPU')
        return

    original = ort.InferenceSession
    if getattr(original, '_soniccore_dml', False):
        return

    def _has_dml(providers):
        for item in providers:
            name = item[0] if isinstance(item, (tuple, list)) else item
            if name == 'DmlExecutionProvider':
                return True
        return False

    def patched(path_or_bytes, sess_options=None, providers=None,
                provider_options=None, **kwargs):
        base = list(providers or ['CPUExecutionProvider'])
        if _has_dml(base):
            return original(path_or_bytes, sess_options=sess_options,
                            providers=base, provider_options=provider_options,
                            **kwargs)
        boosted = ['DmlExecutionProvider'] + base
        try:
            return original(path_or_bytes, sess_options=sess_options,
                            providers=boosted, provider_options=provider_options,
                            **kwargs)
        except Exception as e:
            logger.warning(f'DirectML 建 session 失败，回退 CPU: {e}')
            return original(path_or_bytes, sess_options=sess_options,
                            providers=base, provider_options=provider_options,
                            **kwargs)

    patched._soniccore_dml = True
    ort.InferenceSession = patched
    logger.info('已启用 ONNX Runtime DirectML 自动补全（OCR/检测统一走 GPU）')


# ── qfluentwidgets 主题对齐 ───────────────────────────────────────────

def _sync_widget_theme():
    """把 qfluentwidgets 主题配置固定到用户目录，并尊重用户在设置页的选择。

    反色根因（11-27 定位）：qconfig.file 默认是相对路径 ``config\\config.json``，
    相对于「当前工作目录」。SFX 每次解压到全新临时目录运行 → 配置文件每次都是
    全新的 → 用户的浅色/深色选择根本存不住；旧的强制 DARK 逻辑于是每次都生效，
    出现「浅色背景 + 白色文字」的反色。

    修复：
      1) 把 qconfig.file 指向固定的 AppData 目录（跨临时目录持久）。
      2) 不再强制 DARK —— 完全尊重 qconfig 里已经持久化的用户选择；
         首次（配置文件不存在）用 DARK，用户偏好深色。之后尊重用户选择。
    """
    global _theme_synced
    if _theme_synced:
        return
    try:
        import os
        from pathlib import Path
        from qfluentwidgets import Theme, setTheme, qconfig

        # 固定到用户目录，避免 SFX 新临时目录导致配置丢失
        cfg_path = Path(os.environ.get('APPDATA', os.path.expanduser('~'))) / \
            'SonicCore' / 'config.json'
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        first_run = not cfg_path.is_file()
        try:
            # qconfig.file 是代理属性，save() 实际用内部 _cfg.file，两处都要改
            qconfig.file = cfg_path
            if hasattr(qconfig, '_cfg'):
                qconfig._cfg.file = cfg_path
            if cfg_path.is_file():
                qconfig.load(cfg_path)
        except Exception as e:
            logger.debug(f'重定向 qconfig 失败: {e}')

        if first_run:
            # 首次：与框架默认浅色一致；显式 save() 生成配置文件作为"已初始化"标记
            qconfig.set(qconfig.themeMode, Theme.DARK, save=False)
            try:
                qconfig.save()
            except Exception as e:
                logger.debug(f'保存主题配置失败: {e}')
            logger.info('qfluentwidgets 主题首次设为 DARK（用户偏好深色）')
        # 之后：直接用 qconfig 里已持久化的值，不覆盖用户选择
        try:
            setTheme(qconfig.get(qconfig.themeMode))
        except Exception:
            pass
        _theme_synced = True
    except Exception as e:
        logger.warning(f'同步 qfluentwidgets 主题失败: {e}')


_theme_synced = False


# ── 隐藏 3.0.1 顶部运行栏 ──────────────────────────────────────────────

_run_bar_hidden = False


def hide_run_bar(retries=40):
    """隐藏 框架 顶部那条 RunBar（很显眼的「启动游戏 F9」）。

    单游戏场景下主页自己就有开始按钮，这条栏是重复信息。
    MainWindow 构造完成前 og.main_window 还是 None，所以带重试。
    """
    global _run_bar_hidden
    if _run_bar_hidden:
        return
    from ok import og

    main_window = getattr(og, 'main_window', None)
    bar = getattr(main_window, 'run_bar', None) if main_window is not None else None
    if bar is None:
        if retries > 0:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(250, lambda: hide_run_bar(retries - 1))
        else:
            logger.debug('未找到 run_bar，跳过隐藏')
        return
    try:
        bar.hide()
        _run_bar_hidden = True
        logger.info('已隐藏顶部运行栏（RunBar）')
    except Exception as e:
        logger.debug(f'隐藏 run_bar 失败: {e}')


# ── 主窗口尺寸夹取 ────────────────────────────────────────────────────

def fit_main_window(retries=20):
    """把主窗口夹回当前屏幕的可用区域内。

    3.0.1 会把上次的几何存进 ok_config 并在启动时恢复；换分辨率 / 改缩放后
    恢复出来的尺寸可能比屏幕还大（实测 1200x932 落在 1536x864 的屏上），
    表现就是窗口底部/右侧跑到屏幕外。
    """
    from ok import og

    main_window = getattr(og, 'main_window', None)
    if main_window is None:
        if retries > 0:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(250, lambda: fit_main_window(retries - 1))
        return False

    try:
        from PySide6.QtGui import QGuiApplication

        screen = main_window.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return False
        avail = screen.availableGeometry()
        geo = main_window.frameGeometry()

        margin = 16
        width = min(geo.width(), max(640, avail.width() - margin))
        height = min(geo.height(), max(480, avail.height() - margin))
        x = min(max(geo.x(), avail.left()), avail.right() - width + 1)
        y = min(max(geo.y(), avail.top()), avail.bottom() - height + 1)

        if (width, height, x, y) != (geo.width(), geo.height(), geo.x(), geo.y()):
            main_window.setGeometry(x, y, width, height)
            logger.info(f'主窗口已夹回屏幕内: {width}x{height} at ({x},{y}) '
                        f'(屏幕 {avail.width()}x{avail.height()})')
        return True
    except Exception as e:
        logger.debug(f'夹取主窗口尺寸失败: {e}')
        return False


# ── 侧边栏整理 ────────────────────────────────────────────────────────

def arrange_navigation(retries=20):
    """把「主页」提到侧边栏最顶部，并去掉一级分组标题（运行 / 游戏 / 开发）。

    3.0.1 的导航是按 section 分组的，自定义页默认落在 SECTION_GAME 末尾。
    这里把主页挪到 SECTION_RUN 的第一位，再把所有 section 的标题隐藏。
    """
    from ok import og
    from PySide6.QtCore import QCoreApplication

    main_window = getattr(og, 'main_window', None)
    if main_window is None:
        if retries > 0:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(250, lambda: arrange_navigation(retries - 1))
        return False

    nav = getattr(main_window, 'navigation', None)
    if nav is None:
        return False

    try:
        from ok.ui.qt.shell.nav_icons import nav_icon

        from okunified.gui.HomeTab import HomeTab

        pages = getattr(main_window, '_pages', {}) or {}
        home = next((p for p in pages.values() if isinstance(p, HomeTab)), None)
        if home is not None:
            key = home.objectName()
            title = QCoreApplication.translate('app', home.name)
            if nav.has_item(key):
                nav.remove_item(key)
            nav.add_item(key, title, nav_icon('grid'), 'run')
            box, box_layout, _header = nav._sections['run']
            # 0 是 section 标题，1 就是第一项 → 插到「任务」上面
            box_layout.insertWidget(1, nav.item(key))

        for _box, _layout, header in nav._sections.values():
            header.hide()

        # 主页永远是侧边栏第一项：把 run 分组挪到最顶部，并把主页放到 run 的第一位。
        # run 分组标题已在上面 hide，视觉上主页就是最顶一项。
        try:
            run_box = nav._sections['run'][0]
            sec_layout = getattr(nav, '_sections_layout', None)
            if sec_layout is not None:
                # insertWidget 到 0 会把 run 移到 stretch 之前的最顶；重复调用幂等。
                if sec_layout.indexOf(run_box) != 0:
                    sec_layout.removeWidget(run_box)
                    sec_layout.insertWidget(0, run_box)
        except Exception as e:
            logger.debug(f'调整 run 分组置顶失败: {e}')

        logger.info('侧边栏已整理：主页置顶、隐藏分组标题')
        return True
    except Exception as e:
        logger.error(f'整理侧边栏失败: {e}', e)
        return False


# ── 开发者模式 ────────────────────────────────────────────────────────

# (MainWindow 属性名, 内置图标名, 侧边栏文案)
_DEV_PAGES = (
    ('edit_task_tab', 'pen', 'Script'),
    ('template_tab', 'image', 'Templates'),
    ('diagnosis_page', 'pulse', 'Diagnosis'),
)


def apply_developer_mode(enabled, retries=20):
    """脚本 / 模板 / 诊断 默认隐藏，只有开发者模式开启时才进侧边栏。

    MainWindow 构造期间 og.main_window 还没赋值，所以带重试。
    """
    from ok import og

    main_window = getattr(og, 'main_window', None)
    if main_window is None:
        if retries > 0:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(250, lambda: apply_developer_mode(enabled, retries - 1))
        return False

    nav = getattr(main_window, 'navigation', None)
    if nav is None:
        return False

    try:
        from PySide6.QtCore import QCoreApplication

        from ok.ui.qt.shell.nav_icons import nav_icon

        for attr, icon, text in _DEV_PAGES:
            page = getattr(main_window, attr, None)
            if page is None:
                continue
            key = page.objectName()
            if enabled:
                if not nav.has_item(key):
                    nav.add_item(key, QCoreApplication.translate('MainWindow', text),
                                 nav_icon(icon), 'develop')
            elif nav.has_item(key):
                nav.remove_item(key)
        logger.info(f'开发者模式: {"开" if enabled else "关"} —— 脚本/模板/诊断'
                    f'{"已显示" if enabled else "已隐藏"}')
        return True
    except Exception as e:
        logger.error(f'切换开发者模式失败: {e}', e)
        return False


# ── 连接弹窗功能注入（3.0.1 适配）──────────────────────────────────────
#
# 悬浮窗 / 标记框开关、自定义作用域按钮原本挂在旧框架 2.0.6 的「截图方式」
# 页（main_window.start_tab.debug_layout / device_container）上。3.0.1 把这一页
# 改成了运行栏的连接弹窗（main_window.run_bar.popover），start_tab 不存在，
# 所以这些功能一直被跳过。这里按 3.0.1 的真实结构重新注入。

def install_connection_features(retries=20):
    """把悬浮窗/紧凑模式开关 + 自定义作用域按钮装进连接弹窗。

    ok-script 3.0.1:
      - main_window.run_bar.popover  → ConnectionPopover
      - popover.boxes_switch 所在行 = 标记框（Enable Boxes）开关那一行
      - popover.window_combo 所在行 = 游戏窗口选择那一行
    用 objectName 做幂等标记，重复调用不会重复插入。
    """
    from ok import og

    main_window = getattr(og, 'main_window', None)
    if main_window is None:
        if retries > 0:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(300, lambda: install_connection_features(retries - 1))
        return False

    run_bar = getattr(main_window, 'run_bar', None)
    popover = getattr(run_bar, 'popover', None) if run_bar is not None else None
    if popover is None:
        if retries > 0:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(300, lambda: install_connection_features(retries - 1))
        logger.debug('连接弹窗还不存在，稍后重试特色功能注入')
        return False

    # 每次打开弹窗都补一次注入：应对「链接游戏」后 UI 被重建、控件丢失的情况。
    # 用实例属性做标记，避免重复挂钩。
    if not getattr(popover, '_ok_install_hooked', False):
        try:
            _orig_show = popover.showEvent

            def _patched_show(event, _self=popover, _orig=_orig_show):
                try:
                    install_connection_features(retries=0)
                except Exception:
                    pass
                return _orig(event)

            popover.showEvent = _patched_show
            popover._ok_install_hooked = True
        except Exception as e:
            logger.debug(f'挂接弹窗显示钩子失败: {e}')

    ok = True

    # 把「标记框 / 显示悬浮窗 / 紧凑模式 / 选择窗口」组装成一个统一的增强功能
    # 区块，插在弹窗「CHOOSE INTERACTION」之后。三者挨在一起，不再分散。
    try:
        from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QFrame
        from qfluentwidgets import SwitchButton, StrongBodyLabel

        # 幂等：区块已存在就不再建
        if popover.findChild(QFrame, 'okUnifiedFeatureBlock') is not None:
            return True

        from okunified.gui.StatusOverlay import (
            is_compact_enabled, is_overlay_enabled,
            set_compact_enabled, set_overlay_enabled,
        )
        from okunified.gui.window_picker import create_scope_button

        block = QFrame(popover)
        block.setObjectName('okUnifiedFeatureBlock')
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(0, 4, 0, 0)
        block_layout.setSpacing(6)
        block_layout.addWidget(StrongBodyLabel('增强功能', block))

        # 第一行：标记框 + 显示悬浮窗 + 紧凑模式
        row = QHBoxLayout()
        row.setSpacing(10)

        boxes = SwitchButton(block)
        boxes.setObjectName('okUnifiedBoxesSwitch')
        boxes.setOnText('显示标记框')
        boxes.setOffText('隐藏标记框')
        boxes.setToolTip('在采集画面上叠加检测标记框（与框架自带开关等价）')
        def _set_boxes(checked):
            from ok import og as _og
            _og.app.set_overlay_setting('boxes', bool(checked))

        try:
            from ok import og as _og
            boxes.setChecked(bool(_og.app.overlay_state()['boxes']))
        except Exception:
            boxes.setChecked(False)
        boxes.checkedChanged.connect(_set_boxes)
        row.addWidget(boxes)

        overlay_switch = SwitchButton(block)
        overlay_switch.setObjectName('okUnifiedOverlaySwitch')
        overlay_switch.setOnText('显示悬浮窗')
        overlay_switch.setOffText('隐藏悬浮窗')
        overlay_switch.setToolTip('屏幕左下角显示当前任务、触发器数量和实时中文日志')
        overlay_switch.setChecked(is_overlay_enabled())
        overlay_switch.checkedChanged.connect(set_overlay_enabled)
        row.addWidget(overlay_switch)

        compact_switch = SwitchButton(block)
        compact_switch.setObjectName('okUnifiedCompactSwitch')
        compact_switch.setOnText('紧凑模式')
        compact_switch.setOffText('紧凑模式')
        compact_switch.setToolTip('只显示当前任务和运行时长，隐藏日志区')
        compact_switch.setChecked(is_compact_enabled())
        compact_switch.checkedChanged.connect(set_compact_enabled)
        row.addWidget(compact_switch)
        row.addStretch(1)
        block_layout.addLayout(row)

        # 第二行：自定义作用域
        scope_row = QHBoxLayout()
        scope_row.setSpacing(8)
        scope_row.addWidget(create_scope_button(popover))
        scope_row.addStretch(1)
        block_layout.addLayout(scope_row)

        # 插到弹窗主布局：优先放在框架「标记框(Enable Boxes)」那一行之前，
        # 让增强功能区块处在显眼位置；找不到就插到末尾。
        main_layout = popover.layout()
        insert_idx = main_layout.count()
        boxes_switch = getattr(popover, 'boxes_switch', None)
        if boxes_switch is not None:
            for i in range(main_layout.count()):
                item = main_layout.itemAt(i)
                sub = item.layout() if item is not None else None
                if sub is None:
                    continue
                for j in range(sub.count()):
                    w = sub.itemAt(j).widget()
                    if w is boxes_switch:
                        insert_idx = i
                        break
                if insert_idx != main_layout.count():
                    break
        main_layout.insertWidget(insert_idx, block)

        # 框架自带的英文 Enable Boxes 行现在与增强区块重复，隐藏它，
        # 只保留我们中文的「显示标记框」，两者状态本来就同步。
        if boxes_switch is not None:
            parent_row = boxes_switch.parent()
            hide_target = parent_row if parent_row is not None and parent_row is not popover else boxes_switch
            try:
                hide_target.hide()
            except Exception:
                pass

        logger.info('已把「标记框/悬浮窗/紧凑/作用域」组装成增强功能区块')
    except Exception as e:
        ok = False
        logger.error(f'组装增强功能区块失败: {e}', e)

    return ok


# ── 启动前合并游戏配置 ────────────────────────────────────────────────

# 只并这些键：任务/场景/设备/模板是「跑起来」必需的；
# 不动 version、links、about 这些启动器自己的展示配置。
_GAME_CONFIG_KEYS = (
    'onetime_tasks', 'trigger_tasks', 'scene', 'my_app',
    'template_matching', 'ocr', 'windows', 'windows_template',
    'global_configs', 'blur_area', 'coco_feature_folder',
)


def load_game_config(game_key='wuthering'):
    """把 ``games/<key>/config.py`` 并进启动器配置，必须在 ``OK(config)`` 之前调用。

    框架 的 ``TasksPage`` 在 MainWindow 构造时就根据
    executor 里的任务决定「有没有任务页」，建好之后补不进去。而启动器原本
    靠 GameSwitcher 在运行期切换游戏、再重建侧边栏——那套在 3.0.1 里没了。

    所以单游戏场景下最稳的做法是：启动前就把游戏配置并进来。
    """
    import importlib.util
    import os
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    game_dir = os.path.join(root, 'games', game_key)
    game_config_path = os.path.join(game_dir, 'config.py')
    # PyInstaller 把 --add-data 的目标一律当目录。早期构建脚本曾把目标写成
    # games/wuthering/config.py，生成 config.py/config.py 嵌套目录，导致这里
    # 找不到文件、整份任务配置被跳过、侧边栏功能全空。兼容该历史结构。
    if os.path.isdir(game_config_path):
        nested = os.path.join(game_config_path, 'config.py')
        if os.path.isfile(nested):
            logger.warning(f'游戏配置被打包成嵌套目录，已兼容读取: {nested}')
            game_config_path = nested
    if not os.path.isfile(game_config_path):
        logger.warning(f'游戏配置不存在，跳过合并: {game_config_path}')
        return False

    # 顺序很关键：游戏目录里也有一个 config.py，一旦先进 sys.path，
    # 下面的 import config 就会拿到游戏配置。所以先取启动器配置。
    if root not in sys.path:
        sys.path.insert(0, root)
    import config as launcher_module
    launcher_config = launcher_module.config

    if game_dir not in sys.path:
        sys.path.insert(0, game_dir)

    try:
        spec = importlib.util.spec_from_file_location(
            'soniccore_game_config', game_config_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        game_config = module.config
    except Exception as e:
        logger.error(f'加载游戏配置失败: {e}', e)
        return False

    merged = []
    for key in _GAME_CONFIG_KEYS:
        if key in game_config:
            launcher_config[key] = game_config[key]
            merged.append(key)

    # 游戏配置默认 use_openvino=True，但没装 openvino 时 OCR 初始化会直接抛错。
    # 以前这一步由 GameSwitcher 在切游戏时降级，现在启动路径绕过了它，这里补上。
    ocr = launcher_config.get('ocr') or {}
    params = ocr.get('params') or {}
    if params.get('use_openvino') and importlib.util.find_spec('openvino') is None:
        params['use_openvino'] = False
        logger.warning('未安装 openvino，OCR 已降级为 onnxruntime')
    # NPU 同样依赖 openvino，没装就没必要先试一遍再失败
    if params.get('use_npu') and importlib.util.find_spec('openvino') is None:
        params['use_npu'] = False
        logger.warning('未安装 openvino，已关闭 OCR 的 NPU 尝试')

    # 自定义页：启动器的 HomeTab + 游戏自己的（角色代码）
    tabs = list(launcher_config.get('custom_tabs') or [])
    for tab in (game_config.get('custom_tabs') or []):
        if tab not in tabs:
            tabs.append(tab)
    launcher_config['custom_tabs'] = tabs

    logger.info(
        f'已合并游戏配置 {game_key}: {merged}，'
        f'一次性任务 {len(launcher_config.get("onetime_tasks") or [])} 个，'
        f'触发器任务 {len(launcher_config.get("trigger_tasks") or [])} 个')
    return True


# ── 入口 ──────────────────────────────────────────────────────────────

def install():
    """在 OK(config) 之前调用。"""
    global _installed
    if _installed:
        return
    _installed = True
    try:
        _install_op_log()
    except Exception as e:
        logger.error(f'挂载 op_log 信号失败: {e}', e)
    # 框架 起 AboutTab 重构：VersionCard / LinksBar / ProjectCard
    # 三个模块被删除，对应的两个补丁已失效并移除。
    for patch in (_sync_widget_theme, _patch_about_tab,
                  _patch_feature_set_encoding, _patch_logger_name,
                  _patch_ort_dml):
        try:
            patch()
        except Exception as e:
            logger.error(f'{patch.__name__} 失败: {e}', e)

    # 特色功能（悬浮窗/紧凑模式开关、自定义作用域按钮）的注入改由 HomeTab.__init__
    # 里的 QTimer 轮询负责（那里 QApplication 已存在，install 阶段还没有）。
    # 不依赖 start_success 信号，避免时序问题导致功能整个不显示。
