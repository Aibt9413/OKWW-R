"""自定义出招宏面板 — 数据层。"""

import json
import re
import shutil
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
COMBOS_FILE = REPO_ROOT / 'config' / 'custom_combos.json'

# 动作指令白名单（存储/解析统一格式）
ACTION_NAMES = {
    'attack': '普通攻击',
    'heavy': '重击',
    'resonance': '共鸣技能',
    'echo': '声骸技能',
    'liberation': '解放技能',
    'tool': '工具键',
    'jump': '跳跃',
    'finisher': '处决',
    'switch': '切换下一角色',
}

# 文本语法字母映射
TEXT_LETTER_MAP = {
    'A': 'attack',
    'E': 'resonance',
    'Q': 'echo',
    'R': 'liberation',
    'T': 'tool',
    'H': 'heavy',
    'J': 'jump',
    'F': 'finisher',
}

HOTKEY_RE = re.compile(r'^(?:(Ctrl|Alt|Shift|Win)\+)*(.+)$', re.IGNORECASE)


class ComboValidationError(Exception):
    pass


def combos_file_path() -> Path:
    return COMBOS_FILE


def _default_combo():
    return {
        'id': '',
        'combo_name': '',
        'bind_role': None,      # 角色类名，如 "Jinhsi"
        'bind_team': None,      # 队伍角色名列表（任意顺序）
        'bind_slot': None,      # 角色位 1/2/3
        'sequence': [],         # ["resonance", "delay(200)", ...] / ["slot(1)", "attack", ...]
        'hotkey': '',
        'trigger_count': 0,     # 0 = 不限次数
        'mb_click_count': 2,    # 执行前鼠标中键点击次数（0 = 不点击）
        'default_interval_ms': 120,  # 指令间默认间隔（无 Dxxx 时自动等待）
        'heavy_hold_ms': 1000,  # 重击（H 无数字时）默认长按时长，毫秒
        'description': '',      # 自定义招数描述
        'key_mapping': None,    # 分享时附带的 语法字母->实际按键 映射
        'enabled': True,
        'created': '',
        'updated': '',
    }


# 语法字母 -> 动作名 展示名（用于映射表）
MAPPING_LABELS = {
    'attack': '普通攻击',
    'heavy': '重击',
    'resonance': '共鸣技能',
    'echo': '声骸技能',
    'liberation': '解放技能',
    'tool': '工具键',
    'jump': '跳跃',
    'finisher': '处决',
    'slot': '角色切换',
}


def finisher_key(key_config: dict) -> str:
    """处决键：优先动态读取，缺省按项目现有实现为 f。"""
    return str(key_config.get('F Key') or key_config.get('Finisher Key') or 'f')


def build_key_mapping(key_config: dict) -> dict:
    """由 key_config 生成 动作 -> 实际按键 的映射表（发送方视角）。"""
    return {
        'attack': '鼠标左键（点按）',
        'heavy': '鼠标左键（长按）',
        'resonance': str(key_config.get('Resonance Key', '?')),
        'echo': str(key_config.get('Echo Key', '?')),
        'liberation': str(key_config.get('Liberation Key', '?')),
        'tool': str(key_config.get('Tool Key', '?')),
        'jump': str(key_config.get('Jump Key', '?')),
        'finisher': finisher_key(key_config),
        'slot': '数字键 1/2/3（跨度1走智能切换）',
    }


def format_mapping_diff(sender_mapping: dict, local_mapping: dict) -> str:
    """发送方与本地键位映射差异说明；一致返回空串。"""
    if not sender_mapping:
        return ''
    diffs = []
    for action, label in MAPPING_LABELS.items():
        s = sender_mapping.get(action)
        l = (local_mapping or {}).get(action)
        if s and l and str(s) != str(l):
            diffs.append(f'{label}: 发送方[{s}] → 你的[{l}]（执行时自动适配）')
    return '；'.join(diffs)


