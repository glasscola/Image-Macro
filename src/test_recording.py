from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from recording import Recorder, key_name


class RecordingKeyboardTests(unittest.TestCase):
    def test_unsupported_keys_and_multi_character_translations(self):
        self.assertIsNone(key_name(None))
        self.assertIsNone(key_name(SimpleNamespace(char=None, vk=None)))
        self.assertEqual(key_name(SimpleNamespace(char='ab', vk=65)), 'vk:65')
        self.assertEqual(key_name(SimpleNamespace(char='\x13', vk=83)), 's')

    def test_unknown_key_between_press_and_release_does_not_interrupt_recording(self):
        emit = Mock()
        target = {'pid': 202, 'title': 'Keyboard test'}
        known = SimpleNamespace(char='a', vk=65)
        with (
            patch('recording.keyboard.Listener'),
            patch('recording.mouse.Listener'),
            patch('recording.user.GetForegroundWindow'),
            patch('recording.window_info', return_value=target),
            patch('recording.korean_mode', return_value=None),
            patch('recording.os.getpid', return_value=101),
        ):
            recorder = Recorder(emit)
            recorder.key(known, True)
            recorder.key(None, True)
            recorder.key(None, False)
            recorder.key(known, False)
        label, events, _, title = emit.call_args.args
        self.assertEqual((label, title), ('A', 'Keyboard test'))
        self.assertEqual([(event['key'], event['down']) for event in events],
                         [('a', True), ('a', False)])
        self.assertEqual(events[0]['target'], target)

    def test_korean_mode_and_physical_letter_are_saved(self):
        target = {'pid': 202, 'title': 'Keyboard test'}
        key = SimpleNamespace(char='g', vk=71)
        with (
            patch('recording.keyboard.Listener'),
            patch('recording.mouse.Listener'),
            patch('recording.user.GetForegroundWindow'),
            patch('recording.window_info', return_value=target),
            patch('recording.korean_mode', return_value=True),
            patch('recording.os.getpid', return_value=101),
        ):
            emit = Mock()
            recorder = Recorder(emit)
            recorder.key(key, True)
            recorder.key(key, False)
        label, events, _, _ = emit.call_args.args
        self.assertEqual(label,'한글 · G')
        self.assertIs(events[0]['korean_mode'],True)
        self.assertEqual([event['vk'] for event in events],[71,71])
        self.assertNotIn('korean_mode',events[1])

    def test_desktop_and_missing_foreground_record_keys_without_window_binding(self):
        desktop = {'pid': 202, 'title': 'Program Manager', 'kind': 'Progman'}
        key = SimpleNamespace(char='a', vk=65)
        for foreground in (desktop, None):
            with (
                self.subTest(foreground=foreground),
                patch('recording.keyboard.Listener'),
                patch('recording.mouse.Listener'),
                patch('recording.user.GetForegroundWindow'),
                patch('recording.window_info', return_value=foreground),
                patch('recording.korean_mode', return_value=True),
            ):
                emit = Mock()
                recorder = Recorder(emit)
                recorder.key(key, True)
                recorder.key(key, False)
                events = emit.call_args.args[1]
                self.assertEqual([(event['key'], event['down']) for event in events],
                                 [('a', True), ('a', False)])
                self.assertNotIn('target', events[0])
                if foreground is None:
                    self.assertNotIn('korean_mode', events[0])
                else:
                    self.assertIs(events[0]['korean_mode'], True)

    def test_desktop_records_chords_mixed_actions_and_mouse_paths(self):
        with (
            patch('recording.keyboard.Listener'),
            patch('recording.mouse.Listener'),
            patch('recording.user.GetForegroundWindow'),
            patch('recording.window_info', return_value=None),
            patch('recording.pointer_window', return_value=None),
            patch('recording.capture', return_value=None),
        ):
            emit = Mock()
            recorder = Recorder(emit)
            ctrl = SimpleNamespace(name='ctrl_l')
            key = SimpleNamespace(char='\x03', vk=67)
            side = SimpleNamespace(name='x1')
            left = SimpleNamespace(name='left')

            recorder.move(120, 150)
            recorder.move(123, 155)
            recorder.key(ctrl, True)
            recorder.key(key, True)
            recorder.key(key, False)
            recorder.key(ctrl, False)
            recorder.key(ctrl, True)
            recorder.click(150, 150, side, True)
            recorder.click(150, 150, side, False)
            recorder.key(ctrl, False)
            recorder.scroll(150, 150, 0, -2)
            recorder.click(150, 150, left, True)
            recorder.move(172, 190)
            recorder.click(172, 190, left, False)
            recorder.stop()

        groups = [call.args[1] for call in emit.call_args_list]
        path, chord, mixed, scroll, drag = groups
        self.assertEqual([(event['x'], event['y']) for event in path], [(120, 150), (123, 155)])
        self.assertEqual([(event['key'], event['down']) for event in chord],
                         [('ctrl_l', True), ('c', True), ('c', False), ('ctrl_l', False)])
        self.assertEqual([(event['type'], event['down']) for event in mixed],
                         [('key', True), ('mouse', True), ('mouse', False), ('key', False)])
        self.assertEqual(mixed[1]['button'], 'x1')
        self.assertEqual(scroll[0]['dy'], -2)
        self.assertEqual([event['type'] for event in drag], ['mouse', 'move', 'mouse'])
