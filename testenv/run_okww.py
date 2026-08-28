"""Launch the OK-WW Qt window.

Two dependency modes:
  1. .deps/ exists  → use bundled deps (portable, zero-install)
  2. .deps/ missing → use pip-installed packages (requires `pip install -r requirements.txt`)

All paths are relative to the workspace root (parent of testenv/).
"""
import os
import sys
import ctypes

# ---------------------------------------------------------------------------
# Resolve all paths relative to workspace root (= parent of this script dir)
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(SCRIPT_DIR)

DEPS = os.path.join(WORKSPACE, '.deps')
PY_DIR = os.path.join(WORKSPACE, 'python-win')
REPO = os.path.join(WORKSPACE, 'ok-wuthering-waves-master', 'ok-wuthering-waves-master')
PORTABLE_MODE = os.path.isdir(DEPS)

# ---------------------------------------------------------------------------
# Environment diagnostics
# ---------------------------------------------------------------------------
def _check_env():
    """Pre-flight checks with actionable suggestions."""
    errors = []

    # 1. Python runtime
    if not os.path.isfile(os.path.join(PY_DIR, 'python.exe')):
        errors.append(f'[ERROR] Python runtime not found:\n  {PY_DIR}\n'
                       '  -> Download Python 3.11 embeddable and extract to python-win/')

    # 2. Repo directory
    if not os.path.isdir(REPO):
        errors.append(f'[ERROR] OKWW source not found:\n  {REPO}')

    # 3. VC++ Runtime (pywin32 / numpy need it)
    try:
        ctypes.CDLL('vcruntime140.dll')
    except OSError:
        errors.append('[WARN] Visual C++ Runtime (VCRUNTIME140.dll) not found.\n'
                       '  -> Download and install: https://aka.ms/vs/17/release/vc_redist.x64.exe')

    # 4. Check critical deps
    if PORTABLE_MODE:
        for pkg_dir in ('ok', 'qfluentwidgets', 'numpy', 'cv2'):
            pkg_path = os.path.join(DEPS, pkg_dir)
            if not os.path.exists(pkg_path):
                errors.append(f'[WARN] Missing package in .deps: {pkg_dir}')
    else:
        # pip mode: try importing critical packages
        for mod in ('numpy', 'cv2', 'PySide6', 'ok'):
            try:
                __import__(mod)
            except ImportError:
                errors.append(f'[ERROR] Missing pip package: {mod}\n'
                               '  -> Run: python-win\\python.exe -m pip install -r requirements.txt')

    if errors:
        print('=' * 60)
        print('  OKWW-R Environment Diagnostics')
        print('=' * 60)
        for i, err in enumerate(errors, 1):
            print(f'\n  {i}. {err}')
        print('\n' + '=' * 60)
        has_error = any('[ERROR]' in e for e in errors)
        if has_error:
            print('\n  Critical errors found. Please fix before launching.')
            if not PORTABLE_MODE:
                print('  Install deps: python-win\\python.exe -m pip install -r requirements.txt')
            print('  Download VC++ Runtime: https://aka.ms/vs/17/release/vc_redist.x64.exe')
            print('  Download Python 3.11:  https://www.python.org/downloads/release/python-3119/')
            print()
            return False
        else:
            print('\n  Warnings found but non-critical. Continuing...')
            print()
    return True

if not _check_env():
    sys.exit(1)

# ---------------------------------------------------------------------------
# Bootstrap: portable mode (.deps) or pip mode (site-packages)
# ---------------------------------------------------------------------------
os.environ['PYAPPIFY_PYTHON_TEST'] = '1'

if PORTABLE_MODE:
    sys.path[:0] = [DEPS, os.path.join(DEPS, 'win32'),
                    os.path.join(DEPS, 'win32', 'lib'),
                    os.path.join(DEPS, 'Pythonwin'), REPO]
    for d in (PY_DIR, os.path.join(DEPS, 'pywin32_system32'), DEPS,
              os.path.join(DEPS, 'win32')):
        try:
            os.add_dll_directory(d)
        except Exception:
            pass
    print(f'bootstrap: portable mode (.deps)', flush=True)
else:
    # pip mode: deps are in site-packages, just add REPO to path
    sys.path[:0] = [REPO]
    try:
        os.add_dll_directory(PY_DIR)
    except Exception:
        pass
    print('bootstrap: pip mode (site-packages)', flush=True)

os.chdir(REPO)

# Log redirection for pythonw (no console)
if sys.stdout is None:
    _gui_log = open(os.path.join(SCRIPT_DIR, 'okww_gui.log'), 'a', encoding='utf-8')
    sys.stdout = _gui_log
    sys.stderr = _gui_log
else:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

try:
    print('admin:', bool(ctypes.windll.shell32.IsUserAnAdmin()), flush=True)
except Exception:
    print('admin: unknown', flush=True)

print(f'bootstrap ok, workspace = {WORKSPACE}', flush=True)

from config import config

config.pop('update_pyappify', None)
config['debug'] = True
print('config loaded, gui =', config.get('gui'), flush=True)

from ok import OK

print('creating OK...', flush=True)
ok = OK(config)
print('OK created, starting...', flush=True)
ok.start()
print('app exited normally', flush=True)
