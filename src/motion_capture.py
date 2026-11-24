"""Extract representative foreground samples from a short screen recording."""
import time

import cv2
import numpy as np
from PIL import Image

from recognition_features import rgb
from motion_features import follow


def foreground(image):
    pixels = rgb(image)
    h,w = pixels.shape[:2]
    if min(w,h)<12 or max(w,h)>600:
        raise ValueError('대상을 12~600픽셀 크기로 둘러싸세요.')
    rim = max(1,round(min(w,h)*.04))
    mask = np.zeros((h,w),np.uint8)
    cv2.grabCut(pixels.copy(),mask,(rim,rim,w-2*rim,h-2*rim),
                np.zeros((1,65)),np.zeros((1,65)),2,cv2.GC_INIT_WITH_RECT)
    mask = (mask & 1).astype(np.uint8)
    if mask.sum()<24 or mask.mean()<.06:
        raise ValueError('대상 윤곽이 부족합니다. 대상 전체와 주변 여백을 조금 포함해 다시 선택하세요.')
    return mask


def masked_hits(pixels, reference, mask, threshold, check):
    """Find color-anchor proposals, then compare foreground pixels only."""
    h,w = mask.shape
    rows,cols = pixels.shape[0]-h+1,pixels.shape[1]-w+1
    if rows<=0 or cols<=0:
        return []
    interior = cv2.erode(mask,np.ones((3,3),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0)
    ys,xs = np.nonzero(interior if interior.sum()>=8 else mask)
    if not len(xs):
        return []
    colors = reference[ys,xs].astype(np.int16)
    first = int(np.argmin(((xs-w/2)**2+(ys-h/2)**2)))
    second = int(np.argmax(np.abs(colors-colors[first]).max(axis=1)))
    # Articulated edges move between appearances. Propose using two interior
    # colors and leave the whole foreground comparison to reject lookalikes.
    grid = None
    for index in dict.fromkeys((second,first)):
        check()
        x,y = xs[index],ys[index]
        lo = np.maximum(0,colors[index]-29).astype(np.uint8)
        hi = np.minimum(255,colors[index]+29).astype(np.uint8)
        allowed = cv2.inRange(pixels[y:y+rows,x:x+cols],lo,hi)
        grid = allowed if grid is None else cv2.bitwise_and(grid,allowed)
        if not cv2.countNonZero(grid):
            return []
    count = cv2.countNonZero(grid)
    if not count:
        return []
    candidates = cv2.findNonZero(grid).reshape(-1,2)
    # Rank dense color matches using foreground pixels spread across the crop.
    # Keep separated locations so repeated features can still be ambiguous.
    if count > 64:
        stride = max(1, len(xs)//64)
        indices = np.arange(0,len(xs),stride)[:64]
        errors = np.zeros(count,np.float32)
        for index in indices:
            check()
            x,y = xs[index],ys[index]
            delta = pixels[candidates[:,1]+y,candidates[:,0]+x].astype(np.int16)-colors[index]
            errors += np.minimum(np.abs(delta),65).mean(axis=1)
        selected = []
        for _ in range(24):
            index = int(errors.argmin())
            if not np.isfinite(errors[index]):
                break
            x,y = candidates[index]
            selected.append((x,y))
            errors[(np.abs(candidates[:,0]-x)<=2)&(np.abs(candidates[:,1]-y)<=2)] = np.inf
        candidates = selected
    matches = []
    use = mask!=0
    for x,y in candidates:
        check()
        difference = cv2.absdiff(pixels[y:y+h,x:x+w],reference)[use]
        score = 1-float(np.minimum(difference,65).mean())/180
        if score>=threshold and (difference.max(axis=1)<=44).mean()>=.82:
            matches.append((score,int(x),int(y)))
    return matches


def select_appearances(samples):
    """Retain the original pose and use spare slots to cover distinct poses."""
    signatures = []
    for image, mask, _ in samples:
        scaled = cv2.resize(rgb(image),(40,40),interpolation=cv2.INTER_AREA).astype(np.float32)
        gray = cv2.cvtColor(scaled,cv2.COLOR_RGB2GRAY)
        edges = np.clip(cv2.Laplacian(gray,cv2.CV_32F),-96,96)
        inside = cv2.resize(mask,(40,40),interpolation=cv2.INTER_NEAREST)!=0
        signatures.append((gray,edges,inside))
    comparison = np.eye(len(samples),dtype=np.float32)
    for i,(gray,edges,inside) in enumerate(signatures):
        for j,(other,other_edges,other_inside) in enumerate(signatures[:i]):
            overlap = inside & other_inside
            if overlap.any():
                error = (np.abs(gray[overlap]-other[overlap]).mean()/255*.55
                         + np.abs(edges[overlap]-other_edges[overlap]).mean()/192*.25
                         + .2*(1-overlap.sum()/(inside|other_inside).sum()))
                comparison[i,j] = comparison[j,i] = np.clip(1-error/.22,0,1)
    selected = [0]
    covered = comparison[0].copy()
    for _ in range(2):
        gains = np.maximum(comparison-covered,0).sum(axis=1)
        choice = int(gains.argmax())
        if gains[choice]<.15:
            break
        selected.append(choice)
        covered = np.maximum(covered,comparison[choice])
    return [samples[i] for i in selected]


def record_appearances(seed, rect, bounds, capture, *, seconds=3.):
    """Follow the selected target through successive captures and keep distinct samples."""
    mask = foreground(seed)
    x,y,w,h = rect
    bx,by,bw,bh = bounds
    samples = [(seed,mask,rect)]
    previous = rgb(seed)
    started = time.monotonic()
    last_sample = started
    while time.monotonic()-started<seconds:
        left,top = max(bx,x-72),max(by,y-72)
        right,bottom = min(bx+bw,x+w+72),min(by+bh,y+h+72)
        captured = capture((left,top,right-left,bottom-top))
        frame = rgb(captured)
        hits = masked_hits(frame,previous,mask,.80,lambda:None)
        if not hits:
            tracked = follow(previous,mask,frame,x-left,y-top)
            if tracked is not None:
                hits.append((.89,*tracked))
        if not hits:
            # Fall back to agreeing contextual marks when a new pose changes
            # enough pixels to defeat whole-crop comparison.
            from recognition_articulated import marked_candidates
            from recognition_features import Model
            model = Model(Image.fromarray(previous))
            model.foreground_mask = mask
            for hit in marked_candidates(captured,'seed',model,.90,(.5,.5),lambda:None,None):
                cx,cy,cw,ch = hit['box']
                px,py = round(cx+(cw-w)/2),round(cy+(ch-h)/2)
                if 0<=px<=frame.shape[1]-w and 0<=py<=frame.shape[0]-h:
                    hits.append((hit['score'],px,py))
        hits.sort(reverse=True)
        if hits:
            score,px,py = hits[0]
            ambiguous = any(score-other<=.02 and (abs(px-u)>w/2 or abs(py-v)>h/2)
                            for other,u,v in hits[1:])
            if not ambiguous:
                x,y = left+px,top+py
                current = frame[py:py+h,px:px+w].copy()
                now = time.monotonic()
                if (len(samples)<32 and now-last_sample>=.065 and score>=.88
                        and cv2.absdiff(rgb(samples[-1][0]),current)[mask!=0].mean()>7):
                    appearance = Image.fromarray(current)
                    try:
                        sample_mask = foreground(appearance)
                    except ValueError:
                        sample_mask = None
                    if sample_mask is not None and (sample_mask & mask).sum() >= .38*(sample_mask|mask).sum():
                        samples.append((appearance,sample_mask,(x,y,w,h)))
                        mask = sample_mask
                        last_sample = now
                previous = current
        time.sleep(.025)
    return select_appearances(samples)
