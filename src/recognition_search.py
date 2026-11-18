"""Candidate generation. Fast correlation first, sparse orientation search on demand."""
import cv2
import numpy as np
from recognition_features import gradients


def response(screen, target):
    if target.std() < 3:
        return 1 - cv2.matchTemplate(screen, target, cv2.TM_SQDIFF_NORMED)
    return cv2.matchTemplate(screen, target, cv2.TM_CCOEFF_NORMED)


def pixel_candidates(screen, target, threshold, check, native=False, broad=False, budget=1, precise=False):
    h, w = target.shape
    factor = 2 if not native and screen.gray.size > 500000 and min(h, w) >= 24 else 1
    if factor == 2 and broad and min(h,w) >= 28:
        factor = 4
    if factor > 1:
        sample = screen.coarse_gray(factor)
        needle = cv2.resize(target, (w // factor, h // factor), interpolation=cv2.INTER_AREA)
    else:
        sample, needle = screen.gray, target
    scores = response(sample, needle)
    floor = max(.60 if factor == 4 else .48, threshold - (.40 if factor > 1 else .06))
    return peaks(scores, w // factor, h // factor, .979 if precise else floor, 32*budget, check), factor


def peaks(scores, width, height, floor, limit, check):
    """Report if work is left beyond the verification budget."""
    found = []
    for _ in range(limit + 1):
        check()
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        if score < floor:
            return found, False
        if len(found) == limit:
            return found, True
        found.append((x, y))
        rx, ry = max(1, width // 5), max(1, height // 5)
        scores[max(0, y-ry):y+ry+1, max(0, x-rx):x+rx+1] = -1
    return found, False


def orientation_candidates(screen, pixels, check, budget=1):
    # Each grid cell records which directions occur nearby in original pixels.
    # Offsets are rounded to this grid; native verification restores precision.
    stride = 4
    h, w = pixels.shape[:2]
    if min(h, w) < 12:
        return ([], False), stride
    gray = cv2.cvtColor(pixels,cv2.COLOR_RGB2GRAY)
    magnitude, direction = gradients(gray[:,:,None])
    anchors = []
    for ys in np.array_split(np.arange(1, h-1), 4):
        for xs in np.array_split(np.arange(1, w-1), 4):
            patch = magnitude[np.ix_(ys, xs)]
            iy, ix = np.unravel_index(patch.argmax(), patch.shape)
            if patch[iy, ix] >= 24:
                x, y = int(xs[ix]), int(ys[iy])
                anchors.append((round(x/stride), round(y/stride), direction[y, x]))
    anchors = list(dict.fromkeys(anchors))
    if len(anchors) < 5:
        return ([], False), stride

    if screen.maps is None:
        check()
        dx = cv2.Sobel(screen.gray,cv2.CV_32F,1,0)
        dy = cv2.Sobel(screen.gray,cv2.CV_32F,0,1)
        strength, angle = cv2.cartToPolar(dx,dy,angleInDegrees=True)
        bins = (np.floor((angle + 11.25) / 22.5).astype(np.uint8) & 7)
        fh, fw = bins.shape
        gh, gw = (fh+3)//4, (fw+3)//4
        palette = np.array([1 << (i & 7) for i in range(256)], np.uint8)
        flags = cv2.LUT(bins, palette)
        flags[strength < 16] = 0
        flags = np.pad(flags,((0,gh*4-fh),(0,gw*4-fw)))
        pooled = np.zeros((gh,gw),np.uint8)
        for iy in range(4):
            for ix in range(4):
                pooled |= flags[iy::4,ix::4]
        pooled = np.pad(pooled,((0,1),(0,1)))
        screen.maps = []
        for d in range(8):
            check()
            wanted = (1 << d) | (1 << ((d-1)&7)) | (1 << ((d+1)&7))
            present = ((pooled & wanted)!=0).astype(np.uint8)
            screen.maps.append(cv2.dilate(present,np.ones((3,3),np.uint8)))

    fh, fw = screen.gray.shape
    rows, cols = (fh-h)//stride+1, (fw-w)//stride+1
    votes = np.zeros((rows, cols), np.float32)
    for x, y, d in anchors:
        votes += screen.maps[d][y:y+rows, x:x+cols]
    return peaks(votes, max(1,w//stride), max(1,h//stride),
                 np.ceil(len(anchors)*.82), 24*budget, check), stride
