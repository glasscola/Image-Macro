import copy,tempfile,threading,time,unittest
from pathlib import Path
import numpy as np
from PIL import Image
from core import *

class CoreTests(unittest.TestCase):
    def setUp(self):
        rng=np.random.default_rng(19)
        self.template=Image.fromarray(rng.integers(30,245,(24,36,3),dtype=np.uint8))
        self.frame=Image.new('RGB',(240,160),(32,48,64));self.frame.paste(self.template,(70,55))
        self.p=project();self.p['images']['target']=dict(name='테스트 버튼',data=encode_image(self.template))
    def execute(self,steps,frame=None):
        p=copy.deepcopy(self.p);p['steps']=steps;self.logs=[];self.inputs=[]
        r=Runner(p,lambda *a:self.logs.append(a),capture=lambda roi:frame if frame is not None else self.frame,output=lambda *a:self.inputs.append(a));r.run();return r
    def test_exact_location(self):
        r=match(self.frame,self.template);self.assertTrue(r['found']);self.assertEqual(r['point'],(88,67))
    def test_multiscale(self):
        frame=Image.new('RGB',(240,160),(30,40,60));frame.paste(self.template.resize((43,29)),(50,40))
        r=match(frame,self.template,.9,(1,1.2));self.assertTrue(r['found']);self.assertEqual(r['scale'],1.2)
    def test_ambiguous_rejected(self):
        self.frame.paste(self.template,(160,100));self.assertFalse(match(self.frame,self.template)['found'])
    def test_absent(self):self.assertFalse(match(Image.new('RGB',(200,150),(30,40,60)),self.template)['found'])
    def test_constant_template(self):
        tpl=Image.new('RGB',(12,12),'white');frame=Image.new('RGB',(100,80),'black');frame.paste(tpl,(30,20));self.assertTrue(match(frame,tpl)['found'])
    def test_roundtrip_nested(self):
        group=step('loop');cond=step('condition');cond['image']='target';cond['children']=[step('delay')];cond['otherwise']=[step('stop')];group['children']=[cond];self.p['steps']=[group]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'테스트.imacro.json';save(self.p,path);self.assertEqual(load(path),self.p)
    def test_draft_save(self):
        self.p['steps']=[step('wait')]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'draft.json';save(self.p,path);self.assertEqual(load(path),self.p)
        with self.assertRaises(ValueError):Runner(self.p,lambda *a:None)
    def test_loop_nested(self):
        a=step('loop');a['count']=2;b=step('loop');b['count']=3;c=step('point');b['children']=[c];a['children']=[b];self.execute([a]);self.assertEqual(len(self.inputs),6)
    def test_break(self):
        a=step('loop');a['children']=[step('point'),step('break'),step('point')];self.execute([a]);self.assertEqual(len(self.inputs),1)
    def test_continue(self):
        a=step('loop');a['count']=3;a['children']=[step('point'),step('continue'),step('point')];self.execute([a]);self.assertEqual(len(self.inputs),3)
    def test_condition(self):
        a=step('condition');a['image']='target';a['children']=[step('point')];a['otherwise']=[step('stop')];self.execute([a]);self.assertEqual(len(self.inputs),1)
    def test_click_refresh(self):
        a=step('find');a['image']='target';b=step('click');b['source']=a['id'];self.execute([a,b]);self.assertEqual(self.inputs,[('click',88,67)])
    def test_watch_break(self):
        a=step('loop');a['watch']='target';a['stable']=1;a['children']=[step('point')];self.execute([a]);self.assertEqual(len(self.inputs),0)
    def test_watch_after_group(self):
        a=step('loop');a['watch']='target';a['watch_timing']='after';a['children']=[step('point'),step('point')];self.execute([a]);self.assertEqual(len(self.inputs),2)
    def test_black_unknown(self):
        a=step('condition');a['image']='target';a['otherwise']=[step('point')];self.execute([a],Image.new('RGB',(200,120),'black'));self.assertEqual(len(self.inputs),0);self.assertIn(('state','오류'),self.logs)
    def test_cancel(self):
        p=project();s=step('delay');s['seconds']=30;p['steps']=[s];logs=[];r=Runner(p,lambda *a:logs.append(a),output=lambda *a:None);t=threading.Thread(target=r.run);t.start();time.sleep(.05);r.cancel.set();t.join(1);self.assertFalse(t.is_alive());self.assertIn(('state','정지됨'),logs)
    def test_invalid_nan(self):
        s=step('delay');s['seconds']=float('nan');self.p['steps']=[s]
        with self.assertRaises(ValueError):validate(self.p)
    def test_invalid_break(self):
        self.p['steps']=[step('break')]
        with self.assertRaises(ValueError):validate(self.p)
    def test_duplicate_id(self):
        s=step('delay');self.p['steps']=[s,copy.deepcopy(s)]
        with self.assertRaises(ValueError):validate(self.p)
    def test_disabled(self):
        s=step('point');s['enabled']=False;self.execute([s]);self.assertEqual(self.inputs,[])

if __name__=='__main__':unittest.main(verbosity=2)
