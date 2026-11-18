import unittest
import cv2
from PIL import Image, ImageDraw, ImageFont
from recognition import DEFAULT_SCALES, match, recheck
from recognition_features import Model


class MixedImageTests(unittest.TestCase):
    def test_equal_flat_regions_at_edges_are_ambiguous(self):
        frame=Image.new('RGB',(430,290),'#243341')
        uniform=Image.new('RGB',(31,23),'#36a4d1')
        frame.paste(uniform,(399,267))
        r=match(frame,uniform,scales=DEFAULT_SCALES)
        self.assertTrue(r['found'],r)
        self.assertEqual(r['box'],(399,267,31,23))
        frame.paste(uniform,(0,0))
        self.assertEqual(match(frame,uniform,scales=DEFAULT_SCALES)['status'],'ambiguous')

    def test_bare_text_at_arbitrary_width_and_changed_digit(self):
        def draw(scale,last):
            w,h=round(148*scale),round(33*scale)
            image=Image.new('RGB',(w,h),'#24262e')
            font=ImageFont.truetype('arialbd.ttf',round(20*scale))
            ImageDraw.Draw(image).text((w//2,h//2),'ITEM 62'+last,fill='#e9edf3',font=font,anchor='mm')
            return image
        frame=Image.new('RGB',(1040,720),'#52606d')
        model=Model(draw(1,'7'))
        frame.paste(draw(1.33,'7'),(712,517))
        r=match(frame,model,scales=DEFAULT_SCALES)
        self.assertTrue(r['found'],r)
        self.assertTrue(recheck(frame,model,r,.9,(.5,.5))['found'])
        frame.paste(draw(1.33,'1'),(712,517))
        self.assertFalse(match(frame,model,scales=DEFAULT_SCALES)['found'])


if __name__=='__main__':
    unittest.main()
