import tempfile
import unittest
from pathlib import Path

from PIL import Image
from image_files import load_image


class ImageInputTests(unittest.TestCase):
    def test_file_contents_determine_format_even_without_extension(self):
        source=Image.new('RGB',(24,20),(86,42,112))
        with tempfile.TemporaryDirectory() as directory:
            for kind in ('PNG','JPEG','WEBP','BMP','GIF','TIFF','AVIF','ICO','PPM','QOI','TGA','JPEG2000'):
                with self.subTest(format=kind):
                    path=Path(directory)/f'{kind}.unknown'
                    options={'sizes':[(16,16)]} if kind=='ICO' else {}
                    (source.crop((0,0,16,16)) if kind=='ICO' else source).save(path,format=kind,**options)
                    decoded=load_image(path)
                    self.assertEqual(decoded.mode,'RGB')
                    self.assertEqual(decoded.size,(16,16) if kind=='ICO' else source.size)

    def test_transparency_is_composited_on_white(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'image.dat'
            Image.new('RGBA',(20,20),(255,0,0,0)).save(path,format='PNG')
            self.assertEqual(load_image(path).getpixel((0,0)),(255,255,255))
