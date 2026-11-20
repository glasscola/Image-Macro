"""Screen selection and window-relative coordinates on Windows."""
import ctypes
from ctypes import wintypes as win
import os
import time
import tkinter as tk
from tkinter import messagebox

from PIL import ImageTk
import desktop
from selection_capture import capture_visible_desktop
from automation_errors import TargetUnavailable

user = ctypes.windll.user32
user.GetAncestor.argtypes = [win.HWND, win.UINT]
user.GetAncestor.restype = win.HWND
user.WindowFromPoint.argtypes = [win.POINT]
user.WindowFromPoint.restype = win.HWND
user.GetForegroundWindow.restype = win.HWND
user.FindWindowW.argtypes = [win.LPCWSTR, win.LPCWSTR]
user.FindWindowW.restype = win.HWND
user.GetWindowThreadProcessId.argtypes = [win.HWND,ctypes.POINTER(win.DWORD)]
user.ClientToScreen.argtypes = [win.HWND,ctypes.POINTER(win.POINT)]
user.IsWindowVisible.argtypes = [win.HWND]
user.IsIconic.argtypes = [win.HWND]
user.GetClientRect.argtypes=[win.HWND,ctypes.POINTER(win.RECT)]
user.IsWindow.argtypes = [win.HWND]
user.ShowWindow.argtypes = [win.HWND,ctypes.c_int]
user.GetDpiForWindow.argtypes = [win.HWND]
kernel=ctypes.windll.kernel32
kernel.OpenProcess.argtypes=[win.DWORD,win.BOOL,win.DWORD]
kernel.OpenProcess.restype=win.HANDLE
kernel.CloseHandle.argtypes=[win.HANDLE]
kernel.QueryFullProcessImageNameW.argtypes=[win.HANDLE,win.DWORD,win.LPWSTR,ctypes.POINTER(win.DWORD)]


def executable(pid):
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:
        return ''
    try:
        path=ctypes.create_unicode_buffer(1024)
        size=win.DWORD(len(path))
        return path.value.lower() if kernel.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(size)) else ''
    finally:
        kernel.CloseHandle(handle)
user.SetForegroundWindow.argtypes = [win.HWND]
user.GetTopWindow.argtypes = [win.HWND]
user.GetTopWindow.restype = win.HWND
user.GetWindow.argtypes = [win.HWND, win.UINT]
user.GetWindow.restype = win.HWND
user.SetWindowDisplayAffinity.argtypes = [win.HWND, win.DWORD]
user.SetWindowPos.argtypes = [win.HWND, win.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, win.UINT]


def window_info(handle):
    if not handle:
        return None
    handle = user.GetAncestor(handle, 2) or handle
    pid = win.DWORD()
    user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    title = ctypes.create_unicode_buffer(1024)
    kind = ctypes.create_unicode_buffer(256)
    user.GetWindowTextW(handle, title, len(title))
    user.GetClassNameW(handle, kind, len(kind))
    return dict(handle=handle, pid=pid.value, title=title.value, kind=kind.value)


def pointer_window(x, y):
    return window_info(user.WindowFromPoint(win.POINT(x, y)))


def root_window_at(x,y):
    hwnd=user.WindowFromPoint(win.POINT(x,y))
    return user.GetAncestor(hwnd,2) if hwnd else None


def screen_point(x, y, origin=None):
    pt = win.POINT()
    if origin is None:
        user.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
    point = win.POINT(int(x), int(y))
    if not user.ClientToScreen(origin, ctypes.byref(point)):
        raise RuntimeError('기록한 창의 위치를 읽을 수 없습니다.')
    return point.x, point.y


def client_size(hwnd):
    rect=win.RECT()
    if user.GetClientRect(hwnd,ctypes.byref(rect)):
        return [rect.right-rect.left,rect.bottom-rect.top]
    return None


def attach(point, window):
    if not window or not window['title'] or window['pid'] == os.getpid():
        return None
    try:
        x,y=screen_point(0,0,window['handle'])
    except RuntimeError:
        return None
    return dict(window,dx=int(point[0])-x,dy=int(point[1])-y,
                dpi=user.GetDpiForWindow(window['handle']) or 96,
                client_size=client_size(window['handle']))


