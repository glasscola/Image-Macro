import unittest

from PIL import Image, ImageDraw, ImageFont
from recognition import match


def render(scale, text="START 742"):
    image = Image.new("RGB",(round(100*scale),round(40*scale)),"#1765aa")
    draw = ImageDraw.Draw(image)
    draw.rectangle((1,1,image.width-2,image.height-2),
                   outline="white",width=max(1,round(scale)))
    font = ImageFont.truetype("arialbd.ttf",round(15*scale))
    draw.text((image.width//2,image.height//2),text,font=font,anchor="mm",fill="white")
    return image


class RenderingTests(unittest.TestCase):
    def setUp(self):
        self.template = render(1)
        self.frame = Image.new("RGB",(1300,900),"#354150")
        drawing = ImageDraw.Draw(self.frame)
        for y in range(12,800,32):
            drawing.text((20,y),"Menus and labels START 12345678",fill="white")

    def test_independently_rendered_150_percent(self):
        self.frame.paste(render(1.5),(701,511))
        result = match(self.frame,self.template,scales=(.8,.9,1.,1.1,1.2))
        self.assertTrue(result['found'],result)
        self.assertEqual(result['box'],(701,511,150,60))

    def test_reject_one_changed_digit(self):
        self.frame.paste(render(1,"START 741"),(701,511))
        result = match(self.frame,self.template,scales=(.8,.9,1.,1.1,1.2))
        self.assertEqual(result['status'],'not_found',result)

    def test_offset_remains_inside_target(self):
        self.frame.paste(self.template,(701,511))
        result = match(self.frame,self.template,offset=(1,1))
        self.assertEqual(result['point'],(800,550))


    def test_intermediate_windows_scales_detect_and_confirm(self):
        from recognition import recheck
        from recognition_features import Model
        for scale in (.83,1.05,1.15,1.33,1.45):
            with self.subTest(scale=scale):
                frame=self.frame.copy()
                target=render(scale)
                frame.paste(target,(701,511))
                model=Model(self.template)
                result=match(frame,model,scales=(.8,.9,1.,1.1,1.2))
                self.assertTrue(result['found'],result)
                self.assertLessEqual(abs(result['point'][0]-(701+target.width/2)),3)
                self.assertLessEqual(abs(result['point'][1]-(511+target.height/2)),3)
                self.assertTrue(recheck(frame,model,result,.9,(.5,.5))['found'],result)

    def test_outline_fallback_does_not_click_rescaled_wrong_digit(self):
        for scale in (1.,1.5):
            with self.subTest(scale=scale):
                frame=self.frame.copy()
                frame.paste(render(scale,'START 741'),(701,511))
                self.assertFalse(match(frame,self.template,scales=(.8,.9,1.,1.1,1.2))['found'])


if __name__ == "__main__":
    unittest.main()
