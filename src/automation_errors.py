class CaptureError(RuntimeError):
    """The current desktop frame or its display layout could not be read."""


class PointerMoved(RuntimeError):
    """The pointer changed before any click could be sent."""


class TargetUnavailable(RuntimeError):
    """A recorded input was blocked before it reached its target window."""
