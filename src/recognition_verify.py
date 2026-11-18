"""Resolve candidate coordinates and verify original screen pixels."""
import cv2
import numpy as np
from recognition_search import response
from recognition_outline import aligned_detail


def verify(screen, pixels, target, x, y, radius, threshold, resized=False, *, aligned=False):
    h, w = target.shape
    fh, fw = screen.gray.shape
    left, top = max(0, x-radius), max(0, y-radius)
    right, bottom = min(fw, x+w+radius), min(fh, y+h+radius)
    if right-left < w or bottom-top < h:
        return None
    scores = response(screen.gray[top:bottom,left:right], target)
    _, score, _, (dx, dy) = cv2.minMaxLoc(scores)
    x, y = left+dx, top+dy
    if score < max(.40, threshold-(.28 if aligned else .15)):
        return None
    patch = screen.pixels[y:y+h,x:x+w]
    if aligned and resized and score < threshold:
        score=aligned_detail(target,screen.gray[y:y+h,x:x+w],threshold)
        if score is None:
            return None
        ref=pixels.mean(axis=(0,1))
        actual=patch.mean(axis=(0,1))
        if np.max(np.abs((ref-ref.mean())-(actual-actual.mean()))) > 30:
            return None
        return float(score),x,y
    if target.std() < 3:
        # Equal-luminance colors still carry information. Check all channels.
        score = 1 - float(np.abs(pixels.astype(np.float32)-patch).mean())/85
    else:
        # A separate local check prevents the frame around a button from
        # covering up a missing or different glyph inside it.
        inner = (slice(h//5, h-h//5), slice(w//5, w-w//5))
        interior = target[inner]
        if min(interior.shape) >= 4 and interior.std() >= 6:
            local = float(response(screen.gray[y:y+h,x:x+w][inner], interior)[0,0])
            if local < max(.55, threshold-(.22 if resized else .12)):
                return None
        local_patch = screen.gray[y:y+h,x:x+w]
        tile_w,tile_h = max(6,w//8),max(6,h//3)
        for yy in range(h//5,h-h//5-tile_h+1,max(1,tile_h//2)):
            for xx in range(w//10,w-w//10-tile_w+1,max(1,tile_w//2)):
                a = target[yy:yy+tile_h,xx:xx+tile_w]
                if a.std() < 12:
                    continue
                b = local_patch[yy:yy+tile_h,xx:xx+tile_w]
                if float(response(b,a)[0,0]) < (.40 if resized else .83):
                    return None
        if resized and score < threshold:
            # Keep the native checks above. The additional correlation tolerates
            # fractional stroke shifts when an app renders at a different DPI.
            a = cv2.GaussianBlur(target,(5,5),.95)
            b = cv2.GaussianBlur(local_patch,(5,5),.95)
            score = max(score,float(response(b,a)[0,0]))
        # Hue is checked independently; global brightness can change.
        ref = pixels.astype(np.float32).mean(axis=(0,1))
        actual = patch.astype(np.float32).mean(axis=(0,1))
        if np.max(np.abs((ref-ref.mean())-(actual-actual.mean()))) > 30:
            return None
    if min(w,h)<12 and (score<.978 or np.abs(pixels.astype(np.int16)-patch).mean()>8):
        return None
    if resized and 12<=min(w,h)<24 and np.abs(pixels.astype(np.int16)-patch).mean()>23:
        return None
    return float(score), x, y
