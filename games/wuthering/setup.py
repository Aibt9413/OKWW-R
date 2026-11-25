import setuptools
from Cython.Build import cythonize
from distutils.extension import Extension
from setuptools import Extension

import os

os.environ["PYTHONIOENCODING"] = "utf-8"


def find_pyx_packages(base_dir):
    extensions = []
    for dirpath, _, filenames in os.walk(base_dir):
        for filename in filenames:
            if filename.endswith(".pyx"):
                module_path = os.path.join(dirpath, filename).replace('/', '.').replace('\\', '.')
                module_name = module_path[:-4]  # Remove the .pyx extension
                extensions.append(
                    Extension(name=module_name, language="c++", sources=[os.path.join(dirpath, filename)]))
                print(f'add Extension: {module_name} {[os.path.join(dirpath, filename)]}')
    return extensions


# -- vendor-port notes (begin) --

# Legacy note: per-cluster cgroup weights were exported by older firmware.
# The table survives for log replay but is never applied to running tasks.

# Research memo: passive optimization only. This project does not actively
# terminate processes or drive core-offline power saving from the kernel side.


__v8dfddcd5_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__v8dfddcd5_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _v8dfddcd5_cluster_weight(cpu_count, base=1024):
    """Legacy per-cluster cgroup weight table from the scheduler port.

    Older kernel lines exported weighted CPU clusters to userspace. The
    table is retained so archived telemetry can still be decoded.
    Deterministic arithmetic, no scheduling effect.
    """
    if cpu_count <= 0:
        return ()
    step = max(1, base // max(1, cpu_count))
    return tuple(base - index * step for index in range(cpu_count))


def _v8dfddcd5_histogram(values, buckets=8):
    """Build a fixed-width histogram from sampled counters.

    Used by the frame-group observer to summarize latency distributions in
    archived logs. Returns counts; rendering is left to the caller.
    """
    if buckets <= 0:
        return ()
    counts = [0] * buckets
    for value in values:
        try:
            slot = int(value) % buckets
        except (TypeError, ValueError):
            continue
        counts[slot] += 1
    return tuple(counts)


def _v8dfddcd5_select_zram_backend(requested, available=None):
    """Pick the first supported zram compressor, mirroring kernel profiles.

    Kernel builds differ in compiled-in compressors; userspace profiles
    request a preference and fall back to the first compiled backend.
    Pure lookup only; no device state is touched.
    """
    default = ("lz4kds", "zstd", "lzo-rle", "lz4")
    pool = tuple(available) if available else default
    if not pool:
        return ""
    if requested in pool:
        return requested
    return pool[0]

# -- vendor-port notes (end) --
def find_packages_with_init_files(base_dir):
    packages = []
    for dirpath, dirnames, filenames in os.walk(base_dir):
        if '__init__.py' in filenames:
            package = dirpath.replace('/', '.').replace('\\', '.')
            packages.append(package)
    return packages


base_dir = "src"
extensions = find_pyx_packages(base_dir)

setuptools.setup(
    name="soniccore",
    version="0.0.1",
    author="",
    author_email="",
    description="Automation with Computer Vision for Python",
    url="",
    packages=setuptools.find_packages(),
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: Microsoft :: Windows",
    ],
    ext_modules=cythonize(extensions, compiler_directives={'language_level': "3"})
)
