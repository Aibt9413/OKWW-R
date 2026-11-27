"""
IMAO CoreHost 管道客户端。

IMAO 的架构是双进程：WinUI（控制界面）+ CoreHost（WGC 采集 / YOLO 定位 / ImGui 叠加层）。
CoreHost 通过命名管道接受单客户端 JSON 命令（换行分隔，version=1）。

本模块让 SonicCore 直接成为 CoreHost 的控制端 —— 不启动 IMAO WinUI，
由 SC 自己启动 CoreHost 并收发命令，从而把完整控制能力放进 SC 的页面。

协议（来自 IMAO 源码 IMao-Core/src/CoreHost/CoreHostMain.cpp v1）：
  - CoreHost 端：CreateNamedPipeW(\\\\.\\pipe\\<name>)，单客户端
  - 消息：JSON + '\\n'，UTF-8
  - 命令：{"version":1,"type":"hello|configure|start|stop|...","requestId":"<guid>", ...}
  - 响应：{"version":1,"type":"ack","requestId":"...","accepted":bool,"message":"...","data":{}}
  - 事件：type=status（每 200ms）/ log / markerResult / routePlanning 等
"""
import json
import os
import subprocess
import threading
import time
import uuid

logger = None
try:
    from ok import Logger
    logger = Logger.get_logger(__name__)
except Exception:
    import logging
    logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
DEFAULT_CONNECT_TIMEOUT = 8.0


