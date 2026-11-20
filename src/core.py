"""Image Macro: portable project model, image matching and cancellable runner."""
import base64, copy, io, json, math, threading, time, uuid
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageGrab
from imacro_flow import Workflow, Jump, validate_flow

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

def walk(steps):
    for s in steps:
        yield s
        yield from walk(s['children']); yield from walk(s['otherwise'])

def validate(p,ready=True):
    if p.get('format')!='ImageMacro' or p.get('version')!=1: raise ValueError('지원하지 않는 프로젝트 형식입니다.')
    count=p.get('workflow_repeats',1)
    if type(count) is not int or not 0<=count<=100000:
        raise ValueError('전체 반복 횟수 오류')
    ids=set()
    def number(v,lo,hi):
        if not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi: raise ValueError('숫자 설정 범위 오류')
    def visit(items,depth=0,loops=0):
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
            if 'moving' in s and type(s['moving']) is not bool:
                raise ValueError('움직이는 대상 설정 오류')
            if 'motion_feature' in s and (type(s['motion_feature']) is not bool or
                                          s['motion_feature'] and not s.get('moving')):
                raise ValueError('색 무늬 모드 설정 오류')
            variants=s.get('variants',[])
            if not isinstance(variants,list) or len(variants)>2 or any(
                    not isinstance(k,str) or k not in p['images'] for k in variants):
                raise ValueError('추가 이미지 설정 오류')
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
            if s['button'] not in ('left','right','middle'):raise ValueError('마우스 버튼 오류')
            number(s['clicks'],1,100);number(s['interval'],0,60)
            if ready and s['kind'] in ('image','wait','find','condition') and s['enabled'] and s['image'] not in p['images']: raise ValueError(s['name']+': 이미지를 선택하세요.')
            if ready and s['kind']=='click' and not s['source']: raise ValueError('클릭할 인식 단계를 연결하세요.')
            if s['watch'] and s['watch'] not in p['images']: raise ValueError('감시 이미지 누락')
            if s['kind'] in ('break','continue') and not loops: raise ValueError('반복 밖에 탈출/다음 반복 단계가 있습니다.')
            visit(s['children'],depth+1,loops+(s['kind']=='loop')); visit(s['otherwise'],depth+1,loops)
    visit(p['steps'])
    for asset in p['images'].values():
        number(asset.get('dpi',96),48,768)
        im=decode_image(asset['data'])
        if min(im.size)<4 or max(im.size)>8000: raise ValueError('이미지 크기 오류')
    # v1/v2 assigned the template crop itself as a search region. Keep a backup
    # and repair only that exact legacy signature; explicit user scopes survive.
    for s in walk(p['steps']):
        if s['roi'] and not s.get('scope_explicit') and s['image'] in p['images']:
            size=decode_image(p['images'][s['image']]['data']).size
            if tuple(s['roi'][2:])==size:
                s['legacy_capture_roi']=s['roi'];s['roi']=None
    validate_flow(p)
    return p

def save(p,path):
    validate(p,ready=False); path=Path(path); temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding='utf-8'); temp.replace(path)

def load(path):
    p=validate(json.loads(Path(path).read_text(encoding='utf-8')),ready=False)
    for s in walk(p['steps']):
        if s['kind']=='image' and s['image_mode']=='wait' and s['timeout']==10:
            s.setdefault('wait_forever',True)
    return p

def expand_image_clicks(project):
    for image in walk(project['steps']):
        if image['kind']=='image' and image['image_action']=='click':
            action=step('click')
            action.update(source=image['id'], configured_target=True, image_retry=True)
            for field in ('offset','button','clicks','interval'):
                action[field]=copy.deepcopy(image[field])
            image['children'].insert(0,action)
            image['image_action']='actions'


from recognition import match, search_regions, scale_candidates, Model, recheck
from recognition_motion import moving_matches
from recognition_landmark import landmark_model

class Halt(Exception): pass
class Flow(Exception):
    def __init__(self,action,owner=None): self.action=action; self.owner=owner

class CaptureError(RuntimeError): pass


