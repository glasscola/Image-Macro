"""Image Macro: portable project model, image matching and cancellable runner."""
import base64, copy, io, json, math, threading, time, uuid
from pathlib import Path
import cv2
from PIL import Image
from imacro_flow import Workflow, Jump, validate_flow
from automation_errors import CaptureError, PointerMoved, TargetUnavailable
from macro_tabs import tab_count, tab_steps, validate_tabs
from contextlib import ExitStack, nullcontext
from desktop import MOUSE_BUTTON_LABELS

KINDS = {'image':'이미지 작업','text':'글자 입력','scroll':'스크롤','hold':'키 누르고 있기','wait':'이미지 기다리기', 'find':'이미지 찾기', 'click':'찾은 위치 클릭',
 'point':'좌표 클릭', 'drag':'드래그', 'key':'키 입력', 'delay':'시간 대기',
 'loop':'반복 그룹', 'condition':'이미지 조건', 'break':'이 반복 탈출',
 'continue':'다음 반복', 'stop':'전체 정지', 'record':'녹화 동작'}

def step(kind):
    return dict(id=uuid.uuid4().hex, kind=kind, name=KINDS[kind], enabled=True,
      image='', threshold=.9, timeout=10., stable=1, scales=[.8,.9,1.,1.1,1.2],
      roi=None, offset=[.5,.5], source='', seconds=1., count=10, x=0,y=0,
      x2=200,y2=200,key='enter', failure='stop', children=[], otherwise=[],
      events=[], watch='', watch_timing='during',watch_apply='action',watch_action='break',
      image_mode='wait',image_action='click',button='left',clicks=1,interval=.1,text='',scroll=3)

def encode_image(im):
    buf=io.BytesIO(); im.convert('RGB').save(buf,format='PNG')
    return base64.b64encode(buf.getvalue()).decode('ascii')

def decode_image(data):
    return Image.open(io.BytesIO(base64.b64decode(data,validate=True))).convert('RGB')

def project(): return dict(format='ImageMacro',version=1,images={},steps=[])

def repeat_waits_for_image(step, continuous):
    return (step['kind'] in ('image','wait') and step['failure']=='stop'
            and not step['otherwise'] and (continuous or step.get('repeat_while_visible',False)))

def walk(steps):
    for s in steps:
        yield s
        yield from walk(s['children']); yield from walk(s['otherwise'])

def validate(p,ready=True,*,on_legacy_motion=None):
    if p.get('format')!='ImageMacro' or p.get('version')!=1: raise ValueError('지원하지 않는 프로젝트 형식입니다.')
    validate_tabs(p)
    if type(p.get('repeat_on_reappear',False)) is not bool:
        raise ValueError('첫 이미지 재등장 설정 오류')
    count=p.get('workflow_repeats',1)
    if type(count) is not int or not 0<=count<=100000:
        raise ValueError('전체 반복 횟수 오류')
    ids=set()
    converted=0
    def number(v,lo,hi):
        if not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi: raise ValueError('숫자 설정 범위 오류')
    def visit(items,depth=0,loops=0):
        nonlocal converted
        if depth>24: raise ValueError('중첩이 너무 깊습니다 (최대 24).')
        if not isinstance(items,list): raise ValueError('단계 목록 오류')
        for s in items:
            for key,value in step(s['kind']).items():s.setdefault(key,value)
            if s['kind'] not in KINDS or s['id'] in ids: raise ValueError('단계 종류 또는 ID 오류')
            ids.add(s['id'])
            if len(ids)>10000: raise ValueError('단계가 너무 많습니다.')
            if 'wait_forever' in s and type(s['wait_forever']) is not bool:
                raise ValueError('기다림 설정 오류')
            if type(s.get('advance_on_next',False)) is not bool:
                raise ValueError('다음 이미지 이동 설정 오류')
            repeat=s.get('repeat_while_visible',False)
            if type(repeat) is not bool or (repeat and s['kind']!='image'):
                raise ValueError('이미지 반복 설정 오류')
            if ready and repeat and s['enabled'] and not any(child.get('enabled',True) for child in s['children']) and s.get('image_action')!='click':
                raise ValueError('구간 반복을 켠 이미지에 실행할 행동을 추가하세요.')
            # Legacy recordings already store a representative image in 'image'.
            moving=s.pop('moving',False)
            variants=s.pop('variants',[])
            s.pop('motion_feature',None)
            converted+=int(bool(moving or variants))
            number(s.get('before',0),0,3600)
            number(s['threshold'],.01,1); number(s['timeout'],.1,3600)
            number(s['stable'],1,100); number(s['seconds'],0,3600); number(s['count'],1,100000)
            if int(s['count'])!=s['count'] or int(s['stable'])!=s['stable']: raise ValueError('횟수는 정수입니다.')
            if not s['scales'] or len(s['scales'])>25: raise ValueError('배율 설정 오류')
            for v in s['scales']: number(v,.2,4)
            if s['failure'] not in ('stop','skip'): raise ValueError('실패 처리 오류')
            if s['watch_timing'] not in ('during','after') or s['watch_apply'] not in ('action','group') or s['watch_action'] not in ('break','continue','stop'): raise ValueError('감시 설정 오류')
            if s.get('roi') is not None:
                if len(s['roi'])!=4: raise ValueError('영역 형식 오류')
                x,y,w,h=s['roi']; number(w,2,30000); number(h,2,30000)
            if len(s['offset'])!=2: raise ValueError('클릭 위치 오류')
            for v in s['offset']: number(v,0,1)
            if s['image_mode'] not in ('wait','once') or s['image_action'] not in ('click','actions'):raise ValueError('이미지 동작 설정 오류')
            if s['button'] not in MOUSE_BUTTON_LABELS:raise ValueError('마우스 버튼 오류')
            number(s['clicks'],1,100);number(s['interval'],0,60)
            if ready and s['kind'] in ('image','wait','find','condition') and s['enabled'] and s['image'] not in p['images']: raise ValueError(s['name']+': 이미지를 선택하세요.')
            if ready and s['kind']=='click' and not s['source']: raise ValueError('클릭할 인식 단계를 연결하세요.')
            if s['watch'] and s['watch'] not in p['images']: raise ValueError('감시 이미지 누락')
            if s['kind'] in ('break','continue') and not loops: raise ValueError('반복 밖에 탈출/다음 반복 단계가 있습니다.')
            visit(s['children'],depth+1,loops+(s['kind']=='loop')); visit(s['otherwise'],depth+1,loops)
    all_steps = [stage for index in range(tab_count(p)) for stage in tab_steps(p,index)]
    for index in range(tab_count(p)):
        visit(tab_steps(p,index))
    sizes = {}
    for uid,asset in p['images'].items():
        asset.pop('motion_mask',None)
        number(asset.get('dpi',96),48,768)
        im=decode_image(asset['data'])
        sizes[uid] = im.size
        if min(im.size)<4 or max(im.size)>8000: raise ValueError('이미지 크기 오류')
    # v1/v2 assigned the template crop itself as a search region. Keep a backup
    # and repair only that exact legacy signature; explicit user scopes survive.
    for s in walk(all_steps):
        if s['roi'] and not s.get('scope_explicit') and s['image'] in p['images']:
            size=sizes[s['image']]
            if tuple(s['roi'][2:])==size:
                s['legacy_capture_roi']=s['roi'];s['roi']=None
    validate_flow(p)
    if converted and on_legacy_motion is not None:
        on_legacy_motion(converted)
    return p