def find_window(anchor):
    hwnd = anchor['handle']
    live = window_info(hwnd)
    if not live or not all(live[k] == anchor[k] for k in ('pid','kind')):
        hwnd = user.FindWindowW(anchor['kind'], anchor['title'])
        if not hwnd and anchor.get('exe'):
            candidates=[]
            callback_type=ctypes.WINFUNCTYPE(win.BOOL,win.HWND,win.LPARAM)
            @callback_type
            def collect(h,_):
                if user.IsWindowVisible(h):
                    info=window_info(h)
                    if info['title'] and info['kind']==anchor['kind'] and executable(info['pid'])==anchor['exe']:
                        candidates.append(h)
                return True
            user.EnumWindows(collect,0)
            if len(candidates)>1:
                raise RuntimeError(f'대상 창이 여러 개입니다 · 클릭 위치를 다시 지정하세요 · {anchor["title"]}')
            hwnd=candidates[0] if candidates else None
        if not hwnd:
            raise TargetUnavailable(f'기록한 창을 열어 주세요 · {anchor["title"]}')
    if not user.IsWindowVisible(hwnd):
        raise TargetUnavailable(f'기록한 창을 화면에 표시해 주세요 · {anchor["title"]}')
    return hwnd


def focus_window(target):
    hwnd=find_window(target)
    if user.IsIconic(hwnd):
        user.ShowWindow(hwnd,9)
    if user.GetForegroundWindow()!=hwnd:
        user.SetForegroundWindow(hwnd)
    if user.GetForegroundWindow()!=hwnd:
        raise TargetUnavailable(f'기록한 창을 활성화해 주세요 · {target["title"]}')


def resolve(anchor,require_visible=True,*,activate=False,wait_if_covered=None):
    hwnd=find_window(anchor)
    if activate:
        if user.IsIconic(hwnd):
            user.ShowWindow(hwnd,9)
        if user.GetForegroundWindow()!=hwnd:
            user.SetForegroundWindow(hwnd)
    ratio=(user.GetDpiForWindow(hwnd) or 96)/anchor.get('dpi',user.GetDpiForWindow(hwnd) or 96)
    # Some windows retain their physical size across a DPI change. Apply
    # DPI scaling only when the window itself resized in the same proportion.
    previous=anchor.get('client_size')
    current=client_size(hwnd)
    if not previous or not current or any(abs(after-max(1,before)*ratio)>max(3,before*.05)
                                           for before,after in zip(previous,current)):
        ratio=1
    try:
        point=screen_point(round(anchor['dx']*ratio),round(anchor['dy']*ratio),hwnd)
    except RuntimeError as error:
        raise TargetUnavailable(str(error)) from error
    if wait_if_covered is not None:
        wait_if_covered(*point)
    hit = pointer_window(*point)
    if require_visible and (not hit or hit['handle'] != hwnd):
        raise TargetUnavailable(f'기록한 위치가 다른 창에 가려져 있습니다 · {anchor["title"]}')
    return point


def exclude(widget, value=True):
    widget.update_idletasks()
    hwnd = user.GetAncestor(widget.winfo_id(), 2)
    return bool(user.SetWindowDisplayAffinity(hwnd, 0x11 if value else 0))


