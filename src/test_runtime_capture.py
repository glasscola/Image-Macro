import ctypes
from unittest import TestCase
from unittest.mock import Mock, patch

from PIL import Image

from runtime_capture import RuntimeCapture
from desktop_capture import CaptureBuffer


class RuntimeCaptureTests(TestCase):
    def test_cpu_buffer_reuses_only_identical_pixels_at_same_position(self):
        buffer = CaptureBuffer()
        buffer.size = (2,2)
        buffer.pixels = (ctypes.c_ubyte*16)(*([255]*16))
        key = (-2,3,False)
        first = buffer._image_from_pixels(key)
        self.assertIs(buffer._image_from_pixels(key),first)
        self.assertIsNot(buffer._image_from_pixels(None),first)
        buffer.pixels[0] = 0
        changed = buffer._image_from_pixels(key)
        self.assertIsNot(changed,first)
        self.assertEqual(first.getpixel((0,0)),(255,255,255))
        self.assertEqual(changed.getpixel((0,0)),(255,255,0))
        self.assertIsNot(buffer._image_from_pixels((10,3,False)),changed)
        buffer.close()
        self.assertIsNone(buffer.image)

    def test_reads_and_confirms_with_separate_buffers(self):
        capture = RuntimeCapture()
        frame = Image.new('RGB',(16,12),'white')
        patch_frame = Image.new('RGB',(4,5),'red')
        fallback = Mock()
        with (patch.object(capture.cpu_buffer,'read',return_value=frame) as read,
              patch.object(capture.confirmation_buffer,'read',return_value=patch_frame) as confirm):
            self.assertIs(capture.read((50,15,16,12),fallback),frame)
            self.assertIs(capture.confirm((50,15,4,5),fallback),patch_frame)
        read.assert_called_once_with(50,15,16,12,include_layered=False,reuse_unchanged=True)
        confirm.assert_called_once_with(50,15,4,5,include_layered=False,reuse_unchanged=False)
        fallback.assert_not_called()

    def test_black_frame_and_capture_failure_use_fallback(self):
        capture = RuntimeCapture()
        fallback = Mock(return_value=Image.new('RGB',(16,12),'white'))
        roi = (-16,0,16,12)
        with (patch.object(capture.cpu_buffer,'read',return_value=Image.new('RGB',(16,12))),
              patch.object(capture.confirmation_buffer,'read',side_effect=OSError)):
            self.assertIs(capture.read(roi,fallback),fallback.return_value)
            self.assertIs(capture.confirm(roi,fallback),fallback.return_value)
        self.assertEqual(fallback.call_count,2)
