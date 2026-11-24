"""Reuse CPU capture buffers while polling the desktop."""
import desktop
from desktop_capture import CaptureBuffer


class RuntimeCapture:
    def __init__(self):
        self.cpu_buffer = CaptureBuffer()
        self.confirmation_buffer = CaptureBuffer()

    def close(self):
        try:
            self.cpu_buffer.close()
        finally:
            self.confirmation_buffer.close()

    def read(self, roi, fallback):
        return self._read_buffer(self.cpu_buffer, tuple(roi or desktop.bounds()),
                                 fallback, roi, reuse_unchanged=True)

    def confirm(self, roi, fallback):
        """Read a fresh patch without replacing the main desktop bitmap."""
        return self._read_buffer(self.confirmation_buffer, tuple(roi), fallback, roi)

    @staticmethod
    def _read_buffer(buffer, rect, fallback, roi, *, reuse_unchanged=False):
        try:
            frame = buffer.read(*rect, include_layered=False,reuse_unchanged=reuse_unchanged)
            if frame.getbbox():
                return frame
        except OSError:
            pass
        return fallback(roi)