def save(p,path):
    validate(p,ready=False); path=Path(path); temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding='utf-8'); temp.replace(path)

def load(path,*,on_legacy_motion=None):
    p=validate(json.loads(Path(path).read_text(encoding='utf-8')),ready=False,
               on_legacy_motion=on_legacy_motion)
    for index in range(tab_count(p)):
        for s in walk(tab_steps(p,index)):
            if s['kind']=='image' and s['image_mode']=='wait' and s['timeout']==10:
                s.setdefault('wait_forever',True)
    return p

def expand_image_clicks(project):
    steps = [stage for index in range(tab_count(project)) for stage in tab_steps(project,index)]
    for image in walk(steps):
        if image['kind']=='image' and image['image_action']=='click':
            action=step('click')
            action.update(source=image['id'], configured_target=True, image_retry=True)
            for field in ('offset','button','clicks','interval'):
                action[field]=copy.deepcopy(image[field])
            image['children'].insert(0,action)
            image['image_action']='actions'


from recognition import match, search_regions, Model, recheck

class Halt(Exception): pass
class InputTargetChanged(Exception): pass
class Flow(Exception):
    def __init__(self,action,owner=None): self.action=action; self.owner=owner

class ImageLeft(Exception):
    def __init__(self, image_id):
        self.image_id=image_id


