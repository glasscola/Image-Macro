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


def capture_rectangle(x, y, width, height, *, include_layered=True):
    if width <= 0 or height <= 0:
        raise ValueError("캡처 크기가 올바르지 않습니다.")
    user, gdi = functions()
    source = user.GetDC(None)
    if not source:
        raise ctypes.WinError(ctypes.get_last_error())

    destination = bitmap = previous = None
    try:
        destination = gdi.CreateCompatibleDC(source)
        if not destination:
            raise ctypes.WinError(ctypes.get_last_error())
        header = BitmapHeader(size=ctypes.sizeof(BitmapHeader), width=width,
                              height=-height, planes=1, bits=32)
        data = ctypes.c_void_p()
        bitmap = gdi.CreateDIBSection(destination, ctypes.byref(header), 0,
                                      ctypes.byref(data), None, 0)
        if not bitmap or not data:
            raise ctypes.WinError(ctypes.get_last_error())
        previous = gdi.SelectObject(destination, bitmap)
        if not previous or previous == ctypes.c_void_p(-1).value:
            previous = None
            raise ctypes.WinError(ctypes.get_last_error())
        raster_operation = 0x00CC0020  # SRCCOPY
        if include_layered:
            raster_operation |= 0x40000000  # CAPTUREBLT
        if not gdi.BitBlt(destination, 0, 0, width, height, source, x, y, raster_operation):
            raise ctypes.WinError(ctypes.get_last_error())
        gdi.GdiFlush()
        pixels = ctypes.string_at(data, width * height * 4)
        return Image.frombytes("RGB", (width, height), pixels, "raw", "BGRX")
    finally:
        if previous:
            gdi.SelectObject(destination, previous)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if destination:
            gdi.DeleteDC(destination)
        user.ReleaseDC(None, source)