def select_screen(app, mode, callback):
    app.withdraw()
    app.update_idletasks()

    def start():
        try:
            x, y, w, h = desktop.bounds()
            ctypes.windll.dwmapi.DwmFlush()
            displays = desktop.monitors()
            frame = capture_visible_desktop((x, y, w, h), displays)
        except Exception as err:
            app.deiconify()
            messagebox.showerror('화면 선택', str(err), parent=app)
            return
        overlay = tk.Toplevel(app)
        overlay.withdraw()
        overlay.overrideredirect(True)
        overlay.geometry(f'{w}x{h}+0+0')
        overlay.attributes('-topmost', True)
        overlay.configure(cursor='crosshair')
        canvas = tk.Canvas(overlay, highlightthickness=0, cursor='crosshair')
        canvas.pack(fill='both', expand=True)
        overlay.photos = []
        for monitor in displays:
            mx,my,mw,mh=monitor['rect']
            left,top=mx-x,my-y
            tile=frame.crop((left,top,left+mw,top+mh))
            photo=ImageTk.PhotoImage(tile,master=overlay)
            overlay.photos.append(photo)
            canvas.create_image(left,top,image=photo,anchor='nw')
        msg = {'image':'이미지로 찾을 부분을 둘러싸세요',
               'point':'다시 누를 위치를 한 번 찍으세요',
               'drag':'시작점에서 끝점까지 끌어 놓으세요',
               'scroll':'대상 창 위에서 휠을 굴리세요. Enter로 적용'}[mode]
        mx, my = screen_point(0, 0)
        display = next((m['rect'] for m in displays
                        if m['rect'][0] <= mx < m['rect'][0]+m['rect'][2]
                        and m['rect'][1] <= my < m['rect'][1]+m['rect'][3]), (x,y,w,h))
        left, top = display[0]-x, display[1]-y
        canvas.create_rectangle(left+16,top+16,left+475,top+63,fill='#14243d',outline='')
        canvas.create_text(left+32,top+39,text=msg+'   ·   Esc 취소',anchor='w',
                           fill='white',font=('맑은 고딕',12,'bold'))
        overlay.update_idletasks()
        start_point = None
        marker = None
        drag_path = []
        drag_started = 0

        def xy():
            px, py = screen_point(0, 0)
            return px-x, py-y

        wheel_delta = 0
        wheel_point = None

        def wheel(event):
            nonlocal wheel_delta, wheel_point
            if wheel_point is None:
                wheel_point = xy()
            wheel_delta += int(event.delta / 120)
            canvas.delete('wheel')
            canvas.create_text(left+16,top+82,text=f'휠 입력 {wheel_delta:+d}칸 · Enter 적용',
                               anchor='w',fill='#2454d0',font=('맑은 고딕',12,'bold'),tags='wheel')

        def commit_wheel(_):
            if wheel_delta and wheel_point is not None:
                point = wheel_point[0]+x,wheel_point[1]+y
                overlay.destroy()
                callback(frame,(x,y),[point,point],wheel_delta)
                app.deiconify()

        def down(_):
            nonlocal start_point, marker, drag_started
            if mode == 'scroll':
                return
            start_point = xy()
            canvas.delete('pick')
            if mode == 'image':
                marker = canvas.create_rectangle(*start_point,*start_point,outline='#388cff',width=3,tags='pick')
            elif mode == 'drag':
                drag_path.clear()
                drag_started = time.monotonic()
                marker = canvas.create_line(*start_point,*start_point,fill='#388cff',width=3,arrow='last',tags='pick')

        def move(_):
            if marker and start_point is not None:
                px,py=xy()
                canvas.coords(marker,*start_point,px,py)
                if mode=='drag':
                    elapsed=time.monotonic()-drag_started
                    if not drag_path or elapsed-drag_path[-1][1]>=.016:
                        drag_path.append(((px+x,py+y),elapsed))

        def finish(_=None):
            if _ is None or start_point is None:
                overlay.destroy()
                app.deiconify()
                return
            end = xy()
            a, b = start_point, end
            if mode == 'image':
                x0,x1 = sorted((max(0,min(w,v)) for v in (a[0],b[0])))
                y0,y1 = sorted((max(0,min(h,v)) for v in (a[1],b[1])))
                if min(x1-x0,y1-y0)<4:
                    return
                result = (frame.crop((x0,y0,x1,y1)),(x0+x,y0+y,x1-x0,y1-y0))
                overlay.destroy()
                app.deiconify()
                callback(*result)
            else:
                overlay.destroy()
                points = [(p[0]+x,p[1]+y) for p in (a,b)]
                if mode=='drag':
                    drag_path.append((points[-1],time.monotonic()-drag_started))
                    callback(frame,(x,y),points,path=drag_path)
                else:
                    callback(frame,(x,y),points)
                app.deiconify()

        if mode=='scroll':
            overlay.bind('<MouseWheel>',wheel)
            overlay.bind('<Return>',commit_wheel)
        else:
            canvas.bind('<Button-1>',down)
            canvas.bind('<B1-Motion>',move)
            canvas.bind('<ButtonRelease-1>',finish)
        overlay.bind('<Escape>',lambda _:finish())
        overlay.deiconify()
        overlay.update_idletasks()
        hwnd = user.GetAncestor(overlay.winfo_id(),2)
        # Place above other always-on-top windows as well as normal windows.
        if not hwnd or not user.SetWindowPos(hwnd,-1,x,y,w,h,0x0050):
            overlay.destroy()
            app.deiconify()
            messagebox.showerror('화면 선택','선택창을 화면 맨 위에 표시할 수 없습니다.',parent=app)
            return
        user.SetForegroundWindow(hwnd)
        overlay.focus_force()
        overlay.grab_set()

        # New topmost windows can appear after selection begins. Only raise
        # this overlay while its own modal grab is active; never take focus
        # back from the user's other applications.
        raise_timer = None

        def keep_above():
            nonlocal raise_timer
            raise_timer = None
            if overlay.grab_current() != overlay:
                return
            ahead=user.GetTopWindow(None)
            while ahead and ahead!=hwnd and not user.IsWindowVisible(ahead):
                ahead=user.GetWindow(ahead,2)
            if ahead and ahead!=hwnd:
                user.SetWindowPos(hwnd,-1,0,0,0,0,0x0013)
            raise_timer = overlay.after(90,keep_above)

        def stop_raising(event):
            if event.widget == overlay and raise_timer is not None:
                overlay.after_cancel(raise_timer)

        overlay.bind('<Destroy>', stop_raising, add='+')
        raise_timer = overlay.after(90,keep_above)

    app.after(100,start)
