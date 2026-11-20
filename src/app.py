"""Image Macro workflow editor."""
import ctypes
try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except AttributeError:
    pass

import copy
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import uuid

from PIL import Image, ImageDraw, ImageGrab, ImageTk
from pynput import keyboard
from tkinterdnd2 import DND_FILES, TkinterDnD

import core
from image_files import load_image
import desktop

# Leave CPU time for the input executor while a watch runs.
core.cv2.setNumThreads(2)
from recording import Recorder
from screen_ui import select_screen, exclude
from imacro_flow import validate_flow
from workflow_editor import WorkflowEditor

BG='#f0f4f9'
WHITE='#ffffff'
INK='#14253b'
MUTED='#566981'
BLUE='#244ed0'
LINE='#dae3ee'
FONT='맑은 고딕'
NAMES={'point':'클릭','drag':'드래그','key':'키 누르기','hold':'길게 누르기',
       'text':'글자 입력','scroll':'스크롤','image':'나타나면 클릭','wait':'나타날 때까지 기다리기',
       'find':'화면에서 찾기','condition':'보이는지 확인','break':'이 반복 종료','continue':'다음 반복으로',
       'stop':'실행 종료','record':'녹화','delay':'대기','click':'찾은 곳 클릭','loop':'반복'}
COLORS={'running':('#eaf0ff',BLUE),'done':('#e9faf2','#166a50'),
        'error':('#fff0f0','#a92743'),'paused':('#fff5df','#855510'),
        'stopped':('#f2f4f7',MUTED)}