class CoreHostClient:
    """IMAO CoreHost 客户端：启动进程 + 管道连接 + 命令 + 事件回调。"""

    def __init__(self, host_dir, env=None, resource_snapshot=None):
        self.host_dir = host_dir
        self.env = env
        self.resource_snapshot = resource_snapshot
        self.proc = None
        self.pipe_name = None
        self._client = None
        self._reader = None
        self._writer = None
        self._read_thread = None
        self._stop = threading.Event()
        self._pending = {}          # requestId -> threading.Event + result
        self._lock = threading.Lock()
        self._status = {}           # 最新 status 事件
        self.on_status = None       # callback(dict)
        self.on_log = None          # callback(dict)
        self.on_event = None        # callback(dict) 通用事件
        self.last_error = ''

    # ── 生命周期 ──────────────────────────────────────────────────────
    def start(self, timeout=DEFAULT_CONNECT_TIMEOUT):
        """启动 CoreHost 并建立管道连接，完成 hello 握手。返回是否成功。"""
        import win32pipe
        import win32file

        exe = os.path.join(self.host_dir, 'IMao-CoreHost.exe')
        if not os.path.isfile(exe):
            self.last_error = 'CoreHost 不存在'
            return False

        self.pipe_name = 'IMao.CoreHost.%d.%s' % (os.getpid(), uuid.uuid4().hex)
        full = '\\\\.\\pipe\\' + self.pipe_name
        try:
            # CREATE_NO_WINDOW：CoreHost 是 Console 子系统，不加这个会弹黑窗口。
            # 实测不影响命名管道握手（连接/hello/status 全部正常）。
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            args = [exe, '--pipe', self.pipe_name]
            if self.resource_snapshot and os.path.isfile(self.resource_snapshot):
                args += ['--resource-snapshot', self.resource_snapshot]
            self.proc = subprocess.Popen(
                args, cwd=self.host_dir, env=self.env, creationflags=flags)
        except Exception as e:
            self.last_error = f'启动 CoreHost 失败: {e}'
            return False

        # 连接到 CoreHost 创建的管道（它启动后创建，最多等 timeout 秒）
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                self.last_error = f'CoreHost 提前退出: {self.proc.returncode}'
                return False
            try:
                self._client = win32file.CreateFile(
                    full, win32file.GENERIC_READ | win32file.GENERIC_WRITE, 0, None,
                    win32file.OPEN_EXISTING, 0, None)
                break
            except Exception:
                time.sleep(0.15)
        if self._client is None:
            self.last_error = '连接 CoreHost 管道超时'
            return False

        # win32file 返回的不是标准 file object，用线程直接 ReadFile 拼行
        self._stop.clear()
        self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._read_thread.start()

        # hello 握手
        ack = self.send('hello', {}, timeout=5)
        if not ack or not ack.get('accepted'):
            self.last_error = 'CoreHost 握手被拒: %s' % ((ack or {}).get('message'),)
            self.stop()
            return False
        logger.info('IMAO CoreHost 已连接: ' + str(ack.get('data') or {}))
        return True

    def _read_loop(self):
        import win32file
        buf = ''
        while not self._stop.is_set():
            try:
                hr, data = win32file.ReadFile(self._client, 65536)
                if not data:
                    break
                buf += data.decode('utf-8', errors='replace')
                while '\n' in buf:
                    line, buf = buf.split('\n', 1)
                    line = line.rstrip('\r')
                    if line:
                        self._handle_event(line)
            except Exception:
                break

    def _handle_event(self, line):
        try:
            ev = json.loads(line)
        except Exception:
            return
        etype = ev.get('type')
        if etype == 'ack':
            rid = ev.get('requestId')
            with self._lock:
                slot = self._pending.pop(rid, None)
            if slot:
                slot['result'] = ev
                slot['event'].set()
        elif etype == 'status':
            self._status = ev
            if self.on_status:
                try: self.on_status(ev)
                except Exception: pass
        elif etype == 'log':
            if self.on_log:
                try: self.on_log(ev)
                except Exception: pass
        if self.on_event:
            try: self.on_event(ev)
            except Exception: pass

    def send(self, cmd_type, payload=None, timeout=10.0):
        """发送命令并等待 ack；返回 ack dict 或 None。"""
        import win32file
        if self._client is None:
            return None
        rid = uuid.uuid4().hex
        msg = dict(payload or {})
        msg.update({'version': PROTOCOL_VERSION, 'type': cmd_type, 'requestId': rid})
        slot = {'event': threading.Event(), 'result': None}
        with self._lock:
            self._pending[rid] = slot
        try:
            data = (json.dumps(msg, ensure_ascii=False) + '\n').encode('utf-8')
            win32file.WriteFile(self._client, data)
            if not slot['event'].wait(timeout):
                with self._lock:
                    self._pending.pop(rid, None)
                return None
            return slot['result']
        except Exception as e:
            with self._lock:
                self._pending.pop(rid, None)
            self.last_error = str(e)
            return None

    def configure(self, config_payload):
        return self.send('configure', config_payload)

    def start_capture(self, capture_target=None):
        payload = {'captureTarget': capture_target} if capture_target else {}
        return self.send('start', payload)

    def stop_capture(self):
        return self.send('stop')

    def set_items(self, add=None, remove=None):
        payload = {}
        if add: payload['add'] = list(add)
        if remove: payload['remove'] = list(remove)
        return self.send('setItems', payload)

    def set_overlay_hidden(self, hidden=True):
        return self.send('setOverlayHidden', {'hidden': bool(hidden)})

    def route_planning(self, action, arguments=None):
        """路线规划：action 如 'plan'/'clear'/'undo' 等，参数见 IMAO RoutePlanningService。"""
        payload = dict(arguments or {})
        payload['action'] = action
        return self.send('routePlanning', payload)

    def set_diagnostics_capture(self, enabled):
        return self.send('setDiagnosticsCapture', {'enabled': bool(enabled)})

    def shutdown(self):
        """请求 CoreHost 正常退出（比直接 kill 干净）。"""
        return self.send('shutdown', {})

    @property
    def status(self):
        return dict(self._status)

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        # 顺序很重要：先发正常退出命令（此时 _client 仍有效），
        # 再停读线程/关句柄，最后才终止进程。旧顺序先关句柄导致 send 永远无效。
        if self._client is not None and self.proc is not None and self.proc.poll() is None:
            try:
                self.send('shutdown', timeout=1) or self.send('stop', timeout=1)
            except Exception:
                pass
        self._stop.set()
        try:
            if self._client is not None:
                import win32file
                win32file.CloseHandle(self._client)
        except Exception:
            pass
        self._client = None
        if self._read_thread is not None and self._read_thread.is_alive():
            try:
                self._read_thread.join(timeout=1)
            except Exception:
                pass
        if self.proc is not None and self.proc.poll() is None:
            try: self.proc.terminate()
            except Exception: pass
            try: self.proc.wait(timeout=3)
            except Exception:
                try: self.proc.kill()
                except Exception: pass
        self.proc = None
