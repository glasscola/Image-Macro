import unittest,copy
from unittest.mock import patch
from test_core import CoreTests
from core import *
from desktop import local_to_screen

class UpdateTests(CoreTests):
    def test_unified_click(self):
        s=step('image');s['image']='target';s['stable']=1;self.execute([s]);self.assertEqual(self.inputs[0][:3],('configured_click',88,67))
    def test_unified_actions(self):
        s=step('image');s['image']='target';s['stable']=1;s['image_action']='actions';s['children']=[step('text')];self.execute([s]);self.assertEqual(self.inputs[0][0],'text')
    def test_unified_absent_branch(self):
        s=step('image');s['image']='target';s['image_mode']='once';s['otherwise']=[step('key')]
        frame=Image.new('RGB',(240,160),(30,40,60));self.execute([s],frame);self.assertEqual(self.inputs,[('key','enter')])
    def test_negative_origin(self):
        with patch('desktop.bounds',return_value=(-1920,-200,3840,1280)):
            self.assertEqual(local_to_screen((100,300)),(-1820,100))
    def test_negative_roi(self):self.assertEqual(local_to_screen((10,20),[-1500,-50,300,200]),(-1490,-30))
    def test_input_actions(self):
        items=[step(k) for k in ('hold','text','scroll')];self.execute(items);self.assertEqual([a[0] for a in self.inputs],['hold','text','scroll'])
    def test_legacy_defaults(self):
        s=step('delay');del s['image_mode'];del s['button'];self.p['steps']=[s];validate(self.p);self.assertEqual(s['button'],'left')
    def test_unified_roundtrip(self):
        s=step('image');s['image']='target';s['otherwise']=[step('loop')];self.p['steps']=[s];self.assertEqual(validate(copy.deepcopy(self.p)),self.p)

if __name__=='__main__':unittest.main(verbosity=2)
