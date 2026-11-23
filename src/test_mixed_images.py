import unittest
import cv2
from PIL import Image, ImageDraw, ImageFont
from recognition import DEFAULT_SCALES, match, recheck, search_regions
from recognition_features import Model
from recognition_multiscale import small_anchor_candidates


class MixedImageTests(unittest.TestCase):
    def test_pixel_fallback_rejects_substituted_digits_and_letters(self):
        def label(text, size):
            font = ImageFont.truetype('arialbd.ttf',size)
            left,top,right,bottom = font.getbbox(text)
            image = Image.new('RGB',(right-left+72,bottom-top+62),'black')
            ImageDraw.Draw(image).text((36-left,31-top),text,font=font,fill='white')
            return image

        regions = [dict(rect=(i*480,0,480,360),dpi=96,device=str(i)) for i in range(2)]
        for wanted,decoy,size,scale in (('08','06',142,.63),('5','6',42,.63),
                                        ('READY','READV',42,.8)):
            with self.subTest(wanted=wanted, decoy=decoy):
                reference = Model(label(wanted,size))
                def scene(text):
                    tile = label(text,size)
                    tile = tile.resize(tuple(round(value*scale) for value in tile.size),
                                       Image.Resampling.LANCZOS)
                    frame = Image.new('RGB',(960,360),'#ebedf4')
                    frame.paste(tile,(512,117))
                    return frame
                for quick in (True,False):
                    exact = search_regions(scene(wanted),reference,regions,(0,0),
                                           DEFAULT_SCALES,96,.9,(.5,.5),quick=quick,fast=True)
                    self.assertTrue(exact['found'],exact)
                    wrong = search_regions(scene(decoy),reference,regions,(0,0),
                                           DEFAULT_SCALES,96,.9,(.5,.5),quick=quick,fast=True)
                    self.assertFalse(wrong['found'],wrong)
                # A pixel candidate from an earlier frame must also reject a replaced label.
                width,height = (round(value*scale) for value in label(wanted,size).size)
                previous = dict(box=(512,117,width,height),scale=scale)
                self.assertFalse(recheck(scene(decoy),reference,previous,.9,(.5,.5))['found'])

    def test_scaled_label_wider_than_icon_limit_is_checked_at_native_pixels(self):
        import numpy as np

        label = Image.new('RGB',(207,101),'#b21334')
        font = ImageFont.truetype('malgun.ttf',80)
        ImageDraw.Draw(label).text((12,13),'시작!',font=font,fill='#fff199',anchor='lt')
        model = Model(label)
        scaled = label.resize((104,50),Image.Resampling.LANCZOS)
        frame = Image.new('RGB',(640,360),'#39445c')
        frame.paste(scaled,(173,85))

        candidates, limited = small_anchor_candidates(np.asarray(frame),model,(.5,),lambda:None,1)
        self.assertFalse(limited)
        self.assertEqual(candidates,[(1.,173,85,104,50)])

    def test_small_icon_fast_search_with_flat_monitor_and_duplicate(self):
        icon = Image.new('RGB',(24,24),'#e2e7ef')
        draw = ImageDraw.Draw(icon)
        draw.polygon([(1,21),(12,1),(22,20)],fill='#693ebc',outline='#212942')
        draw.ellipse((8,8,16,16),fill='#ffc257')
        model = Model(icon)
        frame = Image.new('RGB',(980,360),'#ffc257')
        frame.paste('#39445c',(0,0,480,360))
        regions = [dict(rect=(0,0,480,360),dpi=144,device='left'),
                   dict(rect=(480,0,500,360),dpi=120,device='right')]

        def search():
            return search_regions(frame,model,regions,(0,0),DEFAULT_SCALES,None,.9,
                                  (.5,.5),quick=True,fast=True)

        frame.paste(icon,(53,120))
        self.assertEqual(search()['box'],(53,120,24,24))
        frame.paste('#39445c',(53,120,77,144))
        enlarged = icon.resize((30,30),Image.Resampling.LANCZOS)
        frame.paste(enlarged,(691,172))
        result = search()
        self.assertTrue(result['found'],result)
        self.assertEqual(result['box'],(691,172,30,30))
        self.assertTrue(recheck(frame,model,result,.9,(.5,.5))['found'])
        frame.paste(enlarged,(53,120))
        self.assertEqual(search()['status'],'ambiguous')

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
