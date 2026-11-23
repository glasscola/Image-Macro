import ctypes
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import core
import desktop
from automation_errors import TargetUnavailable
from selection_capture import capture_visible_desktop


class CaptureRecoveryTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(ctypes, 'WinDLL'), 'requires Windows display enumeration')
    def test_overlapping_native_display_queries_keep_every_display(self):
        expected = desktop.monitors()
        barrier = threading.Barrier(3)

        def check_layout():
            barrier.wait(timeout=5)
            for _ in range(100):
                self.assertEqual(desktop.monitors(), expected)

        with ThreadPoolExecutor(3) as pool:
            futures = [pool.submit(check_layout) for _ in range(3)]
            for future in futures:
                future.result(timeout=10)

    def test_display_outage_during_continuous_repeat_resumes_same_card(self):
        frame = Image.new('RGB', (50, 36), 'white')
        target = Image.new('RGB', (12, 10), 'navy')
        frame.paste(target, (15, 5))
        p = core.project()
        p['workflow_repeats'] = 0
        p['images']['t'] = dict(name='t', data=core.encode_image(target))
        p['steps'] = [dict(core.step('image'), image='t', wait_forever=True,
                           image_action='actions', children=[dict(core.step('text'), text='hit')])]
        emitted = Mock()
        scans = []
        deliveries = []

        def send(kind, value):
            deliveries.append((len(scans), kind, value))
            if len(deliveries) == 2:
                runner.cancel.set()

        runner = core.Runner(p, emitted, output=send)
        runner.capture_source = lambda _: frame
        # First cycle succeeds. The second sees failed enumeration, an empty
        # enumeration, then a partial layout before both displays return.
        def enumerate_displays(dc, clip, visit, param):
            scans.append(len(scans) + 1)
            self.assertLessEqual(len(scans), 5)
            if len(scans) == 2:
                return False
            if len(scans) != 3:
                for handle in (1, 2):
                    if not visit(handle, None, None, 0):
                        break
            return True

        def get_info(handle, address):
            if len(scans) == 4 and handle == 2:
                return False
            info = ctypes.cast(address, ctypes.POINTER(desktop._MonitorInfo)).contents
            info.device = str(handle)
            info.rect.left, info.rect.right = (0, 30) if handle == 1 else (30, 50)
            info.rect.top, info.rect.bottom = 0, 36
            return True

        api = (lambda fn: fn, enumerate_displays, get_info, lambda *_: 1)
        with patch('desktop._monitor_api', return_value=api), \
             patch('desktop.bounds', return_value=(0, 0, 50, 36)), \
             patch.object(runner, 'sleep'):
            runner.run()
        self.assertEqual(deliveries, [(1, 'text', 'hit'), (5, 'text', 'hit')])
        events = [call.args for call in emitted.call_args_list]
        self.assertTrue(any(k == 'waiting' and v[2] == 'capture_error' for k, v in events))
        self.assertEqual([v for k, v in events if k == 'state'], ['정지됨'])

    def test_layout_change_during_capture_rejects_frame_before_matching(self):
        frame = Image.new('RGB', (50, 36), 'white')
        project = core.project()
        step = dict(core.step('image'), image='target')
        project['images']['target'] = dict(name='target', data=core.encode_image(frame))
        project['steps'] = [step]
        runner = core.Runner(project, Mock(), output=Mock())
        runner.capture_source = lambda _: frame
        with patch('desktop.bounds', side_effect=[(0, 0, 50, 36), (-50, 0, 50, 36)]), \
             patch('core.search_regions') as match:
            with self.assertRaises(core.CaptureError):
                runner.probe(step)
        match.assert_not_called()

    def test_continuous_read_uses_plain_copy_and_falls_back_only_for_black_frame(self):
        rect = (-6, 0, 8, 8)
        visible = Image.new('RGB', (8, 8), 'red')
        black = Image.new('RGB', (8, 8))
        with patch('desktop_capture.capture_rectangle', side_effect=[visible, black]) as read, \
             patch('desktop.capture', return_value=visible) as fallback:
            self.assertIs(desktop.capture_runtime(rect), visible)
            fallback.assert_not_called()
            self.assertIs(desktop.capture_runtime(rect), visible)
            fallback.assert_called_once_with(rect)
        self.assertEqual(read.call_count, 2)
        read.assert_called_with(*rect, include_layered=False)

    def test_monitor_fallback_rejects_black_and_preserves_negative_origin(self):
        displays = [
            dict(device='left', rect=(-6, 0, 6, 5)),
            dict(device='right', rect=(0, 1, 8, 4)),
        ]
        black = Image.new('RGB', (6, 5))
        green = Image.new('RGB', (6, 5), 'green')
        red = Image.new('RGB', (8, 4), 'red')
        with patch('selection_capture.capture_gpu', return_value=[('right', red)]), \
             patch('selection_capture.desktop.capture', side_effect=[black, green]) as fallback, \
             patch('selection_capture.time.sleep'):
            frame = capture_visible_desktop((-6, 0, 14, 5), displays)
        self.assertEqual(frame.getpixel((1, 2)), (0, 128, 0))
        self.assertEqual(frame.getpixel((7, 2)), (255, 0, 0))
        self.assertEqual(fallback.call_count, 2)

    def test_still_black_does_not_open_a_drag_selection(self):
        with patch('selection_capture.capture_gpu', return_value=[]), \
             patch('selection_capture.desktop.capture', return_value=Image.new('RGB', (8, 8))), \
             patch('selection_capture.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, '검게 읽혀'):
                capture_visible_desktop((0, 0, 8, 8), [dict(device='screen', rect=(0, 0, 8, 8))])

    def test_long_repeat_recovers_without_replaying_delivered_events(self):
        project = core.project()
        project['workflow_repeats'] = 0
        project['steps'] = [core.step('record')]
        emitted = Mock()
        output = Mock()
        frame = Image.new('RGB', (8, 8), 'red')
        runner = core.Runner(project, emitted, lambda _: frame, output)
        first = dict(type='key', key='a', down=True, delay=0)
        release = dict(type='key', key='a', down=False, delay=0)
        blocked = dict(type='key', key='b', down=True, delay=0)
        final = dict(type='key', key='b', down=False, delay=0)
        runner.top_steps[0]['events'] = [first, release, blocked, final]
        runner.sleep = Mock()
        executed = []
        failures = {400: 30, 2800: 60, 4400: 90}

        def send(_, event):
            cursor = len(executed)
            if failures.get(cursor - 2, 0) and event is blocked:
                failures[cursor - 2] -= 1
                raise TargetUnavailable('window temporarily covered')
            executed.append(event)
            if len(executed) == 8000:
                runner.cancel.set()

        runner.send = send
        runner.run()
        self.assertEqual(executed, [first, release, blocked, final] * 2000)
        self.assertEqual(set(failures.values()), {0})
        self.assertIn(('state', '정지됨'), [call.args for call in emitted.call_args_list])

    def test_once_per_cycle_resumes_after_a_black_capture_and_capture_errors(self):
        project = core.project()
        project['workflow_repeats'] = 0
        frame = Image.new('RGB', (8, 8), 'red')
        project['images']['target'] = dict(name='target', data=core.encode_image(frame))
        image = dict(core.step('image'), image='target', image_mode='once',
                     image_action='actions', children=[core.step('text')])
        project['steps'] = [image]
        emitted = Mock()
        output = Mock()
        runner = core.Runner(project, emitted, lambda _: frame, output)
        detected = dict(found=True, status='found', score=1, point=(4, 4))
        runner.probe = Mock(side_effect=[core.CaptureError('black')] * 25 + [detected])
        runner.sleep = Mock()
        output.side_effect = lambda *_: runner.cancel.set()
        runner.run()
        output.assert_called_once()
        self.assertEqual(runner.probe.call_count, 26)
        self.assertIn(('state', '정지됨'), [call.args for call in emitted.call_args_list])
