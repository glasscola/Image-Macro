"""Read and restore Korean IME mode on the focused Windows control."""
import ctypes
from ctypes import wintypes as win
from functools import lru_cache


VK_HANGUL = 0x15
KOREAN_LANGUAGE = 0x0412
WM_IME_CONTROL = 0x0283
IMC_GETCONVERSIONMODE = 1
IMC_SETCONVERSIONMODE = 2
IME_CMODE_NATIVE = 1


class _GuiThreadInfo(ctypes.Structure):
    _fields_ = [('size', win.DWORD), ('flags', win.DWORD),
                *[(name, win.HWND) for name in ('active', 'focus', 'capture', 'menu',
                                               'move', 'caret')],
                ('caret_rect', win.RECT)]


@lru_cache(maxsize=1)
def _apis():
    user = ctypes.WinDLL('user32', use_last_error=True)
    imm = ctypes.WinDLL('imm32')
    user.GetForegroundWindow.restype = win.HWND
    user.GetWindowThreadProcessId.argtypes = [win.HWND, ctypes.POINTER(win.DWORD)]
    user.GetWindowThreadProcessId.restype = win.DWORD
    user.GetKeyboardLayout.argtypes = [win.DWORD]
    user.GetKeyboardLayout.restype = win.HANDLE
    user.GetGUIThreadInfo.argtypes = [win.DWORD, ctypes.POINTER(_GuiThreadInfo)]
    imm.ImmGetDefaultIMEWnd.argtypes = [win.HWND]
    imm.ImmGetDefaultIMEWnd.restype = win.HWND
    user.SendMessageTimeoutW.argtypes = [win.HWND, win.UINT, win.WPARAM, win.LPARAM,
                                         win.UINT, win.UINT, ctypes.POINTER(ctypes.c_size_t)]
    user.SendMessageTimeoutW.restype = win.LPARAM
    return user, imm


def _ime_window():
    user, imm = _apis()
    foreground = user.GetForegroundWindow()
    if not foreground:
        return None
    thread = user.GetWindowThreadProcessId(foreground, None)
    layout = user.GetKeyboardLayout(thread) if thread else None
    if not layout or layout & 0xffff != KOREAN_LANGUAGE:
        return None
    info = _GuiThreadInfo(size=ctypes.sizeof(_GuiThreadInfo))
    if user.GetGUIThreadInfo(thread, ctypes.byref(info)) and info.focus:
        return imm.ImmGetDefaultIMEWnd(info.focus)
    return imm.ImmGetDefaultIMEWnd(foreground)


def _control(window, command, value=0):
    user, _ = _apis()
    result = ctypes.c_size_t()
    if user.SendMessageTimeoutW(window, WM_IME_CONTROL, command, value, 2, 25, ctypes.byref(result)):
        return result.value
    return None


def korean_mode():
    window = _ime_window()
    conversion = _control(window, IMC_GETCONVERSIONMODE) if window else None
    return None if conversion is None else bool(conversion & IME_CMODE_NATIVE)


def restore_korean_mode(native):
    window = _ime_window()
    conversion = _control(window, IMC_GETCONVERSIONMODE) if window else None
    if conversion is None:
        return False
    if bool(conversion & IME_CMODE_NATIVE) == native:
        return True
    mode = conversion | IME_CMODE_NATIVE if native else conversion & ~IME_CMODE_NATIVE
    _control(window, IMC_SETCONVERSIONMODE, mode)
    return korean_mode() == native
