"""Windows notification area controls for the editor."""
import threading

from PIL import Image
from pystray import Icon, Menu, MenuItem
from pystray._util import win32
import ctypes


class WindowsTrayIcon(Icon):
    def _show(self):
        # pystray's Windows backend does not report a failed NIM_ADD.
        self._assert_icon_handle()
        registered = win32.Shell_NotifyIcon(win32.NIM_ADD, win32.NOTIFYICONDATAW(
            cbSize=ctypes.sizeof(win32.NOTIFYICONDATAW),
            hWnd=self._hwnd,
            hID=id(self),
            uFlags=win32.NIF_MESSAGE | win32.NIF_ICON | win32.NIF_TIP,
            uCallbackMessage=win32.WM_NOTIFY,
            hIcon=self._icon_handle,
            szTip=self.title,
        ))
        if not registered:
            raise RuntimeError('Windows 알림 영역에 아이콘을 등록할 수 없습니다.')


class RunTray:
    def __init__(self, icon_path, events):
        self.status = '준비'
        self.active = False
        self.closed = threading.Event()

        def command(name, value=None):
            def enqueue(icon, item):
                events.put((name, value))
            return enqueue

        with Image.open(icon_path) as image:
            artwork = image.convert('RGBA')
        self.icon = WindowsTrayIcon('Image Macro', artwork, 'Image Macro', Menu(
            MenuItem('창 열기', command('tray_restore'), default=True),
            MenuItem(lambda _: '계속' if self.status == '일시정지' else '일시정지',
                     command('tray_pause'), enabled=lambda _: self.active),
            MenuItem('정지', command('stop', '알림 영역 정지'), enabled=lambda _: self.active),
            Menu.SEPARATOR,
            MenuItem('종료', command('tray_exit')),
        ))

        def setup(icon):
            if self.closed.is_set():
                icon.stop()
                return
            try:
                icon.visible = True
            except Exception:
                icon.stop()
            else:
                events.put(('tray_ready', None))

        def run():
            try:
                self.icon.run(setup)
            finally:
                if not self.closed.is_set():
                    events.put(('tray_unavailable', None))

        threading.Thread(target=run, daemon=True, name='Image Macro tray').start()

    def update(self, status, active):
        self.status, self.active = status, active
        self.icon.title = f'Image Macro · {status}'
        self.icon.update_menu()

    def close(self):
        self.closed.set()
        self.icon.stop()
