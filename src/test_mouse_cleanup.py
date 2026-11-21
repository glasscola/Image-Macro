from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import core
from desktop import Input


class MouseCleanupTests(unittest.TestCase):
    def setUp(self):
        self.input = Input.__new__(Input)
        self.input.mouse = Mock()
        self.input.keys = Mock()
        self.input.buttons = SimpleNamespace(left='left', right='right', middle='middle', x1='x1', x2='x2')
        self.input.held = set()
        self.input.held_buttons = set()
        self.input.move_to = Mock()
        self.flags = []
        self.mouse_data = []
        self.api = Mock()

        def send(count, events, _size):
            if hasattr(events, '_obj'):
                events = [events._obj]
            self.flags.extend(events[index].mouse.flags for index in range(count))
            self.mouse_data.extend(events[index].mouse.data for index in range(count))
            return count

        self.api.SendInput.side_effect = send
        win_api = patch('desktop.ctypes.WinDLL', return_value=self.api, create=True)
        win_api.start()
        self.addCleanup(win_api.stop)

    def test_completed_click_has_no_extra_releases(self):
        self.input.click_at(20, 30, 'left')
        self.input.release()
        self.assertEqual(self.flags, [2, 4])
        self.input.mouse.release.assert_not_called()

    def test_configured_right_click_is_preserved(self):
        self.input.click_at(20, 30, 'right')
        self.input.release()
        self.assertEqual(self.flags, [8, 16])

    def test_side_buttons_use_distinct_windows_codes(self):
        for button in ('x1', 'x2'):
            self.input.mouse_button(button, True)
            self.input.mouse_button(button, False)
        self.input.release()
        self.assertEqual(self.flags, [128, 256, 128, 256])
        self.assertEqual(self.mouse_data, [1, 1, 2, 2])

    def test_interrupted_recording_releases_only_its_held_button(self):
        runner = core.Runner(core.project(), Mock())
        runner.input = self.input
        runner.sleep = Mock(side_effect=[None, core.Halt()])
        events = [
            dict(type='mouse', button='left', down=True, delay=0),
            dict(type='mouse', button='left', down=False, delay=.1),
        ]
        with self.assertRaises(core.Halt):
            runner.replay_events(events)
        self.input.release()
        self.assertEqual(self.flags, [2, 4])

    def test_interrupted_drag_releases_only_left_button(self):
        runner = core.Runner(core.project(), Mock())
        runner.input = self.input
        runner.sleep = Mock(side_effect=core.Halt())
        with self.assertRaises(core.Halt):
            runner.send('drag', 20, 30, 40, 50, .1)
        self.input.release()
        self.assertEqual(self.flags, [2, 4])

    def test_partial_click_remains_tracked_when_immediate_release_fails(self):
        self.api.SendInput.side_effect = [1, 0, 1]
        with self.assertRaises(RuntimeError):
            self.input.click_at(20, 30, 'left')
        self.assertEqual(self.input.held_buttons, {'left'})
        self.input.release()
        self.assertFalse(self.input.held_buttons)
        self.assertEqual(self.api.SendInput.call_count, 3)
