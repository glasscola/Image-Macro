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

    def test_multiline_text_at_common_rendered_sizes(self):
        font = ImageFont.truetype('malgun.ttf',22)

        def paragraph(word):
            image = Image.new('RGB',(408,129),'#f5f7fb')
            draw = ImageDraw.Draw(image)
            for index,line in enumerate(('화면에서 대상을 찾습니다.',f'버튼을 누르면 작업이 {word}.',
                                         '다음 단계까지 계속 진행합니다.')):
                draw.text((14,13+index*33),line,font=font,fill='#182539')
            return image

        source = paragraph('시작됩니다')
        model = Model(source)
        for scale in (.8,.9,1.1,1.25,4/3):
            with self.subTest(scale=scale):
                frame = Image.new('RGB',(810,440),'#39445c')
                size = (round(source.width*scale),round(source.height*scale))
                frame.paste(source.resize(size,Image.Resampling.LANCZOS),(151,97))
                regions = [dict(rect=(0,0,*frame.size),dpi=96,device='test')]
                quick = scale in (.8,1.25)
                result = search_regions(frame,model,regions,(0,0),DEFAULT_SCALES,None,
                                        .9,(.5,.5),quick=quick,fast=True)
                self.assertEqual(result.get('method'),'scaled_rgb',result)
                self.assertEqual(result['box'],(151,97,*size))
                self.assertTrue(recheck(frame,model,result,.9,(.5,.5))['found'])
                frame.paste(paragraph('중지됩니다').resize(size,Image.Resampling.LANCZOS),(151,97))
                self.assertFalse(recheck(frame,model,result,.9,(.5,.5))['found'])
                if quick:
                    self.assertFalse(self.search(frame,model)['found'])

    def test_striped_artwork_uses_the_complete_scaled_rectangle(self):
        source = Image.new('RGB',(240,112),'#eeeeff')
        draw = ImageDraw.Draw(source)
        for x in range(3,237,8):
            draw.line((x,4,x,106),fill='#111722',width=3)
        draw.line((58,92,168,17),fill='#ed423c',width=5)
        model = Model(source)
        frame = Image.new('RGB',(810,440),'#39445c')
        frame.paste(source.resize((300,140),Image.Resampling.LANCZOS),(151,97))
        result = self.search(frame,model)
        self.assertEqual(result.get('method'),'scaled_rgb',result)
        self.assertEqual(result['box'],(151,97,300,140))
        local = dict(result,box=(8,8,300,140))
        self.assertTrue(recheck(frame.crop((143,89,459,245)),model,local,.9,(.5,.5))['found'])

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
