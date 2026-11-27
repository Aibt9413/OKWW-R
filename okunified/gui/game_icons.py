"""
游戏图标解析。

「设置 → 游戏」里每个游戏显示真实图标而不是 emoji。取图顺序：

  1. 启动器缓存      ``<启动器根>/icons/games/<game_key>.png``
  2. 游戏项目自带    ``<game_path>/icons/icon.png`` → 拷进缓存
  3. 网络下载        ``GAMES[key]['icon_url']``（在 config.py 里配置，默认留空）

三步都拿不到就退回 emoji（``icon_emoji``），所以离线、没配 URL 也照常能用。

注意：解析/下载是阻塞的，必须放到后台线程跑；本模块内部一律用 QImage 而不是
QPixmap —— QPixmap 只能在 GUI 线程里用，QImage 可以跨线程。
"""
import os
import threading
import urllib.request

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPainterPath, QColor

from ok import Logger

from okunified.gui.home_state import LAUNCHER_ROOT

logger = Logger.get_logger(__name__)

ICON_DIR = os.path.join(LAUNCHER_ROOT, 'icons', 'games')

# 游戏项目里可能放图标的位置，按优先级
_LOCAL_SUBPATHS = (
    os.path.join('icons', 'icon.png'),
    'icon.png',
    os.path.join('icons', 'icon.ico'),
    'icon.ico',
)

_DOWNLOAD_TIMEOUT = 12
_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) SonicCore/0.1'


# ── 路径 ──────────────────────────────────────────────────────────────

def cache_path(game_key):
    return os.path.join(ICON_DIR, f'{game_key}.png')


def cached_icon_path(game_key):
    """缓存里已有的图标，没有返回 None。"""
    path = cache_path(game_key)
    return path if os.path.isfile(path) else None


def local_icon_candidates(game_info):
    """游戏项目自带的图标文件。"""
    base = game_info.get('path') or ''
    if not base or not os.path.isdir(base):
        return
    for rel in _LOCAL_SUBPATHS:
        candidate = os.path.join(base, rel)
        if os.path.isfile(candidate):
            yield candidate


# ── 转换与下载 ────────────────────────────────────────────────────────

def _write_png(image: QImage, dest: str) -> bool:
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        return bool(image.save(dest, 'PNG'))
    except Exception as e:
        logger.warning(f'写入图标缓存失败 {dest}: {e}')
        return False


def _import_local(source: str, dest: str) -> bool:
    image = QImage(source)
    if image.isNull():
        return False
    return _write_png(image, dest)


def _download(url: str) -> QImage:
    request = urllib.request.Request(url, headers={'User-Agent': _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as response:
        data = response.read()
    if not data:
        return QImage()
    image = QImage()
    if not image.loadFromData(data):
        logger.warning(f'下载到的内容不是图片: {url}')
        return QImage()
    return image


def resolve_icon(game_key, game_info, allow_download=True):
    """返回可用图标路径；都拿不到返回 None。**阻塞**，请在后台线程调用。"""
    cached = cached_icon_path(game_key)
    if cached:
        return cached

    dest = cache_path(game_key)
    for candidate in local_icon_candidates(game_info):
        if _import_local(candidate, dest):
            logger.info(f'[{game_key}] 图标取自游戏项目: {candidate}')
            return cached_icon_path(game_key)

    url = (game_info.get('icon_url') or '').strip()
    if not (allow_download and url):
        if not url:
            logger.debug(f'[{game_key}] 未配置 icon_url，跳过网络下载')
        return None

    try:
        image = _download(url)
        if not image.isNull() and _write_png(image, dest):
            logger.info(f'[{game_key}] 图标下载成功: {url}')
            return cached_icon_path(game_key)
    except Exception as e:
        logger.warning(f'[{game_key}] 图标下载失败（保留 emoji 兜底）: {e}')
    return None


def clear_cache(game_key=None):
    """删掉缓存，下次重新走"本地 → 网络"。"""
    if game_key:
        path = cache_path(game_key)
        if os.path.isfile(path):
            os.remove(path)
        return
    if os.path.isdir(ICON_DIR):
        for name in os.listdir(ICON_DIR):
            if name.endswith('.png'):
                try:
                    os.remove(os.path.join(ICON_DIR, name))
                except OSError:
                    pass


# ── 显示 ──────────────────────────────────────────────────────────────

def rounded_pixmap(path, size=36, radius=8):
    """把图标缩放到 size×size 并切圆角，返回 QPixmap；失败返回 None。"""
    from PySide6.QtGui import QPixmap

    source = QPixmap(path)
    if source.isNull():
        return None
    scaled = source.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    canvas = QPixmap(size, size)
    canvas.fill(QColor(0, 0, 0, 0))
    painter = QPainter(canvas)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addRoundedRect(0, 0, size, size, radius, radius)
    painter.setClipPath(clip)
    painter.drawPixmap((size - scaled.width()) // 2,
                       (size - scaled.height()) // 2, scaled)
    painter.end()
    return canvas


# ── 后台加载 ──────────────────────────────────────────────────────────

class GameIconLoader(QObject):
    """在后台线程里解析图标，完成后用信号把结果交回 GUI 线程。"""

    icon_ready = Signal(str, str)  # game_key, icon_path

    def load_async(self, games, allow_download=True):
        for game_key, game_info in games.items():
            threading.Thread(
                target=self._load_one,
                args=(game_key, game_info, allow_download),
                name=f'GameIcon-{game_key}',
                daemon=True,
            ).start()

    def _load_one(self, game_key, game_info, allow_download):
        try:
            path = resolve_icon(game_key, game_info, allow_download=allow_download)
        except Exception as e:
            logger.warning(f'[{game_key}] 图标解析异常: {e}')
            return
        if path:
            # 跨线程 emit，Qt 会自动排队到 GUI 线程
            self.icon_ready.emit(game_key, path)
