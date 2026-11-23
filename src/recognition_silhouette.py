"""Match flat-color lettering and shapes using the captured color palette."""
from typing import NamedTuple

import cv2
import numpy as np


class Silhouette(NamedTuple):
    width: int
    height: int
    mask: np.ndarray
    x: int
    y: int
    lower: tuple
    upper: tuple
    seed_lower: tuple
    seed_upper: tuple
    segments: tuple
    holes: int


def _mask(pixels, lower, upper):
    return cv2.inRange(pixels, lower, upper)


def _normalize(mask, width):
    return cv2.resize(mask, (width, 64), interpolation=cv2.INTER_AREA) >= 128


def _holes(mask):
    contours, hierarchy = cv2.findContours(mask.astype(np.uint8),cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return 0
    return sum(parent>=0 and cv2.contourArea(contour)>=24
               for contour,(_,_,_,parent) in zip(contours,hierarchy[0]))


def contradicts_silhouette(pixels, model, box):
    """Detect contradictory glyph detail in a plausible pixel-match candidate."""
    reference = model.silhouette
    if reference is None:
        return False
    x,y,w,h = box
    sx,sy = w/model.width,h/model.height
    margin_x = max(2,round(.12*reference.width*sx))
    margin_y = max(2,round(.12*reference.height*sy))
    x0 = x+max(0,round(reference.x*sx)-margin_x)
    y0 = y+max(0,round(reference.y*sy)-margin_y)
    x1 = x+min(w,round((reference.x+reference.width)*sx)+margin_x)
    y1 = y+min(h,round((reference.y+reference.height)*sy)+margin_y)
    if isinstance(pixels,np.ndarray):
        patch = pixels[y0:y1,x0:x1]
    else:
        patch = np.asarray(pixels.crop((x0,y0,x1,y1)).convert('RGB'))
    if not patch.size:
        return False
    ink = _mask(patch,reference.lower,reference.upper)
    left,top,width,height = cv2.boundingRect(ink)
    # A candidate can extend beyond a label onto a background that shares
    # its ink color. Remove edge-connected spill from the interior check.
    if (left==0 or top==0 or left+width==ink.shape[1] or top+height==ink.shape[0]):
        _, labels = cv2.connectedComponents(ink)
        edges = np.unique(np.concatenate((labels[0],labels[-1],labels[:,0],labels[:,-1])))
        if np.any(edges):
            ink[np.isin(labels,edges[edges!=0])] = 0
            left,top,width,height = cv2.boundingRect(ink)
    if min(width,height)<12:
        return False
    sx,sy = width/reference.width,height/reference.height
    if not .84 <= sx/sy <= 1.18:
        return False
    observed = _normalize(ink[top:top+height,left:left+width],reference.mask.shape[1])
    if _holes(observed) != reference.holes:
        return True
    for start,end in reference.segments:
        expected, actual = reference.mask[:,start:end], observed[:,start:end]
        if np.count_nonzero(expected & actual)<.58*np.count_nonzero(expected | actual):
            return True
    return False


def verify_silhouette(pixels, reference, threshold, minimum, maximum):
    ink = _mask(pixels, reference.lower, reference.upper)
    x,y,w,h = cv2.boundingRect(ink)
    if min(w,h)<7:
        return None
    sx,sy=w/reference.width,h/reference.height
    if not minimum <= sy <= maximum or not .91 <= sx/sy <= 1.10:
        return None
    normalized = reference.mask
    observed = _normalize(ink[y:y+h,x:x+w], normalized.shape[1])
    common = observed & normalized
    either = observed | normalized
    overlap = np.count_nonzero(common)
    union = np.count_nonzero(either)
    raw = overlap/union if union else 0.
    small_text = reference.height<=48 and reference.width>1.65*reference.height and h<=32
    if raw < (.57 if small_text else .74):
        return None
    # Downsampling can move antialiased edges by a pixel. Only tolerate
    # nearby stroke differences, and still reject a changed character.
    radius = min(3,max(2,round(64/h))) if small_text else 1
    kernel = np.ones((radius*2+1,radius*2+1), np.uint8)
    near_reference = cv2.dilate(normalized.astype(np.uint8),kernel).astype(bool)
    near_observed = cv2.dilate(observed.astype(np.uint8),kernel).astype(bool)
    explained = (observed & near_reference) | (normalized & near_observed)
    weight = .16 if small_text else .30
    score = weight*raw + (1-weight)*np.count_nonzero(explained)/union
    if score < max(.91,threshold):
        return None
    if _holes(observed) != reference.holes:
        return None
    for a,b in reference.segments:
        count = np.count_nonzero(either[:,a:b])
        if (np.count_nonzero(common[:,a:b]) < (.48 if small_text else .63)*count
                or np.count_nonzero(explained[:,a:b]) < max(.88,threshold-.04)*count):
            return None
    return score,x,y,w,h


def build_silhouette(pixels):
    border = np.concatenate((pixels[0], pixels[-1], pixels[1:-1,0], pixels[1:-1,-1]))
    background = np.median(border,axis=0).astype(np.int16)
    if (np.max(np.abs(border-background),axis=1)<=16).mean()<.62:
        return None
    sample = pixels[::2,::2].reshape(-1,3)
    distance = np.max(np.abs(sample-background),axis=1)
    peak = np.quantile(distance,.998)
    if peak<53:
        return None
    strong = sample[distance>=peak*.86]
    foreground = np.median(strong,axis=0).astype(np.int16)
    contrast = np.abs(foreground-background)
    if (np.max(np.abs(strong-foreground),axis=1)<=25).mean()<.82:
        return None
    tolerance = np.maximum(16,contrast*.50).astype(int)
    lower = tuple(map(int,np.maximum(0,foreground-tolerance)))
    upper = tuple(map(int,np.minimum(255,foreground+tolerance)))
    seed_tolerance = np.minimum(16,tolerance)
    seed_lower = tuple(map(int,np.maximum(0,foreground-seed_tolerance)))
    seed_upper = tuple(map(int,np.minimum(255,foreground+seed_tolerance)))
    mask = _mask(pixels,lower,upper)
    contrasted = np.count_nonzero(distance>=max(18,peak*.30))
    if np.count_nonzero(mask[::2,::2])<.66*contrasted:
        return None
    x, y, w, h = cv2.boundingRect(mask)
    if min(w,h)<8 or not np.any(mask==0):
        return None
    ink = mask[y:y+h, x:x+w]
    if not .10 <= np.count_nonzero(ink)/ink.size <= .82:
        return None
    # A button's frame can dominate text similarity. Let the existing
    # framed-button verifier check its internal glyphs instead.
    edges = (ink[0],ink[-1],ink[:,0],ink[:,-1])
    if all(np.count_nonzero(edge)>.80*edge.size for edge in edges):
        return None
    normalized = _normalize(ink,max(32,min(256,round(64*w/h))))
    bounds = np.flatnonzero(np.diff(np.pad(normalized.any(axis=0).astype(np.int8),1)))
    segments = tuple((a,b) for a,b in zip(bounds[::2],bounds[1::2]) if b-a>=4)
    return Silhouette(w,h,normalized,x,y,lower,upper,seed_lower,seed_upper,segments,_holes(normalized))


def silhouette_candidates(pixels, reference, threshold, check, minimum, maximum):
    ref_w, ref_h = reference.width, reference.height
    height,width = pixels.shape[:2]
    factor = 2 if height*width > 600_000 and min(ref_w,ref_h)*minimum>=12 else 1
    reduced = pixels if factor == 1 else cv2.resize(
        pixels, (width//2, height//2), interpolation=cv2.INTER_AREA)
    mask = _mask(reduced,reference.seed_lower,reference.seed_upper)
    if not mask.any() or mask.all():
        return []
    # Keep disconnected characters and punctuation in one candidate.
    gap = .50 if ref_h<=48 else .32
    kx = max(3, min(61, round(min(ref_h*gap, ref_w*.40)/factor) | 1))
    ky = max(3, min(53, round(ref_h*.22/factor) | 1))
    joined = cv2.dilate(mask, np.ones((ky, kx), np.uint8))
    _, _, components, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    found = []
    for component in components[1:]:
        check()
        x,y,w,h,_ = map(int,component)
        estimated_w = max(1, w-kx+1)*factor
        estimated_h = max(1, h-ky+1)*factor
        if not .78*minimum*ref_w <= estimated_w <= 1.17*maximum*ref_w:
            continue
        if not .78*minimum*ref_h <= estimated_h <= 1.17*maximum*ref_h:
            continue
        left = max(0,(x+kx//2)*factor-3)
        top = max(0,(y+ky//2)*factor-3)
        right = min(width,(x+w-kx//2)*factor+3)
        bottom = min(height,(y+h-ky//2)*factor+3)
        if left >= right or top >= bottom:
            continue
        hit = verify_silhouette(pixels[top:bottom,left:right],reference,threshold,minimum,maximum)
        if hit is not None:
            score,dx,dy,ink_width,ink_height = hit
            found.append((score,left+dx,top+dy,ink_width,ink_height))
    return found
