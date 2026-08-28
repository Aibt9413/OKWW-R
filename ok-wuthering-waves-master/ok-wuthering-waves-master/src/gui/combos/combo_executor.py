"""出招宏执行器：解析序列、暂停当前任务、调用 task 接口执行。"""

import threading
import time

from ok import Logger, og
from ok.ui.qt.util.app import show_info_bar

from src.gui.combos import combos_store

logger = Logger.get_logger(__name__)

SLOT_CYCLE = {1: 2, 2: 3, 3: 1}   # “下一个角色位”循环


class ComboExecutor:
    """单例执行器：热键触发 -> 暂停当前任务 -> 执行宏 -> 恢复。"""

    def __init__(self):
        self._running = set()          # combo_id 正在执行（防重入）
        self._trigger_counts = {}      # combo_id -> 已触发次数（内存计数）

    # ---------- 触发入口 ----------
    def trigger(self, combo: dict):
        combo_id = combo.get('id')
        if not combo.get('enabled', True):
            return
        if combo_id in self._running:
            return
        limit = int(combo.get('trigger_count') or 0)
        if limit > 0 and self._trigger_counts.get(combo_id, 0) >= limit:
            show_info_bar(og.main_window,
                          f"出招宏「{combo.get('combo_name')}」已达到触发次数上限 ({limit} 次)")
            return
        thread = threading.Thread(target=self._run, args=(combo,), daemon=True,
                                  name=f'Combo-{combo.get("combo_name")}')
        thread.start()

    # ---------- 执行 ----------
    def _run(self, combo: dict):
        combo_id = combo.get('id')
        self._running.add(combo_id)
        try:
            task = self._pick_task()
            if task is None:
                show_info_bar(og.main_window,
                              "未找到可用的战斗任务，无法执行出招宏", error=True)
                return
            if not self._match_binding(combo, task):
                return
            self._trigger_counts[combo_id] = self._trigger_counts.get(combo_id, 0) + 1
            paused_task = self._pause_current_task()
            try:
                self._click_middle_button(task, int(combo.get('mb_click_count') or 0))
                interval = max(int(combo.get('default_interval_ms') or 120), 0) / 1000.0
                heavy_hold_ms = int(combo.get('heavy_hold_ms') or 1000)
                self._execute_sequence(combo.get('sequence') or [], task, interval,
                                       heavy_hold_ms)
                if combo_id in self._trigger_counts:
                    left = int(combo.get('trigger_count') or 0)
                    left = left - self._trigger_counts[combo_id] if left > 0 else 0
                    if left >= 0:
                        logger.info(f"combo {combo.get('combo_name')} executed, "
                                    f"remaining triggers: {left}")
            finally:
                self._resume_task(paused_task)
        except Exception as e:
            logger.exception(f'combo execute error: {e}')
            show_info_bar(og.main_window, f"出招宏执行失败: {e}", error=True)
        finally:
            self._running.discard(combo_id)

    def _pick_task(self):
        """优先当前任务，否则第一个启用的战斗任务。"""
        executor = og.executor
        if executor is None:
            return None
        if executor.current_task is not None:
            return executor.current_task
        for task in list(getattr(executor, 'onetime_tasks', [])):
            if getattr(task, 'enabled', False) and hasattr(task, 'key_config'):
                return task
        for task in list(getattr(executor, 'trigger_tasks', [])):
            if getattr(task, 'enabled', False) and hasattr(task, 'key_config'):
                return task
        return None

    # ---------- 绑定匹配 ----------
    def _match_binding(self, combo: dict, task) -> bool:
        bind_role = combo.get('bind_role')
        bind_team = combo.get('bind_team')
        bind_slot = combo.get('bind_slot')
        if not bind_role and not bind_team and not bind_slot:
            return True
        chars = [c for c in getattr(task, 'chars', []) if c is not None]
        if not chars:
            show_info_bar(og.main_window,
                          f"出招宏「{combo.get('combo_name')}」未匹配到当前队伍，已跳过")
            return False
        if bind_role:
            names = [getattr(c, 'name', '') for c in chars]
            if bind_role not in names and bind_role not in [type(c).__name__ for c in chars]:
                show_info_bar(og.main_window,
                              f"出招宏「{combo.get('combo_name')}」绑定的角色 {bind_role} 不在当前队伍，已跳过")
                return False
        if bind_team:
            team_names = {getattr(c, 'name', '') for c in chars} | {
                type(c).__name__ for c in chars}
            if not set(bind_team).issubset(team_names):
                show_info_bar(og.main_window,
                              f"出招宏「{combo.get('combo_name')}」绑定的队伍不在当前配置，已跳过")
                return False
        if bind_slot:
            if bind_slot > len(chars):
                show_info_bar(og.main_window,
                              f"出招宏「{combo.get('combo_name')}」绑定的角色位 {bind_slot} 不存在，已跳过")
                return False
        return True

    # ---------- 任务暂停 / 恢复 ----------
    def _pause_current_task(self):
        executor = og.executor
        if executor is None:
            return None
        task = executor.current_task
        if task is None or getattr(task, 'paused', False):
            return None
        try:
            if executor.pause(task):
                return task
        except Exception as e:
            logger.warning(f'pause current task failed: {e}')
        return None

    def _resume_task(self, task):
        if task is None:
            return
        try:
            task.unpause()
        except Exception as e:
            logger.warning(f'unpause task failed: {e}')

    # ---------- 序列执行 ----------
    def _execute_sequence(self, sequence: list, task, interval=0.12,
                          heavy_hold_ms=1000):
        """执行序列（OKCombo v2）。

        - 每条指令执行后自动等待 interval（默认指令间隔）
        - delay(N) 用显式 N 毫秒替代该处间隔
        - action(N)：重复 N 次（重复循环内也用默认间隔，循环外不再等待）
        - heavy(N)：重击长按 N 毫秒
        """
        current_slot = self._current_slot(task)
        logger.info(f'combo start, sequence={sequence}, current_slot={current_slot}, '
                    f'interval={interval * 1000:.0f}ms')
        for item in sequence:
            name = item.split('(')[0].strip()
            arg = item.split('(', 1)[1].rstrip(')') if '(' in item else ''
            if name == 'delay':
                try:
                    self._sleep(task, max(int(float(arg)), 0) / 1000.0)
                except ValueError:
                    logger.warning(f'bad delay arg {arg}')
                continue
            if name == 'slot':
                target = int(arg) if arg.isdigit() else None
                if target in (1, 2, 3):
                    current_slot = self._switch_to_slot(task, current_slot, target)
                if interval > 0:
                    self._sleep(task, interval)
                continue
            if name == 'switch':
                current_slot = SLOT_CYCLE.get(current_slot, 1)
                self._switch_next(task)
                if interval > 0:
                    self._sleep(task, interval)
                continue
            # 重复次数 / 重击长按时长
            repeat = 1
            hold_ms = 0
            if name == 'heavy' and arg:
                hold_ms = max(int(arg), 1)
            elif arg:
                repeat = max(int(arg), 1)
            for _ in range(repeat):
                self._do_action(name, hold_ms or heavy_hold_ms, task)
                if interval > 0:
                    self._sleep(task, interval)
        logger.info('combo done')

    def _do_action(self, name, hold_ms, task):
        if name == 'attack':
            task.click(interval=0.05, move=False)
        elif name == 'heavy':
            task.mouse_down()
            self._sleep(task, hold_ms / 1000.0 if hold_ms else 1.0)  # 默认长按 1 秒
            task.mouse_up()
        elif name == 'resonance':
            task.send_key(task.get_resonance_key())
        elif name == 'echo':
            task.send_key(task.get_echo_key())
        elif name == 'liberation':
            task.send_key(task.get_liberation_key())
        elif name == 'tool':
            task.send_key(task.key_config['Tool Key'])
        elif name == 'jump':
            task.send_key(task.key_config['Jump Key'])
        elif name == 'finisher':
            task.send_key(task.key_config.get('F Key') or
                          task.key_config.get('Finisher Key') or 'f')
        else:
            logger.warning(f'unknown combo item: {name}')

    def _click_middle_button(self, task, count):
        """执行前点按多次鼠标中键（游戏内常用于解除锁定/重置目标）。"""
        for _ in range(max(count, 0)):
            try:
                task.mouse_down(key='middle')
                self._sleep(task, 0.03)
                task.mouse_up(key='middle')
            except Exception as e:
                logger.warning(f'middle click failed: {e}')
                return
            self._sleep(task, 0.05)

    def _current_slot(self, task):
        try:
            result = task.in_team()
            if result and len(result) >= 2:
                index = result[1]
                if isinstance(index, int) and 1 <= index <= 3:
                    return index
        except Exception as e:
            logger.warning(f'in_team failed: {e}')
        # 兜底：从当前角色对象反查
        try:
            current = task.get_current_char()
            chars = [c for c in getattr(task, 'chars', []) if c is not None]
            for i, c in enumerate(chars, 1):
                if c is current:
                    return i
        except Exception:
            pass
        return 1

    def _switch_to_slot(self, task, current_slot, target):
        """跨度 1（循环下一个）用项目现有 switch_next_char；否则按数字键直切。
        切换后的等待由统一指令间隔控制。"""
        if target == SLOT_CYCLE.get(current_slot):
            self._switch_next(task)
        else:
            task.send_key(str(target))
        return target

    def _switch_next(self, task):
        try:
            current = task.get_current_char()
            task.switch_next_char(current)
        except Exception as e:
            logger.warning(f'switch_next_char failed, fallback to key: {e}')
            task.send_key('1')

    def _sleep(self, task, seconds):
        if seconds <= 0:
            return
        task.sleep(seconds)


_combo_executor = None


def get_combo_executor() -> ComboExecutor:
    global _combo_executor
    if _combo_executor is None:
        _combo_executor = ComboExecutor()
    return _combo_executor
