"""Record complete gestures and stream them back to the editor."""
import os
import threading
import time

from pynput import keyboard, mouse
from screen_ui import attach, executable, pointer_window, user, window_info
from desktop import capture, MOUSE_BUTTON_LABELS
from keyboard_ime import VK_HANGUL, korean_mode

RESERVED = {'f7','f10'}
DESKTOP_WINDOWS = {'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'}


def key_name(key):
    if getattr(key,'vk',None) == VK_HANGUL:
        return f'vk:{VK_HANGUL}'
    name = getattr(key, 'name', None)
    if name:
        return name
    char = getattr(key, 'char', None)
    if char and len(char) == 1:
        if 1 <= ord(char) <= 26:
            return chr(ord(char) + 96)
        return char
    vk = getattr(key, 'vk', None)
    return f'vk:{vk}' if vk is not None else None


class Recorder:
    def __init__(self, emit):
        self.emit = emit
        self.lock = threading.RLock()
        self.last = time.monotonic()
        self.active = True
        self.held = {}
        self.events = []
        self.last_move = 0
        self.path = []
        self.path_window = None
        self.keyboard = keyboard.Listener(on_press=lambda k:self.key(k,True),
                                          on_release=lambda k:self.key(k,False))
        self.mouse = mouse.Listener(on_click=self.click,on_move=self.move,on_scroll=self.scroll)
        self.keyboard.start()
        self.mouse.start()

    def stop(self):
        with self.lock:
            self.flush_path()
            self.active = False
            self.events.clear()
        self.keyboard.stop()
        self.mouse.stop()

    def step(self, event, now):
        event['delay'] = min(3600,max(0,now-self.last))
        self.last = now
        self.events.append(event)

    def flush(self, label, preview=None, window=None):
        if not self.held and self.events:
            self.emit(label, self.events, preview, (window or {}).get('title',''))
            self.events = []

    def flush_path(self):
        if not self.path:
            return
        events=self.path
        self.path=[]
        duration=sum(e['delay'] for e in events[1:])
        self.emit(f'마우스 이동 · {duration:.2f}초',events,None,
                  (self.path_window or {}).get('title',''))
        self.path_window=None

    def key(self,key,down):
        name = key_name(key)
        if not name or name in RESERVED:
            return
        with self.lock:
            if not self.active:
                return
            token = ('key',getattr(key,'vk',None) or name)
            window = window_info(user.GetForegroundWindow())
            if down:
                if token in self.held or (window and window['pid']==os.getpid()):
                    return
                self.flush_path()
                mode = (korean_mode() if not self.events and window
                        and window.get('kind') not in DESKTOP_WINDOWS else None)
                # Preserve physical letters even if the layout translated them.
                vk = getattr(key,'vk',None)
                physical = vk if vk is not None and 65 <= vk <= 90 else None
                self.held[token] = (time.monotonic(),name,physical)
            elif token not in self.held:
                return
            now = time.monotonic()
            started,saved_name,physical = self.held[token]
            event=dict(type='key',key=saved_name,down=down)
            if physical is not None:
                event['vk']=physical
            if down and mode is not None:
                event['korean_mode']=mode
            if (down and not self.events and window and window.get('title')
                    and window.get('kind') not in DESKTOP_WINDOWS):
                event['target']=window
            self.step(event,now)
            if not down:
                del self.held[token]
                names = list(dict.fromkeys(e['key'] for e in self.events if e['type']=='key'))
                display = ' + '.join('한/영' if n==f'vk:{VK_HANGUL}' else
                                     n.replace('_l','').replace('_r','').title() for n in names)
                if len(names)==1 and now-started>=.45:
                    display += f' · {now-started:.1f}초 누름'
                if self.events[0].get('korean_mode') and display!='한/영':
                    display = '한글 · '+display
                self.flush(display,window=window)

    def click(self,x,y,button,down):
        name = button.name
        if name not in MOUSE_BUTTON_LABELS:
            return
        with self.lock:
            token = ('mouse',name)
            if not self.active:
                return
            if down:
                window = pointer_window(x,y)
                if window and window['pid']==os.getpid():
                    return
                self.flush_path()
                anchor=None
                if window and window.get('kind') not in DESKTOP_WINDOWS:
                    window['exe']=executable(window['pid'])
                    anchor=attach((x,y),window)
                try:
                    preview = capture((int(x)-50,int(y)-30,100,60))
                except OSError:
                    preview = None
                self.last_move = 0
                self.held[token] = (x,y,window,preview,anchor)
            elif token not in self.held:
                return
            ox,oy,window,preview,start_anchor = self.held[token]
            event = dict(type='mouse',button=name,down=down,x=int(x),y=int(y))
            event['anchor']=(dict(start_anchor,dx=start_anchor['dx']+int(x-ox),
                                  dy=start_anchor['dy']+int(y-oy)) if start_anchor else None)
            self.step(event,time.monotonic())
            if not down:
                del self.held[token]
                label='드래그' if abs(x-ox)+abs(y-oy)>5 or any(e['type']=='move' for e in self.events) else MOUSE_BUTTON_LABELS[name]+' 클릭'
                self.flush(label,preview,window)

    def move(self,x,y):
        with self.lock:
            now=time.monotonic()
            if not self.active:
                return
            held_mouse=next((v for k,v in self.held.items() if k[0]=='mouse'),None)
            event=dict(type='move',x=int(x),y=int(y))
            if held_mouse:
                ox,oy,_,_,anchor=held_mouse
                if abs(x-ox)+abs(y-oy)<5 or now-self.last_move<.015:
                    return
                if anchor:
                    event['anchor']=dict(anchor,dx=anchor['dx']+int(x-ox),dy=anchor['dy']+int(y-oy))
                self.last_move=now
                self.step(event,now)
                return
            window=pointer_window(x,y)
            if window and window['pid']==os.getpid():
                self.flush_path()
                return
            if self.path and (now-self.last>.20 or len(self.path)>=300):
                self.flush_path()
            if len(self.path)>1 and now-self.last_move<.012:
                # Keep the newest end point while limiting samples per second.
                prior=self.path[-1]['delay']
                self.path[-1]=dict(event,delay=prior+now-self.last)
                self.last=now
                return
            self.last_move=now
            if self.held:
                self.step(event,now)
            else:
                event['delay']=min(3600,max(0,now-self.last))
                self.last=now
                self.path.append(event)
                self.path_window=window

    def scroll(self,x,y,dx,dy):
        with self.lock:
            window = pointer_window(x,y)
            if self.active and (not window or window['pid']!=os.getpid()):
                self.flush_path()
                anchor=attach((x,y),window) if window and window.get('kind') not in DESKTOP_WINDOWS else None
                self.step(dict(type='scroll',dx=int(dx),dy=int(dy),x=int(x),y=int(y),
                               anchor=anchor),time.monotonic())
                self.flush('아래로 스크롤' if dy<0 else '위로 스크롤' if dy else '가로 스크롤',window=window)
