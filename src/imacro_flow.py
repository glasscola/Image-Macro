"""Sequence execution, repeat ranges and image-triggered jumps."""
import time
import threading


class Jump(Exception):
    def __init__(self, target, result):
        self.target, self.result = target, result


def validate_flow(project):
    order = {s['id']: i for i,s in enumerate(project['steps'])}
    occupied=set()
    for r in project.get('ranges',[]):
        a,b=(order.get(r[k],-1) for k in ('start','end'))
        if a<0 or b<a or type(r['count']) is not int or not 0<=r['count']<=100000:
            raise ValueError('반복 구간의 시작·끝과 횟수를 확인하세요.')
        indexes=set(range(a,b+1))
        if occupied & indexes:
            raise ValueError('반복 구간은 서로 겹칠 수 없습니다.')
        occupied.update(indexes)
    scopes={r['id'] for r in project.get('ranges',[])} | {None}
    for rule in project.get('routes',[]):
        target=order.get(rule['target'])
        if target is None or project['steps'][target]['kind']!='image' or rule.get('scope') not in scopes:
            raise ValueError('이미지 이동 조건의 대상과 범위를 확인하세요.')


class Workflow:
    def init_flow(self):
        self.position=None
        self.repeat=None
        self.repeat_count=0
        self.pending_jump=None
        self.carried=None
        self.last_route_check=float('-inf')
        self.seen_images=set()
        self.route_hits={}
        self.gesture_held=set()
        self.in_action=False
        self.watch_stop=threading.Event()
        self.watch_thread=None
        self.route_lock=threading.Lock()
        self.top_steps=self.p['steps']
        self.index={s['id']:i for i,s in enumerate(self.top_steps)}
        self.repeat_for={}
        if self.p.get('repeat_enabled',False):
            for r in self.p.get('ranges',[]):
                a,b=(self.index[r[k]] for k in ('start','end'))
                self.repeat_for.update((i,r) for i in range(a,b+1))

    def start_watch_thread(self):
        if not self.native_capture or not (self.p.get('routes') or self.has_legacy_live_watch):
            return
        self.watch_thread=threading.Thread(target=self.watch_routes,daemon=True,
                                           name='ImageMacro image watch')
        self.watch_thread.start()

    def watch_routes(self):
        sweep=0
        while not self.watch_stop.is_set() and not self.cancel.is_set():
            if not self.paused.is_set():
                started=time.monotonic()
                try:
                    self.observe_routes(background=True,quick=sweep%3!=2)
                    self.observe_legacy(background=True,quick=sweep%3!=2)
                except InterruptedError:
                    pass
                except Exception as error:
                    if not self.watch_stop.is_set() and not self.cancel.is_set():
                        self.emit('log',f'이미지 감시 재시도 · {error}')
                sweep+=1
                self.watch_stop.wait(max(.012,.08-(time.monotonic()-started)))
            else:
                self.watch_stop.wait(.05)

    def observe_legacy(self, *, background, quick):
        with self.route_lock:
            watches=[w for w in self.watches if w['s']['watch'] and
                     w['s']['watch_timing']=='during' and not w['latched']]
        if not watches:
            return
        frame=self.capture(None)
        for watch in watches:
            step=watch['s']
            result=self.probe(step,step['watch'],shared_frame=frame,diagnostic=False,
                              quick=quick,checkpoint=self.watch_checkpoint if background else None)
            with self.route_lock:
                if not any(w is watch for w in self.watches):
                    continue
                watch['hits']=watch['hits']+1 if result['found'] else 0
                if watch['hits']>=step['stable']:
                    watch['latched']=True

    def watch_checkpoint(self):
        if self.watch_stop.is_set() or self.cancel.is_set() or self.paused.is_set():
            raise InterruptedError('감시 중단')

    def observe_routes(self,*,background=False,quick=False):
        if not self.p.get('routes') or self.pending_jump or self.position is None:
            return
        now=time.monotonic()
        if now-self.last_route_check<.08:
            return
        scope=self.repeat['id'] if self.repeat else None
        rules=[r for r in self.p['routes'] if r.get('scope') is None or r['scope']==scope]
        if not rules:
            return
        self.last_route_check=now
        frame=None
        detections={}
        eligible=[]
        for rule in rules:
            uid=rule['target']
            target=self.top_steps[self.index[uid]]
            if not target['enabled'] or target['image'] not in self.templates:
                continue
            try:
                if uid not in detections:
                    if frame is None:
                        frame=self.capture(None)
                        if not background:
                            self.route_frame=(time.monotonic(),frame)
                    detections[uid]=self.probe(target,shared_frame=frame,diagnostic=False,
                                               quick=quick,
                                               checkpoint=self.watch_checkpoint if background else None)
                result=detections[uid]
            except self.capture_error:
                return
            with self.route_lock:
                if result['status']=='not_found':
                    self.seen_images.discard(uid)
                if not result['found']:
                    self.route_hits.pop((uid,rule.get('scope')),None)
                    continue
                if uid in self.seen_images:
                    continue
                key=(uid,rule.get('scope'))
                count,point,last=self.route_hits.get(key,(0,None,-1))
                if last!=now:
                    near=point is not None and max(abs(a-b) for a,b in zip(point,result['point']))<=8
                    count=count+1 if near else 1
                    self.route_hits[key]=(count,result['point'],now)
                if count<target['stable']:
                    continue
                if self.position==self.index[uid]:
                    self.seen_images.add(uid)
                    continue
                eligible.append((uid,result,rule.get('when','safe'),rule.get('scope')))
        with self.route_lock:
            active=self.repeat['id'] if self.repeat else None
            eligible=[item for item in eligible if item[0] not in self.seen_images
                      and item[3] in (None,active)]
            if eligible and self.pending_jump is None:
                self.pending_jump=eligible[0]
                self.seen_images.update(uid for uid,_,_,_ in eligible[1:])

    def commit_route(self):
        with self.route_lock:
            if not self.pending_jump or self.gesture_held:
                return
            uid,result,when,scope=self.pending_jump
            if when=='after' and self.in_action:
                return
            self.pending_jump=None
            active=self.repeat['id'] if self.repeat else None
            if scope not in (None,active) or self.index[uid]==self.position:
                return
        try:
            point=self.confirm_target(self.top_steps[self.index[uid]],result)
        except self.capture_error:
            return
        if point is not None:
            with self.route_lock:
                self.seen_images.add(uid)
                self.route_hits={key:value for key,value in self.route_hits.items() if key[0]!=uid}
            raise Jump(uid,dict(result,point=point))

    def execute_workflow(self):
        if not any(step['enabled'] for step in self.top_steps):
            return
        self.start_watch_thread()
        limit=self.p.get('workflow_repeats',1)
        cycle=0
        while not limit or cycle<limit:
            cycle+=1
            self.position=0
            self.repeat,self.repeat_count=None,0
            self.carried=None
            self.results.clear()
            self.emit('workflow_iteration',(cycle,limit))
            self.execute_workflow_pass()
            if (not limit or cycle<limit) and len(self.top_steps)==1:
                first=self.top_steps[0]
                found=self.results.get(first['id'])
                if first['kind']=='image' and first['enabled'] and found and found[1]['found'] and not first.get('repeat_while_visible'):
                    result=found[1]
                    while result is not None:
                        result=self.verify_disappearance(first,result)
            if not limit or cycle<limit:
                self.sleep(.025)

    def execute_workflow_pass(self):
        while self.position<len(self.top_steps):
            step=self.top_steps[self.position]
            repeat=self.repeat_for.get(self.position)
            if repeat is not self.repeat:
                if self.repeat is not None:
                    self.emit('range_left',self.repeat['start'])
                self.repeat,self.repeat_count=repeat,0
            if repeat and (not self.repeat_count or self.position==self.index[repeat['start']]):
                self.repeat_count+=1
                self.emit('range_iteration',(repeat['start'],self.repeat_count,repeat['count']))
            try:
                self.execute([step])
                self.check()
                self.boundary()
            except Jump as jump:
                self.position=self.index[jump.target]
                if self.repeat is not None:
                    self.emit('range_left',self.repeat['start'])
                self.repeat,self.repeat_count=None,0
                self.carried=(jump.target,jump.result)
                self.emit('transition',(step['id'],jump.target))
                continue
            if repeat and step['id']==repeat['end'] and (
                    not repeat['count'] or self.repeat_count<repeat['count']):
                self.position=self.index[repeat['start']]
            else:
                self.position+=1
