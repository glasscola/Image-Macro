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
        runner.probe=Mock(side_effect=[dict(found=True,point=(20,20)),dict(found=False,status='not_found')])
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
