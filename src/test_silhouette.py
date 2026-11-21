import unittest

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from recognition import DEFAULT_SCALES, Model, recheck, search_regions


def glyph(symbol):
    pixels = np.zeros((450, 640), np.uint8)
    cv2.putText(pixels, symbol, (245, 295), cv2.FONT_HERSHEY_SIMPLEX,
                6.5, 255, 19, cv2.LINE_AA)
    return Image.fromarray(pixels).convert('RGB')


class VideoSilhouetteTests(unittest.TestCase):
    def search(self, frame, reference):
        regions = [dict(rect=(0,0,*frame.size), dpi=96, device='test')]
        return search_regions(frame,reference,regions,(0,0),DEFAULT_SCALES,96,
                              .9,(.5,.5),quick=True,fast=True)

    def test_padded_digit_at_smaller_scale_and_recheck(self):
        reference = Model(glyph('5'))
        frame = Image.new('RGB',(960,540),'#20243a')
        frame.paste(glyph('5').resize((256,180)),(314,188))
        result = self.search(frame,reference)
        self.assertTrue(result['found'], result)
        self.assertEqual(result['method'],'silhouette')
        self.assertTrue(recheck(frame,reference,result,.9,(.5,.5))['found'])
        frame.paste(glyph('3').resize((256,180)),(314,188))
        self.assertFalse(self.search(frame,reference)['found'])
        self.assertFalse(recheck(frame,reference,result,.9,(.5,.5))['found'])

    def test_identical_digits_in_two_locations_are_ambiguous(self):
        small = glyph('5').resize((256,180))
        frame = Image.new('RGB',(960,540),'#20243a')
        frame.paste(small,(140,170))
        frame.paste(small,(550,170))
        self.assertEqual(self.search(frame,Model(glyph('5')))['status'],'ambiguous')

    def test_colored_digits_are_checked_individually_after_resize(self):
        font=ImageFont.truetype('arialbd.ttf',142)

        def colored(text):
            image=Image.new('RGB',(250,166),'#a00000')
            ImageDraw.Draw(image).text((125,83),text,font=font,anchor='mm',fill='#003eff')
            return image

        frame=Image.new('RGB',(960,540),'#ebedf4')
        reference=Model(colored('08'))
        frame.paste(colored('08').resize((100,66)),(380,190))
        result=self.search(frame,reference)
        self.assertTrue(result['found'],result)
        self.assertTrue(recheck(frame,reference,result,.9,(.5,.5))['found'])
        frame.paste(colored('06').resize((100,66)),(380,190))
        self.assertFalse(self.search(frame,reference)['found'])

    def test_quick_search_checks_resized_photo_on_second_monitor(self):
        rng=np.random.default_rng(293)
        colors=rng.integers(24,240,(12,16,3),dtype=np.uint8)
        source=Image.fromarray(cv2.resize(colors,(312,236),interpolation=cv2.INTER_CUBIC))
        frame=Image.new('RGB',(1920,540),'#48546a')
        frame.paste(source.resize((250,189)),(1058,190))
        monitors=[dict(rect=(x,0,960,540),dpi=96,device=str(x)) for x in (0,960)]
        result=search_regions(frame,Model(source),monitors,(0,0),DEFAULT_SCALES,96,
                              .9,(.5,.5),quick=True,fast=True)
        self.assertTrue(result['found'],result)
        self.assertAlmostEqual(result['box'][0],1058,delta=3)

    def test_sparse_digit_in_a_full_black_video_frame(self):
        original=Image.new('RGB',(1280,900),'black')
        original.paste(glyph('1'),(180,200))
        ratio=np.count_nonzero(np.asarray(original)[:,:,0])/(1280*900)
        self.assertLess(ratio,.015)
        frame=Image.new('RGB',(960,540),'#20243a')
        frame.paste(original.resize((512,360)),(215,76))
        self.assertTrue(self.search(frame,Model(original))['found'])
