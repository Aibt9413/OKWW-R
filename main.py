"""
SonicCore 统一启动器入口。
通过 custom_tabs 机制注入 HomeTab。
"""
import sys
import os

# 确保项目根目录在 sys.path 中
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 启动器自身的 configs/ logs/ icons/ 都相对于项目根目录，
# 切换游戏后 GameSwitcher 会把 cwd 切到游戏目录，所以这里先固定一次。
os.chdir(project_root)

if __name__ == '__main__':
    # 必须在 OK(config) 之前：补 op_log 信号 + 精简「关于」页，
    # 这两件事都要赶在 MainWindow 构造之前完成。
    from okunified import compat

    compat.install()

    # 单游戏：必须在 OK(config) 之前把游戏配置并进来，否则 3.0.1 的
    # TasksPage 构造时看不到任何任务，任务页会整个消失。
    compat.load_game_config()

    from config import config
    from ok import OK

    ok = OK(config)

    # 诊断钩子：仅当 SC_IMAO_AUTOTEST=1 时，窗口出现后自动触发 IMAO 连接，
    # 把结果写入固定日志。发布版默认不设置该变量，完全不影响正常使用。
    if os.environ.get('SC_IMAO_AUTOTEST') == '1':
        from PySide6.QtCore import QTimer
        from ok import og

        def _imao_autotest():
            import time
            log_path = os.path.join(
                os.environ.get('TEMP', '.'), 'sc_imao_autotest.log')
            def w(msg):
                with open(log_path, 'a', encoding='utf-8') as fh:
                    fh.write('%s %s\n' % (time.strftime('%H:%M:%S'), msg))
            try:
                mw = getattr(og, 'main_window', None)
                pages = getattr(mw, '_pages', {}) or {}
                tab = next((p for p in pages.values()
                            if p.__class__.__name__ == 'IMaoTab'), None)
                w('tab found: %s' % (tab is not None))
                if tab is not None:
                    w('calling _on_connect')
                    tab._on_connect()
                    w('client=%s status=%s detail=%s' % (
                        tab._client is not None, tab._core_status.text(),
                        tab._detail_label.text()))
                    if tab._client is not None:
                        w('core status=%s' % tab._client.status.get('coreState'))
            except Exception as e:
                w('AUTOTEST ERROR: %r' % e)

        QTimer.singleShot(3000, _imao_autotest)

    ok.start()