class Runner(Workflow):
    capture_error = CaptureError
    def __init__(self,p,emit,capture=None,output=None,*,editor_at=None,
                 shared_capture=None,input_gate=None,validated=False):
        self.p=copy.deepcopy(p if validated else validate(p)); self.emit=emit
        from desktop import capture_runtime
        self.native_capture=capture is None
        self.capture_source=capture or capture_runtime
        self.runtime_capture=None
        self.shared_capture=shared_capture
        self.input_gate=input_gate
        self.visible_repeat_depth=0
        self.output=output; self.cancel=threading.Event(); self.paused=threading.Event()
        self.editor_at=editor_at
        self.results={}; self.watches=[]; self.last_watch=0; self.held_keys=set(); self.paused_time=0
        self.probe_cache=threading.local()
        self.recovery_thread=None
        self.last_frame=None
        self.route_frame = None
        self.continuous=self.p.get('workflow_repeats',1)==0
        self.templates={k:Model(decode_image(v['data'])) for k,v in p['images'].items()}
        self.init_flow()
        if self.native_capture and not self.output:
            from desktop import Input
            self.input=Input()
        self.has_legacy_live_watch=any(s['kind']=='loop' and s['watch'] and s['watch_timing']=='during'
                                       for s in walk(self.p['steps']))

    def capture(self,roi):
        try:
            return self.capture_source(roi)
        except Exception as error:
            raise CaptureError(str(error)) from error

    def probe(self,s,image=None,*,shared_frame=None,diagnostic=True,budget=1,quick=False,
              checkpoint=None,runtime_capture=None):
        roi=s['roi']
        desktop_rect=None
        if self.native_capture and (roi is None or shared_frame is not None):
            from desktop import bounds
            desktop_rect=bounds()
        if shared_frame is not None:
            frame=shared_frame
        elif self.shared_capture is not None:
            try:
                frame=self.shared_capture.read(roi,self.capture)
            except Exception as error:
                raise CaptureError(str(error)) from error
        elif runtime_capture is not None:
            frame=runtime_capture.read(roi,self.capture)
        else:
            frame=self.capture(roi)
        if desktop_rect is not None and (frame.size!=tuple(desktop_rect[2:]) or bounds()!=desktop_rect):
            raise CaptureError('화면 배치 변경 중 · 캡처를 다시 확인합니다')
        if shared_frame is not None and roi:
            ox,oy=desktop_rect[:2] if desktop_rect is not None else (0,0)
            x,y,w,h=roi
            frame=frame.crop((x-ox,y-oy,x-ox+w,y-oy+h))
        if min(frame.size)<2: raise CaptureError('화면 캡처 크기 오류')
        asset=self.p['images'][image or s['image']]
        template=self.templates[image or s['image']]
        if (s['kind']=='condition' or s.get('repeat_while_visible') or
                template.silhouette is None) and not frame.getbbox():
            raise CaptureError('화면 판정 불가: 검은 화면')
        source_dpi=asset.get('dpi')
        cancel=checkpoint or (lambda:self.check(False))
        if self.native_capture:
            from desktop import monitors, bounds, capture_metadata
            if roi:
                dpi=capture_metadata(roi).get('dpi',96)
                regions=[dict(rect=roi,dpi=dpi,device='지정 영역')];origin=roi[:2]
            else:
                regions=monitors();origin=desktop_rect[:2]
                ox,oy,width,height=desktop_rect
                if bounds()!=desktop_rect or any(
                        not (ox<=x<x+w<=ox+width and oy<=y<y+h<=oy+height)
                        for x,y,w,h in (region['rect'] for region in regions)):
                    raise CaptureError('화면 배치 변경 중 · 캡처를 다시 확인합니다')
            key = (image or s['image'],tuple(origin),repr(regions),tuple(s['scales']),
                   s['threshold'],tuple(s['offset']),budget,quick)
            scope=tuple(roi) if roi else None
            banks=getattr(self.probe_cache,'banks',None)
            if banks is None:
                self.probe_cache.banks=banks={}
            bank=banks.get(scope)
            if bank is None or (bank[0] is not frame and (
                    runtime_capture is not None or self.shared_capture is not None or bank[0]!=frame)):
                if scope not in banks and len(banks)>=3:
                    banks.pop(next(iter(banks)))
                bank=(frame,{})
                banks[scope]=bank
            results=bank[1]
            r=results.get(key)
            if r is None:
                r=search_regions(frame,template,regions,origin,s['scales'],source_dpi,
                                 s['threshold'],s['offset'],cancel,budget=budget,quick=quick,fast=True)
                if len(results)>=48:
                    results.pop(next(iter(results)))
                results[key]=r.copy()
            else:
                r=r.copy()
        else:
            r=match(frame,template,s['threshold'],s['scales'],s['offset'],cancel)
            if r['box'] and roi:
                x,y,w,h=r['box']; px,py=r['point']
                r.update(box=(x+roi[0],y+roi[1],w,h),point=(px+roi[0],py+roi[1]))
        if diagnostic:
            self.last_frame=frame
            self.last_origin=roi[:2] if roi else (origin if self.native_capture else (0,0))
            self.last_detection=r
        return r
    def confirm_target(self, s, previous):
        x,y,w,h = previous['box']
        margin=8
        if self.native_capture:
            from desktop import bounds
            bx,by,bw,bh = s['roi'] or bounds()
            left,top = max(bx,x-margin),max(by,y-margin)
            right,bottom = min(bx+bw,x+w+margin),min(by+bh,y+h+margin)
            if right-left < w or bottom-top < h:
                return None
            rect = (left,top,right-left,bottom-top)
            if self.shared_capture is not None:
                try:
                    frame=self.shared_capture.confirm(rect,self.capture)
                except Exception as error:
                    raise CaptureError(str(error)) from error
            else:
                frame = (self.runtime_capture.confirm(rect,self.capture)
                         if self.runtime_capture is not None else self.capture(rect))
        else:
            frame = self.capture(s['roi'])
            left,top = s['roi'][:2] if s['roi'] else (0,0)
        if not frame.getbbox():
            if s['kind']!='condition' and self.templates[s['image']].silhouette is not None:
                return None
            raise CaptureError('화면 판정 불가: 검은 화면')
        local = dict(previous,box=(x-left,y-top,w,h))
        result=recheck(frame,self.templates[s['image']],local,s['threshold'],s['offset'],
                       lambda:self.check(False))
        if not result['found']:
            return None
        px,py=result['point']
        return px+left,py+top

    def check(self,monitor=True):
        if self.cancel.is_set(): raise Halt()
        pause_start=time.monotonic()
        while self.paused.is_set():
            if self.cancel.wait(.05): raise Halt()
        self.paused_time+=time.monotonic()-pause_start
        if monitor and self.watch_thread is None:
            self.observe_routes()
        now=time.monotonic()
        if monitor and self.watch_thread is None and now-self.last_watch>.15:
            self.last_watch=now
            for w in self.watches:
                if not w['s']['watch'] or w['s']['watch_timing']!='during' or w['latched']: continue
                try:
                    r=self.probe(w['s'],w['s']['watch'])
                except CaptureError:
                    w['hits']=0
                    continue
                w['hits']=w['hits']+1 if r['found'] else 0
                if w['hits']>=w['s']['stable']: w['latched']=True
    def sleep(self,seconds,monitor=True):
        left=seconds
        while left>0:
            self.check(monitor)
            if monitor:
                self.commit_route()
            start=time.monotonic()
            self.cancel.wait(min(.03,left))
            left-=time.monotonic()-start
    def boundary(self):
        self.commit_route()
        if self.gesture_held:
            return
        for w in self.watches:
            if w['latched'] and w['s']['watch_apply']=='action': raise Flow(w['s']['watch_action'],w['s']['id'])

    def wait_for_pointer_target(self,x,y):
        if self.editor_at is None or not self.editor_at(x,y):
            return False
        self.emit('input_blocked',None)
        try:
            while self.editor_at(x,y):
                self.sleep(.05)
            self.check()
            self.boundary()
            return True
        finally:
            self.emit('input_clear',None)

    def input_turn(self):
        self.check(False)
        return self.input_gate.turn(self.cancel) if self.input_gate else nullcontext()

    def send(self,kind,*args,revalidate=None,retry_pointer=None):
        with self.input_turn():
            self.send_input(kind,*args,revalidate=revalidate,retry_pointer=retry_pointer)

    def send_input(self,kind,*args,revalidate=None,retry_pointer=None):
        self.check()
        self.boundary()
        self.route_frame=None
        if kind=='configured_click' and self.input_gate and revalidate is not None:
            args=(*revalidate(),*args[2:])
        if self.output: self.output(kind,*args); return
        from desktop import Input
        if not hasattr(self,'input'):self.input=Input()
        inp=self.input
        if kind=='click':
            self.wait_for_pointer_target(*args[:2])
            inp.click_at(*args[:2],inp.buttons.left);return
        if kind=='configured_click':
            x,y,button,clicks,interval=args
            for i in range(clicks):
                if i:
                    self.check()
                    self.boundary()
                    if revalidate is not None:
                        x,y=revalidate()
                while True:
                    if self.wait_for_pointer_target(x,y) and revalidate is not None:
                        x,y=revalidate()
                        continue
                    self.check(False)
                    try:
                        inp.click_at(x,y,getattr(inp.buttons,button))
                    except PointerMoved as error:
                        if retry_pointer is None:
                            raise
                        self.report_wait(retry_pointer,0,'moved',str(error))
                        self.sleep(.10)
                        x,y=revalidate()
                    else:
                        break
                if i+1<clicks:self.sleep(interval)
            return
        if kind=='drag':
            x,y,x2,y2,duration=args
            self.wait_for_pointer_target(x,y)
            inp.mouse.position=(x,y)
            inp.mouse_button(inp.buttons.left,True)
            try:
                for i in range(1,61):self.sleep(duration/60);inp.mouse.position=(round(x+(x2-x)*i/60),round(y+(y2-y)*i/60))
            finally:inp.mouse_button(inp.buttons.left,False)
            return
        if kind in ('key','hold'):
            keys=args[0].split('+')
            try:
                for key in keys:inp.key(key,True)
                if kind=='hold':self.sleep(args[1])
            finally:
                for key in reversed(keys):inp.key(key,False)
            return
        if kind=='text':inp.keys.type(args[0]);return
        if kind=='scroll':
            self.wait_for_pointer_target(*inp.mouse.position)
            inp.mouse.scroll(0,args[0]);return
        if kind=='event':
            e=args[0]
            guard=self.wait_for_pointer_target if e['type']=='scroll' or e.get('down',False) else None
            if 'x' in e and 'y' in e:
                if e.get('anchor'):
                    from screen_ui import resolve
                    point=resolve(e['anchor'],e['type']=='scroll' or e.get('down',False),
                                  activate=e['type']=='mouse' and e.get('down',False),
                                  wait_if_covered=guard)
                else:
                    point=(e['x'],e['y'])
                    if guard:
                        guard(*point)
                inp.move_to(*point)
            elif e['type']=='scroll':
                self.wait_for_pointer_target(*inp.mouse.position)
            if e['type']=='mouse':
                inp.mouse_button(getattr(inp.buttons,e['button']), e['down'])
            elif e['type']=='scroll':inp.mouse.scroll(e.get('dx',0),e['dy'])
            elif e['type']=='key':
                if e.get('target') and (e['down'] or ('key',e['key']) not in self.gesture_held):
                    from screen_ui import focus_window
                    focus_window(e['target'])
                if 'korean_mode' in e:
                    from keyboard_ime import restore_korean_mode
                    mode=e['korean_mode']
                    if not restore_korean_mode(mode) and mode:
                        raise RuntimeError('대상 창에서 한글 입력 모드를 사용할 수 없습니다.')
                inp.key(f'vk:{e["vk"]}' if 'vk' in e else e['key'],e['down'])
            return
    def replay_events(self,events,step_id=None):
        turn=ExitStack()
        try:
            for e in events:
                self.sleep(e['delay'])
                wait_started=None
                while True:
                    try:
                        if self.input_gate:
                            if not self.gesture_held:
                                turn.enter_context(self.input_turn())
                            self.send_input('event',e)
                        else:
                            self.send('event',e)
                        if wait_started is not None:
                            self.emit('active',step_id)
                            self.emit('log','대상 창이 다시 사용 가능해져 녹화 동작을 계속합니다.')
                        break
                    except TargetUnavailable as error:
                        repeating = self.continuous or self.visible_repeat_depth or self.repeat is not None
                        if not repeating or step_id is None:
                            raise
                        if self.gesture_held:
                            self.emit('log',f'대상 창이 가려져 진행 중이던 녹화 동작을 중단했습니다. · {error}')
                            return False
                        turn.close()
                        now=time.monotonic()
                        if wait_started is None:
                            wait_started=now
                            self.emit('log',f'대상 창 대기 · {error}')
                        self.report_wait(step_id,int(now-wait_started),'target_unavailable',str(error))
                        self.sleep(.15)
                if e['type'] in ('mouse','key'):
                    token=(e['type'],e.get('button',e.get('key')))
                    if e['down']:
                        self.gesture_held.add(token)
                    else:
                        self.gesture_held.discard(token)
                if not self.gesture_held:
                    turn.close()
        finally:
            try:
                if self.gesture_held and getattr(self,'input',None):
                    self.input.release()
            finally:
                self.gesture_held.clear()
                turn.close()

    def wait_image(self,s):
        capture = None
        if self.native_capture and self.output is None and self.shared_capture is None:
            from runtime_capture import RuntimeCapture
            if self.runtime_capture is None:
                self.runtime_capture = RuntimeCapture()
            capture = self.runtime_capture
        if (not self.native_capture or s['kind'] not in ('image','wait')
                or (s['image_mode']=='once' and not repeat_waits_for_image(s,self.continuous))):
            return self.poll_image(s,runtime_capture=capture)
        stop=threading.Event()
        try:
            return self.poll_image(s, recovery_stop=stop,runtime_capture=capture)
        finally:
            stop.set()

    def start_image_recovery(self,step,stop,result,frame=None):
        def checkpoint():
            if stop.is_set() or self.cancel.is_set() or self.paused.is_set():
                raise Halt()
        try:
            candidate=self.probe(step,shared_frame=frame,diagnostic=False,checkpoint=checkpoint,budget=2)
            if candidate['found'] and not stop.is_set():
                result.append(candidate)
        except (Halt,CaptureError):
            pass
        except Exception as error:
            result.append(error)

    def poll_image(self,s,recovery_stop=None,runtime_capture=None):
        if self.carried and self.carried[0]==s['id']:
            _,result=self.carried
            self.carried=None
            return result
        retry_missing=repeat_waits_for_image(s,self.continuous)
        once=s['kind'] not in ('image','wait') or (s['image_mode']=='once' and not retry_missing)
        budget=1
        checks=0
        elapsed=0.
        hits=0
        old=None
        previous=None
        recovered=[]
        next_recovery=time.monotonic()+(.16 if s['roi'] is None else .32)
        recovery_frame=None
        outage_started=None
        while True:
            started=time.monotonic()
            paused=self.paused_time
            self.check()
            if self.paused_time!=paused:
                recovery_frame=None
            self.boundary()
            quick=False
            try:
                point=self.confirm_target(s,previous) if self.native_capture and hits and previous else None
                if point is None:
                    quick=recovery_stop is not None
                    candidate=recovered.pop() if recovered else None
                    if isinstance(candidate,Exception):
                        raise candidate
                    point=self.confirm_target(s,candidate) if candidate else None
                    if point is not None:
                        x,y,w,h=candidate['box']
                        px,py=candidate['point']
                        r=dict(candidate,point=point,box=(x+point[0]-px,y+point[1]-py,w,h))
                    else:
                        if runtime_capture is not None:
                            r=self.probe(s,budget=budget,quick=quick,runtime_capture=runtime_capture)
                        else:
                            r=self.probe(s,budget=budget,quick=quick)
                    if quick and recovery_stop and not r['found'] and checks>=2 and started>=next_recovery and (
                            self.recovery_thread is None or not self.recovery_thread.is_alive()):
                        frame = self.last_frame
                        if runtime_capture is None or frame is None or frame is not recovery_frame:
                            recovery_frame = frame
                            shared = frame if s['roi'] is None else None
                            worker=threading.Thread(target=self.start_image_recovery,
                                                    args=(s,recovery_stop,recovered,shared),
                                                    daemon=True,
                                                    name='ImageMacro precise search')
                            try:
                                worker.start()
                            except (OSError,RuntimeError) as error:
                                self.emit('log',f'백그라운드 검색 시작 실패 · 일반 검색으로 계속 · {error}')
                                recovery_stop=None
                            else:
                                self.recovery_thread=worker
                        next_recovery=time.monotonic()+.18
                else:
                    x,y,w,h=previous['box']
                    px,py=previous['point']
                    r=dict(previous,point=point,box=(x+point[0]-px,y+point[1]-py,w,h))
            except CaptureError as error:
                if self.continuous or retry_missing:
                    hits,old,previous=0,None,None
                    self.last_frame=None
                    if outage_started is None:
                        outage_started=time.monotonic()
                        self.emit('log',f'{s["name"]} · 화면 읽기 중단 · {error}')
                    self.report_wait(s['id'],int(time.monotonic()-outage_started),'capture_error',str(error))
                    self.sleep(.10)
                    continue
                if once or not s.get('wait_forever'):
                    raise
                self.last_frame=None
                r=dict(found=False,status='capture_error',point=None,reason=str(error),score=0.)
            if outage_started is not None:
                self.emit('log',f'{s["name"]} · 화면 읽기 복구')
                outage_started=None
            checks+=1
            status=r.get('status')
            if once and status in ('ambiguous','insufficient','incomplete','capture_error'):
                raise RuntimeError(r['reason'])
            point=r['point']
            near=old is not None and point is not None and max(abs(a-b) for a,b in zip(point,old))<8
            hits=(hits+1 if near else 1) if r['found'] else 0
            old=point
            previous=r if r['found'] else None
            if once or hits>=s['stable']:
                if r['found']:
                    with self.route_lock:
                        self.seen_images.add(s['id'])
                return r
            budget=min(8,budget*2) if status=='incomplete' and not quick and checks>2 else 1
            self.report_wait(s['id'],round(elapsed),status,r['reason'])
            interval = .010 if recovery_stop is not None else .045
            self.sleep(max(0,interval-(time.monotonic()-started)))
            elapsed+=time.monotonic()-started-(self.paused_time-paused)
            if not retry_missing and not s.get('wait_forever') and elapsed>=s['timeout']:
                if s['kind']=='wait' or status in ('ambiguous','insufficient','incomplete'):
                    raise TimeoutError(r['reason'])
                return dict(r,found=False)

    def locate_click(self,source,result,action,retry):
        settings=dict(source,offset=action['offset'] if action.get('configured_target') or action is source else source['offset'])
        repeat=source.get('repeat_while_visible',False)
        while result['found']:
            try:
                point=self.confirm_target(settings,result)
            except CaptureError:
                if (self.continuous or retry) and not repeat:
                    self.report_wait(action['id'],0,'capture_error','클릭 위치를 읽을 수 있을 때까지 기다립니다.')
                    self.sleep(.10)
                    continue
                if not retry and not repeat:
                    raise
                point=None
            if point is not None:
                if self.wait_for_pointer_target(*point):
                    continue
                return point,result
            if not (repeat or retry):
                break
            self.report_wait(action['id'],0,'moved','클릭 위치를 새 화면에서 확인합니다.')
            if repeat:
                # A changed scene ends this card; do not replay earlier
                # actions or click the original coordinates.
                result=self.verify_disappearance(source,result,self.next_image(source),local=False)
                if result is None:
                    raise ImageLeft(source['id'])
            else:
                self.sleep(.025)
                result=self.wait_image(source)
            self.results[source['id']]=(source,result)
        raise RuntimeError('클릭 직전 대상이 이동하거나 사라짐')

    def click_detected_image(self,source,result,action,retry=False):
        if self.input_gate:
            self.parallel_image_click(source,result,action,retry)
            return
        point,result=self.locate_click(source,result,action,retry)
        def revalidate():
            nonlocal result
            new_point,result=self.locate_click(source,result,action,retry)
            return new_point
        self.emit('log',f'{source["name"]} · 클릭 위치 확인 · {point}')
        self.send('configured_click',*point,action['button'],action['clicks'],action['interval'],
                  revalidate=revalidate,
                  retry_pointer=action['id'] if self.continuous or source.get('repeat_while_visible') else None)
        self.emit('log',f'{source["name"]} · 클릭 입력 전달')

    def parallel_image_click(self,source,result,action,retry):
        settings=dict(source,offset=action['offset'] if action.get('configured_target') or action is source
                      else source['offset'])

        def confirm():
            try:
                point=self.confirm_target(settings,result)
            except CaptureError:
                point=None
            if point is None:
                raise InputTargetChanged()
            return point

        for index in range(action['clicks']):
            if index:
                self.sleep(action['interval'])
            while True:
                try:
                    self.send('configured_click',*result['point'],action['button'],1,0,
                              revalidate=confirm)
                    break
                except (InputTargetChanged,PointerMoved):
                    if index:
                        self.emit('log','대상이 바뀌어 남은 클릭을 취소했습니다.')
                        return
                    if not (retry or source.get('repeat_while_visible')):
                        self.emit('log','입력 차례에 이미지가 사라져 클릭하지 않았습니다.')
                        raise ImageLeft(source['id']) if source['kind']=='image' else RuntimeError(
                            '클릭 직전 이미지가 사라졌습니다.')
                    _,result=self.locate_click(source,result,action,retry)
        self.emit('log',f'{source["name"]} · 클릭 입력 전달')

    def presence(self, image, previous=None, *, budget=1):
        if previous and previous.get('box') and not image.get('repeat_while_visible'):
            point=self.confirm_target(image,previous)
            if point is not None:
                x,y,w,h=previous['box']
                px,py=previous['point']
                return dict(previous,point=point,box=(x+point[0]-px,y+point[1]-py,w,h))
        return self.probe(image,budget=budget)

    def verify_disappearance(self, image, result, following=None, *, local=True):
        misses=0
        missing_since=None
        # A visible group can briefly lose its image during redraws or overlays.
        absence_grace=.75 if self.native_capture and image.get('repeat_while_visible') else 0.
        uncertain=0
        budget=1
        next_hits=0
        next_checks=0
        next_candidate=None
        delay=.025
        while True:
            self.sleep(delay)
            delay=.025
            if following:
                next_checks+=1
                detected=self.wait_image_candidate(following)
                if detected:
                    near=next_candidate and max(abs(a-b) for a,b in zip(detected['point'],next_candidate['point']))<8
                    next_hits=next_hits+1 if near else 1
                    next_candidate=detected
                    if next_hits>=following['stable']:
                        self.carried=(following['id'],detected)
                        self.emit('log',f'{following["name"]} · 다음 이미지 발견')
                        return None
                else:
                    next_hits=0
                    next_candidate=None
            try:
                if (absence_grace and missing_since is not None
                        and time.monotonic()-self.paused_time-missing_since>=absence_grace):
                    budget=max(2,budget)
                current=self.presence(image,result if local else None,budget=budget)
            except CaptureError:
                current=dict(found=False,status='capture_error',reason='화면을 읽을 수 없습니다')
            if current['found']:
                missing_since=None
                misses=0
                if next_hits and next_checks<following['stable']:
                    result=current
                    continue
                return current
            if current['status']=='not_found':
                now=time.monotonic()-self.paused_time
                if missing_since is None:
                    missing_since=now
                misses+=1
                uncertain=0
                if misses>=2 and now-missing_since>=absence_grace:
                    if absence_grace and budget<2:
                        budget=2
                        delay=0
                        continue
                    break
                budget=1
                self.report_wait(image['id'],int(now-missing_since),'disappearing',
                                 '대상이 다시 보이는지 확인합니다')
                if absence_grace:
                    # Sample again at the cutoff instead of waiting another full poll.
                    delay=min(.05,absence_grace-(now-missing_since))
                elif self.native_capture:
                    self.sleep(.10)
            else:
                misses=0
                missing_since=None
                uncertain+=1
                budget=min(8,budget*2) if current['status']=='incomplete' else 1
                self.report_wait(image['id'],0,current['status'],current['reason'])
                if uncertain>=20 and not (self.continuous or image.get('repeat_while_visible')):
                    raise RuntimeError(current['reason'])
        self.emit('log',f'{image["name"]} · 사라짐 확인')
        return None

    def next_image(self, image):
        if not image.get('advance_on_next') or self.position is None:
            return None
        if self.top_steps[self.position]['id'] != image['id']:
            return None
        step=next((step for step in self.top_steps[self.position+1:] if step['enabled']),None)
        return step if step and step['kind']=='image' else None

    def retry_image_click(self, image):
        return (repeat_waits_for_image(image,self.continuous)
                or (image['image_mode']=='wait' and image.get('wait_forever',False)))

    def execute_image_actions(self, image, result):
        uid=image['id']
        repeat=image.get('repeat_while_visible',False)
        iteration=1
        self.visible_repeat_depth+=int(repeat)
        try:
            while True:
                self.results[uid]=(image,result)
                if repeat:
                    self.emit('image_iteration',(uid,iteration))
                try:
                    if image['image_action']=='click':
                        self.click_detected_image(image,result,image,retry=self.retry_image_click(image))
                    self.execute(image['children'])
                except ImageLeft as error:
                    if error.image_id!=uid:
                        raise
                    return
                if not repeat:
                    return
                result=self.verify_disappearance(image,self.results[uid][1],self.next_image(image))
                if result is None:
                    return
                iteration+=1
        finally:
            self.visible_repeat_depth-=int(repeat)

    def wait_image_candidate(self,image):
        try:
            result=self.probe(image)
        except CaptureError:
            return None
        return result if result['found'] else None

    def report_wait(self,uid,seconds,status,reason):
        event=(uid,seconds,status,reason)
        if event!=getattr(self,'last_wait_event',None):
            self.last_wait_event=event
            self.emit('waiting',event)

    def execute(self,items):
        for s in items:
            self.check(); self.boundary()
            if not s['enabled']: continue
            self.last_wait_event=None
            self.emit('active',s['id']); k=s['kind']
            try:
                self.sleep(s.get('before',0))
                self.in_action=k in ('record','point','drag','key','hold','text','scroll','click')
                if k in ('image','wait','find','condition'):
                    r=self.wait_image(s)
                    self.results[s['id']]=(s,r)
                    if r['found']:
                        label='대상 후보 발견' if k=='image' else '인식 완료'
                        self.emit('log',f'{s["name"]} · {label} · {r.get("scale",1):.0%} · 위치 {r.get("point")}')
                    if k=='image':
                        if r['found']:
                            self.execute_image_actions(s,r)
                        elif s['otherwise']:self.execute(s['otherwise'])
                        else:
                            reason = r.get('reason','이미지 없음')
                            if r.get('score'):
                                reason += f' · 최고 유사도 {r["score"]:.3f} / 기준 {s["threshold"]:.3f}'
                            scope = '모든 모니터' if s['roi'] is None else '지정 영역'
                            raise TimeoutError(f'{reason} · {scope}')
                    elif k=='condition': self.execute(s['children'] if r['found'] else s['otherwise'])
                    elif not r['found']: raise RuntimeError('이미지 없음 또는 후보가 여러 개입니다.')
                elif k=='click':
                    source=self.results.get(s['source'])
                    if not source or not source[1]['found']:
                        raise RuntimeError('클릭할 인식 결과가 없습니다.')
                    image,found=source
                    retry=self.retry_image_click(image)
                    if s.get('configured_target') or self.input_gate:
                        self.click_detected_image(image,found,s,retry=retry)
                    else:
                        point,_=self.locate_click(image,found,s,retry)
                        self.send('click',*point)
                elif k=='point': self.send('configured_click',s['x'],s['y'],s['button'],s['clicks'],s['interval'])
                elif k=='drag': self.send('drag',s['x'],s['y'],s['x2'],s['y2'],max(.1,s['seconds']))
                elif k=='key': self.send('key',s['key'])
                elif k=='hold':self.send('hold',s['key'],s['seconds'])
                elif k=='text':self.send('text',s['text'])
                elif k=='scroll':self.send('scroll',s['scroll'])
                elif k=='delay': self.sleep(s['seconds'])
                elif k=='record':
                    if self.replay_events(s['events'],s['id']) is False:
                        self.in_action=False
                        self.emit('step_skipped',s['id'])
                        self.boundary()
                        continue
                elif k=='loop': self.loop(s)
                elif k in ('break','continue'): raise Flow(k)
                elif k=='stop':
                    self.emit('log',s['name']+' · 작업 순서에서 정지 요청')
                    raise Halt()
                self.in_action=False
                self.emit('step_done',s['id'])
                self.emit('log',s['name']+' · 완료'); self.boundary()
            except (Halt,Flow,Jump,ImageLeft):
                self.in_action=False
                raise
            except Exception as e:
                self.in_action=False
                self.emit('step_error',(s['id'],str(e)))
                self.emit('log',s['name']+' · 오류: '+str(e))
                if s['failure']=='stop': raise
    def loop(self,s):
        w=dict(s=s,hits=0,latched=False)
        with self.route_lock:
            self.watches.append(w)
        self.last_watch=0
        try:
            for i in range(s['count']):
                self.emit('iteration',(s['id'],i+1,s['count']))
                self.emit('log',s['name']+f' · {i+1}/{s["count"]}회')
                try:
                    self.execute(s['children'])
                    if s['watch'] and s['watch_timing']=='after':
                        while True:
                            try:
                                w['latched']=self.probe(s,s['watch'])['found']
                                break
                            except CaptureError as error:
                                if not self.continuous:
                                    raise
                                self.report_wait(s['id'],0,'capture_error',str(error))
                                self.sleep(.10)
                    if w['latched']: raise Flow(s['watch_action'],s['id'])
                except Flow as f:
                    if f.action=='stop':
                        self.emit('log',s['name']+' · 감시 조건이 충족되어 정지')
                        raise Halt()
                    if f.owner and f.owner!=s['id']: raise
                    if f.action=='break': break
                    with self.route_lock:
                        w['latched']=False; w['hits']=0
        finally:
            with self.route_lock:
                self.watches.remove(w)
    def run(self):
        try:
            self.execute_workflow()
            self.emit('state','완료')
        except Halt: self.emit('state','정지됨')
        except Exception as e: self.emit('log',str(e)); self.emit('state','오류')
        finally:
            self.watch_stop.set()
            if self.watch_thread:
                self.watch_thread.join(.20)
            if self.recovery_thread:
                self.recovery_thread.join(.20)
            try:
                if self.runtime_capture is not None:
                    capture,self.runtime_capture = self.runtime_capture,None
                    capture.close()
                if not self.output and hasattr(self,'input'):
                    self.input.release()
            except Exception as error:
                self.emit('log',f'입력 정리 중 오류 · {error}')
            finally:
                self.emit('done',None)