class App(WorkflowEditor,TkinterDnD.Tk):
    def __init__(self,path=None):
        super().__init__()
        self.title('Image Macro')
        icon = Path(__file__).with_name('image-macro.ico')
        if icon.exists():
            self.iconbitmap(default=str(icon))
        self.collapsed = set()
        self.picker = None
        self.geometry('1060x720')
        self.minsize(700,480)
        self.configure(bg=BG)
        self.option_add('*Font',(FONT,10))
        self.project=core.project()
        self.path=None
        self.dirty=False
        self.undo_items=[]
        self.redo_items=[]
        self.selected=set()
        self.rows={}
        self.preview_cache={}
        self.queue=queue.Queue()
        self.runner=None
        self.recorder=None
        self.run_status=''
        self.current=None
        self.states={}
        self.iterations={}
        self.log=[]
        self.drag=None
        self.line=None
        self.progress=None
        self.build()
        self.hotkeys=keyboard.GlobalHotKeys({
            '<f7>':lambda:self.queue.put(('record_end_request',None)),
            '<f10>':lambda:self.queue.put(('stop',None))})
        self.hotkeys.start()
        self.after(30,self.poll)
        self.protocol('WM_DELETE_WINDOW',self.close)
        for key,fn in [('Control-s',self.save),('Control-o',self.open),
                       ('Control-z',self.undo),('Control-y',self.redo),
                       ('Control-v',self.paste),('Delete',self.delete)]:
            self.bind('<'+key+'>',lambda e,f=fn:(f(),'break')[1])
        if path:
            self.read(Path(path))
        self.render()

    def button(self,parent,label,command,primary=False):
        return tk.Button(parent,text=label,command=command,padx=14,pady=7,
                         bd=0,highlightthickness=1,highlightbackground=BLUE if primary else LINE,
                         bg=BLUE if primary else WHITE,fg=WHITE if primary else INK,
                         activebackground='#1c40b3' if primary else '#ecf1fc',
                         activeforeground=WHITE if primary else INK,cursor='hand2',font=(FONT,10,'bold'))

    def build(self):
        bar=tk.Frame(self,bg=WHITE,padx=24,pady=14,highlightthickness=1,highlightbackground=LINE)
        bar.pack(fill='x')
        icon=Path(__file__).with_name('image-macro.ico')
        if icon.exists():
            with Image.open(icon) as original:
                mark=original.resize((32,32),Image.Resampling.LANCZOS)
            self.brand_icon=ImageTk.PhotoImage(mark)
            tk.Label(bar,image=self.brand_icon,bg=WHITE).pack(side='left',padx=(0,9))
        tk.Label(bar,text='Image Macro',font=('Segoe UI',19,'bold'),bg=WHITE,fg=INK).pack(side='left')
        self.file_button=self.button(bar,'새 작업  ▾',self.file_menu)
        self.file_button.pack(side='left',padx=18)
        self.run_button=self.button(bar,'▶  실행',self.run,True)
        self.run_button.pack(side='right')
        self.cycle_button=self.button(bar,'전체 실행 · 1회',self.choose_cycles)
        self.cycle_button.pack(side='right',padx=8)
        self.cycle_caption=''

        self.stop_button=self.button(bar,'■  정지',self.stop)
        self.pause_button=self.button(bar,'일시정지',self.pause)
        self.body=tk.Frame(self,bg=BG)
        self.body.pack(fill='both',expand=True,padx=30,pady=(24,0))
        head=tk.Frame(self.body,bg=BG)
        head.pack(fill='x',pady=(0,13))
        tk.Label(head,text='작업 순서',font=(FONT,21,'bold'),bg=BG,fg=INK).pack(side='left')
        self.total=tk.Label(head,bg=BG,fg=MUTED)
        self.total.pack(side='left',padx=13)
        self.record_button=self.button(head,'●  녹화 시작',self.toggle_record)
        panel=tk.Frame(self.body,bg=WHITE,highlightthickness=1,highlightbackground=LINE)
        panel.pack(fill='both',expand=True)
        self.next_stage=tk.Frame(self.body,bg=BG)
        self.canvas=tk.Canvas(panel,bg=WHITE,highlightthickness=0)
        scroll=tk.Scrollbar(panel,orient='vertical',command=self.canvas.yview)
        scroll.pack(side='right',fill='y')
        self.canvas.pack(side='left',fill='both',expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.list=tk.Frame(self.canvas,bg=WHITE)
        wid=self.canvas.create_window((0,0),window=self.list,anchor='nw')
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfig(wid,width=e.width))
        self.list.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.bind_all('<MouseWheel>',self.wheel)
        self.canvas.drop_target_register(DND_FILES)
        self.canvas.dnd_bind('<<Drop>>',self.drop)
        self.list.drop_target_register(DND_FILES)
        self.list.dnd_bind('<<Drop>>',self.drop)
        foot=tk.Frame(self,bg=BG,padx=30,pady=11)
        foot.pack(fill='x')
        self.status=tk.Label(foot,bg=BG,fg=MUTED,anchor='w',text='준비')
        self.status.pack(side='left',fill='x',expand=True)
        self.logs=tk.Label(foot,text='실행 기록',fg=BLUE,bg=BG,cursor='hand2')
        self.logs.pack(side='right')
        self.logs.bind('<Button-1>',lambda _:self.show_log())
        self.diagnostics=tk.Label(foot,text='읽은 화면',fg=BLUE,bg=BG,cursor='hand2')
        self.diagnostics.bind('<Button-1>',lambda _:self.show_frame())
        # Desktop file drops resolve against the visible row under the pointer.
        self.drop_widgets=(self.canvas,self.list)

    def wheel(self,event):
        if self.canvas.winfo_ismapped() and not self.modal_event(event):
            self.canvas.yview_scroll(-int(event.delta/120),'units')

    def modal_event(self,event):
        return event.widget.winfo_toplevel()!=self

    def editable(self):
        return not self.runner and not self.recorder

    def file_menu(self):
        menu=tk.Menu(self,tearoff=0)
        for label,fn in [('새 작업',self.new),('열기…',self.open),('저장',self.save),
                         ('다른 이름으로 저장…',lambda:self.save(True)),
                         ('실행 취소',self.undo),('다시 실행',self.redo)]:
            menu.add_command(label=label,command=fn,state='normal' if self.editable() else 'disabled')
        menu.tk_popup(self.file_button.winfo_rootx(),self.file_button.winfo_rooty()+self.file_button.winfo_height())

    def snapshot(self):
        self.undo_items.append(copy.deepcopy(self.project))
        self.undo_items=self.undo_items[-20:]
        self.redo_items.clear()
        self.dirty=True

    def undo(self):
        self.restore(self.undo_items,self.redo_items)

    def redo(self):
        self.restore(self.redo_items,self.undo_items)

    def restore(self,source,dest):
        if self.editable() and source:
            dest.append(self.project)
            self.project=source.pop()
            self.selected.clear()
            self.preview_cache.clear()
            self.states.clear()
            self.dirty=True
            self.render()

    def abandon(self):
        if not self.dirty:
            return True
        choice=messagebox.askyesnocancel('변경사항 저장','작업을 저장하시겠습니까?',parent=self)
        return self.save() if choice else choice is False

    def read(self,path):
        try:
            project=core.load(path)
        except Exception as e:
            messagebox.showerror('작업을 열 수 없음',str(e),parent=self)
            return
        core.expand_image_clicks(project)
        had_flow=bool(project.pop('ranges',[]) or project.get('routes'))
        project.pop('routes',None)
        project.pop('repeat_enabled',None)
        self.project,self.path=project,path
        self.reset()
        if had_flow:
            self.status.configure(text='이전 흐름 설정은 해제되었습니다. 각 이미지 카드에서 반복을 켤 수 있습니다.')

    def reset(self):
        self.collapsed.clear()
        self.status.configure(text='준비')
        self.selected.clear()
        self.preview_cache.clear()
        self.states.clear()
        self.undo_items.clear()
        self.redo_items.clear()
        self.dirty=False
        self.render()

    def new(self):
        if self.editable() and self.abandon():
            self.project,self.path=core.project(),None
            self.reset()

    def open(self):
        if self.editable() and self.abandon():
            filename=filedialog.askopenfilename(parent=self,filetypes=[('Image Macro','*.imacro.json'),('JSON','*.json')])
            if filename:
                self.read(Path(filename))

    def save(self,as_new=False):
        if not self.editable():
            return False
        path=self.path
        if not path or as_new:
            name=filedialog.asksaveasfilename(parent=self,defaultextension='.imacro.json',
                                             filetypes=[('Image Macro','*.imacro.json')])
            if not name:
                return False
            path=Path(name)
        try:
            core.save(self.project,path)
        except Exception as e:
            messagebox.showerror('저장 실패',str(e),parent=self)
            return False
        self.path,self.dirty=path,False
        self.update_header()
        return True

    def close(self):
        if self.runner:
            self.stop()
            self.after(100,self.close)
            return
        if self.recorder:
            self.toggle_record()
            self.after(80,self.close)
            return
        if self.abandon():
            self.hotkeys.stop()
            self.destroy()

    def locate(self,uid,items=None):
        if items is None:
            items=self.project['steps']
        for i,s in enumerate(items):
            if s['id']==uid:
                return items,i,s
            for branch in ('children','otherwise'):
                result=self.locate(uid,s[branch])
                if result:
                    return result
        return None

    def insertion(self):
        for uid in reversed(list(self.rows)):
            if uid in self.selected:
                items,i,_=self.locate(uid)
                return items,i+1
        items=self.project['steps']
        return items,len(items)

    def insert(self,s,at=None,snapshot=True):
        items,i=self.insertion() if at is None else at
        if snapshot:
            self.snapshot()
        items.insert(i,s)
        self.selected={s['id']}
        self.render()
        return s

    def choose_cycles(self):
        menu=tk.Menu(self,tearoff=False)
        menu.add_command(label='1회 실행',command=lambda:self.save_cycles(1))
        menu.add_command(label='계속 반복',command=lambda:self.save_cycles(0))
        def custom():
            n=simpledialog.askinteger('전체 실행 횟수','마지막 카드까지 몇 번 실행할까요?',
                                       initialvalue=3,minvalue=1,maxvalue=100000,parent=self)
            if n is not None:
                self.save_cycles(n)
        menu.add_command(label='횟수 지정…',command=custom)
        menu.tk_popup(self.cycle_button.winfo_rootx(),
                      self.cycle_button.winfo_rooty()+self.cycle_button.winfo_height())

    def save_cycles(self,count):
        self.snapshot()
        self.project['workflow_repeats']=count
        self.render()

    def render_transition(self, step, next_step):
        if not self.editable() or step['kind']!='image':
            return
        if next_step is None:
            count=self.project.get('workflow_repeats',1)
            text='마치면 완료' if count==1 else '마치면 01번으로 · 전체 반복'
        else:
            name=self.caption(next_step)[0]
            condition='이 이미지가 사라지면' if step.get('repeat_while_visible') else '행동이 끝나면'
            if step.get('repeat_while_visible') and next_step['kind']=='image' and step.get('advance_on_next'):
                condition='이 이미지가 사라지거나 다음 이미지가 보이면'
            text=f'{condition} → {self.top_numbers[next_step["id"]]+1:02} {name}'
        row=tk.Frame(self.list,bg=WHITE)
        row.pack(fill='x',padx=52,pady=4)
        tk.Label(row,text=text,bg=WHITE,fg=MUTED).pack(side='left')
        if next_step and next_step['kind']=='image' and step.get('repeat_while_visible'):
            self.button(row,'다음 이미지 우선 해제' if step.get('advance_on_next') else '다음 이미지가 보이면 이동',
                        lambda:self.change(step,advance_on_next=not step.get('advance_on_next',False))).pack(side='right')

    def update_header(self):
        count=self.project.get('workflow_repeats',1)
        self.cycle_button.configure(text='전체 실행 · '+(f'{count}회' if count else '계속 반복'),
                                    state='normal' if self.editable() else 'disabled')
        title=self.path.name.removesuffix('.imacro.json') if self.path else '새 작업'
        self.file_button.configure(text=title+('  •' if self.dirty else '')+'  ▾')
        count = len(self.project['steps'])
        self.total.configure(text=f'{count}단계' if count else '')
        self.run_button.configure(state='normal' if self.editable() and self.rows else 'disabled')
        self.record_button.configure(text='■  녹화 끝내기 · F7' if self.recorder else '●  녹화 시작',
                                    state='disabled' if self.runner else 'normal')

    def thumbnail(self,data,key,size=(58,42)):
        tag=(key,size)
        if tag not in self.preview_cache:
            try:
                image=core.decode_image(data)
                image.thumbnail(size)
                self.preview_cache[tag]=ImageTk.PhotoImage(image)
            except Exception:
                return None
        return self.preview_cache[tag]

    def caption(self,s):
        kind=s['kind']
        asset=self.project['images'].get(s['image'],{})
        title=NAMES[kind] if s['name']==core.KINDS[kind] else s['name']
        desc=''
        if kind=='image':
            title=asset.get('name') or '대상 이미지'
            wait='계속 기다림' if s.get('wait_forever') else f'최대 {s["timeout"]:g}초'
            if s['image_mode']=='once':
                wait='한 번 확인'
            desc=wait
            if s['id'] in self.collapsed:
                desc+=f' · 행동 {len(s["children"])+len(s["otherwise"])}개 접힘'
            if s.get('moving'):
                desc+=' · 움직이는 대상'
        elif kind=='loop':
            title=f'{s["count"]}회 반복'
            watch=self.project['images'].get(s['watch'])
            desc=f'{watch["name"]} 표시 시 종료' if watch else ''
        elif kind=='record':
            if s['name']==core.KINDS[kind]:
                title='녹화한 동작'
            desc=s.get('window_title','') or f'입력 {len(s["events"])}개'
        elif kind in ('key','hold'):
            title=s['key'].upper()+(f' · {s["seconds"]:g}초 누름' if kind=='hold' else '')
        elif kind=='text':
            desc=s['text'].replace('\n',' ')[:70]
        elif kind=='click' and s.get('configured_target'):
            title='찾은 이미지 클릭'
            origin=self.locate(s['source'])
            image=self.project['images'].get(origin[2]['image'],{}) if origin else {}
            desc=image.get('name','원본 단계 확인')+' · '+{'left':'왼쪽','right':'오른쪽','middle':'가운데'}[s['button']]+f' {s["clicks"]}회'
        elif kind=='delay':
            title=f'{s["seconds"]:g}초 대기'
        elif kind in ('condition','wait','find'):
            desc=asset.get('name','대상 없음')
        if s.get('before'):
            desc+=f'  ·  시작 전 {s["before"]:g}초'
        return title,desc

    def render(self):
        for container in (self.list,self.next_stage):
            for widget in container.winfo_children():
                widget.destroy()
        self.next_stage.pack_forget()
        self.rows={}
        self.picker=None
        self.top_numbers={s['id']:i for i,s in enumerate(self.project['steps'])}
        self.image_buttons={}
        self.visible_parent={}
        self.stage_numbers={}
        for i,step in enumerate(self.project['steps'],1):
            self.stage_numbers.update((node['id'],i) for node in core.walk([step]))
        if not self.project['steps']:
            box=tk.Frame(self.list,bg=WHITE,padx=24,pady=60)
            box.pack(fill='x')
            tk.Label(box,text='첫 동작을 만들어 보세요',bg=WHITE,fg=INK,font=(FONT,23,'bold')).pack()
            tk.Label(box,text='매크로를 시작할 화면의 이미지나 버튼을 고르세요.',
                     bg=WHITE,fg=MUTED,pady=12).pack()
            actions=tk.Frame(box,bg=WHITE)
            actions.pack(pady=10)
            self.button(actions,'화면에서 대상 선택',self.capture_target,True).pack(side='left',padx=5)
            hint=tk.Label(box,text='이미지를 Ctrl+V로 붙여넣거나 여기에 끌어놓기  ·  파일 열기',
                          bg=WHITE,fg=BLUE,cursor='hand2',pady=12)
            hint.pack()
            hint.bind('<Button-1>',lambda _:self.import_images())
            for widget in (box,hint):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind('<<Drop>>',self.drop)
            self.record_button.pack_forget()
            if self.recorder:
                self.record_button.pack(side='right')
        else:
            if self.recorder:
                self.record_button.pack(side='right')
            else:
                self.record_button.pack_forget()
            steps=self.project['steps']
            for i,step in enumerate(steps):
                self.render_rows([step])
                self.render_transition(step,steps[i+1] if i+1<len(steps) else None)
            if self.editable():
                footer=self.next_stage
                footer.pack(fill='x',pady=(9,0))
                at=(self.project['steps'],len(self.project['steps']))
                self.button(footer,'＋  다음 이미지 선택',lambda:self.capture_target(at=at),True).pack(side='left')
                self.button(footer,'이미지 파일 열기',lambda:self.import_images(at)).pack(side='left',padx=8)
        self.update_header()

    def render_rows(self,items,depth=0):
        for s in items:
            uid=s['id']
            slab=tk.Frame(self.list,bg=WHITE)
            slab.pack(fill='x',padx=(15+depth*37,15),pady=(8,0))
            row=tk.Frame(slab,padx=10,pady=8,highlightthickness=1,highlightbackground=LINE)
            row.pack(side='left',fill='x',expand=True)
            index=f'{self.top_numbers[uid]+1:02}' if not depth else '↳'
            number=tk.Label(row,text=f'⠿  {index}',width=6,anchor='w',cursor='fleur')
            number.pack(side='left')
            folded=uid in self.collapsed
            if s['kind']=='image':
                fold=self.button(row,'▸ 펼치기' if folded else '▾ 접기',lambda u=uid:self.toggle_fold(u))
                fold.configure(width=8,padx=2,pady=3)
                fold.pack(side='left',padx=(0,8))
                if self.editable():
                    repeat=self.button(row,'구간 반복 켜짐' if s.get('repeat_while_visible') else '구간 반복',
                                       lambda step=s:self.toggle_image_repeat(step),bool(s.get('repeat_while_visible')))
                    repeat.configure(padx=7,pady=3)
                    repeat.pack(side='right',padx=(6,0))
            labels=[]
            asset=self.project['images'].get(s['image'],{})
            image_data=asset.get('data') or s.get('preview')
            if image_data:
                photo=self.thumbnail(image_data,s['image'] or uid)
                if photo:
                    cover=tk.Label(row,image=photo,cursor='hand2')
                    cover.pack(side='left',padx=(0,12))
                    cover.bind('<Double-1>',lambda _,a=s:self.details(a))
                    labels.append(cover)
            ellipsis=tk.Label(row,text='•••',cursor='hand2',width=4)
            ellipsis.pack(side='right')
            if self.editable():
                edit=self.button(row,'설정' if s['kind']=='image' else '편집',lambda a=s:self.details(a))
                edit.configure(padx=7,pady=3)
                edit.pack(side='right')
            indicator=tk.Label(row,width=13 if self.runner else 1,anchor='e',font=(FONT,9,'bold'))
            indicator.pack(side='right')
            title,desc=self.caption(s)
            label=tk.Label(row,text=title,anchor='w',font=(FONT,11,'bold'))
            label.pack(side='top',fill='x')
            sub=tk.Label(row,text=desc,anchor='w',font=(FONT,9))
            if desc:
                sub.pack(side='top',fill='x')
            self.rows[uid]=(row,number,indicator,[label,sub,ellipsis]+labels)
            self.paint(uid)
            for widget in (row,number,label,sub,*labels):
                widget.bind('<Button-1>',lambda e,u=uid:self.row_down(e,u))
                if widget is number:
                    widget.bind('<B1-Motion>',self.row_motion)
                    widget.bind('<ButtonRelease-1>',self.row_up)
                widget.bind('<Double-1>',lambda _,a=s:self.details(a))
                widget.bind('<Button-3>',lambda e,a=s:self.context(a,e.x_root,e.y_root))
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind('<<Drop>>',self.drop)
            ellipsis.bind('<Button-1>',lambda e,a=s:self.context(a,e.x_root,e.y_root))
            if folded:
                for branch in ('children','otherwise'):
                    for child in core.walk(s[branch]):
                        self.visible_parent[child['id']]=uid
                self.paint(uid)
                continue
            if s['children']:
                self.render_rows(s['children'],depth+1)
            if self.editable() and s['kind'] in ('image','loop'):
                self.action_footer(s,depth)
            if s['otherwise']:
                tk.Label(self.list,text='못 찾았을 때',bg=WHITE,fg=MUTED,anchor='w').pack(
                    fill='x',padx=25+(depth+1)*26,pady=(8,0))
                self.render_rows(s['otherwise'],depth+1)

    def action_footer(self, step, depth):
        footer=tk.Frame(self.list,bg=WHITE,highlightthickness=0)
        footer.pack(fill='x',padx=(52+depth*37,15),pady=(4,8))
        if step['kind']=='loop':
            at=(step['children'],len(step['children']))
            self.button(footer,'＋ 반복 안에 단계 추가',lambda:self.show_picker(footer,at=at,stages=True)).pack(anchor='w')
            return
        button=self.button(footer,'＋ 이 이미지가 보이면 할 행동',lambda:self.show_picker(footer,step))
        button.pack(anchor='w')
        self.image_buttons[step['id']]=button

    def toggle_fold(self, uid):
        if uid in self.collapsed:
            self.collapsed.remove(uid)
        else:
            self.collapsed.add(uid)
        self.render()
        if self.selected - self.rows.keys():
            self.selected.intersection_update(self.rows)
            self.selected.add(uid)
            self.paint(uid)

    def toggle_image_repeat(self, step):
        if self.editable():
            on=not step.get('repeat_while_visible',False)
            self.change(step,repeat_while_visible=on)
            message='이미지가 보이는 동안 이 카드의 행동을 반복합니다.' if on else '이미지를 찾으면 이 카드의 행동을 한 번 실행합니다.'
            self.status.configure(text=message)

    def paint(self,uid):
        row,number,status,labels=self.rows[uid]
        state,detail=self.states.get(uid,('',''))
        if uid in self.collapsed:
            for child,parent in self.visible_parent.items():
                if parent==uid and self.states.get(child,('',None))[0]=='error':
                    state,detail='error','! 행동 오류'
                    break
            else:
                current=self.visible_parent.get(self.current)
                if current==uid and state!='running':
                    child_state,_=self.states.get(self.current,('',''))
                    if child_state in ('running','paused'):
                        state,detail=child_state,'행동 실행 중'
        bg,fg=COLORS.get(state,('#eef2ff' if uid in self.selected else WHITE,INK))
        s=self.locate(uid)[2]
        if not s['enabled']:
            fg=MUTED
            detail='실행 제외'
        row.configure(bg=bg,highlightbackground=BLUE if uid in self.selected else LINE)
        number.configure(bg=bg,fg=MUTED)
        status.configure(bg=bg,fg=fg,text=detail,width=14 if detail else 1)
        for widget in labels:
            widget.configure(bg=bg,fg=fg)

    def row_down(self,event,uid):
        if not self.editable():
            return
        if event.state&1 and self.selected:
            order=list(self.rows)
            anchor=next(i for i in order if i in self.selected)
            a,b=sorted((order.index(anchor),order.index(uid)))
            self.selected.update(order[a:b+1])
        elif event.state&4:
            self.selected.symmetric_difference_update({uid})
        elif uid not in self.selected or len(self.selected)>1:
            self.selected={uid}
        for u in self.rows:
            self.paint(u)
        self.drag=(uid,event.y_root,None) if event.widget is self.rows[uid][1] else None

    def hit_row(self,y):
        for uid,(row,*_) in self.rows.items():
            top=row.winfo_rooty()
            if top <= y < top+row.winfo_height():
                return uid,y>=top+row.winfo_height()/2
        return None

    def row_motion(self,event):
        if not self.drag or not self.editable():
            return
        uid,start,old=self.drag
        if abs(event.y_root-start)<6 and old is None:
            return
        hit=self.hit_row(event.y_root)
        if old:
            self.paint(old[0])
        self.drag=(uid,start,hit)
        if self.line:
            self.line.destroy()
            self.line=None
        if hit:
            row=self.rows[hit[0]][0]
            ypos=row.winfo_rooty()-self.canvas.winfo_rooty()+self.canvas.canvasy(0)
            if hit[1]:
                ypos+=row.winfo_height()
            self.line=tk.Frame(self.list,bg=BLUE,height=3)
            self.line.place(x=14,y=ypos-1,relwidth=1,width=-28)
            self.line.lift()

    def row_up(self,event):
        if not self.drag:
            return
        uid,_,hit=self.drag
        self.drag=None
        if self.line:
            self.line.destroy()
            self.line=None
        if not hit or hit[0]==uid:
            return
        a,ai,s=self.locate(uid)
        b,bi,t=self.locate(hit[0])
        self.paint(hit[0])
        if a is not b:
            return
        self.snapshot()
        a.pop(ai)
        bi=b.index(t)
        b.insert(bi+int(hit[1]),s)
        try:
            validate_flow(self.project)
        except ValueError as e:
            self.undo()
            self.status.configure(text=str(e))
            return
        self.render()

    def add_menu(self,button=None,at=None,x=None,y=None):
        if not self.editable():
            return
        menu=tk.Menu(self,tearoff=0)
        menu.add_command(label='화면에서 대상 선택',command=lambda:self.capture_target(at=at))
        menu.add_command(label='이미지 파일 열기…',command=lambda:self.import_images(at))
        menu.add_separator()
        for label,fn in [('화면에서 클릭 위치 찍기',lambda:self.pick_motion('point',at=at)),
                         ('화면에서 드래그 그리기',lambda:self.pick_motion('drag',at=at)),
                         ('마우스 이동 위치 찍기',lambda:self.pick_motion('point_move',at=at)),
                         ('누를 키 지정',lambda:self.key_dialog(at=at)),
                         ('문구 입력',lambda:self.text_dialog(at=at))]:
            menu.add_command(label=label,command=fn)
        if button:
            x=button.winfo_rootx()
            y=button.winfo_rooty()+button.winfo_height()
        menu.tk_popup(x,y)

    def context(self,s,x,y):
        if not self.editable():
            return
        uid=s['id']
        if uid not in self.selected:
            self.selected={uid}
            for u in self.rows:
                self.paint(u)
        items,i,_=self.locate(uid)
        menu=tk.Menu(self,tearoff=0)
        menu.add_command(label='편집',command=lambda:self.details(s))
        menu.add_command(label='이 아래에 추가',command=lambda:self.add_menu(at=(items,i+1),x=x,y=y))
        if s['kind']=='loop':
            menu.add_command(label='반복 안에 단계 추가',command=lambda:self.add_menu(at=(s['children'],len(s['children'])),x=x,y=y))
        if s['kind'] in ('image','condition'):
            if s['kind']=='image':
                if uid in self.image_buttons:
                    menu.add_command(label='찾았을 때 행동 추가',command=self.image_buttons[uid].invoke)
            else:
                menu.add_command(label='찾았을 때 행동 추가',command=lambda:self.add_menu(at=(s['children'],len(s['children'])),x=x,y=y))
            menu.add_command(label='못 찾았을 때 행동 추가',command=lambda:self.add_menu(at=(s['otherwise'],len(s['otherwise'])),x=x,y=y))
        menu.add_command(label='이 단계 전 간격…',command=lambda:self.edit_number(s,'before','시작 전 간격 (초)',0.,3600.))
        menu.add_command(label='실행 제외' if s['enabled'] else '다시 포함',command=lambda:self.change(s,enabled=not s['enabled']))
        menu.add_separator()
        menu.add_command(label='복제',command=lambda:self.duplicate(s,items,i))
        menu.add_command(label='삭제',command=self.delete)
        menu.tk_popup(x,y)

    def duplicate(self,step,items,index):
        clone=copy.deepcopy(step)
        nodes=list(core.walk([clone]))
        ids={s['id']:uuid.uuid4().hex for s in nodes}
        for node in nodes:
            node['id']=ids[node['id']]
            if node['source'] in ids:
                node['source']=ids[node['source']]
        self.insert(clone,(items,index+1))

    def change(self,s,**values):
        self.snapshot()
        s.update(values)
        self.preview_cache.clear()
        self.render()

    def delete(self):
        if self.editable() and self.selected:
            self.snapshot()
            for uid in list(self.selected):
                entry=self.locate(uid)
                if entry:
                    items,i,_=entry
                    items.pop(i)
            self.selected.clear()
            self.render()

    def asset(self,image,name,roi=None):
        if min(image.size)<4 or max(image.size)>8000:
            raise ValueError('이미지는 가로·세로 4~8,000픽셀이어야 합니다.')
        uid=uuid.uuid4().hex
        info=dict(name=name,data=core.encode_image(image))
        if roi:
            x,y,w,h=roi
            for m in desktop.monitors():
                a,b,c,d=m['rect']
                if a<=x+w/2<a+c and b<=y+h/2<b+d:
                    info.update(dpi=m['dpi'],capture_rect=list(roi))
                    break
        self.project['images'][uid]=info
        return uid

    def add_image(self,image,name='화면 대상',roi=None,at=None,replace=None):
        if not self.editable():
            return
        try:
            if min(image.size)<4 or max(image.size)>8000:
                raise ValueError('이미지는 가로·세로 4~8,000픽셀이어야 합니다.')
            self.snapshot()
            uid=self.asset(image,name,roi)
            if replace:
                replace['image']=uid
                self.render()
            else:
                s=core.step('image')
                s.update(image=uid,image_action='actions',wait_forever=True)
                self.insert(s,at,snapshot=False)
        except Exception as e:
            messagebox.showerror('이미지 추가',str(e),parent=self)

    def capture_target(self,at=None,replace=None):
        if self.editable():
            select_screen(self,'image',lambda im,roi:self.add_image(im,roi=roi,at=at,replace=replace))

    def image_files(self,paths,at=None,replace=None):
        for path in paths:
            try:
                image=load_image(path)
                self.add_image(image,Path(path).stem,at=at,replace=replace)
                if at:
                    at=(at[0],at[1]+1)
                if replace:
                    break
            except Exception as e:
                messagebox.showerror('이미지 열기',str(e),parent=self)

    def import_images(self,at=None,replace=None):
        if self.editable():
            paths=filedialog.askopenfilenames(parent=self,filetypes=[
                ('모든 파일','*.*'),('일반 이미지','*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff *.avif *.ico *.qoi *.tga *.ppm')])
            self.image_files(paths,at,replace)

    def drop(self,event):
        if not self.editable():
            return
        hit=self.hit_row(event.y_root)
        at=None
        if hit:
            owner=next((s for s in self.project['steps']
                        if any(child['id']==hit[0] for child in core.walk([s]))),None)
            if owner:
                items=self.project['steps']
                at=(items,items.index(owner)+int(hit[1]))
        paths=self.tk.splitlist(event.data)
        if len(paths)==1 and paths[0].lower().endswith('.imacro.json'):
            if self.abandon():
                self.read(Path(paths[0]))
        else:
            self.image_files(paths,at)

    def paste(self):
        if not self.editable():
            return
        try:
            image=ImageGrab.grabclipboard()
        except OSError as e:
            self.status.configure(text=str(e))
            return
        if isinstance(image,Image.Image):
            self.add_image(image,'붙여넣은 이미지')
        elif isinstance(image,list):
            self.image_files(image)
        else:
            self.status.configure(text='클립보드에 이미지가 없습니다. 화면에서 대상을 선택할 수도 있습니다.')

    def pick_motion(self,kind,at=None,replace=None):
        if not self.editable():
            return
        from screen_ui import attach,pointer_window

        def picked(frame,origin,points,delta=0,path=None):
            a,b=points
            x,y=a
            window=pointer_window(x,y)
            if window:
                from screen_ui import executable
                window['exe']=executable(window['pid'])
            preview=frame.crop((x-origin[0]-50,y-origin[1]-30,x-origin[0]+50,y-origin[1]+30))
            anchor=attach(a,window)
            first=dict(type='mouse',button='left',down=True,x=x,y=y,anchor=anchor,delay=0)
            last=dict(type='mouse',button='left',down=False,
                      x=b[0] if kind=='drag' else x,y=b[1] if kind=='drag' else y,
                      anchor=attach(b if kind=='drag' else a,window),delay=.08)
            events=[dict(type='move',x=x,y=y,anchor=anchor,delay=0)] if kind=='point_move' else [first,last]
            if kind=='scroll':
                events=[dict(type='scroll',x=x,y=y,dx=0,dy=delta,anchor=anchor,delay=0)]
            if kind=='drag':
                path=path or [(b,.3)]
                previous=0
                moves=[]
                for point,elapsed in path:
                    moves.append(dict(type='move',x=point[0],y=point[1],
                                      anchor=attach(point,window),delay=min(5,elapsed-previous)))
                    previous=elapsed
                events[1:1]=moves
            values=dict(kind='record',name={'drag':'끌어 놓기','point_move':'마우스 이동',
                                          'scroll':f'{"아래" if delta<0 else "위"}로 {abs(delta)}칸 스크롤'}.get(kind,'왼쪽 클릭'),
                        preview=core.encode_image(preview),events=events,
                        window_title=(window or {}).get('title',''))
            if replace:
                self.change(replace,**values)
            else:
                s=core.step('record')
                s.update(values)
                self.insert(s,at)
        select_screen(self,'point' if kind=='point_move' else kind,picked)

    def key_dialog(self,at=None,replace=None):
        win=self.dialog('누를 키 지정')
        tk.Label(win,text='여기서 키 또는 키 조합을 직접 누르세요.',bg=WHITE,fg=MUTED).pack(anchor='w',padx=18,pady=12)
        label=tk.StringVar(value='키를 기다리는 중')
        tk.Label(win,textvariable=label,bg='#edf2ff',fg=BLUE,font=(FONT,16,'bold'),pady=16).pack(fill='x',padx=18)
        value=[]
        duration=tk.StringVar(value=str(replace['seconds']) if replace and replace['kind']=='hold' else '')
        options=tk.Frame(win,bg=WHITE)
        options.pack(fill='x',padx=18,pady=(9,0))
        tk.Label(options,text='길게 누를 시간 (초, 비우면 한 번 누름)',bg=WHITE,fg=MUTED).pack(side='left')
        seconds_input=tk.Entry(options,textvariable=duration,width=7)
        seconds_input.pack(side='left',padx=6)
        modifiers={'Shift_L','Shift_R','Control_L','Control_R','Alt_L','Alt_R','Win_L','Win_R'}
        names={'Return':'enter','BackSpace':'backspace','Escape':'esc','Prior':'page_up',
               'Next':'page_down','space':'space','plus':'vk:187',
               'KP_Enter':'enter','Caps_Lock':'caps_lock','Print':'print_screen',
               'Scroll_Lock':'scroll_lock','Num_Lock':'num_lock'}

        def press(e):
            if e.widget is seconds_input:
                return None
            if e.keysym in modifiers:
                return 'break'
            keys=[]
            if e.state&4: keys.append('ctrl')
            if e.state&1: keys.append('shift')
            if e.state&0x20000: keys.append('alt')
            keys.append(names.get(e.keysym,e.keysym.lower()) if len(e.keysym)==1 or e.keysym in names
                        or e.keysym.lower() in ('left','right','up','down','delete','insert','home','end','tab')
                        or (e.keysym.startswith('F') and e.keysym[1:].isdigit()) else f'vk:{e.keycode}')
            value[:]=keys
            label.set(' + '.join(keys).upper())
            return 'break'

        def done():
            if not value:
                return
            try:
                seconds=float(duration.get()) if duration.get().strip() else 0
                if not 0<=seconds<=3600:
                    raise ValueError
            except ValueError:
                messagebox.showerror('키 입력','길게 누를 시간은 0~3,600초 사이로 입력하세요.',parent=win)
                return
            win.destroy()
            kind='hold' if seconds else 'key'
            values=dict(kind=kind,name=core.KINDS[kind],key='+'.join(value),seconds=seconds)
            if replace and replace['kind']=='record':
                target=next((e['target'] for e in replace['events'] if e.get('target')),None)
                down=[dict(type='key',key=k,down=True,delay=0) for k in value]
                up=[dict(type='key',key=k,down=False,delay=0) for k in reversed(value)]
                up[0]['delay']=seconds
                if target:
                    down[0]['target']=target
                self.change(replace,events=down+up,name=label.get()+(f' · {seconds:g}초 누름' if seconds else ''))
            elif replace:
                self.change(replace,**values)
            else:
                s=core.step(kind)
                s.update(values)
                self.insert(s,at)
        self.button(win,'적용',done,True).pack(anchor='e',padx=18,pady=14)
        win.bind('<KeyPress>',press)
        win.focus_set()

    def text_dialog(self,at=None,replace=None):
        value=simpledialog.askstring('문구 입력','실행할 때 쓸 문구를 적으세요.',
                                     initialvalue=replace['text'] if replace else '',parent=self)
        if value is None:
            return
        if replace:
            self.change(replace,text=value)
        else:
            s=core.step('text')
            s['text']=value
            self.insert(s,at)

    def dialog(self,title):
        win=tk.Toplevel(self)
        win.title(title)
        win.configure(bg=WHITE)
        win.transient(self)
        win.minsize(390,80)
        win.grab_set()
        return win

    def edit_number(self,s,field,title,minvalue,maxvalue,integer=False):
        ask=simpledialog.askinteger if integer else simpledialog.askfloat
        value=ask(title,title,minvalue=minvalue,maxvalue=maxvalue,
                  initialvalue=s.get(field,minvalue),parent=self)
        if value is not None:
            self.change(s,**{field:value})

    def details(self,s):
        if not self.editable():
            return
        kind=s['kind']
        if kind in ('image','condition','wait','find'):
            self.image_details(s)
        elif kind in ('key','hold'):
            self.key_dialog(replace=s)
        elif kind=='click' and s.get('configured_target'):
            self.detected_click_details(s)
        elif kind=='text':
            self.text_dialog(replace=s)
        elif kind in ('drag','point'):
            self.pick_motion(kind,replace=s)
        elif kind=='delay':
            self.edit_number(s,'seconds','기다릴 시간 (초)',0.,3600.)
        elif kind=='scroll':
            self.edit_number(s,'scroll','스크롤 양 (아래로는 음수)',-10000,10000,True)
        elif kind=='loop':
            self.loop_details(s)
        elif kind=='record':
            self.record_details(s)
        else:
            messagebox.showinfo('단계',self.caption(s)[0],parent=self)

    def detected_click_details(self, step):
        origin=self.locate(step['source'])
        image=self.project['images'].get(origin[2]['image']) if origin else None
        if not image:
            return
        win=self.dialog('찾은 이미지 클릭')
        photo=self.thumbnail(image['data'],origin[2]['image'],(420,230))
        if photo is None:
            return
        panel=tk.Frame(win,bg=WHITE,padx=18,pady=12)
        panel.pack(fill='both',expand=True)
        tk.Label(panel,text='이미지 위에서 클릭할 지점을 찍으세요.',bg=WHITE,fg=MUTED).pack(anchor='w')
        canvas=tk.Canvas(panel,width=photo.width(),height=photo.height(),bg=WHITE,highlightthickness=0,cursor='crosshair')
        canvas.pack(anchor='w',pady=(8,0))
        canvas.photo=photo
        canvas.create_image(0,0,image=photo,anchor='nw')
        offset=list(step['offset'])
        def mark(e=None):
            width,height=max(1,photo.width()-1),max(1,photo.height()-1)
            if e:
                offset[:]=[min(1,max(0,e.x/width)),min(1,max(0,e.y/height))]
            x,y=offset[0]*width,offset[1]*height
            canvas.delete('point')
            canvas.create_oval(x-5,y-5,x+5,y+5,fill=BLUE,outline=WHITE,width=2,tags='point')
        canvas.bind('<Button-1>',mark)
        mark()
        choice=tk.StringVar(value=step['button'])
        times=tk.StringVar(value=str(step['clicks']))
        interval=tk.StringVar(value=str(step['interval']))
        row=tk.Frame(panel,bg=WHITE)
        row.pack(anchor='w',pady=10)
        for key,label in [('left','왼쪽'),('right','오른쪽'),('middle','가운데')]:
            tk.Radiobutton(row,text=label,value=key,variable=choice,bg=WHITE).pack(side='left')
        for label,value in [(' 클릭 횟수',times),(' 간격(초)',interval)]:
            tk.Label(row,text=label,bg=WHITE).pack(side='left')
            tk.Entry(row,textvariable=value,width=5).pack(side='left',padx=4)
        def save():
            try:
                n,pause=int(times.get()),float(interval.get())
                if not 1<=n<=100 or not 0<=pause<=60:
                    raise ValueError
            except ValueError:
                messagebox.showerror('이미지 클릭','횟수는 1~100회, 간격은 0~60초로 입력하세요.',parent=win)
                return
            win.destroy()
            self.change(step,offset=offset,button=choice.get(),clicks=n,interval=pause)
        self.button(panel,'적용',save,True).pack(anchor='e')

    def motion_settings(self,s):
        win=self.dialog('움직이는 대상')
        box=tk.Frame(win,bg=WHITE,padx=18,pady=14)
        box.pack(fill='x')
        enabled=tk.BooleanVar(value=s.get('moving',False))
        feature=tk.BooleanVar(value=s.get('motion_feature',False))
        def toggle():
            self.change(s,moving=enabled.get(),motion_feature=feature.get() if enabled.get() else False)
        tk.Checkbutton(box,text='움직이는 대상 빠르게 찾기',variable=enabled,
                       command=toggle,bg=WHITE).pack(anchor='w')
        def toggle_feature():
            if feature.get():
                enabled.set(True)
            self.change(s,moving=enabled.get(),motion_feature=feature.get())
        tk.Checkbutton(box,text='중앙의 색 무늬와 주변 색으로 찾기',variable=feature,
                       command=toggle_feature,bg=WHITE).pack(anchor='w')
        tk.Label(box,text='영상 안에서 캐릭터가 움직이는 범위를 지정하세요.\n얼굴 등 꾸준히 보이는 부분을 등록하면 더 빨리 확인할 수 있습니다.',
                 bg=WHITE,fg=MUTED,justify='left').pack(anchor='w',pady=8)
        def area(frame,roi):
            self.change(s,roi=list(roi),scope_explicit=True,moving=True)
        self.button(box,'영상 범위 화면에서 지정',lambda:(win.destroy(),select_screen(self,'image',area))).pack(fill='x',pady=4)
        if s.get('roi'):
            self.button(box,'모든 모니터에서 검색',lambda:(win.destroy(),self.change(s,roi=None))).pack(fill='x',pady=4)
        variants=s.get('variants',[])
        preview=tk.Frame(box,bg=WHITE)
        preview.pack(fill='x',pady=(4,8))
        for uid in [s['image'],*variants]:
            asset=self.project['images'].get(uid)
            if asset:
                photo=self.thumbnail(asset['data'],uid,(80,50))
                if photo:
                    thumb=tk.Label(preview,image=photo,bg=WHITE)
                    thumb.image=photo
                    thumb.pack(side='left',padx=(0,8))
        if len(variants)<2:
            def register(frame,roi):
                self.snapshot()
                uid=self.asset(frame,'추가 모습 '+str(len(variants)+1),roi)
                s.update(variants=[*variants,uid],moving=True)
                self.render()
            self.button(box,'같은 이미지의 다른 모습 추가',lambda:(win.destroy(),select_screen(self,'image',register))).pack(fill='x',pady=4)
        for i,uid in enumerate(variants):
            title=self.project['images'][uid]['name']
            self.button(box,title+' 제거',lambda u=uid:(win.destroy(),
                        self.change(s,variants=[v for v in variants if v!=u]))).pack(fill='x',pady=4)

    def image_details(self,s):
        win=self.dialog(self.caption(s)[0])
        asset=self.project['images'].get(s['image'])
        panel=tk.Frame(win,bg=WHITE,padx=20,pady=14)
        panel.pack(fill='both',expand=True)
        if asset:
            im=core.decode_image(asset['data'])
            tk.Label(panel,text=f'등록 크기 {im.width} × {im.height} 픽셀',bg=WHITE,fg=MUTED).pack(anchor='w')
            img=self.thumbnail(asset['data'],s['image'],(410,170))
            if img:
                c=tk.Canvas(panel,width=img.width(),height=img.height(),bg=WHITE,
                            highlightthickness=0)
                c.pack(anchor='w',pady=(0,8))
                c.photo=img
                c.create_image(0,0,image=img,anchor='nw')
        def button(text,fn):
            self.button(panel,text,lambda:(win.destroy(),fn())).pack(fill='x',pady=(8,0))
        button('화면에서 대상 다시 선택',lambda:self.capture_target(replace=s))
        button('이미지 파일로 교체',lambda:self.import_images(replace=s))
        if self.project['images']:
            button('프로젝트의 이미지 선택…',lambda:self.choose_asset(s,'image'))
        if s['kind']=='image':
            button('다른 모습 추가 및 움직이는 대상…',lambda:self.motion_settings(s))
        if s['kind'] in ('image','wait'):
            button('나타날 때까지 계속 기다림',lambda:self.change(s,wait_forever=True,image_mode='wait'))
            def limit():
                value=simpledialog.askfloat('기다릴 시간','최대 기다림 (초)',minvalue=.1,maxvalue=3600,
                                            initialvalue=s['timeout'],parent=self)
                if value is not None:
                    self.change(s,timeout=value,wait_forever=False,image_mode='wait')
            button('기다릴 시간 제한…',limit)
        button('인식 세부 설정…',lambda:self.advanced(s))

    def choose_asset(self,s,field):
        win=self.dialog('프로젝트 이미지 선택')
        box=tk.Frame(win,bg=WHITE,padx=12,pady=12)
        box.pack(fill='both')
        def choose(uid):
            win.destroy()
            self.change(s,**{field:uid})
        images=tk.Listbox(box,height=min(12,len(self.project['images'])),width=46,exportselection=False)
        images.pack(fill='x')
        ids=list(self.project['images'])
        for uid in ids:
            images.insert('end',self.project['images'][uid]['name'])
        def done():
            if images.curselection():
                choose(ids[images.curselection()[0]])
        images.bind('<Double-1>',lambda _:done())
        self.button(box,'선택',done,True).pack(anchor='e',pady=8)

    def advanced(self,s):
        win=self.dialog('인식 세부 설정')
        box=tk.Frame(win,bg=WHITE,padx=16,pady=16)
        box.pack(fill='x')
        def action(label,fn):
            self.button(box,label,lambda:(win.destroy(),fn())).pack(fill='x',pady=4)
        action(f'일치 기준  ·  {s["threshold"]:g}',lambda:self.edit_number(s,'threshold','일치 기준',.01,1.))
        action(f'연속 확인  ·  {s["stable"]}회',lambda:self.edit_number(s,'stable','연속 확인 횟수',1,100,True))
        action('검색할 범위를 화면에서 선택',lambda:select_screen(self,'image',
               lambda im,roi:self.change(s,roi=list(roi),scope_explicit=True)))
        if s['roi']:
            action('모든 모니터에서 찾기',lambda:self.change(s,roi=None))
        if s['kind']=='image':
            mode='once' if s['image_mode']=='wait' else 'wait'
            action('한 번만 확인' if mode=='once' else '나타날 때까지 확인',lambda:self.change(s,image_mode=mode))
        failure='skip' if s['failure']=='stop' else 'stop'
        action('실패 시 다음으로' if failure=='skip' else '실패 시 실행 멈추기',lambda:self.change(s,failure=failure))

    def loop_details(self,s):
        win=self.dialog(self.caption(s)[0])
        panel=tk.Frame(win,bg=WHITE,padx=20,pady=14)
        panel.pack(fill='x')
        def action(label,fn):
            self.button(panel,label,lambda:(win.destroy(),fn())).pack(fill='x',pady=4)
        action('반복 횟수…',lambda:self.edit_number(s,'count','반복 횟수',1,100000,True))
        def assign(im,roi):
            self.snapshot()
            s.update(watch=self.asset(im,'반복을 끝낼 이미지',roi),watch_action='break')
            self.render()
        action('이 이미지가 나타나면 반복 종료',lambda:select_screen(self,'image',assign))
        if self.project['images']:
            action('등록한 이미지로 반복 종료…',lambda:self.choose_asset(s,'watch'))
        if s['watch']:
            current=s['watch_timing']
            action('이번 반복이 끝나면 확인' if current=='during' else '실행하면서 확인',
                   lambda:self.change(s,watch_timing='after' if current=='during' else 'during'))
            action('종료 이미지 제거',lambda:self.change(s,watch=''))

    def record_details(self,s):
        events=s['events']
        buttons=[e for e in events if e['type']=='mouse']
        keys=[e for e in events if e['type']=='key']
        win=self.dialog(self.caption(s)[0])
        box=tk.Frame(win,bg=WHITE,padx=18,pady=14)
        box.pack(fill='x')
        tk.Label(box,text=s.get('window_title') or '기록한 동작',bg=WHITE,fg=INK).pack(anchor='w')
        if s.get('preview'):
            photo=self.thumbnail(s['preview'],s['id'],(180,110))
            if photo:
                label=tk.Label(box,image=photo,bg=WHITE)
                label.photo=photo
                label.pack(anchor='w',pady=8)
        if any('x' in event and 'y' in event for event in events):
            self.button(box,'현재 화면에서 위치 보기',lambda:self.preview_positions(s,win)).pack(fill='x',pady=4)
        if keys and not buttons and s.get('window_title'):
            self.button(box,'키 바꾸기…',lambda:(win.destroy(),self.key_dialog(replace=s))).pack(fill='x',pady=4)
        if buttons and len(buttons)==2:
            kind='drag' if any(e['type']=='move' for e in events) else 'point'
            self.button(box,'화면에서 다시 지정',lambda:(win.destroy(),self.pick_motion(kind,replace=s))).pack(fill='x',pady=4)
            if kind=='point':
                def replacement(im,roi):
                    self.snapshot()
                    s.update(kind='image',name=core.KINDS['image'],image=self.asset(im,'클릭할 대상',roi),
                             wait_forever=True,image_action='click',
                             button=buttons[0]['button'],events=[])
                    core.expand_image_clicks(self.project)
                    self.render()
                self.button(box,'이 모양을 찾아 클릭…',lambda:(win.destroy(),select_screen(self,'image',replacement))).pack(fill='x',pady=4)
        if events and all(e['type']=='scroll' for e in events):
            def scroll_amount():
                value=simpledialog.askinteger('스크롤','스크롤 양 (아래로는 음수)',
                                              initialvalue=sum(e['dy'] for e in events),minvalue=-10000,maxvalue=10000,parent=win)
                if value is not None:
                    win.destroy()
                    changed=[dict(events[0],dy=value)]
                    self.change(s,events=changed)
            self.button(box,'스크롤 양 조정',scroll_amount).pack(fill='x',pady=4)
        if len(events)>1:
            tk.Label(box,text=f'기록된 입력 {len(events)}개 · 재생할 때 입력 순서와 간격을 사용합니다.',
                     bg=WHITE,fg=MUTED).pack(anchor='w',pady=8)

    def preview_positions(self, step, editor):
        from screen_ui import resolve
        editor.withdraw()
        self.withdraw()

        def show():
            try:
                points=[resolve(e['anchor'],False) if e.get('anchor') else (e['x'],e['y'])
                        for e in step['events'] if 'x' in e and 'y' in e]
                left=min(x for x,_ in points)-120
                top=min(y for _,y in points)-95
                width=max(x for x,_ in points)-left+120
                height=max(y for _,y in points)-top+95
                screen=desktop.capture((left,top,width,height))
                screen.thumbnail((740,440))
                sx,sy=screen.width/width,screen.height/height
                path=[((x-left)*sx,(y-top)*sy) for x,y in points]
                draw=ImageDraw.Draw(screen)
                if len(set(path))>1:
                    draw.line(path,fill='white',width=7)
                    draw.line(path,fill=BLUE,width=4)
                for x,y in {path[0],path[-1]}:
                    draw.ellipse((x-6,y-6,x+6,y+6),fill=BLUE,outline='white',width=2)
            except (RuntimeError,OSError) as error:
                self.deiconify()
                editor.deiconify()
                messagebox.showerror('위치 보기',str(error),parent=editor)
                return
            self.deiconify()
            editor.deiconify()
            win=self.dialog('클릭 위치 및 마우스 경로')
            photo=ImageTk.PhotoImage(screen)
            label=tk.Label(win,image=photo,bg=WHITE)
            label.image=photo
            label.pack(padx=14,pady=14)
            self.button(win,'닫기',win.destroy).pack(anchor='e',padx=14,pady=(0,12))
        self.after(120,show)

    def toggle_record(self,at=None):
        if self.runner:
            return
        if self.recorder:
            if not getattr(self,'record_stopping',False):
                self.record_stopping=True
                self.recorder.stop()
                self.queue.put(('record_finished',None))
            return
        if self.grab_current():
            return
        self.record_at=self.insertion() if at is None else at
        owner=next((s for s in core.walk(self.project['steps']) if s['children'] is self.record_at[0]),None)
        dest=self.caption(owner)[0] if owner else '다음 단계'
        self.record_added=0
        self.recorder=Recorder(lambda *row:self.queue.put(('record_row',row)))
        self.status.configure(text=f'●  {dest} · 녹화 중 · F7로 종료')
        self.render()
        self.record_overlay=tk.Toplevel(self)
        self.record_overlay.title('Image Macro 녹화 중')
        self.record_overlay.attributes('-topmost',True)
        self.record_overlay.geometry('410x90+18+18')
        self.record_overlay.configure(bg=WHITE,padx=12,pady=9)
        tk.Label(self.record_overlay,text=f'●  {dest} · 녹화 중',bg=WHITE,fg='#9d2740').pack(anchor='w')
        self.button(self.record_overlay,'녹화 끝내기 · F7',self.toggle_record).pack(anchor='e',pady=(4,0))
        self.record_overlay.protocol('WM_DELETE_WINDOW',self.toggle_record)
        self.iconify()

    def record_row(self,label,events,image,window_title):
        if not self.recorder:
            return
        s=core.step('record')
        before=events[0]['delay'] if self.record_added else 0
        events[0]['delay']=0
        s.update(name=label,events=events,before=before,window_title=window_title)
        if image is not None:
            from PIL import ImageDraw
            p=image.copy()
            center=(p.width//2,p.height//2)
            ImageDraw.Draw(p).ellipse((center[0]-5,center[1]-5,center[0]+5,center[1]+5),
                                     fill='#2454ff',outline='white',width=2)
            s['preview']=core.encode_image(p)
        items,at=self.record_at
        if self.record_added and before<.23 and all(e['type']=='scroll' for e in events):
            previous=items[at-1]
            old=previous['events']
            if old and previous['name']==label and previous.get('window_title')==window_title and all(e['type']=='scroll' for e in old):
                events[0]['delay']=before
                old.extend(events)
                self.render()
                return
        self.insert(s,(items,at),snapshot=self.record_added==0)
        self.record_at=(items,at+1)
        self.record_added+=1


    def run(self):
        if not self.editable() or not self.rows:
            return
        try:
            self.runner=core.Runner(copy.deepcopy(self.project),lambda k,v:self.queue.put((k,v)))
        except Exception as e:
            messagebox.showerror('실행 준비',str(e),parent=self)
            return
        self.states.clear()
        self.iterations.clear()
        self.current=None
        self.log=[]
        self.diagnostics.pack(side='right',padx=12)
        self.last_error=''
        self.run_status='실행 중'
        self.cycle_caption=''
        self.run_button.pack_forget()
        self.stop_button.pack(side='right')
        self.pause_button.pack(side='right',padx=8)
        self.status.configure(text='실행 중 · F10 정지')
        self.render()
        if len(desktop.monitors())<=1:
            self.withdraw()
            self.progress=tk.Toplevel(self)
            self.progress.title('Image Macro 실행 중')
            self.progress.attributes('-topmost',True)
            self.progress.geometry('420x106+12+12')
            self.progress.configure(bg=WHITE,padx=14,pady=8)
            self.progress.protocol('WM_DELETE_WINDOW',self.stop)
            self.progress_label=tk.Label(self.progress,text='실행 중',bg=WHITE,fg=INK,anchor='w')
            self.progress_label.pack(fill='x')
            self.button(self.progress,'정지 · F10',self.stop).pack(side='right',pady=4)
            self.progress_pause=self.button(self.progress,'일시정지',self.pause)
            self.progress_pause.pack(side='right',padx=6,pady=4)
            exclude(self.progress)
        else:
            exclude(self)
        self.after(70,lambda:threading.Thread(target=self.runner.run,daemon=True).start())

    def pause(self):
        if self.runner:
            paused=not self.runner.paused.is_set()
            (self.runner.paused.set if paused else self.runner.paused.clear)()
            self.pause_button.configure(text='계속' if paused else '일시정지')
            if self.progress:
                self.progress_pause.configure(text='계속' if paused else '일시정지')
            if self.current:
                self.set_state(self.current,'paused' if paused else 'running','일시정지' if paused else '실행 중')
            self.run_status='일시정지' if paused else '실행 중'
            self.status.configure(text=self.run_status)

    def stop(self):
        if self.runner:
            self.runner.cancel.set()

    def set_state(self,uid,state,label):
        self.states[uid]=(state,label)
        if uid in self.rows:
            self.paint(uid)
        elif uid in self.visible_parent:
            self.paint(self.visible_parent[uid])

    def event(self,kind,value):
        if kind=='record_end_request':
            if self.recorder:
                self.toggle_record()
        elif kind=='record_finished':
            self.recorder=None
            self.record_stopping=False
            self.record_overlay.destroy()
            self.deiconify()
            self.status.configure(text=f'녹화 끝 · 행동 {self.record_added}개 추가' if self.record_added else '녹화된 행동이 없습니다.')
            self.render()
            if self.selected:
                row=self.rows.get(next(iter(self.selected)))
                if row:
                    self.after_idle(lambda w=row[0]:self.reveal_widget(w) if w.winfo_exists() else None)
        elif kind=='waiting':
            uid,seconds,status,reason=value
            labels={'capture_error':'화면 읽기 재시도','incomplete':'후보 확인 중','moved':'대상 위치 다시 확인',
                    'ambiguous':'후보 여러 곳','insufficient':'구별할 특징 부족','disappearing':'사라짐 확인 중'}
            label=labels.get(status,'이미지 기다리는 중')
            detail=f'{label} · {seconds}초'
            self.set_state(uid,'running',detail)
            name=self.caption(self.locate(uid)[2])[0]
            text=f'{self.cycle_caption}{self.stage_numbers[uid]}단계 · {name} · {detail}'
            self.status.configure(text=text if status=='not_found' else f'{text} · {reason}')
            if self.progress:
                self.progress_label.configure(text=detail)
        elif kind=='workflow_iteration':
            n,total=value
            self.cycle_caption=f'전체 {n}/{total}회 · ' if total else f'전체 {n}회차 · '
            self.states.clear()
            for uid in self.rows:
                self.paint(uid)
        elif kind=='image_iteration':
            uid,iteration=value
            self.set_state(uid,'running',f'{iteration}회째 반복 중')
            self.log.append(f'{self.stage_numbers[uid]}단계 · {iteration}회째 반복 중')
        elif kind=='stop':
            self.stop()
        elif kind=='record_row':
            self.record_row(*value)
        elif kind=='log':
            self.log.append(value)
            if len(self.log)>2000:
                del self.log[:500]
        elif kind=='active':
            self.current=value
            s=self.locate(value)[2]
            detail='이미지 찾는 중' if s['kind'] in ('image','find','wait','condition') else '실행 중'
            self.set_state(value,'running',detail)
            n=self.stage_numbers[value]
            msg=f'{self.cycle_caption}{n} / {len(self.top_numbers)}  ·  {self.caption(s)[0]}  ·  {detail}'
            self.status.configure(text=msg)
            if self.progress:
                self.progress_label.configure(text=msg)
            else:
                row=self.rows[self.visible_parent.get(value,value)][0]
                y=row.winfo_rooty()-self.list.winfo_rooty()
                if y<self.canvas.canvasy(0) or y+row.winfo_height()>self.canvas.canvasy(self.canvas.winfo_height()):
                    self.canvas.yview_moveto(y/max(1,self.list.winfo_height()))
        elif kind=='step_done':
            self.set_state(value,'done','✓ 완료')
        elif kind=='step_error':
            uid,error=value
            self.set_state(uid,'error','! 실패')
            n=self.stage_numbers[uid]
            self.status.configure(text=f'{n}단계 · {error}')
            self.last_error=f'{n}단계 · {error}'
        elif kind=='iteration':
            uid,a,b=value
            self.set_state(uid,'running',f'{a} / {b}회')
            loop=self.locate(uid)[2]
            for s in core.walk(loop['children']):
                if s['id'] in self.states:
                    self.states.pop(s['id'])
                    if s['id'] in self.rows:
                        self.paint(s['id'])
        elif kind=='state':
            self.run_status=value
        elif kind=='done':
            self.last_runner=self.runner
            self.runner=None
            if self.progress:
                self.progress.destroy()
                self.progress=None
            else:
                exclude(self,False)
            if self.run_status=='정지됨' and self.current and self.states.get(self.current,('',''))[0] in ('running','paused'):
                self.set_state(self.current,'stopped','■ 정지됨')
            self.deiconify()
            self.pause_button.pack_forget()
            self.stop_button.pack_forget()
            self.run_button.pack(side='right')
            self.status.configure(text=(self.last_error or self.run_status) if self.run_status=='오류' else self.run_status)
            self.render()

    def poll(self):
        try:
            for _ in range(160):
                try:
                    kind,value=self.queue.get_nowait()
                except queue.Empty:
                    break
                self.event(kind,value)
        finally:
            self.after(30,self.poll)

    def show_frame(self):
        runner=self.runner or getattr(self,'last_runner',None)
        frame=getattr(runner,'last_frame',None)
        if frame is None:
            messagebox.showinfo('읽은 화면','표시할 캡처 화면이 없습니다.',parent=self)
            return
        if self.runner and not self.runner.paused.is_set():
            self.pause()
        from PIL import ImageDraw
        preview=frame.copy()
        result=getattr(runner,'last_detection',{})
        if result.get('box'):
            x,y,w,h=result['box']
            ox,oy=runner.last_origin
            ImageDraw.Draw(preview).rectangle((x-ox,y-oy,x-ox+w,y-oy+h),outline='#ffb000',width=5)
        preview.thumbnail((900,570))
        win=tk.Toplevel(self)
        win.title('프로그램이 읽은 화면')
        if self.runner:
            win.transient(self)
            win.grab_set()
        photo=ImageTk.PhotoImage(preview)
        shown=tk.Label(win,image=photo)
        shown.photo=photo
        shown.pack()
        tk.Label(win,text=result.get('reason','화면 캡처'),padx=12,pady=8).pack()

    def show_log(self):
        win=tk.Toplevel(self)
        win.title('실행 기록')
        win.geometry('630x390')
        text=tk.Text(win,wrap='word',padx=12,pady=12)
        text.pack(fill='both',expand=True)
        text.insert('1.0','\n'.join(self.log) or '실행 기록이 없습니다.')
        text.configure(state='disabled')


if __name__=='__main__':
    App(sys.argv[1] if len(sys.argv)>1 else None).mainloop()
