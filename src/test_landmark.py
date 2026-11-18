import unittest
import cv2
from PIL import Image,ImageDraw
from recognition_features import Model
from recognition_motion import moving_matches


def badge(surround='#907060'):
    image=Image.new('RGB',(140,118),surround)
    draw=ImageDraw.Draw(image)
    draw.ellipse((29,24,108,92),fill='#c7f8f5')
    return image


class LandmarkTests(unittest.TestCase):
    def search(self,image,threshold=.9):
        return moving_matches(image,[('model',Model(badge()))],threshold,(.5,.5),
                              lambda:None,landmark=True)

    def test_rotated_mark_matching_its_surround(self):
        frame=Image.new('RGB',(320,240),'#c7f8f5')
        frame.paste(badge().rotate(33,fillcolor='#907060'),(61,40))
        result=self.search(frame)
        self.assertTrue(result['found'],result)
        self.assertAlmostEqual(result['point'][0],130,delta=5)
        self.assertAlmostEqual(result['point'][1],98,delta=5)

    def test_same_mark_with_wrong_surround_does_not_match(self):
        frame=Image.new('RGB',(340,240),'#c7f8f5')
        frame.paste(badge('#3951a0'),(90,50))
        self.assertFalse(self.search(frame)['found'])

    def test_duplicate_matches_do_not_choose_one_arbitrarily(self):
        frame=Image.new('RGB',(440,210),'#324f73')
        frame.paste(badge(),(30,31))
        frame.paste(badge(),(245,44))
        self.assertEqual(self.search(frame)['status'],'ambiguous')


if __name__=='__main__':
    unittest.main()
