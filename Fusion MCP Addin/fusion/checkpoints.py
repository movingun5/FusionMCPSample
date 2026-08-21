"""Latest successful Fusion MCP mutation checkpoint."""

_last_checkpoint = None


def record_checkpoint(checkpoint):
    if not isinstance(checkpoint, dict):
        raise TypeError("checkpoint must be a dictionary")
    global _last_checkpoint
    _last_checkpoint = dict(checkpoint)
    return dict(_last_checkpoint)


def get_last_checkpoint():
    return dict(_last_checkpoint) if _last_checkpoint else None


def clear_last_checkpoint():
    global _last_checkpoint
    _last_checkpoint = None
