from pathlib import Path
from PIL import Image,ImageOps,UnidentifiedImageError
import cv2
import numpy as np


def load_image(path):
    """Identify by file content, normalize orientation and flatten transparency."""
    try:
        with Image.open(path) as source:
            image=ImageOps.exif_transpose(source)
            if 'A' in image.getbands() or 'transparency' in image.info:
                rgba=image.convert('RGBA')
                white=Image.new('RGBA',rgba.size,'white')
                return Image.alpha_composite(white,rgba).convert('RGB')
            return image.convert('RGB')
    except UnidentifiedImageError as error:
        payload=np.frombuffer(Path(path).read_bytes(),dtype=np.uint8)
        decoded=cv2.imdecode(payload,cv2.IMREAD_COLOR) if len(payload) else None
        if decoded is not None:
            return Image.fromarray(cv2.cvtColor(decoded,cv2.COLOR_BGR2RGB))
        raise ValueError('이 형식은 현재 열 수 없습니다. 화면에 띄운 뒤 직접 캡처할 수 있습니다.') from error
