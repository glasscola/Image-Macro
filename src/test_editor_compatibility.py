import unittest
from unittest.mock import Mock

from PIL import Image

import core


class EditorCompatibilityTests(unittest.TestCase):
    def test_legacy_image_click_becomes_first_reorderable_action(self):
        project = core.project()
        project['images']['start'] = dict(name='start', data=core.encode_image(Image.new('RGB',(12,12))))
        image = dict(core.step('image'), image='start', button='right', clicks=2, offset=[.3,.7])
        text = dict(core.step('text'), text='1')
        image['children'] = [text]
        project['steps'] = [image]
        core.expand_image_clicks(project)
        core.expand_image_clicks(project)
        click, existing = image['children']
        self.assertIs(existing,text)
        self.assertEqual(click['button'],'right')
        self.assertEqual(click['offset'],[.3,.7])
        self.assertEqual(image['image_action'],'actions')
        image['children'].reverse()
        output = Mock()
        runner = core.Runner(project,lambda *_:None,capture=lambda _:Image.new('RGB',(20,20)),output=output)
        runner.wait_image = Mock(return_value=dict(found=True,box=(0,0,12,12)))
        runner.confirm_target = Mock(return_value=(3,8))
        runner.run()
        self.assertEqual([c.args for c in output.call_args_list],
                         [('text','1'),('configured_click',3,8,'right',2,.1)])
        self.assertEqual(runner.confirm_target.call_args.args[0]['offset'],[.3,.7])
