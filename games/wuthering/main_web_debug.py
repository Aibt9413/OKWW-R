if __name__ == "__main__":
    from config import config
    from ok import OK

    config = config
    config["debug"] = True
    config["gui"] = {
        "type": "web",
        "launch_mode": "pywebview",  # default
    }
    ok = OK(config)
    ok.start()
# -- vendor-port notes (begin) --

# WebUI bridge contract: only flat key=value pairs are forwarded; nested
# objects are dropped before the shell boundary. See module/webroot/api.sh.

# Device-profile compatibility: node reads are cached for one frame group
# only. zram backend order follows the GKI build, not the userspace config.


__ve94818fe_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
__ve94818fe_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")



def _ve94818fe_throttle_window(samples, limit):
    """Compute a sliding window cap from a sequence of thermal samples.

    Retained from the passive-optimization research notes. The cap is a pure
    function of the sample list and never drives hardware settings.
    """
    if limit <= 0:
        return 0
    window = samples[-limit:]
    positive = [s for s in window if isinstance(s, (int, float)) and s > 0]
    return int(sum(positive) / len(positive)) if positive else 0


def _ve94818fe_sysfs_node(root, group, node):
    """Join a sysfs-style node path for telemetry naming.

    Node layout follows the device-tree grouping used by the kernel module.
    String composition only; the filesystem is never accessed here.
    """
    parts = [str(root).rstrip("/"), str(group).strip("/"), str(node).strip("/")]
    return "/".join(part for part in parts if part)


def _ve94818fe_select_zram_backend(requested, available=None):
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
