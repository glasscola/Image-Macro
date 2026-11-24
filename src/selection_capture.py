"""Read the visible desktop before opening the drag selection window."""
import time

from PIL import Image

import desktop


def capture_visible_desktop(bounds, displays):
    if not displays:
        raise RuntimeError('캡처할 모니터를 찾을 수 없습니다.')
    x, y, width, height = bounds
    result = Image.new('RGB', (width, height))
    for monitor in displays:
        left, top, w, h = monitor['rect']
        for _ in range(3):
            frame = desktop.capture((left, top, w, h))
            if frame.getbbox():
                break
            time.sleep(.035)
        else:
            raise RuntimeError(
                '모니터 화면이 검게 읽혀 캡처 선택을 열 수 없습니다. '
                '대상 화면이 보이는 상태에서 다시 캡처해 주세요.'
            )
        result.paste(frame, (left - x, top - y))
    return result
