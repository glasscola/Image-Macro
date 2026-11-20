import unittest
from unittest.mock import Mock

from PIL import Image

import core


class ImageRepeatTests(unittest.TestCase):
    def setUp(self):
        image=Image.new('RGB',(12,12),'blue')
        self.project=core.project()
        self.project['images']['target']=dict(name='target',data=core.encode_image(image))
        self.first=dict(core.step('image'),image='target',image_action='actions',
                        children=[dict(core.step('text'),text='A'),dict(core.step('text'),text='B')])
        self.project['steps']=[self.first,dict(core.step('text'),text='C')]
        self.output=Mock()
        self.emit=Mock()
        self.frame=image

    def runner(self):
        runner=core.Runner(self.project,self.emit,capture=lambda _:self.frame,output=self.output)
        runner.wait_image=Mock(return_value=dict(found=True,point=(1,1)))
        runner.probe=Mock(side_effect=[dict(found=True,point=(20,20)),dict(found=False,status='not_found'),dict(found=False,status='not_found')])
        return runner

    def test_repeat_ends_on_disappearance_and_next_step_runs(self):
        self.first['repeat_while_visible']=True
        runner=self.runner()
        runner.run()
        self.assertEqual([c.args for c in self.output.call_args_list],
                         [('text','A'),('text','B'),('text','A'),('text','B'),('text','C')])
        self.assertEqual([c.args[1][1] for c in self.emit.call_args_list if c.args[0]=='image_iteration'],[1,2])
        self.assertEqual(runner.wait_image.call_count,1)

    def test_disabled_repeat_runs_once(self):
        runner=self.runner()
        runner.run()
        runner.probe.assert_not_called()
        self.assertEqual([c.args[1] for c in self.output.call_args_list],['A','B','C'])

    def test_uncertain_image_reports_error_instead_of_starting_next_step(self):
        self.first['repeat_while_visible']=True
        runner=self.runner()
        runner.probe=Mock(return_value=dict(found=False,status='ambiguous',reason='후보가 여러 곳입니다.'))
        runner.run()
        self.assertEqual([c.args[1] for c in self.output.call_args_list],['A','B'])
        self.assertIn(('state','오류'),[c.args for c in self.emit.call_args_list])

    def test_one_missed_frame_does_not_exit_repeat(self):
        self.first['repeat_while_visible']=True
        runner=self.runner()
        miss=dict(found=False,status='not_found')
        runner.probe.side_effect=[miss,dict(found=True,point=(20,20)),miss,miss]
        runner.run()
        self.assertEqual([c.args[1] for c in self.output.call_args_list],['A','B','A','B','C'])

    def test_workflow_repeats_all_steps(self):
        self.project['workflow_repeats']=3
        runner=self.runner()
        runner.run()
        self.assertEqual([c.args[1] for c in self.output.call_args_list],['A','B','C']*3)
        self.assertEqual(runner.wait_image.call_count,3)

    def test_single_image_rearms_only_after_two_misses(self):
        self.project['workflow_repeats']=2
        self.project['steps']=[self.first]
        runner=self.runner()
        miss=dict(found=False,status='not_found')
        runner.probe.side_effect=[dict(found=True,point=(1,1)),miss,miss]
        runner.run()
        self.assertEqual(runner.probe.call_count,3)
        self.assertEqual([c.args[1] for c in self.output.call_args_list],['A','B','A','B'])

    def test_next_image_takes_priority_while_first_is_still_visible(self):
        self.first.update(repeat_while_visible=True,advance_on_next=True)
        other=dict(core.step('image'),image='target',image_action='actions',
                   children=[self.project['steps'][1]])
        self.project['steps'][1]=other
        runner=self.runner()
        real_wait=runner.wait_image
        def wait(step):
            if step is other:
                self.assertEqual(runner.carried[0],other['id'])
            return real_wait(step)
        runner.wait_image=wait
        runner.run()
        self.assertEqual([c.args[1] for c in self.output.call_args_list],['A','B','C'])
