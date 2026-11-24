"""Read a physical screen rectangle without grabbing the whole desktop."""
import ctypes
from ctypes import wintypes as win
from functools import lru_cache
from PIL import Image


class BitmapHeader(ctypes.Structure):
    _fields_ = [
        ("size", win.DWORD), ("width", win.LONG), ("height", win.LONG),
        ("planes", win.WORD), ("bits", win.WORD), ("compression", win.DWORD),
        ("image_size", win.DWORD), ("x_resolution", win.LONG),
        ("y_resolution", win.LONG), ("colors", win.DWORD),
        ("important_colors", win.DWORD),
    ]


@lru_cache(maxsize=1)
def functions():
    user = ctypes.WinDLL("user32", use_last_error=True)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    handle = win.HANDLE
    signatures = [
        (user.GetDC, [handle], handle),
        (user.ReleaseDC, [handle, handle], ctypes.c_int),
        (gdi.CreateCompatibleDC, [handle], handle),
        (gdi.DeleteDC, [handle], win.BOOL),
        (gdi.CreateDIBSection,
         [handle, ctypes.POINTER(BitmapHeader), win.UINT,
          ctypes.POINTER(ctypes.c_void_p), handle, win.DWORD], handle),
        (gdi.SelectObject, [handle, handle], handle),
        (gdi.DeleteObject, [handle], win.BOOL),
        (gdi.BitBlt, [handle, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                      handle, ctypes.c_int, ctypes.c_int, win.DWORD], win.BOOL),
    ]
    for function, args, result in signatures:
        function.argtypes, function.restype = args, result
    return user, gdi


@lru_cache(maxsize=1)
def _compare_bytes():
    compare = ctypes.CDLL('msvcrt').memcmp
    compare.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t)
    compare.restype = ctypes.c_int
    return compare


class CaptureBuffer:
    """Reuse the destination bitmap on the worker that owns the capture session."""
    def __init__(self):
        self.destination = self.bitmap = self.previous = self.pixels = None
        self.size = None
        self.snapshot = self.snapshot_key = self.image = None

    def _allocate(self, source, width, height):
        self.close()
        _, gdi = functions()
        self.destination = gdi.CreateCompatibleDC(source)
        if not self.destination:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            self._select_bitmap(source,width,height)
        except OSError:
            self.close()
            raise

    def _select_bitmap(self, source, width, height):
        _, gdi = functions()
        header = BitmapHeader(size=ctypes.sizeof(BitmapHeader), width=width,
                              height=-height, planes=1, bits=32)
        data = ctypes.c_void_p()
        self.bitmap = gdi.CreateDIBSection(source, ctypes.byref(header), 0,
                                           ctypes.byref(data), None, 0)
        if not self.bitmap or not data:
            raise ctypes.WinError(ctypes.get_last_error())
        previous = gdi.SelectObject(self.destination, self.bitmap)
        if not previous or previous == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self.previous = previous
        self.pixels = (ctypes.c_ubyte * (width * height * 4)).from_address(data.value)
        self.size = (width,height)

    def read(self, x, y, width, height, *, include_layered=True, reuse_unchanged=False):
        if width <= 0 or height <= 0:
            raise ValueError("캡처 크기가 올바르지 않습니다.")
        user,gdi = functions()
        source = user.GetDC(None)
        if not source:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if self.size != (width,height):
                self._allocate(source,width,height)
            operation = 0x40CC0020 if include_layered else 0x00CC0020
            if not gdi.BitBlt(self.destination, 0, 0, width, height, source, x, y, operation):
                raise ctypes.WinError(ctypes.get_last_error())
            gdi.GdiFlush()
            key = (x,y,include_layered) if reuse_unchanged else None
            return self._image_from_pixels(key)
        except OSError:
            self.close()
            raise
        finally:
            user.ReleaseDC(None,source)

    def _image_from_pixels(self, key):
        if key is not None:
            count = ctypes.sizeof(self.pixels)
            if (self.snapshot_key == key and self.snapshot is not None
                    and _compare_bytes()(self.pixels,self.snapshot,count) == 0):
                return self.image
        # The returned RGB image owns its pixels across subsequent reads.
        image = Image.frombytes("RGB",self.size,self.pixels,"raw","BGRX")
        if key is not None:
            if self.snapshot is None:
                self.snapshot = ctypes.create_string_buffer(count)
            ctypes.memmove(self.snapshot,self.pixels,count)
            self.snapshot_key,self.image = key,image
        return image

    def close(self):
        self.snapshot = self.snapshot_key = self.image = None
        if not self.destination:
            return
        _,gdi = functions()
        self.pixels = None
        if self.previous:
            gdi.SelectObject(self.destination,self.previous)
        if self.bitmap:
            gdi.DeleteObject(self.bitmap)
        gdi.DeleteDC(self.destination)
        self.destination = self.bitmap = self.previous = self.size = None


def capture_rectangle(x, y, width, height, *, include_layered=True):
    buffer = CaptureBuffer()
    try:
        return buffer.read(x,y,width,height,include_layered=include_layered)
    finally:
        buffer.close()
