"""自定义出招宏面板 — UI 主界面（侧边栏 Tab）。

纯文本输入（1A2E3Q 语法），解析结果以只读列表 GUI 呈现；
修改仍改文本，实时重新解析。顶部提供「询问 AI」一键复制提示词。
"""

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox,
                               QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QSpinBox, QVBoxLayout, QWidget)
from qfluentwidgets import FluentIcon, PrimaryPushButton, PushButton

from ok import Logger, og
from ok.gui.util.app import show_info_bar
from ok.gui.widget.CustomTab import CustomTab
from ok.gui.tasks.EditTaskTab import CodeEditor
from ok.gui.tasks.PythonHighlighter import PythonHighlighter
from qfluentwidgets import FluentIcon

from src.char.CharFactory import char_dict
from src.char.CustomCharLoader import list_custom_teams
from src.gui.combos import combos_store
from src.gui.combos.combo_executor import get_combo_executor
from src.gui.combos.hotkey_manager import (get_hotkey_manager, normalize_hotkey,
                                           parse_hotkey)

logger = Logger.get_logger(__name__)

CHAR_NAMES = sorted({info['cls'].__name__ for info in char_dict.values()})


# ---------------------------------------------------------------- 热键输入框
class HotkeyLineEdit(QLineEdit):
    hotkey_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText('点击后按快捷键...')
        self.setMinimumWidth(140)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.setText('...')

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if self.text() == '...':
            self.setText('')

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_Backspace, Qt.Key_Delete):
            self.setText('')
            self.hotkey_changed.emit('')
            return
        mods = event.modifiers()
        parts = []
        if mods & Qt.ControlModifier:
            parts.append('Ctrl')
        if mods & Qt.AltModifier:
            parts.append('Alt')
        if mods & Qt.ShiftModifier:
            parts.append('Shift')
        if mods & Qt.MetaModifier:
            parts.append('Win')
        key = event.key()
        if key in (Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta):
            self.setText('+'.join(parts) + '+' if parts else '')
            return
        name = self._key_name(key)
        if not name:
            return
        text = '+'.join(parts + [name]) if parts else name
        self.setText(text)
        self.hotkey_changed.emit(text)
        event.accept()

    @staticmethod
    def _key_name(key):
        if Qt.Key_0 <= key <= Qt.Key_9:
            return str(key - Qt.Key_0)
        if Qt.Key_A <= key <= Qt.Key_Z:
            return chr(key)
        if Qt.Key_F1 <= key <= Qt.Key_F24:
            return f'F{key - Qt.Key_F1 + 1}'
        return {Qt.Key_Space: 'Space', Qt.Key_Tab: 'Tab', Qt.Key_Return: 'Enter',
                Qt.Key_Escape: 'Esc', Qt.Key_Left: 'Left', Qt.Key_Right: 'Right',
                Qt.Key_Up: 'Up', Qt.Key_Down: 'Down', Qt.Key_Home: 'Home',
                Qt.Key_End: 'End', Qt.Key_PageUp: 'PageUp', Qt.Key_PageDown: 'PageDown'}.get(key)


