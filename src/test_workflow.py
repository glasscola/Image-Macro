import threading
import time
import unittest
from PIL import Image
import numpy as np
import core


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.p=core.project()
        self.frame=Image.new('RGB',(140,100),'#23384b')
        self.asset=Image.fromarray(np.random.default_rng(7).integers(15,240,(25,33,3),dtype=np.uint8))
        self.p['images']['exit']=dict(name='EXIT',data=core.encode_image(self.asset))
        self.exit_frame=self.frame.copy()
        self.exit_frame.paste(self.asset,(57,43))
        self.actions=[]
        self.log=[]

    def image(self,x):
        s=core.step('image')
        s.update(image='exit',scales=[1.],image_action='actions',wait_forever=True,
                 children=[self.click(x)])
        return s

    def click(self,x):
        return dict(core.step('point'),x=x,y=20)

    def evaluate(self,output):
        r=core.Runner(self.p,lambda *event:self.log.append(event),
                      capture=lambda roi:self.frame,output=output)
        t=threading.Thread(target=r.run)
        t.start()
        t.join(5)
        if t.is_alive():
            r.cancel.set()
            t.join(2)
            self.fail('test workflow did not finish')
        self.assertIn(('state','완료'),self.log)

    def test_repeat_until_image(self):
        a,b,c,d=self.click(1),self.click(2),self.image(3),self.click(4)
        self.p.update(steps=[a,b,c,d],repeat_enabled=True,
                      ranges=[dict(id='range',start=b['id'],end=b['id'],count=0)],
                      routes=[dict(target=c['id'],scope='range')])
        def action(kind,x,*rest):
            self.actions.append(x)
            if self.actions.count(2)==3:
                self.frame=self.exit_frame
                time.sleep(.17)
        self.evaluate(action)
        self.assertEqual(self.actions,[1,2,2,2,3,4])

    def test_jump_over_2_3_4_with_destination_repeat(self):
        a,b,c,d,e,f=self.click(1),self.click(2),self.image(3),self.click(4),self.image(5),self.click(6)
        a= dict(core.step('record'),events=[dict(type='move',delay=0,x=1,y=0),
                                            dict(type='move',delay=.35,x=10,y=0)])
        self.p.update(steps=[a,b,c,d,e,f],repeat_enabled=True,
                      ranges=[dict(id='range',start=e['id'],end=e['id'],count=2)],
                      routes=[dict(target=e['id'],scope=None),dict(target=c['id'],scope=None)])
        def action(kind,*args):
            self.actions.append(args[0]['x'] if kind=='event' else args[0])
            if kind=='event':
                self.frame=self.exit_frame
        self.evaluate(action)
        self.assertEqual(self.actions,[1,5,5,6])

    def test_jump_releases_recorded_button_before_transition(self):
        first=dict(core.step('record'),events=[
            dict(type='mouse',button='left',down=True,delay=0,x=1,y=0),
            dict(type='mouse',button='left',down=False,delay=.24,x=1,y=0),
            dict(type='move',delay=.25,x=99,y=0)])
        second=self.image(5)
        self.p.update(steps=[first,second],routes=[dict(target=second['id'],scope=None)])
        def action(kind,*args):
            if kind=='event':
                event=args[0]
                self.actions.append(event.get('down',event['x']))
                self.frame=self.exit_frame
            else:
                self.actions.append(args[0])
        self.evaluate(action)
        self.assertEqual(self.actions,[True,False,5])

    def test_indefinite_wait_survives_old_deadline(self):
        s=self.image(1)
        s['timeout']=.1
        self.p['steps']=[s]
        timer=threading.Timer(.35,lambda:setattr(self,'frame',self.exit_frame))
        timer.start()
        try:
            self.evaluate(lambda _,x,*rest:self.actions.append(x))
        finally:
            timer.cancel()
        self.assertEqual(self.actions,[1])
        self.assertTrue(any(type=='waiting' for type,_ in self.log))


if __name__=='__main__':
    unittest.main()