class Runner(Workflow):
    capture_error = CaptureError
    def __init__(self,p,emit,capture=None,output=None):
        self.p=copy.deepcopy(validate(p)); self.emit=emit
        from desktop import capture as desktop_capture
        self.native_capture=capture is None
        self.capture_source=capture or desktop_capture
        self.output=output; self.cancel=threading.Event(); self.paused=threading.Event()
        self.results={}; self.watches=[]; self.last_watch=0; self.held_keys=set(); self.paused_time=0
        self.probe_cache=threading.local()
        self.route_frame = None
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

    def motion_templates(self,s):
        return [(uid,self.templates[uid]) for uid in dict.fromkeys([s['image'],*s.get('variants',[])])
                if uid in self.templates]

    def probe(self,s,image=None,*,shared_frame=None,diagnostic=True,budget=1,quick=False,checkpoint=None):
        roi=s['roi']
        captured=time.monotonic()
        frame=self.capture(roi) if shared_frame is None else shared_frame
        if shared_frame is not None and roi:
            from desktop import bounds
            ox,oy=bounds()[:2] if self.native_capture else (0,0)
            x,y,w,h=roi
            frame=frame.crop((x-ox,y-oy,x-ox+w,y-oy+h))
        if min(frame.size)<2: raise CaptureError('화면 캡처 크기 오류')
        if not frame.getbbox():
            raise CaptureError('화면 판정 불가: 검은 화면')
        asset=self.p['images'][image or s['image']]
        template=self.templates[image or s['image']]
        source_dpi=asset.get('dpi')
        cancel=checkpoint or (lambda:self.check(False))
        if s.get('moving') and image is None:
            models=self.motion_templates(s)
            if s.get('motion_feature') and not any(landmark_model(m) is not None for _,m in models):
                raise ValueError('색 무늬가 사진 중앙에 오고 주위 색이 함께 보이도록 다시 캡처하세요.')
            if roi:
                origin=roi[:2]
            elif self.native_capture:
                from desktop import bounds
                origin=bounds()[:2]
            else:
                origin=(0,0)
            r=moving_matches(frame,models,s['threshold'],s['offset'],cancel,
                             scales=tuple(dict.fromkeys([1.,*s['scales']])) if not quick else (1.,),
                             landmark=s.get('motion_feature',False))
            if r['box']:
                x,y,w,h=r['box']
                px,py=r['point']
                r.update(box=(x+origin[0],y+origin[1],w,h),point=(px+origin[0],py+origin[1]),
                         captured=captured)
        elif self.native_capture:
            from desktop import monitors, bounds, capture_metadata
            if roi:
                dpi=capture_metadata(roi).get('dpi',96)
                regions=[dict(rect=roi,dpi=dpi,device='지정 영역')];origin=roi[:2]
            else:
                regions=monitors();origin=bounds()[:2]
            key = (image or s['image'],tuple(origin),repr(regions),tuple(s['scales']),
                   s['threshold'],tuple(s['offset']),budget,quick)
            scope=tuple(roi) if roi else None
            banks=getattr(self.probe_cache,'banks',None)
            if banks is None:
                self.probe_cache.banks=banks={}
            bank=banks.get(scope)
            if bank is None or (bank[0] is not frame and bank[0]!=frame):
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
    def confirm_target(self, s, previous, *, lead=False):
        x,y,w,h = previous['box']
        moving=s.get('moving') and previous.get('asset')
        if moving:
            age=max(0,time.monotonic()-previous.get('captured',time.monotonic()))
            margin=min(220,max(96,round(age*1250)+20))
        else:
            margin=8
        if self.native_capture:
            from desktop import bounds
            bx,by,bw,bh = s['roi'] or bounds()
            left,top = max(bx,x-margin),max(by,y-margin)
            right,bottom = min(bx+bw,x+w+margin),min(by+bh,y+h+margin)
            if right-left < w or bottom-top < h:
                return None
            frame = self.capture((left,top,right-left,bottom-top))
        else:
            frame = self.capture(s['roi'])
            left,top = s['roi'][:2] if s['roi'] else (0,0)
        sampled=time.monotonic()
        local = dict(previous,box=(x-left,y-top,w,h))
        if moving:
            candidates=self.motion_templates(s)
            def check_motion(new_frame):
                return moving_matches(new_frame,candidates,s['threshold'],s['offset'],
                                      lambda:self.check(False),near=(x-left+w/2,y-top+h/2,margin),
                                      scales=(previous['scale'],),landmark=previous.get('method')=='landmark')
            result=check_motion(frame)
            if lead and self.native_capture and result['found'] and (
                    result['point'][0]+left,result['point'][1]+top)==previous['point']:
                self.cancel.wait(.018)
                self.check(False)
                result=check_motion(self.capture((left,top,right-left,bottom-top)))
                sampled=time.monotonic()
        else:
            result=recheck(frame,self.templates[s['image']],local,s['threshold'],s['offset'],
                           lambda:self.check(False))
        if not result['found']:
            return None
        px,py=result['point']
        if moving and lead and previous.get('captured'):
            ax,ay,aw,ah=result['box']
            dt=max(.012,sampled-previous['captured'])
            # Anticipate at most one display interval, and keep the
            # adjusted click inside the rectangle we just verified.
            for axis,(current,old,size,corner,origin) in enumerate(zip(
                    (px,py),previous['point'],(aw,ah),(ax,ay),(left,top))):
                limit=min(22,size*.25)
                shift=round(max(-limit,min(limit,(current+origin-old)*.023/dt)))
                adjusted=max(corner,min(corner+size-1,current+shift))
                if axis==0:
                    px=adjusted
                else:
                    py=adjusted
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
                r=self.probe(w['s'],w['s']['watch'])
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
    def send(self,kind,*args):
        self.check()
        self.boundary()
        self.route_frame=None
        if self.output: self.output(kind,*args); return
        from desktop import Input
        if not hasattr(self,'input'):self.input=Input()
        inp=self.input
        if kind=='click':
            inp.click_at(*args[:2],inp.buttons.left);return
        if kind=='configured_click':
            x,y,button,clicks,interval=args
            for i in range(clicks):
                if i:
                    self.check()
                    self.boundary()
                inp.click_at(x,y,getattr(inp.buttons,button))
                if i+1<clicks:self.sleep(interval)
            return
        if kind=='drag':
            x,y,x2,y2,duration=args;inp.mouse.position=(x,y);inp.mouse.press(inp.buttons.left)
            try:
                for i in range(1,61):self.sleep(duration/60);inp.mouse.position=(round(x+(x2-x)*i/60),round(y+(y2-y)*i/60))
            finally:inp.mouse.release(inp.buttons.left)
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
        if kind=='scroll':inp.mouse.scroll(0,args[0]);return
        if kind=='event':
            e=args[0]
            if 'x' in e and 'y' in e:
                if e.get('anchor'):
                    from screen_ui import resolve
                    point=resolve(e['anchor'],e['type']=='scroll' or e.get('down',False),
                                  activate=e['type']=='mouse' and e.get('down',False))
                else:
                    point=(e['x'],e['y'])
                inp.move_to(*point)
            if e['type']=='mouse':
                inp.mouse_button(getattr(inp.buttons,e['button']), e['down'])
            elif e['type']=='scroll':inp.mouse.scroll(e.get('dx',0),e['dy'])
            elif e['type']=='key':
                if e.get('target'):
                    from screen_ui import focus_window
                    focus_window(e['target'])
                inp.key(e['key'],e['down'])
            return
    def replay_events(self,events):
        try:
            for e in events:
                self.sleep(e['delay'])
                self.send('event',e)
                if e['type'] in ('mouse','key'):
                    token=(e['type'],e.get('button',e.get('key')))
                    if e['down']:
                        self.gesture_held.add(token)
                    else:
                        self.gesture_held.discard(token)
        finally:
            if self.gesture_held and getattr(self,'input',None):
                self.input.release()
            self.gesture_held.clear()

    def wait_image(self,s):
        if not self.native_capture or s['kind'] not in ('image','wait') or s['image_mode']=='once':
            return self.poll_image(s)
        stop=threading.Event()
        try:
            return self.poll_image(s, recovery_stop=stop)
        finally:
            stop.set()

    def start_image_recovery(self,step,stop,result):
        def checkpoint():
            if stop.is_set() or self.cancel.is_set():
                raise Halt()
        try:
            candidate=self.probe(step,diagnostic=False,checkpoint=checkpoint,budget=2)
            if candidate['found'] and not stop.is_set():
                result.append(candidate)
        except (Halt,CaptureError):
            pass
        except Exception as error:
            result.append(error)

    def poll_image(self,s,recovery_stop=None):
        if self.carried and self.carried[0]==s['id']:
            _,result=self.carried
            self.carried=None
            return result
        once=s['kind'] not in ('image','wait') or s['image_mode']=='once'
        budget=1
        checks=0
        elapsed=0.
        hits=0
        old=None
        previous=None
        recovery=None
        recovered=[]
        next_recovery=time.monotonic()+(.16 if s['roi'] is None else .32)
        while True:
            started=time.monotonic()
            paused=self.paused_time
            self.check()
            self.boundary()
            quick=False
            try:
                point=self.confirm_target(s,previous) if self.native_capture and hits and previous else None
                if point is None:
                    quick=recovery_stop is not None or (s.get('moving') and checks%4!=3)
                    candidate=recovered.pop() if recovered else None
                    if isinstance(candidate,Exception):
                        raise candidate
                    point=self.confirm_target(s,candidate) if candidate else None
                    if point is not None:
                        x,y,w,h=candidate['box']
                        px,py=candidate['point']
                        r=dict(candidate,point=point,box=(x+point[0]-px,y+point[1]-py,w,h))
                    else:
                        r=self.probe(s,budget=budget,quick=quick)
                    if quick and recovery_stop and not r['found'] and checks>=2 and started>=next_recovery and (
                            recovery is None or not recovery.is_alive()):
                        recovery=threading.Thread(target=self.start_image_recovery,
                                                  args=(s,recovery_stop,recovered),daemon=True)
                        recovery.start()
                        next_recovery=started+.18
                else:
                    x,y,w,h=previous['box']
                    px,py=previous['point']
                    r=dict(previous,point=point,box=(x+point[0]-px,y+point[1]-py,w,h),
                           captured=time.monotonic())
            except CaptureError as error:
                if once or not s.get('wait_forever'):
                    raise
                self.last_frame=None
                r=dict(found=False,status='capture_error',point=None,reason=str(error),score=0.)
            checks+=1
            status=r.get('status')
            if once and status in ('ambiguous','insufficient','incomplete','capture_error'):
                raise RuntimeError(r['reason'])
            point=r['point']
            spread=180 if s.get('moving') else 8
            near=old is not None and point is not None and max(abs(a-b) for a,b in zip(point,old))<spread
            hits=(hits+1 if near else 1) if r['found'] else 0
            old=point
            previous=r if r['found'] else None
            if once or hits>=s['stable']:
                if r['found']:
                    with self.route_lock:
                        self.seen_images.add(s['id'])
                return r
            budget=min(8,budget*2) if status=='incomplete' and not quick and checks>2 else 1
            self.emit('waiting',(s['id'],round(elapsed),status,r['reason']))
            self.sleep(max(0,(.015 if recovery_stop is not None else .045)-(time.monotonic()-started)))
            elapsed+=time.monotonic()-started-(self.paused_time-paused)
            if not s.get('wait_forever') and elapsed>=s['timeout']:
                if s['kind']=='wait' or status in ('ambiguous','insufficient','incomplete'):
                    raise TimeoutError(r['reason'])
                return dict(r,found=False)

    def click_detected_image(self, source, result, action, retry=False):
        settings = dict(source, offset=action['offset'])
        options = {'lead': True} if source.get('moving') else {}
        point = self.confirm_target(settings, result, **options)
        while point is None and retry and source.get('wait_forever') and source['image_mode']=='wait':
            self.emit('waiting',(action['id'],0,'moved','클릭 전 대상 위치를 다시 찾습니다.'))
            self.sleep(.05)
            result = self.wait_image(source)
            self.results[source['id']] = (source,result)
            point = self.confirm_target(settings, result, **options)
        if point is None:
            raise RuntimeError('클릭 직전 대상이 이동하거나 사라짐')
        self.emit('log',f'{source["name"]} · 발견 {result["box"]} → 클릭 {point}')
        self.send('configured_click',*point,action['button'],action['clicks'],action['interval'])
        self.emit('log',f'{source["name"]} · 클릭 입력 전달')

    def presence(self, image, previous=None):
        if previous and previous.get('box'):
            point=self.confirm_target(image,previous)
            if point is not None:
                x,y,w,h=previous['box']
                px,py=previous['point']
                return dict(previous,point=point,box=(x+point[0]-px,y+point[1]-py,w,h))
        return self.probe(image)

    def verify_disappearance(self, image, result, following=None):
        misses=0
        uncertain=0
        next_hits=0
        next_candidate=None
        while misses<2:
            self.sleep(.025)
            if following:
                detected=self.wait_image_candidate(following)
                if detected:
                    spread=180 if following.get('moving') else 8
                    near=next_candidate and max(abs(a-b) for a,b in zip(detected['point'],next_candidate['point']))<spread
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
                current=self.presence(image,result)
            except CaptureError:
                current=dict(found=False,status='capture_error',reason='화면을 읽을 수 없습니다')
            if current['found']:
                return current
            if current['status']=='not_found':
                misses+=1
                uncertain=0
            else:
                misses=0
                uncertain+=1
                self.emit('waiting',(image['id'],0,current['status'],current['reason']))
                if uncertain>=20:
                    raise RuntimeError(current['reason'])
            if misses==1:
                self.emit('waiting',(image['id'],0,'disappearing','다음 화면에서 다시 확인합니다'))
        self.emit('log',f'{image["name"]} · 사라짐 확인')
        return None

    def next_image(self, image):
        if not image.get('advance_on_next') or self.position is None:
            return None
        if self.top_steps[self.position]['id'] != image['id']:
            return None
        index=self.position+1
        if index>=len(self.top_steps):
            return None
        step=self.top_steps[index]
        return step if step['enabled'] and step['kind']=='image' else None

    def execute_image_actions(self, image, result):
        uid=image['id']
        repeat=image.get('repeat_while_visible',False)
        iteration=1
        while True:
            self.results[uid]=(image,result)
            if repeat:
                self.emit('image_iteration',(uid,iteration))
            if image['image_action']=='click':
                self.click_detected_image(image,result,image,retry=not repeat)
            self.execute(image['children'])
            following=self.next_image(image)
            if not repeat:
                return
            result=self.verify_disappearance(image,result,following)
            if result is None:
                return
            iteration+=1

    def wait_image_candidate(self,image):
        try:
            result=self.probe(image)
        except CaptureError:
            return None
        return result if result['found'] else None

    def execute(self,items):
        for s in items:
            self.check(); self.boundary()
            if not s['enabled']: continue
            self.emit('active',s['id']); k=s['kind']
            try:
                self.sleep(s.get('before',0))
                self.in_action=k in ('record','point','drag','key','hold','text','scroll','click')
                if k in ('image','wait','find','condition'):
                    r=self.wait_image(s)
                    self.results[s['id']]=(s,r)
                    if r['found']:
                        self.emit('log',f'{s["name"]} · 인식 확정 · {r.get("scale",1):.0%} · 위치 {r.get("point")}')
                    if k=='image':
                        if r['found']:
                            self.execute_image_actions(s,r)
                        elif s['otherwise']:self.execute(s['otherwise'])
                        else:raise TimeoutError(r.get('reason','이미지 없음')+f' · 최고 유사도 {r["score"]:.3f} / 기준 {s["threshold"]:.3f} · '+('모든 모니터' if s['roi'] is None else '지정 영역'))
                    elif k=='condition': self.execute(s['children'] if r['found'] else s['otherwise'])
                    elif not r['found']: raise RuntimeError('이미지 없음 또는 후보가 여러 개입니다.')
                elif k=='click':
                    source=self.results.get(s['source'])
                    if not source or not source[1]['found']:
                        raise RuntimeError('클릭할 인식 결과가 없습니다.')
                    if s.get('configured_target'):
                        retry=s.get('image_retry',False) and not source[0].get('repeat_while_visible')
                        self.click_detected_image(*source,s,retry=retry)
                    else:
                        point=self.confirm_target(*source)
                        if point is None: raise RuntimeError('클릭 직전 재확인 실패')
                        self.send('click',*point)
                elif k=='point': self.send('configured_click',s['x'],s['y'],s['button'],s['clicks'],s['interval'])
                elif k=='drag': self.send('drag',s['x'],s['y'],s['x2'],s['y2'],max(.1,s['seconds']))
                elif k=='key': self.send('key',s['key'])
                elif k=='hold':self.send('hold',s['key'],s['seconds'])
                elif k=='text':self.send('text',s['text'])
                elif k=='scroll':self.send('scroll',s['scroll'])
                elif k=='delay': self.sleep(s['seconds'])
                elif k=='record':
                    self.replay_events(s['events'])
                elif k=='loop': self.loop(s)
                elif k in ('break','continue'): raise Flow(k)
                elif k=='stop': raise Halt()
                self.in_action=False
                self.emit('step_done',s['id'])
                self.emit('log',s['name']+' · 완료'); self.boundary()
            except (Halt,Flow,Jump):
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
                        w['latched']=self.probe(s,s['watch'])['found']
                    if w['latched']: raise Flow(s['watch_action'],s['id'])
                except Flow as f:
                    if f.action=='stop': raise Halt()
                    if f.owner and f.owner!=s['id']: raise
                    if f.action=='break': break
                    with self.route_lock:
                        w['latched']=False; w['hits']=0
        finally:
            with self.route_lock:
                self.watches.remove(w)
    def run(self):
        try:
            if self.native_capture and not self.output and any(
                    s.get('moving') and s['enabled'] for s in walk(self.p['steps'])):
                from desktop import Input
                self.input=Input()
            self.execute_workflow()
            self.emit('state','완료')
        except Halt: self.emit('state','정지됨')
        except Exception as e: self.emit('log',str(e)); self.emit('state','오류')
        finally:
            self.watch_stop.set()
            if self.watch_thread:
                self.watch_thread.join(.20)
            try:
                if not self.output and hasattr(self,'input'):
                    self.input.release()
            finally:
                self.emit('done',None)
