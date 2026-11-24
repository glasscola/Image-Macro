import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw
from core import Runner, encode_image, project, step
from motion_capture import foreground, masked_hits
from recognition_motion import search_appearances


def figure(alt=False):
    im=Image.new('RGB',(64,47),'#33415c')
    draw=ImageDraw.Draw(im)
    draw.ellipse((12,6,49,42),fill='#f2a878')
    draw.rectangle((0 if alt else 49,24,14 if alt else 63,40),fill='#dc4533')
    draw.line((19,31,30,39,43,25),fill='white',width=3)
    return im


class MotionTests(unittest.TestCase):
    def test_primary_appearance_avoids_searching_other_poses(self):
        models=[('primary',object()),('other',object())]
        hit=dict(found=True,status='found',score=.98)
        with patch('recognition_motion.moving_matches',return_value=hit) as search:
            self.assertEqual(search_appearances(None,models,.9,(.5,.5),lambda:None),hit)
        self.assertEqual(search.call_count,1)
        self.assertEqual(search.call_args.args[1],models[:1])

    def test_unchanged_failed_capture_is_reused_until_pixels_change(self):
        seed=figure()
        p=project()
        p['images']['first']=dict(name='first',data=encode_image(seed))
        s=step('image')
        s.update(image='first',moving=True,roi=(0,0,160,120))
        p['steps']=[s]
        initial=Image.new('RGB',(160,120),'#465832')
        updated=initial.copy()
        updated.paste(seed,(20,20))
        captures=iter((initial,initial.copy(),updated))
        runner=Runner(p,lambda *_:None,capture=lambda _:next(captures),output=lambda *_:None)
        runner.native_capture=True
        self.assertFalse(runner.probe(s,quick=True)['found'])
        self.assertTrue(runner.probe(s,quick=True)['unchanged'])
        self.assertTrue(runner.probe(s,quick=True)['found'])

    def test_dense_color_candidates_keep_the_exact_crop(self):
        sample = Image.new('RGB',(53,47),'#83d1cd')
        ImageDraw.Draw(sample).line((13,26,34,13),fill='#776756',width=4)
        frame = Image.new('RGB',(420,210),'#83d1cd')
        for y in range(12,180,6):
            ImageDraw.Draw(frame).line((12,y,320,y),fill='#776756',width=2)
        frame.paste(sample,(340,142))
        reference = np.asarray(sample)
        mask = np.ones((47,53),np.uint8)
        hits = masked_hits(np.asarray(frame),reference,mask,.9,lambda:None)
        self.assertIn((1.,340,142),hits)

    def test_recorded_foreground_follows_target_on_changed_background(self):
        sample = Image.new('RGB',(64,64),'#eff3f9')
        draw = ImageDraw.Draw(sample)
        draw.ellipse((15,10,49,49),fill='#da4475')
        draw.rectangle((26,23,36,33),fill='#59d6a5')
        mask = foreground(sample)
        image_mask = Image.fromarray(mask*255)
        p = project()
        p['images']['clip'] = dict(name='clip',data=encode_image(sample),
                                  motion_mask=encode_image(image_mask))
        s = dict(step('image'),image='clip',moving=True)
        p['steps'] = [s]
        frames = []
        for x in (35,62):
            frame = Image.new('RGB',(260,170),'#465832')
            frame.paste(sample,(x,31),image_mask)
            frames.append(frame)
        runner = Runner(p,lambda *_:None,capture=lambda _:frames.pop(0))
        result = runner.probe(s,quick=True)
        self.assertEqual(result.get('method'),'recorded_motion',result)
        self.assertEqual(result['box'],(35,31,64,64))
        point = runner.confirm_target(s,result,lead=True)
        self.assertEqual(point,(94,63))
        self.assertTrue(mask[point[1]-31,point[0]-62])

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