# ---------------------------------------------------------------- 角色代码编辑器
class CharCodeDialog(QDialog):
    """内嵌简易编辑器：打开并保存 src/char/ 下的角色脚本。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('编辑角色代码')
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel('角色:'))
        self.role_combo = QComboBox()
        self.role_combo.addItems(CHAR_NAMES)
        self.role_combo.currentTextChanged.connect(self._load_role)
        top.addWidget(self.role_combo, 1)
        layout.addLayout(top)

        self.editor = CodeEditor()
        self.highlighter = PythonHighlighter(self.editor.document())
        layout.addWidget(self.editor, 1)

        self.path_label = QLabel('')
        self.path_label.setStyleSheet('color: #74777C; font-size: 12px;')
        layout.addWidget(self.path_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_btn = PrimaryPushButton('保存')
        save_btn.clicked.connect(self._save)
        cancel_btn = PushButton('取消')
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)
        self._load_role(self.role_combo.currentText())

    def _char_file(self, role_name):
        return Path(__file__).resolve().parent.parent.parent / 'char' / f'{role_name}.py'

    def _load_role(self, role_name):
        if not role_name:
            return
        path = self._char_file(role_name)
        if path.exists():
            self.editor.setPlainText(path.read_text(encoding='utf-8'))
            self.path_label.setText(str(path))
        else:
            self.editor.setPlainText('')
            self.path_label.setText(f'{path} 不存在')

    def _save(self):
        role_name = self.role_combo.currentText()
        path = self._char_file(role_name)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.editor.toPlainText(), encoding='utf-8')
        except OSError as e:
            QMessageBox.critical(self, '保存失败', str(e))
            return
        show_info_bar(self.window(), f'已保存 {path.name}', title='成功')
        self.accept()


# ---------------------------------------------------------------- 主面板
class ComboPanelTab(CustomTab):
    """自定义出招宏面板。"""

    @property
    def icon(self):
        return FluentIcon.COMMAND_PROMPT

    def __init__(self):
        super().__init__()
        self.combos = combos_store.load_combos()
        self.current_combo = None
        self._key_config_snapshot = {}
        self._loading = False

        self.hotkey_manager = get_hotkey_manager()
        self.hotkey_manager.signals.hotkey_triggered.connect(self._on_hotkey)
        # 注意：CustomTab.executor 会被 MainWindow 赋值为 TaskExecutor，
        # 所以执行器用独立属性名，避免被覆盖。
        self.combo_runner = get_combo_executor()

        self._build_ui()
        self._refresh_list()
        self._register_all_hotkeys()

        # key_config 实时刷新（轮询对比）
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self._maybe_refresh_key_config)
        self._refresh_timer.start()

    # ---------------------------------------------------------- UI 构建
    def _build_ui(self):
        root = QHBoxLayout()
        self.vBoxLayout.addLayout(root, 1)

        # 左：出招表列表
        left = QVBoxLayout()
        list_tools = QHBoxLayout()
        new_btn = PushButton('新建')
        del_btn = PushButton('删除')
        copy_btn = PushButton('复制')
        paste_btn = PushButton('导入')
        for b, cb in ((new_btn, self._new_combo), (del_btn, self._delete_combo),
                      (copy_btn, self._copy_combo), (paste_btn, self._import_combo)):
            b.clicked.connect(cb)
            list_tools.addWidget(b)
        list_tools.addStretch(1)
        left.addLayout(list_tools)

        self.combo_list = QListWidget()
        self.combo_list.currentRowChanged.connect(self._select_combo)
        left.addWidget(self.combo_list, 1)
        root.addLayout(left, 2)

        # 右：编辑区
        right = QVBoxLayout()
        self._build_topbar(right)
        self._build_text_editor(right)
        self._build_properties(right)
        root.addLayout(right, 3)

    def _build_topbar(self, parent):
        top = QHBoxLayout()
        title = QLabel('自定义出招宏')
        title.setObjectName('viewTitleLabel')
        top.addWidget(title)
        top.addStretch(1)
        ai_btn = PushButton(FluentIcon.ROBOT, '询问 AI')
        ai_btn.clicked.connect(self._copy_ai_prompt)
        code_btn = PushButton('编辑角色代码')
        code_btn.clicked.connect(self._open_char_editor)
        top.addWidget(code_btn)
        top.addWidget(ai_btn)
        parent.addLayout(top)

    def _build_text_editor(self, parent):
        parent.addWidget(QLabel('连招序列（文本输入，修改后实时解析）'))
        self.text_input = QPlainTextEdit()
        self.text_input.setPlaceholderText(
            '示例: 1A(3)H800 2E3Q D300\n\n'
            '语法: 1/2/3=切角色位  A=普攻 H=重击 E=共鸣 Q=声骸 R=解放 T=工具 J=跳跃 F=处决\n'
            '      重复次数用括号: A(3)=普攻3次  H800=重击长按800ms\n'
            '      D300=延迟300ms；空格/逗号为可选分隔符')
        self.text_input.setFixedHeight(110)
        self.text_input.textChanged.connect(self._refresh_preview)
        parent.addWidget(self.text_input)

        self.preview_label = QLabel('解析预览:')
        parent.addWidget(self.preview_label)
        self.preview_list = QListWidget()
        self.preview_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.preview_list.setFocusPolicy(Qt.NoFocus)
        self.preview_list.setMaximumHeight(160)
        parent.addWidget(self.preview_list, 1)

    def _build_properties(self, parent):
        grid = QVBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText('出招表名称，如：今汐爆发循环')
        grid.addWidget(self.name_edit)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText('招数描述（可选），如：开局上协奏爆发')
        grid.addWidget(self.desc_edit)

        bind_row = QHBoxLayout()
        bind_row.addWidget(QLabel('绑定角色:'))
        self.role_combo = QComboBox()
        self.role_combo.addItem('（任意）', '')
        for name in CHAR_NAMES:
            self.role_combo.addItem(name, name)
        bind_row.addWidget(self.role_combo, 1)
        bind_row.addWidget(QLabel('角色位:'))
        self.slot_combo = QComboBox()
        self.slot_combo.addItem('（任意）', 0)
        self.slot_combo.addItem('角色位 1', 1)
        self.slot_combo.addItem('角色位 2', 2)
        self.slot_combo.addItem('角色位 3', 3)
        bind_row.addWidget(self.slot_combo)
        grid.addLayout(bind_row)

        team_row = QHBoxLayout()
        team_row.addWidget(QLabel('绑定队伍:'))
        self.team_combo = QComboBox()
        self.team_combo.setEditable(True)   # 允许自定义输入（逗号分隔角色名）
        self.team_combo.addItem('（任意）', '')
        for team in self._all_teams():
            self.team_combo.addItem(', '.join(team), team)
        self.team_combo.setCurrentIndex(0)
        team_row.addWidget(self.team_combo, 1)
        grid.addLayout(team_row)

        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(QLabel('触发快捷键:'))
        self.hotkey_edit = HotkeyLineEdit()
        self.hotkey_edit.hotkey_changed.connect(self._on_hotkey_input)
        hotkey_row.addWidget(self.hotkey_edit, 1)
        hotkey_row.addWidget(QLabel('触发次数:'))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(0, 999)
        self.count_spin.setValue(0)
        self.count_spin.setToolTip('0 = 不限次数')
        hotkey_row.addWidget(self.count_spin)
        grid.addLayout(hotkey_row)

        extra_row = QHBoxLayout()
        extra_row.addWidget(QLabel('执行前中键次数:'))
        self.mb_spin = QSpinBox()
        self.mb_spin.setRange(0, 20)
        self.mb_spin.setValue(2)
        self.mb_spin.setToolTip('宏执行前先点按鼠标中键的次数（0 = 不点击）')
        extra_row.addWidget(self.mb_spin)
        extra_row.addWidget(QLabel('指令默认间隔(ms):'))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(0, 3000)
        self.interval_spin.setValue(120)
        self.interval_spin.setSingleStep(10)
        self.interval_spin.setToolTip('无 Dxxx 时，每条指令执行后的自动等待时长（0 = 不等待）')
        extra_row.addWidget(self.interval_spin)
        extra_row.addWidget(QLabel('重击长按(ms):'))
        self.heavy_spin = QSpinBox()
        self.heavy_spin.setRange(100, 5000)
        self.heavy_spin.setValue(1000)
        self.heavy_spin.setSingleStep(100)
        self.heavy_spin.setToolTip('重击 H（不带数字）的默认长按时长；H+数字可单独覆盖')
        extra_row.addWidget(self.heavy_spin)
        extra_row.addStretch(1)
        grid.addLayout(extra_row)

        self.conflict_label = QLabel('')
        self.conflict_label.setWordWrap(True)
        self.conflict_label.setStyleSheet('color: #D93025; font-weight: bold;')
        grid.addWidget(self.conflict_label)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = PrimaryPushButton('保存出招表')
        save_btn.clicked.connect(self._save_combo)
        cancel_btn = PushButton('取消修改')
        cancel_btn.clicked.connect(self._load_into_editor)
        save_row.addWidget(cancel_btn)
        save_row.addWidget(save_btn)
        grid.addLayout(save_row)
        parent.addLayout(grid)

    # ---------------------------------------------------------- key_config
    def _current_key_config(self):
        executor = getattr(og, 'executor', None)
        task = executor.current_task if executor else None
        if task is None and executor is not None:
            tasks = list(getattr(executor, 'onetime_tasks', []) or [])
            task = next((t for t in tasks if hasattr(t, 'key_config')), None)
        if task is None:
            return {}
        try:
            return dict(task.key_config)
        except Exception:
            return {}

    def _current_key_mapping(self):
        return combos_store.build_key_mapping(self._current_key_config())

    def _maybe_refresh_key_config(self):
        cfg = self._current_key_config()
        if cfg and cfg != self._key_config_snapshot:
            logger.info('key_config changed, refreshing preview & conflicts')
            self._key_config_snapshot = dict(cfg)
            self._refresh_preview()
            self._check_conflicts(notify=False)

    # ---------------------------------------------------------- 序列解析预览
    def _refresh_preview(self):
        self.preview_list.clear()
        text = self.text_input.toPlainText()
        if not text.strip():
            self.preview_label.setText('解析预览:')
            return
        sequence, err = combos_store.parse_sequence_text(text)
        if err:
            self.preview_label.setText(f'解析预览: ⚠ {err}')
            return
        mapping = self._current_key_mapping()
        self.preview_label.setText(f'解析预览: {len(sequence)} 条指令（修改请直接改上方文本）')
        for i, item in enumerate(sequence, 1):
            name = item.split('(')[0].strip()
            arg = item.split('(', 1)[1].rstrip(')') if '(' in item else ''
            if name == 'slot':
                label = f'{i}. 切换到角色位 {arg}'
            elif name == 'delay':
                label = f'{i}. 延迟 {arg}ms'
            elif name == 'heavy' and arg:
                label = f'{i}. 重击（长按 {arg}ms）'
            elif name in combos_store.ACTION_NAMES and arg:
                label = f'{i}. {combos_store.ACTION_NAMES[name]} ×{arg}'
            else:
                display = combos_store.ACTION_NAMES.get(name, name)
                key = mapping.get(name, '')
                label = f'{i}. {display}' + (f'  → {key}' if key else '')
            self.preview_list.addItem(label)

    def _current_sequence(self):
        text = self.text_input.toPlainText()
        sequence, err = combos_store.parse_sequence_text(text)
        if err:
            return None, err
        return sequence, ''

    # ---------------------------------------------------------- 冲突检测
    def _game_key_values(self):
        cfg = self._current_key_config()
        values = {str(v).lower() for v in cfg.values() if v}
        values.add('lmb')
        values.add('mouseleft')
        return values

    def _check_conflicts(self, notify=False):
        hotkey = self.hotkey_edit.text().strip()
        self.conflict_label.setText('')
        if not hotkey:
            return []
        if parse_hotkey(hotkey)[1] is None:
            self.conflict_label.setText(f'快捷键格式无效: {hotkey}')
            return [f'快捷键格式无效: {hotkey}']
        conflicts = []
        main_key = hotkey.split('+')[-1].lower()
        if main_key in self._game_key_values():
            conflicts.append(f'与游戏键位冲突: 主键 {main_key} 与当前 key_config 动作键重复')
        for combo in self.combos:
            if combo is self.current_combo:
                continue
            other = (combo.get('hotkey') or '').strip()
            if other and normalize_hotkey(other) == normalize_hotkey(hotkey):
                conflicts.append(f'与其他出招宏「{combo.get("combo_name")}」快捷键重复')
        if not self.hotkey_manager.is_available(hotkey):
            conflicts.append(f'快捷键 {normalize_hotkey(hotkey)} 已被系统或其他程序占用')
        if conflicts:
            self.conflict_label.setText('；'.join(conflicts))
        elif notify:
            show_info_bar(self.window(), '快捷键无冲突，可安全保存', title='检测通过')
        return conflicts

    def _on_hotkey_input(self, text):
        if text:
            self._check_conflicts(notify=False)

    # ---------------------------------------------------------- 列表与选中
    def _refresh_list(self):
        self.combo_list.blockSignals(True)
        self.combo_list.clear()
        for combo in self.combos:
            name = combo.get('combo_name', '')
            binds = []
            if combo.get('bind_role'):
                binds.append(combo['bind_role'])
            if combo.get('bind_team'):
                binds.append('队伍')
            if combo.get('bind_slot'):
                binds.append(f'位{combo["bind_slot"]}')
            hotkey = combo.get('hotkey') or '无热键'
            label = f"{name}  [{hotkey}]" + (f"  ({', '.join(binds)})" if binds else '')
            if not combo.get('enabled', True):
                label = f'（停用）{label}'
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, combo.get('id'))
            self.combo_list.addItem(item)
        self.combo_list.blockSignals(False)
        if self.combo_list.count() > 0 and self.current_combo is None:
            self.combo_list.setCurrentRow(0)

    def _select_combo(self, row):
        if row < 0 or row >= len(self.combos):
            self.current_combo = None
            return
        self.current_combo = self.combos[row]
        self._load_into_editor()

    def _load_into_editor(self):
        combo = self.current_combo
        self._loading = True
        try:
            self.name_edit.setText(combo.get('combo_name', '') if combo else '')
            self.desc_edit.setText(combo.get('description', '') if combo else '')
            text = combos_store.sequence_to_text(combo.get('sequence', [])) if combo else ''
            self.text_input.setPlainText(text)
            role = combo.get('bind_role') or ''
            self.role_combo.setCurrentIndex(max(self.role_combo.findData(role), 0))
            slot = combo.get('bind_slot') or 0
            self.slot_combo.setCurrentIndex(max(self.slot_combo.findData(slot), 0))
            team = combo.get('bind_team') or []
            team_text = ', '.join(team) if team else ''
            idx = self.team_combo.findData(team)
            if idx >= 0:
                self.team_combo.setCurrentIndex(idx)
            else:
                self.team_combo.setEditText(team_text)
            self.hotkey_edit.setText(combo.get('hotkey', '') if combo else '')
            self.count_spin.setValue(int(combo.get('trigger_count') or 0))
            self.mb_spin.setValue(int(combo.get('mb_click_count') or 0) if combo else 2)
            self.interval_spin.setValue(int(combo.get('default_interval_ms') or 120) if combo else 120)
            self.heavy_spin.setValue(int(combo.get('heavy_hold_ms') or 1000) if combo else 1000)
        finally:
            self._loading = False
        self._refresh_preview()
        self.conflict_label.setText('')
        if combo and combo.get('hotkey'):
            self._check_conflicts(notify=False)

    # ---------------------------------------------------------- 新建/保存/删除/复制/导入
    def _new_combo(self):
        combo = combos_store._default_combo()
        combo['id'] = combos_store.new_combo_id()
        combo['combo_name'] = f'新出招表 {len(self.combos) + 1}'
        combo['created'] = combo['updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
        self.combos.append(combo)
        self._refresh_list()
        for row, c in enumerate(self.combos):
            if c is combo:
                self.combo_list.setCurrentRow(row)
                break

    def _save_combo(self):
        combo = self.current_combo
        if combo is None:
            show_info_bar(self.window(), '请先新建或选择一个出招表', title='提示', error=True)
            return
        name = self.name_edit.text().strip()
        if not name:
            show_info_bar(self.window(), '请填写出招表名称', title='提示', error=True)
            return
        sequence, err = self._current_sequence()
        if err:
            show_info_bar(self.window(), err, title='保存失败', error=True)
            return
        hotkey = self.hotkey_edit.text().strip()
        err = combos_store.validate_hotkey_format(hotkey)
        if err:
            show_info_bar(self.window(), err, title='保存失败', error=True)
            return
        if self._check_conflicts(notify=False):
            show_info_bar(self.window(), '存在快捷键冲突，已阻止保存（见红色警告）',
                          title='保存失败', error=True)
            return
        combo['combo_name'] = name[:64]
        combo['description'] = self.desc_edit.text().strip()[:200]
        combo['sequence'] = sequence
        combo['hotkey'] = normalize_hotkey(hotkey)
        combo['bind_role'] = self.role_combo.currentData() or None
        combo['bind_slot'] = int(self.slot_combo.currentData() or 0) or None
        combo['bind_team'] = self._parse_team_text() or None
        combo['trigger_count'] = self.count_spin.value()
        combo['mb_click_count'] = self.mb_spin.value()
        combo['default_interval_ms'] = self.interval_spin.value()
        combo['heavy_hold_ms'] = self.heavy_spin.value()
        combo['updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
        combo['enabled'] = True
        combos_store.save_combos(self.combos)
        self._register_all_hotkeys()
        self._refresh_list()
        show_info_bar(self.window(), f'出招表「{name}」已保存', title='成功')

    def _delete_combo(self):
        combo = self.current_combo
        if combo is None:
            return
        box = QMessageBox.question(self, '删除出招表',
                                   f'确定删除「{combo.get("combo_name")}」吗？')
        if box != QMessageBox.Yes:
            return
        self.combos.remove(combo)
        self.hotkey_manager.unregister(combo.get('id'))
        self.current_combo = None
        combos_store.save_combos(self.combos)
        self._refresh_list()

    def _copy_combo(self):
        combo = self.current_combo
        if combo is None:
            return
        text = combos_store.combo_to_share_text(combo, key_mapping=self._current_key_mapping())
        QApplication.clipboard().setText(text)
        show_info_bar(self.window(), '出招表（含键位映射）已复制到剪贴板', title='已复制')

    def _import_combo(self):
        text = QApplication.clipboard().text().strip()
        if not text:
            show_info_bar(self.window(), '剪贴板为空', title='导入失败', error=True)
            return
        try:
            combo = combos_store.combo_from_share_text(text)
        except combos_store.ComboValidationError as e:
            show_info_bar(self.window(), str(e), title='导入失败', error=True)
            return
        diff = combos_store.format_mapping_diff(combo.get('key_mapping'),
                                                self._current_key_mapping())
        self.combos.append(combo)
        combos_store.save_combos(self.combos)
        self._refresh_list()
        for row, c in enumerate(self.combos):
            if c is combo:
                self.combo_list.setCurrentRow(row)
                break
        message = f'已导入出招表「{combo["combo_name"]}」'
        if diff:
            message = message + f'；键位差异: {diff}'
        show_info_bar(self.window(), message, title='成功')

    def _parse_team_text(self):
        """解析队伍输入框（可编辑）：逗号/空格分隔的角色名列表。"""
        text = self.team_combo.currentText().strip()
        if not text or text == '（任意）':
            return None
        names = [p.strip() for p in text.replace('，', ',').split(',') if p.strip()]
        return names or None

    # ---------------------------------------------------------- 热键管理
    def _register_all_hotkeys(self):
        for combo in self.combos:
            hotkey = (combo.get('hotkey') or '').strip()
            if not hotkey or not combo.get('enabled', True):
                self.hotkey_manager.unregister(combo.get('id'))
                continue
            err = self.hotkey_manager.register(combo.get('id'), hotkey)
            if err:
                logger.warning(f"hotkey register failed for {combo.get('combo_name')}: {err}")

    def _on_hotkey(self, combo_id):
        combo = next((c for c in self.combos if c.get('id') == combo_id), None)
        if combo is None:
            return
        logger.info(f'hotkey triggered for combo {combo.get("combo_name")}')
        self.combo_runner.trigger(combo)

    # ---------------------------------------------------------- 询问 AI
    def _copy_ai_prompt(self):
        """复制『语法+实际按键+切换规则』提示词到剪贴板，供粘贴给 AI 生成连招。"""
        mapping = self._current_key_mapping()
        prompt = (
            '你是一名鸣潮(ok-ww)出招宏转换器。用户会用自然语言描述一套连招，'
            '请严格转换为 OKCombo v2 语法字符串。\n'
            '\n'
            '===== 语法参考 =====\n'
            '逐字符解析，大小写不敏感；空格/逗号为可选分隔符。\n'
            '· 裸数字 1/2/3（动作前）= 切换角色位（切到几号位就写几）\n'
            f"· 动作字母: A=普通攻击({mapping.get('attack')})  H=重击({mapping.get('heavy')})  "
            f"E=共鸣技能({mapping.get('resonance')})  Q=声骸技能({mapping.get('echo')})  "
            f"R=解放技能({mapping.get('liberation')})  T=工具键({mapping.get('tool')})  "
            f"J=跳跃({mapping.get('jump')})  F=处决({mapping.get('finisher')})\n"
            '· 重复次数 = 字母后括号/乘号：A(3) 或 A×3 = 普攻3次（必须括号，裸数字不表示重复）\n'
            '· H 后裸数字 = 重击长按毫秒（H800 = 长按800ms；H 无数字=默认长按1秒）\n'
            '· D<毫秒> = 显式延迟（如 D500 = 等待500ms）\n'
            '\n'
            '===== 角色切换规则 =====\n'
            '目标位 = 当前位循环下一个(1→2, 2→3, 3→1)时走智能切换；跨度>1 直接数字键直切。\n'
            '切到角色位后紧跟的动作即该角色执行（如 2E = 切到2号位放共鸣）。\n'
            '同一角色连续动作只需写一次角色位（如 2EQ = 切到2号位，共鸣+声骸）。\n'
            '\n'
            '===== 转换规则（必须遵守） =====\n'
            '1. 只输出语法字符串本身：不要解释、不要代码块、不要引号、不要前缀词。\n'
            '2. 每个动作前带上执行角色位（默认当前角色位为 1，切换时写目标位数字）。\n'
            '3. 描述中的次数词（两下/三次/连打/连点）转成括号重复，如 A(3)；单次可省略。\n'
            '4. 描述中的蓄力/长按/按住：重击用 H+毫秒；技能一律单次。\n'
            '5. 描述中的等待/停顿/间隔/等冷却才用 D，数值按直觉给 200-800ms；'
            '动作间的自然节奏不要加 D（工具自动按默认间隔执行）。\n'
            '6. 按描述顺序拼接；**切角色位的数字与前一动作之间用空格分隔**'
            '（如 2E 3Q，避免歧义；H 紧贴数字=重击长按，如 H800）。\n'
            '7. 重复次数上限 20。\n'
            '\n'
            '===== 示例 =====\n'
            '自然语言 → 输出\n'
            '"当前角色平A三下，然后重击" → 1A(3)H\n'
            '"切到2号位放共鸣技能，再切到3号位放声骸" → 2E 3Q\n'
            '"角色1解放，等0.5秒，切2共鸣，切3声骸，回1普攻两下" → 1R D500 2E 3Q 1A(2)\n'
            '"当前角色重击蓄力接跳跃，再普攻两下" → 1H800 J 1A(2)\n'
            '"循环: 普攻两下，重击，切下一角色放共鸣" → 1A(2)H 2E\n'
            '\n'
            '===== 当前键位 =====\n'
            f"A:{mapping.get('attack')} H:{mapping.get('heavy')} E:{mapping.get('resonance')} "
            f"Q:{mapping.get('echo')} R:{mapping.get('liberation')} T:{mapping.get('tool')} "
            f"J:{mapping.get('jump')} F:{mapping.get('finisher')}\n"
            '（对方机器键位不同时执行自动适配，输出只需按语义转换）\n'
            '\n'
            '===== 用户连招需求 =====\n'
            '<在这里粘贴自然语言描述的连招>'
        )
        QApplication.clipboard().setText(prompt)
        show_info_bar(self.window(),
                      'AI 提示词已复制（含当前键位映射与切换规则），粘贴给 AI 即可',
                      title='已复制')

    # ---------------------------------------------------------- 其他
    def _all_teams(self):
        teams = []
        try:
            teams.extend(list_custom_teams())
        except Exception as e:
            logger.debug(f'list_custom_teams failed: {e}')
        executor = getattr(og, 'executor', None)
        if executor is not None:
            for task in list(getattr(executor, 'onetime_tasks', []) or []):
                chars = [getattr(c, 'name', '') for c in getattr(task, 'chars', []) if c]
                if chars and chars not in teams:
                    teams.append(chars)
        return teams

    def _open_char_editor(self):
        dialog = CharCodeDialog(self.window())
        dialog.exec()

    def closeEvent(self, event):
        self.hotkey_manager.unregister_all()
        super().closeEvent(event)
