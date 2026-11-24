import threading
import unittest

from PIL import Image

import core
from parallel_run import ParallelRun


class ParallelRunTests(unittest.TestCase):
    def test_recorded_chord_keeps_input_until_key_release_and_other_tab_completes(self):
        project = core.project()
        record = core.step('record')
        record['events'] = [
            dict(type='key', key='ctrl', down=True, delay=0),
            dict(type='key', key='c', down=True, delay=.01),
            dict(type='key', key='c', down=False, delay=0),
            dict(type='key', key='ctrl', down=False, delay=0),
        ]
        other = core.step('key')
        other['key'] = 'x'
        project['steps'] = [record]
        project['tabs'] = [dict(name='Other', steps=[other])]
        pressed = threading.Event()
        attempting = threading.Event()
        actions = []

        def output(kind, *args):
            if kind == 'event':
                event = args[0]
                actions.append((event['key'], event['down']))
                if event['key'] == 'ctrl' and event['down']:
                    pressed.set()
                    if not attempting.wait(2):
                        raise AssertionError('second workflow did not reach its input')
            else:
                actions.append(args[0])

        def emit(kind, payload):
            if kind == 'tab_event' and payload == (1, 'active', other['id']):
                if not pressed.wait(2):
                    raise AssertionError('first workflow did not begin its chord')
                attempting.set()

        parallel = ParallelRun(project, [0, 1], emit, editor_at=None,
                               capture=lambda _: Image.new('RGB',(100,100)), output=output)
        parallel.run()
        self.assertEqual(actions, [('ctrl',True),('c',True),('c',False),('ctrl',False),'x'])
        self.assertEqual(parallel.states, {0:'완료',1:'완료'})
