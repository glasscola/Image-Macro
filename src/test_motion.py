import unittest

from PIL import Image, ImageDraw
from core import Runner, encode_image, project, step


def figure(alt=False):
    im=Image.new('RGB',(64,47),'#33415c')
    draw=ImageDraw.Draw(im)
    draw.ellipse((12,6,49,42),fill='#f2a878')
    draw.rectangle((0 if alt else 49,24,14 if alt else 63,40),fill='#dc4533')
    draw.line((19,31,30,39,43,25),fill='white',width=3)
    return im


class MotionTests(unittest.TestCase):
    def test_additional_pose_is_matched_and_rechecked_after_40_pixels(self):
        p=project()
        for key,alt in [('first',False),('other',True)]:
            p['images'][key]=dict(name=key,data=encode_image(figure(alt)))
        s=step('image')
        s.update(image='first',moving=True,variants=['other'],roi=(-300,-80,340,200))
        p['steps']=[s]
        frames=[]
        for x in (100,140):
            frame=Image.new('RGB',(340,200),'#58404e')
            frame.paste(figure(True),(x,73))
            frames.append(frame)
        r=Runner(p,lambda *_:None,capture=lambda roi:frames.pop(0))
        result=r.probe(s,quick=True)
        self.assertEqual(result.get('asset'),'other',result)
        self.assertEqual(result['box'],(-200,-7,64,47))
        self.assertEqual(r.confirm_target(s,result),(-128,17))

    def test_two_identical_moving_targets_are_ambiguous(self):
        p=project()
        p['images']['first']=dict(name='first',data=encode_image(figure()))
        s=step('image')
        s.update(image='first',moving=True)
        p['steps']=[s]
        f=Image.new('RGB',(420,230),'#48505b')
        f.paste(figure(),(32,50))
        f.paste(figure(),(270,100))
        r=Runner(p,lambda *_:None,capture=lambda roi:f).probe(s,quick=True)
        self.assertEqual(r['status'],'ambiguous')


if __name__=='__main__':
    unittest.main()
