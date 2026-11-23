"""Regression checks for the non-blocking watch and local recheck path."""
import threading
import unittest
from unittest.mock import Mock, patch
from itertools import count

from PIL import Image
import core


MATCH=dict(found=True,status='found',reason='발견',point=(10,10),box=(4,4,12,12),score=1.)
MISS=dict(found=False,status='not_found',reason='미검출',point=None,box=None,score=0.)


class TimingTests(unittest.TestCase):
    def runner(self,steps,routes=(),output=None):
        project=core.project()
        project['images']['button']=dict(name='button',data=core.encode_image(Image.new('RGB',(12,12),'blue')))
        project['steps']=steps
        project['routes']=list(routes)
        r=core.Runner(project,lambda *_:None,capture=lambda _:Image.new('RGB',(32,32),'blue'),
                      output=output or (lambda *_:None))
        r.native_capture=True
        return r

    def test_pending_image_search_does_not_block_foreground_click(self):
        foreground=dict(core.step('image'),image='button',image_action='click')
        watch=dict(core.step('image'),image='button',image_action='actions')
        scanning=threading.Event()
        release=threading.Event()
        clicked=threading.Event()
        r=self.runner([foreground,core.step('stop'),watch],[dict(target=watch['id'],scope=None)],
                      lambda *_:clicked.set())
        def probe(step,**options):
            if not options.get('diagnostic',True):
                scanning.set()
                release.wait(3)
                return MISS.copy()
            scanning.wait(1)
            return MATCH.copy()
        r.probe=probe
        r.confirm_target=lambda *_:MATCH['point']
        thread=threading.Thread(target=r.run)
        thread.start()
        try:
            self.assertTrue(scanning.wait(1))
            self.assertTrue(clicked.wait(.4))
        finally:
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_stability_reconfirms_same_location_without_full_rescan(self):
        step=dict(core.step('image'),image='button',image_action='click',stable=3)
        r=self.runner([step])
        jobs=[]
        def probe(*_,**_options):
            jobs.append('full')
            return MATCH.copy()
        def confirm(*_):
            jobs.append('local')
            return MATCH['point']
        r.probe=probe
        r.confirm_target=confirm
        r.run()
        self.assertEqual(jobs,['full','local','local','local'])

    def test_next_wait_does_not_start_another_precise_worker_while_old_one_exits(self):
        first = dict(core.step('image'), image='button')
        second = dict(core.step('image'), image='button')
        runner = self.runner([first, second])
        runner.probe = Mock(side_effect=([MISS]*3+[MATCH])*2)
        runner.sleep = Mock()
        ticks = count(step=.2)
        with patch('core.time.monotonic', side_effect=lambda: next(ticks)), \
             patch('core.threading.Thread') as thread:
            thread.return_value.is_alive.return_value = True
            self.assertTrue(runner.wait_image(first)['found'])
            self.assertTrue(runner.wait_image(second)['found'])
        thread.assert_called_once()
        self.assertTrue(thread.call_args.kwargs['args'][1].is_set())

    def test_precise_worker_start_failure_falls_back_to_full_search(self):
        step = dict(core.step('image'), image='button')
        runner = self.runner([step])
        runner.probe = Mock(side_effect=[MISS]*3+[MATCH])
        runner.sleep = Mock()
        ticks = count(step=.2)
        with patch('core.time.monotonic', side_effect=lambda: next(ticks)), \
             patch('core.threading.Thread') as thread:
            thread.return_value.start.side_effect = RuntimeError('thread unavailable')
            self.assertTrue(runner.wait_image(step)['found'])
        self.assertEqual([call.kwargs['quick'] for call in runner.probe.call_args_list],
                         [True, True, True, False])
