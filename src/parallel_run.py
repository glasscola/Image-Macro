"""Run independent workflows over one desktop capture session and input gate."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Condition, Event
from time import monotonic

import core
from desktop import bounds
from macro_tabs import tab_name, tab_project
from runtime_capture import RuntimeCapture


class InputGate:
    def __init__(self):
        self.condition = Condition()
        self.waiters = deque()

    @contextmanager
    def turn(self, cancel):
        ticket = object()
        with self.condition:
            self.waiters.append(ticket)
        try:
            with self.condition:
                while self.waiters[0] is not ticket and not cancel.is_set():
                    self.condition.wait(.025)
                if cancel.is_set():
                    raise core.Halt()
            yield
        finally:
            with self.condition:
                self.waiters.remove(ticket)
                self.condition.notify_all()


class SharedCapture:
    def __init__(self, common_roi=None):
        self.capture = RuntimeCapture()
        self.common_roi = common_roi
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='Image Macro capture')
        self.rect = self.frame = None
        self.crops = {}
        self.sampled = float('-inf')

    def read(self, roi, fallback):
        return self.worker.submit(self._read, roi, fallback).result()

    def _read(self, roi, fallback):
        # For projects that all watch one region, keep the native ROI fast path.
        scope = self.common_roi if roi is not None and tuple(roi) == self.common_roi else None
        layout = bounds()
        rect = scope or layout
        if rect != self.rect or monotonic() - self.sampled >= .012:
            frame = self.capture.read(scope, fallback)
            if frame.size != tuple(rect[2:]) or bounds() != layout:
                raise core.CaptureError('화면 배치 변경 중 · 캡처를 다시 확인합니다')
            if self.frame is not frame or self.rect != rect:
                self.crops.clear()
            self.rect, self.frame, self.sampled = rect, frame, monotonic()
        if roi is None or scope is not None:
            return self.frame
        key = tuple(roi)
        if key not in self.crops:
            x, y, width, height = key
            left, top = x - rect[0], y - rect[1]
            if len(self.crops) >= 8:
                self.crops.clear()
            crop = self.frame.crop((left, top, left + width, top + height))
            self.crops[key] = crop
        return self.crops[key]

    def confirm(self, roi, fallback):
        return self.worker.submit(self.capture.confirm, roi, fallback).result()

    def close(self):
        try:
            self.worker.submit(self.capture.close).result()
        finally:
            self.worker.shutdown()
            self.frame = None
            self.crops.clear()


class ParallelRun:
    def __init__(self, project, indices, emit, *, editor_at,
                 capture=None, output=None):
        core.validate(project)
        self.emit = emit
        self.cancel = Event()
        self.paused = Event()
        self.states = {}
        self.runners = {}
        views = {index: tab_project(project, index) for index in indices}
        scopes = {tuple(step['roi']) if step['roi'] else None
                  for view in views.values() for step in core.walk(view['steps'])
                  if step['image'] or step['watch']}
        common_roi = next(iter(scopes)) if len(scopes) == 1 else None
        self.capture = SharedCapture(common_roi) if capture is None else None
        gate = InputGate()
        try:
            for index, view in views.items():
                keys = {key for step in core.walk(view['steps'])
                        for key in (step['image'], step['watch'], *step.get('variants', []))}
                view['images'] = {key: value for key, value in project['images'].items() if key in keys}
                runner = core.Runner(view, lambda kind,value,i=index: self.event(i,kind,value),
                                     capture, output, editor_at=editor_at,
                                     shared_capture=self.capture, input_gate=gate, validated=True)
                runner.cancel = self.cancel
                runner.paused = self.paused
                self.runners[index] = runner
        except Exception:
            if self.capture is not None:
                self.capture.close()
            raise

    def event(self, index, kind, value):
        if kind == 'state':
            self.states[index] = value
        if kind != 'done':
            self.emit('tab_event', (index, kind, value))

    def run(self):
        failed = False
        try:
            with ThreadPoolExecutor(max_workers=len(self.runners), thread_name_prefix='Image Macro tab') as workers:
                futures = []
                try:
                    for runner in self.runners.values():
                        futures.append(workers.submit(runner.run))
                    for future in futures:
                        future.result()
                except Exception:
                    self.cancel.set()
                    raise
        except Exception as error:
            self.emit('log', f'탭 실행 오류 · {error}')
            failed = True
        finally:
            self.close()
            state = ('오류' if failed or '오류' in self.states.values() else
                     '정지됨' if self.cancel.is_set() or '정지됨' in self.states.values() else '완료')
            self.emit('state', state)
            self.emit('done', None)

    def close(self):
        if self.capture is not None:
            try:
                self.capture.close()
            except Exception as error:
                self.emit('log', f'공유 캡처 정리 오류 · {error}')
            finally:
                self.capture = None