def load_combos() -> list:
    try:
        with open(COMBOS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        combos = data.get('combos', []) if isinstance(data, dict) else data
        return [c for c in combos if isinstance(c, dict)]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def save_combos(combos: list):
    COMBOS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(COMBOS_FILE, 'w', encoding='utf-8') as f:
        json.dump({'combos': combos}, f, ensure_ascii=False, indent=2)


def new_combo_id() -> str:
    return f'{int(time.time() * 1000)}'


def validate_sequence(sequence: list) -> str:
    """返回空字符串表示合法，否则返回错误描述。"""
    if not sequence:
        return '出招序列不能为空'
    for item in sequence:
        if isinstance(item, str) and item:
            name = item.split('(')[0].strip()
            if name in ('delay', 'slot'):
                continue
            if name not in ACTION_NAMES:
                return f'未知指令: {item}'
            if '(' in item:
                arg = item.split('(', 1)[1].rstrip(')').strip()
                if not arg.isdigit():
                    return f'非法参数: {item}'
                max_allowed = 5000 if name == 'heavy' else 20
                if int(arg) > max_allowed:
                    return f'非法参数: {item}（数值上限 {max_allowed}）'
        else:
            return f'非法指令: {item!r}'
    return ''


def validate_hotkey_format(hotkey: str) -> str:
    if not hotkey:
        return '未设置触发快捷键'
    if not HOTKEY_RE.match(hotkey):
        return f'快捷键格式无效: {hotkey}'
    return ''


def parse_sequence_text(text: str) -> tuple:
    """解析文本语法（OKCombo v2.1，无歧义）。

    语法（逐字符，大小写不敏感，空格/逗号为可选分隔符）：
      裸数字 1/2/3（动作字母前） = 切换角色位
      动作字母   = A攻击 H重击 E共鸣 Q声骸 R解放 T工具 J跳跃 F处决
      重复次数   = 字母后括号/乘号：A(3)、A×3、A*3（仅此写法，裸数字不表示重复）
      重击长按   = H<毫秒>，如 H800（H 后裸数字为长按时长）
      D<毫秒>    = 延迟，如 D300 / delay(300)
    例：'1A(3)H800 2E3Q' = 切位1，普攻3次，重击长按800ms，切位2共鸣，切位3声骸
    返回 (sequence_list, error)。
    """
    sequence = []
    text = (text or '').strip().upper()
    if not text:
        return [], '输入为空'
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in ' \t,;':
            i += 1
        elif ch in '123':
            sequence.append(f'slot({ch})')
            i += 1
        elif ch.isdigit():
            return [], f'角色位只支持 1/2/3（收到 "{ch}"）；重复次数请用括号，如 A(3)'
        elif ch in TEXT_LETTER_MAP:
            action = TEXT_LETTER_MAP[ch]
            i += 1
            repeat = 1
            hold_ms = 0
            if i < n and text[i] == '(':
                k = text.find(')', i)
                if k > i and text[i + 1:k].strip().isdigit():
                    num = int(text[i + 1:k].strip())
                    if num > 20:
                        return [], f'重复次数上限 20（收到 {num}）'
                    repeat = num
                    i = k + 1
                else:
                    return [], f'括号内需为数字，如 A(3)'
            elif i < n and text[i] in '×X*':
                j = i + 1
                num = ''
                while j < n and text[j].isdigit():
                    num += text[j]
                    j += 1
                if num:
                    num = int(num)
                    if num > 20:
                        return [], f'重复次数上限 20（收到 {num}）'
                    repeat = num
                    i = j
                else:
                    return [], f'乘号后需跟数字，如 A×3'
            elif action == 'heavy':
                j = i
                while j < n and text[j].isdigit():
                    j += 1
                if j > i:
                    hold_ms = int(text[i:j])
                    if hold_ms > 5000:
                        return [], f'重击长按时长上限 5000ms（收到 {hold_ms}）'
                    i = j
            elif i < n and text[i].isdigit():
                return [], (f'动作 "{ch}" 后紧跟数字有歧义：'
                            f'切角色位请用空格分隔（如 {ch} 3Q），'
                            f'重复次数请用括号（如 {ch}(3)）')
            if repeat > 1:
                sequence.append(f'{action}({repeat})')
            elif hold_ms:
                sequence.append(f'heavy({hold_ms})')
            else:
                sequence.append(action)
        elif ch == 'D':
            j = i + 1
            num = ''
            while j < n and text[j].isdigit():
                num += text[j]
                j += 1
            if num:
                sequence.append(f'delay({int(num)})')
                i = j
            elif text.startswith('DELAY(', i):
                k = text.find(')', i)
                if k > i and text[i + 6:k].strip().isdigit():
                    sequence.append(f'delay({int(text[i + 6:k].strip())})')
                    i = k + 1
                else:
                    return [], 'delay 后需跟毫秒数，如 D300 或 delay(300)'
            else:
                return [], f'无法识别的字符 "{ch}"（延迟请用 D300）'
        else:
            return [], (f'无法识别的字符 "{ch}"'
                        f'（可用 1/2/3 与 A/E/Q/R/T/H/J/F，延迟用 D300）')
    return sequence, ''


def sequence_to_text(sequence: list) -> str:
    """将序列列表转回文本，且往返无歧义。

    slot 项前自动补空格（首个除外），避免动作后紧跟切位数字（如 2E3Q）
    被解析器判定为歧义；其余项与项之间天然可区分。
    """
    out = []
    for idx, item in enumerate(sequence):
        name = item.split('(')[0].strip()
        arg = item.split('(', 1)[1].rstrip(')') if '(' in item else ''
        if name == 'slot':
            if idx > 0:
                out.append(' ')
            out.append(arg)
        elif name == 'delay':
            out.append(f'D{arg}')
        elif name == 'heavy' and arg:
            out.append(f'H{arg}')
        elif name in TEXT_LETTER_MAP.values():
            letter = next(k for k, v in TEXT_LETTER_MAP.items() if v == name)
            out.append(letter + (f'({arg})' if arg else ''))
        else:
            return ''
    return ''.join(out)


def combo_to_share_text(combo: dict, key_mapping: dict = None) -> str:
    """生成用于复制分享的 JSON 文本。

    key_mapping 为可选的动作->实际按键映射（由发送方 key_config 生成），
    让接收方直接看到这套宏对应按的键。
    """
    payload = {k: combo.get(k) for k in ('combo_name', 'bind_role', 'bind_team',
                                         'bind_slot', 'sequence', 'hotkey',
                                         'trigger_count', 'mb_click_count',
                                         'default_interval_ms', 'heavy_hold_ms',
                                         'description')}
    if key_mapping:
        payload['key_mapping'] = key_mapping
    return json.dumps(payload, ensure_ascii=False, indent=2)


def combo_from_share_text(text: str) -> dict:
    """从分享文本导入一个出招表；非法时抛 ComboValidationError。"""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        raise ComboValidationError(f'无效的 JSON: {e}')
    if not isinstance(payload, dict) or not payload.get('combo_name'):
        raise ComboValidationError('缺少 combo_name')
    sequence = payload.get('sequence')
    if not isinstance(sequence, list):
        raise ComboValidationError('sequence 必须是列表')
    err = validate_sequence(sequence)
    if err:
        raise ComboValidationError(err)
    combo = _default_combo()
    combo['id'] = new_combo_id()
    combo['combo_name'] = str(payload['combo_name'])[:64]
    combo['bind_role'] = payload.get('bind_role')
    combo['bind_team'] = payload.get('bind_team')
    combo['bind_slot'] = payload.get('bind_slot')
    combo['sequence'] = sequence
    combo['hotkey'] = payload.get('hotkey') or ''
    combo['trigger_count'] = int(payload.get('trigger_count') or 0)
    combo['mb_click_count'] = int(payload.get('mb_click_count') or 0)
    combo['default_interval_ms'] = int(payload.get('default_interval_ms') or 120)
    combo['heavy_hold_ms'] = int(payload.get('heavy_hold_ms') or 1000)
    combo['description'] = str(payload.get('description') or '')
    combo['key_mapping'] = payload.get('key_mapping') or None
    combo['created'] = combo['updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
    return combo
