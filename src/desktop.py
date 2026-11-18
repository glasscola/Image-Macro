"""Physical virtual-desktop coordinates, including negative monitor origins."""
import ctypes
from PIL import ImageGrab

def monitors():
    """Enumerate physical display rectangles and effective DPI on the calling thread."""
    from ctypes import wintypes as w
    class Rect(ctypes.Structure):
        _fields_=[('left',w.LONG),('top',w.LONG),('right',w.LONG),('bottom',w.LONG)]
    class Info(ctypes.Structure):
        _fields_=[('size',w.DWORD),('rect',Rect),('work',Rect),('flags',w.DWORD),('device',w.WCHAR*32)]
    u=ctypes.windll.user32
    u.GetMonitorInfoW.argtypes=[w.HANDLE,ctypes.POINTER(Info)]
    dpi=ctypes.windll.shcore.GetDpiForMonitor
    dpi.argtypes=[w.HANDLE,ctypes.c_int,ctypes.POINTER(w.UINT),ctypes.POINTER(w.UINT)]
    items=[]
    callback=ctypes.WINFUNCTYPE(w.BOOL,w.HANDLE,w.HDC,ctypes.POINTER(Rect),w.LPARAM)
    def visit(handle,dc,rect,param):
        info=Info();info.size=ctypes.sizeof(info)
        if not u.GetMonitorInfoW(handle,ctypes.byref(info)):return True
        dx=w.UINT(96);dy=w.UINT(96);dpi(handle,0,ctypes.byref(dx),ctypes.byref(dy))
        r=info.rect
        items.append(dict(device=info.device,rect=[r.left,r.top,r.right-r.left,r.bottom-r.top],dpi=dx.value or 96))
        return True
    if not u.EnumDisplayMonitors(None,None,callback(visit),0):raise RuntimeError('모니터 목록 조회 실패')
    return items

def capture_metadata(roi):
    if roi:
        x,y,w,h=roi
        for m in monitors():
            a,b,c,d=m['rect']
            if a<=x+w/2<a+c and b<=y+h/2<b+d:return dict(capture_rect=roi,dpi=m['dpi'],monitor=m['device'])
    return {}

def bounds():
    u=ctypes.windll.user32
    return tuple(u.GetSystemMetrics(i) for i in (76,77,78,79))

def capture(roi=None):
    from desktop_capture import capture_rectangle
    x,y,w,h=roi or bounds()
    try:
        return capture_rectangle(x,y,w,h)
    except OSError:
        pass
    return ImageGrab.grab(bbox=(x,y,x+w,y+h),all_screens=True)

def local_to_screen(point,roi=None):
    x,y,_,_=roi or bounds()
    return point[0]+x,point[1]+y

class Input:
    def __init__(self):
        from pynput import mouse,keyboard
        self.mouse=mouse.Controller();self.keys=keyboard.Controller();self.buttons=mouse.Button;self.Key=keyboard.Key
        self.held=set()
    def move_to(self,x,y):
        user32=ctypes.WinDLL('user32',use_last_error=True)
        if not user32.SetCursorPos(x,y):
            raise RuntimeError(f'Windows에서 커서 이동 실패 (오류 {ctypes.get_last_error()})')
        current=self.mouse.position
        if current!=(x,y):
            raise RuntimeError(f'마우스 이동 실패 · 요청 {(x,y)}, 실제 {current}')

    def _button_events(self,button,states):
        from ctypes import wintypes as w

        class MouseInput(ctypes.Structure):
            _fields_=[('dx',w.LONG),('dy',w.LONG),('data',w.DWORD),
                      ('flags',w.DWORD),('time',w.DWORD),('extra',ctypes.c_size_t)]

        class Event(ctypes.Structure):
            _fields_=[('kind',w.DWORD),('mouse',MouseInput)]

        down,up={self.buttons.left:(2,4),self.buttons.right:(8,16),
                 self.buttons.middle:(32,64)}[button]
        items=(Event*len(states))(*(Event(0,MouseInput(0,0,0,down if state else up,0,0))
                                    for state in states))
        user32=ctypes.WinDLL('user32',use_last_error=True)
        sent=user32.SendInput(len(states),items,ctypes.sizeof(Event))
        if sent!=len(states):
            if sent and len(states)>1:
                user32.SendInput(1,ctypes.byref(items[1]),ctypes.sizeof(Event))
            raise RuntimeError(f'Windows 클릭 입력 전달 실패 ({sent}/{len(states)})')

    def click_at(self,x,y,button):
        self.move_to(x,y)
        self._button_events(button,(True,False))

    def mouse_button(self,button,down):
        self._button_events(button,(down,))

    def key(self,name,down):
        aliases={'ctrl_l':'ctrl','ctrl_r':'ctrl','shift_l':'shift','shift_r':'shift','alt_l':'alt','alt_r':'alt','win':'cmd','esc':'esc','return':'enter','pageup':'page_up','pagedown':'page_down'}
        if name.startswith('vk:'):
            from pynput.keyboard import KeyCode
            key=KeyCode.from_vk(int(name[3:]))
        else:
            key=getattr(self.Key,aliases.get(name,name),None) or name
        (self.keys.press if down else self.keys.release)(key)
        if down:self.held.add(key)
        else:self.held.discard(key)
    def release(self):
        for k in list(self.held):
            try:self.keys.release(k)
            except Exception:pass
        self.held.clear()
        for b in (self.buttons.left,self.buttons.right,self.buttons.middle):self.mouse.release(b)
