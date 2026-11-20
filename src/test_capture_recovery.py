import unittest
from unittest.mock import Mock, patch

from PIL import Image

import core
import desktop
from automation_errors import TargetUnavailable
from selection_capture import capture_visible_desktop


class CaptureRecoveryTests(unittest.TestCase):
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
