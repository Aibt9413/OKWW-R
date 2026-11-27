"""
SonicCore 游戏切换器。

在同一个 OK 框架实例内动态切换游戏配置，不启动子进程。

关键约束（决定了这里的实现方式）：

1. 每个游戏项目都是独立的 框架 应用，而且都使用顶层包名 ``src``
   （``src.task.*`` / ``src.tasks.*`` / ``src.scene.*``）。
   为此启动器自身的包改名为 ``okunified``，把 ``src`` 这个名字完全让给游戏。
   切换游戏时必须清空上一个游戏遗留在 sys.modules 里的模块，
   否则新游戏会命中旧游戏的模块缓存。

2. 游戏运行期间 cwd 必须停在游戏目录：框架 的 ``get_path_relative_to_exe``
   找不到文件时会回退到 cwd，游戏的 assets / configs 都依赖这一点。

3. 任务的构造方式和框架的 TaskManager 一致：
   ``cls(executor=..., app=...)`` → ``after_init(executor=..., scene=...)`` → ``post_init()``。
"""
import importlib.util
import os
import sys

from ok import Logger
from ok.util.clazz import init_class_by_name

logger = Logger.get_logger(__name__)

# 上游往"框架已有的配置组"里加、但**我们不要显示**的项。
#
#   Basic Options → Game Package：soniccore 3.7.3 加的「游戏包体 sd/hd/uhd」下拉框。
#   它和「设置 → 游戏 → 启动参数」里手填的 `-krqlv=xxx` 是同一个参数
#   （鸣潮新版必须带这个参数才能通过第三方启动器启动）。既然自己的字段更通用
#   （将来上游再加别的启动参数也能写），就只留自己的、不显示这个下拉框。
#
# 值照旧有效：soniccore 的 get_game_launch_arguments() 读不到这个键时会用它自己的
# 默认值 'hd'，所以 -krqlv=hd 仍然会自动带上（保证能启动）；想换包体就在
# 启动参数里写 -krqlv=uhd —— 参数合并是"同键覆盖"，手填的会压掉自动值。
GAME_OPTION_KEYS_TO_HIDE = {
    'Basic Options': {'Game Package'},
}

# 从游戏 config 复制到 og.config 的字段。
# 刻意不包含 custom_tabs / gui_title / config_folder 等启动器自己的字段；
# 也不含 'windows' —— 那一段需要"启动器默认 + 游戏覆盖"的合并，单独处理。
_GAME_CONFIG_KEYS = (
    'onetime_tasks',
    'trigger_tasks',
    'scene',
    'my_app',
    'template_matching',
    'global_configs',
    'links',
    # 刻意不复制 'about'：那是免责声明，属于启动器自己的声明，
    # 不该被游戏项目的文案顶掉（游戏那段写的是它自己的免费说明和下载渠道）。
    'screenshots_folder',
    'screenshot_processor',
    'blur_area',
    'supported_resolution',
    'start_timeout',
    'wait_until_settle_time',
    'analytics',
)

# 框架 的 update_capture_method 认识的采集方式名字。
# ⚠️ 没有 "BitBlt_Full"！soniccore 的注释里把它写作 BitBlt_Full，但实际值是
#    BitBlt_RenderFull。名字写错不会抛异常，只会让那一项被静默跳过，
#    最终 capture_method 建不出来 —— 症状是"识别不到游戏窗口"。
_VALID_CAPTURE_METHODS = (
    'WGC', 'BitBlt', 'BitBlt_RenderFull',
    'ForegroundBitBlt', 'Foreground BitBlt', 'Foreground',
    'LosslessScaling', 'Lossless Scaling', 'DXGI',
)
_DEFAULT_CAPTURE_METHODS = ('WGC', 'BitBlt_RenderFull', 'BitBlt')

# 框架 支持的窗口交互方式名称 -> 类
_INTERACTION_MAP = {}


def _interaction_map():
    global _INTERACTION_MAP
    if not _INTERACTION_MAP:
        from ok.device.interaction import (
            ForegroundPostMessageInteraction,
            GenshinInteraction,
            PostMessageInteraction,
            PyDirectInteraction,
            PynputInteraction,
        )
        _INTERACTION_MAP = {
            'PostMessage': PostMessageInteraction,
            'Genshin': GenshinInteraction,
            'ForegroundPostMessage': ForegroundPostMessageInteraction,
            'Pynput': PynputInteraction,
            'PyDirect': PyDirectInteraction,
        }
    return _INTERACTION_MAP


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def _under(path, folder):
    try:
        normalized = _norm(path)
        folder = _norm(folder)
    except (TypeError, ValueError):
        return False
    return normalized == folder or normalized.startswith(folder + os.sep)


