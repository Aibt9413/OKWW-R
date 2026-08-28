"""本地构建脚本 — 使用 PyInstaller 打包 OKWW-R"""
import os
import sys

DEPS = os.path.join(os.path.dirname(__file__), '..', '..', '.deps')
REPO = os.path.dirname(__file__)

# 将 .deps 加入 sys.path，让 PyInstaller 能找到所有依赖
for p in [DEPS, os.path.join(DEPS, 'win32'), os.path.join(DEPS, 'win32', 'lib'),
          os.path.join(DEPS, 'Pythonwin'), REPO]:
    if os.path.isdir(p):
        sys.path.insert(0, p)

for d in [DEPS, os.path.join(DEPS, 'pywin32_system32'), os.path.join(DEPS, 'win32')]:
    if os.path.isdir(d):
        try:
            os.add_dll_directory(d)
        except Exception:
            pass

import PyInstaller.__main__

args = [
    'main.py',
    '--name=OKWW-R',
    '--noconfirm',
    '--onedir',
    '--windowed',
    f'--paths={DEPS}',
    f'--paths={os.path.join(DEPS, "win32")}',
    f'--paths={os.path.join(DEPS, "win32", "lib")}',
    f'--paths={REPO}',
    f'--paths={os.path.join(REPO, "src")}',
    # 数据文件
    f'--add-data=assets;assets',
    f'--add-data=icons;icons',
    f'--add-data=i18n;i18n',
    f'--add-data=config.py;.',
    f'--add-data=requirements.txt;.',
    # 隐藏导入
    '--hidden-import=PySide6.QtWidgets',
    '--hidden-import=PySide6.QtCore',
    '--hidden-import=PySide6.QtGui',
    '--hidden-import=PySide6.QtSvg',
    '--hidden-import=PySide6.QtSvgWidgets',
    '--hidden-import=qfluentwidgets',
    '--hidden-import=cv2',
    '--hidden-import=numpy',
    '--hidden-import=onnxruntime',
    '--hidden-import=PIL',
    # 排除不需要的大包
    '--exclude-module=tkinter',
    '--exclude-module=matplotlib',
    # 图标
    '--icon=icons/icon.ico' if os.path.isfile(os.path.join(REPO, 'icons', 'icon.ico')) else '',
    '--collect-all=qfluentwidgets',
    '--collect-all=ok',
]

# 过滤空参数
args = [a for a in args if a]

print(f'PyInstaller args: {len(args)} items')
print(f'DEPS: {DEPS}')
print(f'REPO: {REPO}')

PyInstaller.__main__.run(args)
