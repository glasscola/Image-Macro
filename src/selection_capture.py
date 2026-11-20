"""Read the visible desktop before opening the drag selection window."""
import os
import time
from _ctypes import COMError

from PIL import Image

import desktop


def capture_gpu(displays):
    import dxcam

    # The selection window has its own live cursor.
    os.environ.setdefault('DXCAM_WINRT_CURSOR_CAPTURE', 'false')

    # DXcam 0.3 exposes adapter indexes publicly, but its Windows device
    # names are only available on the factory outputs.
    wanted = {monitor['device'] for monitor in displays}
    for adapter, outputs in enumerate(dxcam.__factory.outputs):
        for index, output in enumerate(outputs):
            output.update_desc()
            name = output.devicename
            if name not in wanted or not output.attached_to_desktop:
                continue
            for backend in ('dxgi', 'winrt'):
                try:
                    with dxcam.create(device_idx=adapter, output_idx=index,
                                      backend=backend, max_buffer_len=2) as camera:
                        for _ in range(4):
                            frame = camera.grab()
                            if frame is not None:
                                image = Image.fromarray(frame)
                                if image.getbbox():
                                    yield name, image
                                    break
                            time.sleep(.016)
                        else:
                            continue
                    break
                except (COMError, OSError, RuntimeError, ValueError):
                    continue


def capture_visible_desktop(bounds, displays):
    x, y, width, height = bounds
    try:
        captured = dict(capture_gpu(displays))
    except (COMError, ImportError, OSError, RuntimeError, ValueError):
        captured = {}
    result = Image.new('RGB', (width, height))
    for monitor in displays:
        left, top, w, h = monitor['rect']
        frame = captured.get(monitor['device'])
        if frame is None or frame.size != (w, h):
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
    if not displays:
        raise RuntimeError('캡처할 모니터를 찾을 수 없습니다.')
    return result