# 窗口总标题：固定值，不跟随游戏切换。
WINDOW_TITLE = 'SonicCore'


def force_window_title():
    """把主窗口标题固定成 WINDOW_TITLE。

    框架构造 MainWindow 时会拼成 `{title} {version} {profile}`（比如
    `SonicCore alpha0.1.3  `），所以要等窗口建好之后再覆盖一次；
    切换游戏时框架那边也会被我们覆盖（见 _update_title）。
    """
    from ok import og

    if getattr(og, 'app', None) is not None:
        og.app.title = WINDOW_TITLE
    main_window = getattr(og, 'main_window', None)
    if main_window is None:
        return False
    if main_window.windowTitle() != WINDOW_TITLE:
        main_window.setWindowTitle(WINDOW_TITLE)
    return True


class GameSwitcher:
    """管理游戏配置切换。"""
    def __init__(self):
        self._current_game = None
        self._game_configs = {}          # game_key -> 已加载的游戏 config 字典
        self._game_task_tabs = []        # 当前游戏的任务 Tab 引用，用于切换时移除
        self._game_paths = set()         # 所有见过的游戏目录，用于整理 sys.path
        self._game_module_names = set()  # 当前游戏引入的模块名，切换时清理
        self._switching = False

        # 启动器 config 的原始默认值 —— 必须在这里快照！
        # og.config 就是 config 模块里那个 dict（同一个对象），_apply_config 会就地改它。
        # 如果等到切换时再读"默认值"，读到的已经是上一个游戏的残留了
        # （原神缺 hwnd_class 就是被这么串没的）。
        from config import config as _launcher_config
        self._launcher_defaults = {k: _launcher_config.get(k)
                                   for k in _GAME_CONFIG_KEYS}
        self._launcher_windows = dict(_launcher_config.get('windows') or {})
        # 同名配置组的"框架/别的游戏"基线，见 _merge_global_config
        self._global_config_baselines = {}

    @property
    def current_game(self):
        return self._current_game

    # ── 模块与 sys.path 管理 ──────────────────────────────────────────

    def _prepare_sys_path(self, game_path):
        """把当前游戏目录放到 sys.path 首位，并移出其他游戏目录。"""
        game_path = os.path.abspath(game_path)
        self._game_paths.add(_norm(game_path))
        game_norm = _norm(game_path)

        for path in list(sys.path):
            try:
                normalized = _norm(path)
            except (TypeError, ValueError):
                continue
            if normalized in self._game_paths and normalized != game_norm:
                sys.path.remove(path)

        while game_path in sys.path:
            sys.path.remove(game_path)
        sys.path.insert(0, game_path)

    def _collect_game_modules(self, baseline):
        """收集本次加载新增的、属于游戏目录的模块名，外加整个 ``src`` 命名空间。"""
        names = set()
        for name in set(sys.modules) - baseline:
            module = sys.modules.get(name)
            file = getattr(module, '__file__', None)
            if file and any(_under(file, path) for path in self._game_paths):
                names.add(name)
        # 游戏都依赖顶层包 src，切换时一并清掉，避免跨游戏串味
        for name in list(sys.modules):
            if name == 'src' or name.startswith('src.'):
                names.add(name)
        return names

    def _purge_game_modules(self):
        for name in list(self._game_module_names):
            sys.modules.pop(name, None)
        self._game_module_names.clear()

    # ── 加载游戏 config ───────────────────────────────────────────────

    def load_game_config(self, game_key):
        """加载指定游戏项目目录下的 config.py。"""
        from config import GAMES
        game_info = GAMES.get(game_key)
        if not game_info:
            logger.error(f'Unknown game: {game_key}')
            return None

        game_path = os.path.abspath(game_info['path'])

        # 即使 config 命中缓存，也必须把 sys.path 指回这个游戏目录，
        # 否则实例化任务时 src.task.* 会找不到（缓存不重建模块命名空间）。
        self._prepare_sys_path(game_path)

        if game_key in self._game_configs:
            return self._game_configs[game_key]

        config_py = os.path.join(game_path, 'config.py')
        if not os.path.isfile(config_py):
            logger.error(f'Game config not found: {config_py}')
            return None

        old_cwd = os.getcwd()
        os.chdir(game_path)
        try:
            # 用文件路径加载，避免和启动器自己的 config.py 重名
            spec = importlib.util.spec_from_file_location(
                f'game_config_{game_key}', config_py)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            game_config = module.config
        except Exception as e:
            logger.error(f'Failed to load game config for {game_key}: {e}', e)
            return None
        finally:
            os.chdir(old_cwd)

        self._game_configs[game_key] = game_config
        logger.info(f'Loaded game config for {game_key}: {game_path}')
        return game_config

    # ── 切换主流程 ────────────────────────────────────────────────────

    def switch_game(self, game_key, force=False):
        """切换到指定游戏。成功返回 True。"""
        from ok import og
        from config import GAMES

        if self._switching:
            logger.warning('switch_game already in progress, ignored')
            return False
        if game_key == self._current_game and not force:
            return True

        game_info = GAMES.get(game_key)
        if not game_info:
            logger.error(f'Unknown game: {game_key}')
            return False

        self._switching = True
        try:
            executor = og.executor
            if executor is not None and not executor.paused:
                executor.pause()

            # 1. 卸掉上一个游戏（Tab / 任务 / 模块缓存）
            self._unload_current_game()

            # 现在的 sys.modules 已经不含旧游戏的东西，作为本次切换的基线；
            # 换回去时要靠它重新记录新游戏引入的模块（否则下次切换清不掉）。
            baseline = set(sys.modules)

            # 2. 加载新游戏 config
            game_config = self.load_game_config(game_key)
            if not game_config:
                self._current_game = None
                return False

            game_path = os.path.abspath(game_info['path'])
            # 3. cwd 进入游戏目录：任务 load_config / 游戏 assets 都依赖它
            os.chdir(game_path)

            # 4. 重新加载游戏自带的 gettext 目录。
            #    必须在重建任务 Tab 之前：TaskCard 的标题走 og.app.tr(task.name)，
            #    中文任务名来自游戏项目 i18n/<locale>/LC_MESSAGES/ok.mo。
            self._reload_translations()

            # 5. 把游戏配置写进框架的 config
            self._apply_config(game_info, game_config)

            # 6. 注册游戏自己的全局配置项
            self._register_global_configs(game_config)

            # 7. my_app（游戏 Globals 单例）
            self._rebuild_my_app(game_config)

            # 8. 重建任务（scene / trigger / onetime）
            self._rebuild_executor_tasks(game_config)

            # 9. 重建侧边栏任务 Tab
            self._rebuild_sidebar_tabs()

            # 10. 重建设备管理器状态
            self._rebuild_device_manager()

            # 10.5 恢复这个游戏记住的「自定义窗口」绑定（如果有）
            try:
                from okunified.gui.window_picker import apply_custom_window
                apply_custom_window(game_key)
            except Exception as e:
                logger.warning(f'恢复自定义作用域失败: {e}')

            # 11. 应用用户为该游戏单独指定的 exe 路径
            self._apply_game_exe_override(game_key)

            # 12. 重新加载模版匹配
            self._reload_template_matching(game_config, game_path)

            self._current_game = game_key
            self._update_title(game_info)
            self._update_home_tab(game_key)

            from okunified import compat
            compat.op_log(
                f"切换游戏 → {game_info.get('name', game_key)}"
                f"（{len(executor.onetime_tasks)} 个日常 / {len(executor.trigger_tasks)} 个触发）")

            # 13. 记录本次引入的游戏模块名，供下次切换时清理。
            #     必须在任务 / scene / my_app 都建好之后再收集，
            #     因为 src.task.* 这些模块是实例化任务时才 import 的。
            self._game_module_names |= self._collect_game_modules(baseline)

            logger.info(f'Switched to {game_key} successfully')
            return True
        except Exception as e:
            logger.error(f'switch_game {game_key} failed: {e}', e)
            return False
        finally:
            self._switching = False

    # ── 各步骤实现 ────────────────────────────────────────────────────

    def _unload_current_game(self):
        """移除旧游戏的 Tab、销毁旧任务、清掉旧游戏的模块缓存。"""
        from ok import og

        self._remove_task_tabs()

        executor = og.executor
        if executor is not None:
            for task in (*list(executor.onetime_tasks), *list(executor.trigger_tasks)):
                try:
                    task.on_destroy()
                except Exception as e:
                    logger.warning(f'task on_destroy failed for {task}: {e}')
            # 整体替换而非 clear()，避免执行线程正在遍历这些列表
            executor.onetime_tasks = []
            executor.trigger_tasks = []
            executor.onetime_task_queue = []
            executor.current_task = None
            executor.trigger_task_index = -1
            executor.scene = None
            executor.feature_set = None
            executor._frame = None

        og.my_app = None
        self._purge_game_modules()

    def _apply_config(self, game_info, game_config):
        """把游戏 config 中游戏相关的字段写入 og.config。"""
        from ok import og
        from ok.util.process import WINDOWS_START_METHOD_START

        config = og.config
        for key in _GAME_CONFIG_KEYS:
            if key in game_config:
                config[key] = game_config[key]
            elif key in self._launcher_defaults:
                # 游戏没提供就回退到启动器默认，
                # 否则会一直留着上一个游戏的值（比如原神没有 screenshot_processor，
                # 切到鸣潮后还会用着原神的截图预处理函数）
                config[key] = self._launcher_defaults[key]

        # windows 段：启动器默认打底 + 游戏配置覆盖。
        # 不能整体替换 —— 游戏那边的 windows 往往缺项，最典型的是原神
        # 根本没有 capture_method 和 hwnd_class，整体替换会让 DeviceManager
        # 报 "cant find a usable windows capture"，表现就是"识别不到游戏窗口"。
        base_windows = dict(self._launcher_windows)
        game_windows = dict(game_config.get('windows') or {})
        if not game_windows:
            logger.warning(f'{game_info.get("name")} 的 config 里没有 windows 段')
        windows = {**base_windows, **game_windows}

        exe = windows.get('exe')
        if isinstance(exe, str):
            windows['exe'] = [exe]
        windows.setdefault('start_exe', True)
        windows.setdefault('start_method', WINDOWS_START_METHOD_START)

        # 采集方式名字必须是 框架 认识的，写错不会报错、只会被静默跳过，
        # 最后表现为 "cant find a usable windows capture" / 识别不到游戏窗口。
        methods = windows.get('capture_method') or []
        if isinstance(methods, str):
            methods = [methods]
        valid = [m for m in methods if m in _VALID_CAPTURE_METHODS]
        unknown = [m for m in methods if m not in _VALID_CAPTURE_METHODS]
        if unknown:
            logger.error(f'capture_method 里有 框架 不认识的名字 {unknown}，'
                         f'这些会被静默跳过。合法值：{list(_VALID_CAPTURE_METHODS)}')
        if not valid:
            valid = list(_DEFAULT_CAPTURE_METHODS)
            logger.warning(f'{game_info.get("name")} 没有可用的 capture_method，'
                           f'已回退到 {valid}')
        windows['capture_method'] = valid
        config['windows'] = windows
        logger.info(f'应用 windows 配置: exe={windows.get("exe")} '
                    f'capture_method={windows.get("capture_method")} '
                    f'hwnd_class={windows.get("hwnd_class")} '
                    f'interaction={windows.get("interaction")}')

        # ocr：openvino 未安装时降级，否则 OCR 初始化必失败
        self._apply_ocr_config(game_config)

        # StartController 在构造时缓存了这些值，需要同步
        start_controller = getattr(og.app, 'start_controller', None)
        if start_controller is not None:
            start_controller.config = config
            start_controller.start_exe = windows.get('start_exe', True)
            start_controller.start_method = windows.get('start_method', WINDOWS_START_METHOD_START)
            start_controller.start_timeout = config.get('start_timeout', 60)
            # soniccore 3.7.3 起，游戏用 windows.launch_arguments 声明"怎么算启动参数"
            # （按游戏包体 sd/hd/uhd 返回 -krqlv=hd）。框架 2.0.6 不认这个字段，
            # 所以在这里挂到 start_controller 上，由 launch_inject 的 execute 补丁读取。
            start_controller.launch_arguments = windows.get('launch_arguments')
            logger.info(f'Updated start controller: start_exe={start_controller.start_exe} '
                        f'launch_arguments={callable(start_controller.launch_arguments)}')

    def _apply_ocr_config(self, game_config):
        """应用游戏的 OCR 设置，并按本机实际可用的推理后端做调整。"""
        from ok import og

        ocr = game_config.get('ocr')
        if not ocr:
            return

        ocr = dict(ocr)
        params = dict(ocr.get('params') or {})
        has_openvino = importlib.util.find_spec('openvino') is not None
        has_onnxruntime = importlib.util.find_spec('onnxruntime') is not None

        if params.get('use_openvino') and not has_openvino:
            if has_onnxruntime:
                logger.warning('未安装 openvino，OCR 降级为 onnxruntime')
            else:
                logger.warning('未安装 openvino')
            params['use_openvino'] = False
            params['use_npu'] = False
        if not params.get('use_openvino') and not has_onnxruntime:
            logger.error(
                'OCR 推理后端缺失：onnxruntime 与 openvino 都没有安装，OCR 无法工作。'
                '请执行 pip install onnxruntime （或 pip install openvino）')
        ocr['params'] = params
        # TaskExecutor 用 ocr['default'] 取默认库，缺了会直接报错
        if not ocr.get('default'):
            ocr['default'] = dict(ocr)
        og.config['ocr'] = ocr
        # 已经建好的 OCR 实例属于旧配置，丢掉
        if og.executor is not None:
            og.executor._ocr_lib = {}

    def _reload_translations(self):
        """重新加载游戏项目 i18n/ 下的 gettext 目录。

        框架的 App.tr() 一旦加载失败就把 'Failed' 缓存住、永不重试，
        而启动阶段 cwd 还是启动器目录（没有 i18n/），所以第一次必然失败。
        切到游戏目录后必须手动重置并重载，任务名才会显示中文——
        任务卡片标题走的是 ConfigCard → og.app.tr(task.name)。
        """
        from ok import og
        from ok.util.file import get_path_relative_to_exe

        app = getattr(og, 'app', None)
        if app is None:
            return

        locale = getattr(app, 'locale', None)
        locale_name = locale.name() if hasattr(locale, 'name') else str(locale)
        i18n_dir = get_path_relative_to_exe('i18n')

        app.po_translation = None
        try:
            from ok.core.translation import get_translations
            translation = get_translations(locale_name)
            translation.install()
            app.po_translation = translation
            logger.info(f'Loaded game translations for {locale_name} from {i18n_dir}')
        except Exception as e:
            app.po_translation = 'Failed'
            logger.warning(f'{locale_name} 没有可用的游戏翻译，任务名保持原文 '
                           f'(i18n: {i18n_dir}): {e}')

    def _register_global_configs(self, game_config):
        """把游戏自己的 ConfigOption 注册进框架的 GlobalConfig。"""
        from ok import og

        global_config = getattr(og, 'global_config', None)
        if global_config is None:
            return

        provided = {}
        for option in game_config.get('global_configs') or []:
            name = getattr(option, 'name', None)
            if name:
                provided[name] = option

        # 上一个游戏往某个组里加过的项，这个游戏没有 → 退回基线。
        # 少了这一步，鸣潮的「Game Package」会留在原神的设置里（原神的
        # config 根本没有 Basic Options 这一组，不会走到下面的合并）。
        for name in list(self._global_config_baselines):
            if name in provided:
                continue
            existing = global_config.config_options.get(name)
            if existing is not None:
                self._merge_global_config(global_config, name, existing, None)

        for name, option in provided.items():
            existing = global_config.config_options.get(name)
            if existing is None:
                global_config.get_config(option)
                logger.info(f'Registered global config: {name}')
                continue
            if existing is option:
                continue
            self._merge_global_config(global_config, name, existing, option)

    def _merge_global_config(self, global_config, name, existing, incoming):
        """游戏带来的同名配置组：把游戏**新增的项**并进已注册的那份。

        框架的 GlobalConfig.get_config() 是按名字取的：同名就直接返回旧的，
        整份新 ConfigOption 被丢弃（连 default_config 都不合并）。soniccore 3.7.3
        就往框架已有的 Basic Options 里加了「Game Package」，照原样会被吃掉。

        做法：第一次遇到某个组"已被注册"时，把它当时的定义记成基线；之后每次
        切游戏都把该组恢复成「基线 + 当前游戏新增的项」（incoming 为 None 就是
        只剩基线）。这样切回原神时，鸣潮特有的项不会残留在原神的设置里。

        注意 Config.default 和 option.default_config **是同一个 dict 对象**，
        所以只能原地 clear/update，不能换成新对象，否则两边会脱钩。
        """
        defaults = dict(getattr(incoming, 'default_config', {}) or {}) if incoming else {}
        types = dict(getattr(incoming, 'config_type', {}) or {}) if incoming else {}
        descriptions = (dict(getattr(incoming, 'config_description', {}) or {})
                        if incoming else {})

        baseline = self._global_config_baselines.get(name)
        if baseline is None:
            baseline = {
                'defaults': dict(getattr(existing, 'default_config', {}) or {}),
                'types': dict(getattr(existing, 'config_type', {}) or {}),
                'descriptions': dict(
                    getattr(existing, 'config_description', {}) or {}),
            }
            self._global_config_baselines[name] = baseline

        target_defaults = dict(baseline['defaults'])
        target_types = dict(baseline['types'])
        target_descriptions = dict(baseline['descriptions'])
        added = []
        skip = GAME_OPTION_KEYS_TO_HIDE.get(name, ())
        for key, value in defaults.items():
            if key in baseline['defaults']:
                continue        # 框架已有的项，保持框架自己的定义
            if key in skip:
                # 上游加进来但不要的项（见常量说明）：不进可见配置，
                # 于是设置页不会出现它，值走回调自己的默认值
                logger.info(f'global config "{name}": 按配置跳过 {key}')
                continue
            target_defaults[key] = value
            if key in types:
                target_types[key] = types[key]
            if key in descriptions:
                target_descriptions[key] = descriptions[key]
            added.append(key)

        existing.default_config.clear()
        existing.default_config.update(target_defaults)
        existing.config_type = target_types
        existing.config_description = target_descriptions

        live = global_config.configs.get(name)
        if live is not None:
            live.default = existing.default_config
            for key, value in target_defaults.items():
                if key not in live:
                    live[key] = value      # 补上缺的值，不动用户已改过的
                live.default.setdefault(key, value)

        if added:
            logger.info(f'global config "{name}" 并入游戏新增项: {added}')
        else:
            logger.info(f'global config "{name}" 与框架定义一致，无需并入')

    def _rebuild_my_app(self, game_config):
        """重建游戏的 Globals 单例（og.my_app）。"""
        from ok import og

        my_app_def = game_config.get('my_app')
        if not my_app_def:
            return
        try:
            my_app = init_class_by_name(my_app_def[0], my_app_def[1], og.exit_event)
            if not hasattr(my_app, 'get_overlay_view') and hasattr(og.app, 'get_overlay_view'):
                my_app.get_overlay_view = og.app.get_overlay_view
            og.my_app = my_app
            logger.info(f'Created my_app: {my_app_def[1]}')
        except Exception as e:
            logger.error(f'Failed to create my_app {my_app_def}: {e}', e)

    def _init_tasks(self, task_defs):
        """按框架 TaskManager 的方式实例化任务。"""
        from ok import og

        app = og.app
        executor = og.executor
        locale = getattr(app, 'locale', None)
        locale_name = locale.name() if hasattr(locale, 'name') else str(locale)

        tasks = []
        for task_def in task_defs:
            try:
                task = init_class_by_name(task_def[0], task_def[1], executor=executor, app=app)
                task.after_init(executor=executor, scene=executor.scene)
                # 悬浮窗和任务日志用的中文显示名。
                # 游戏自带 i18n/<locale>/LC_MESSAGES/ok.mo 里就有（上面已重载），
                # 取不到就退回原名。
                if not getattr(task, 'cn_name', None):
                    task.cn_name = app.tr(task.name) or task.name
                # 少数任务不继承游戏的基础任务类（拿不到插桩的 op_log），
                # 在实例上补一个同样接口，保证悬浮窗/日志调用恒不炸。
                if not callable(getattr(task, 'op_log', None)):
                    from okunified import compat
                    task.op_log = compat.default_op_log
                supported = getattr(task, 'supported_languages', None) or []
                if supported and locale_name not in supported:
                    logger.info(f'skip task {task.__class__.__name__}: {locale_name} not supported')
                    continue
                tasks.append(task)
            except Exception as e:
                logger.error(f'Failed to create task {task_def}: {e}', e)
        return tasks

    def _rebuild_executor_tasks(self, game_config):
        """重建 executor 的 scene / trigger / onetime 任务。"""
        from ok import og

        executor = og.executor
        if executor is None:
            return

        scene_def = game_config.get('scene')
        if scene_def:
            try:
                executor.scene = init_class_by_name(scene_def[0], scene_def[1])
                logger.info(f'Loaded scene: {scene_def[1]}')
            except Exception as e:
                logger.error(f'Failed to load scene {scene_def}: {e}', e)
                executor.scene = None
        else:
            executor.scene = None

        trigger_tasks = self._init_tasks(game_config.get('trigger_tasks') or [])
        onetime_tasks = self._init_tasks(game_config.get('onetime_tasks') or [])

        for task in trigger_tasks:
            task.post_init()
        for task in onetime_tasks:
            task.post_init()

        executor.trigger_tasks = trigger_tasks
        executor.onetime_tasks = onetime_tasks
        executor.onetime_task_queue = []
        executor.trigger_task_index = -1

        logger.info(
            f'Rebuilt executor: {len(onetime_tasks)} onetime, {len(trigger_tasks)} trigger tasks')

    # ── 侧边栏任务 Tab ────────────────────────────────────────────────

    def _remove_task_tabs(self):
        from ok import og

        main_window = getattr(og, 'main_window', None)
        if main_window is None:
            self._game_task_tabs.clear()
            return

        for tab in self._game_task_tabs:
            if getattr(main_window, 'onetime_tab', None) is tab:
                main_window.onetime_tab = None
            if getattr(main_window, 'trigger_tab', None) is tab:
                main_window.trigger_tab = None
            grouped = getattr(main_window, 'grouped_task_tabs', None)
            if grouped and tab in grouped:
                grouped.remove(tab)
            try:
                main_window.removeInterface(tab, isDelete=True)
            except Exception as e:
                logger.warning(f'Failed to remove tab {tab}: {e}')
        self._game_task_tabs.clear()

    def _rebuild_sidebar_tabs(self):
        """移除旧游戏的任务 Tab，按新任务列表添加。"""
        from collections import defaultdict

        from qfluentwidgets import FluentIcon, NavigationItemPosition

        from ok import og

        main_window = getattr(og, 'main_window', None)
        executor = og.executor
        if main_window is None or executor is None:
            return

        self._remove_task_tabs()

        visible_triggers = [t for t in executor.trigger_tasks if getattr(t, 'visible', True)]
        if visible_triggers:
            from ok.ui.qt.tasks.TriggerTaskTab import TriggerTaskTab
            trigger_tab = TriggerTaskTab()
            main_window.trigger_tab = trigger_tab
            main_window.addSubInterface(
                trigger_tab, FluentIcon.STOP_WATCH, main_window.tr('Triggers'),
                position=NavigationItemPosition.SCROLL)
            self._game_task_tabs.append(trigger_tab)

        visible_onetime = [t for t in executor.onetime_tasks if getattr(t, 'visible', True)]
        if visible_onetime:
            from ok.ui.qt.tasks.OneTimeTaskTab import OneTimeTaskTab

            imported_names = [imp['script_name']
                              for imp in og.task_manager.imported_scripts.values()]
            groups = defaultdict(list)
            standalone_tasks = []
            for task in visible_onetime:
                group_name = getattr(task, 'group_name', None)
                if group_name and group_name not in imported_names:
                    groups[group_name].append(task)
                else:
                    standalone_tasks.append(task)

            if standalone_tasks:
                onetime_tab = OneTimeTaskTab(is_standalone=True)
                main_window.onetime_tab = onetime_tab
                main_window.addSubInterface(
                    onetime_tab, FluentIcon.BOOK_SHELF, main_window.tr('Tasks'),
                    position=NavigationItemPosition.SCROLL)
                self._game_task_tabs.append(onetime_tab)

            for group_name, tasks_in_group in groups.items():
                group_tab = OneTimeTaskTab(is_standalone=False, group_name=group_name)
                group_icon = getattr(tasks_in_group[0], 'group_icon', None) or FluentIcon.BOOK_SHELF
                main_window.addSubInterface(
                    group_tab, group_icon, og.app.tr(group_name),
                    position=NavigationItemPosition.SCROLL)
                main_window.grouped_task_tabs.append(group_tab)
                self._game_task_tabs.append(group_tab)

        logger.info(f'Rebuilt sidebar: {len(self._game_task_tabs)} task tabs')

    # ── 设备管理器 ────────────────────────────────────────────────────

    def _resolve_interaction(self, interaction):
        mapping = _interaction_map()
        name = interaction
        if isinstance(name, (list, tuple)):
            name = name[0] if name else None
        if isinstance(name, type):
            return name
        if name in mapping:
            return mapping[name]
        logger.warning(f'未知的 interaction {interaction!r}，回退到 Pynput')
        return mapping['Pynput']

    def _rebuild_device_manager(self):
        """按新游戏的 windows 段重建 hwnd_window 与交互方式。"""
        from ok.device.capture import HwndWindow
        from ok.util.collection import parse_ratio

        from ok import og

        dm = getattr(og, 'device_manager', None)
        if dm is None:
            return

        windows_config = dict(og.config.get('windows') or {})
        try:
            dm.close()
        except Exception as e:
            logger.warning(f'Failed to close old device manager state: {e}')
        dm.capture_method = None
        dm.interaction = None
        dm.windows_capture_config = windows_config
        if windows_config:
            dm.hwnd_window = HwndWindow(
                og.exit_event,
                windows_config.get('title'),
                windows_config.get('exe'),
                hwnd_class=windows_config.get('hwnd_class'),
                global_config=og.global_config,
                device_manager=dm,
                top_hwnd_class=windows_config.get('top_hwnd_class'))
            dm.win_interaction_class = self._resolve_interaction(
                windows_config.get('interaction'))
        else:
            dm.hwnd_window = None

        supported_resolution = og.config.get('supported_resolution') or {}
        dm.supported_ratio = parse_ratio(supported_resolution.get('ratio'))

        dm.clear_devices()
        dm.config['capture'] = 'windows'
        dm.config['interaction'] = ''
        exe = windows_config.get('exe') or ['']
        dm.config['selected_exe'] = exe[0] if isinstance(exe, (list, tuple)) else exe
        logger.info(f'Rebuilt device manager: exe={windows_config.get("exe")} '
                    f'interaction={windows_config.get("interaction")}')

    def _apply_game_exe_override(self, game_key):
        """应用用户为这个游戏单独指定的启动 exe（主页 / 设置里选的）。"""
        from ok import og

        from okunified.gui import home_state

        manager = getattr(og, 'device_manager', None)
        if manager is None:
            return
        exe_path = home_state.get_game_exe(game_key) or ''
        try:
            manager.config['pc_full_path'] = exe_path
            manager.config.save_file()
        except Exception as e:
            logger.warning(f'写入 game exe 路径失败: {e}')
        if exe_path:
            logger.info(f'游戏 exe 覆盖: {exe_path}')

    # ── 模版匹配 ──────────────────────────────────────────────────────

    def _reload_template_matching(self, game_config, game_path):
        """重新加载游戏的 COCO 模版 JSON。"""
        from ok.feature.FeatureSet import FeatureSet

        from ok import og

        executor = og.executor
        template_matching = game_config.get('template_matching')
        if executor is None:
            return
        if not template_matching:
            executor.feature_set = None
            return

        coco_json = template_matching.get('coco_feature_json')
        if not coco_json:
            executor.feature_set = None
            return
        if not os.path.isabs(coco_json):
            coco_json = os.path.join(game_path, coco_json)

        try:
            feature_set = FeatureSet(
                og.config.get('debug', False), coco_json,
                default_horizontal_variance=template_matching.get('default_horizontal_variance', 0.002),
                default_vertical_variance=template_matching.get('default_vertical_variance', 0.002),
                default_threshold=template_matching.get('default_threshold', 0.8),
                feature_processor=template_matching.get('feature_processor'),
                hcenter_features=template_matching.get('hcenter_features'),
                vcenter_features=template_matching.get('vcenter_features'),
            )
            executor.feature_set = feature_set
            if getattr(og, 'ok', None) is not None:
                og.ok.feature_set = feature_set
            logger.info(f'Reloaded template matching: {coco_json}')
        except Exception as e:
            logger.error(f'Failed to reload template matching: {e}', e)

    # ── 主页状态 ──────────────────────────────────────────────────────

    def _update_title(self, game_info):
        """窗口总标题**固定**为 SonicCore，不跟随游戏切换。

        原来会把游戏的 gui_title 拼进去（切到原神，窗口标题就变成 "SonicCore <版本号>"），
        但这是个"一个应用装多个游戏"的启动器 —— 标题跟着游戏变，
        任务栏里看起来像开了两个不同的程序。游戏名在主页和
        「设置 → 游戏」里已经显示得很清楚了。
        """
        from ok import og

        if force_window_title():
            logger.info(f'窗口标题固定为 {WINDOW_TITLE}'
                        f'（当前游戏 {game_info.get("name")}）')

    def _update_home_tab(self, game_key):
        """更新主页状态与「设置 → 游戏」的选中态。"""
        from ok import og

        main_window = getattr(og, 'main_window', None)
        if main_window is None:
            return
        stacked = main_window.stackedWidget
        for i in range(stacked.count()):
            widget = stacked.widget(i)
            if hasattr(widget, 'update_current_game'):
                widget.update_current_game(game_key)
                break

        try:
            from okunified.gui.game_settings import refresh_game_settings
            refresh_game_settings()
        except Exception as e:
            logger.warning(f'刷新「设置 → 游戏」失败: {e}')


# 全局单例
game_switcher = GameSwitcher()
