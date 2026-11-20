"""Fast pixel anchors and bounded pose recovery for registered screen images."""
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image

from recognition_features import Screen
from recognition_search import response
from recognition_verify import verify


def position(score,x,y,w,h,scale,offset,angle=0):
    return dict(score=score,box=(x,y,w,h),scale=scale,angle=angle,
                point=(x+min(w-1,round(w*offset[0])),y+min(h-1,round(h*offset[1]))))


def rotate(image, angle):
    if not angle:
        return image
    h,w=image.shape[:2]
    matrix=cv2.getRotationMatrix2D(((w-1)/2,(h-1)/2),angle,1.)
    return cv2.warpAffine(image,matrix,(w,h),borderMode=cv2.BORDER_REPLICATE)


@lru_cache(maxsize=12)
def lanczos_pixels(model, width, height):
    return np.asarray(Image.fromarray(model.pixels).resize((width,height),Image.Resampling.LANCZOS))


def verify_scaled_pixels(screen,model,tw,th,x,y,radius):
    h,w=screen.gray.shape
    x0,y0=max(0,x-radius),max(0,y-radius)
    x1,y1=min(w,x+tw+radius),min(h,y+th+radius)
    if x1-x0<tw or y1-y0<th:
        return None
    target=lanczos_pixels(model,tw,th)
    gray=cv2.cvtColor(target,cv2.COLOR_RGB2GRAY)
    patch=screen.gray[y0:y1,x0:x1]
    _,value,_,(dx,dy)=cv2.minMaxLoc(response(patch,gray))
    if value<.985:
        return None
    px,py=x0+dx,y0+dy
    seen=screen.pixels[py:py+th,px:px+tw]
    if cv2.norm(seen,target,cv2.NORM_INF)>8:
        return None
    return value,px,py


def pose_candidates(frame,model,threshold,offset,check,*,local=None):
    if model.flat or min(model.width,model.height)<24:
        return []
    screen=Screen(frame)
    h,w=screen.gray.shape
    lo,hi,_,_=cv2.minMaxLoc(screen.gray)
    if hi-lo<8:
        return []
    stride=1 if local else max(2, round(max(w,h)/320))
    small=cv2.resize(screen.gray,(w//stride,h//stride),interpolation=cv2.INTER_AREA)
    hits=[]
    poses = [local] if local else [(s,0) for s in (.48,.5,.54,.65,.75,.8,.9,1.,1.15,1.35,1.6)]
    if not local:
        poses.extend((s,a) for s in (1.,.5,.8) for a in (-12,12,-6,6))
    if not local and min(model.width,model.height)<160:
        poses=[(s,0) for s in (.5,.75,.8,.9,1.1,1.25,1.33)]
        stride=min(stride,max(1,min(model.width,model.height)//15))
        small=cv2.resize(screen.gray,(w//stride,h//stride),interpolation=cv2.INTER_AREA)
    for scale,angle in poses:
        check()
        if angle and hits:
            break
        tw,th=round(model.width*scale),round(model.height*scale)
        if min(tw,th)<24 or tw>w or th>h:
            continue
        pixels,gray=model.variant(tw,th)
        gray=rotate(gray,angle)
        pixels=rotate(pixels,angle)
        reduced=cv2.resize(gray,(tw//stride,th//stride),interpolation=cv2.INTER_AREA)
        scores=response(small,reduced)
        for _ in range(3):
            _,value,_,(x,y)=cv2.minMaxLoc(scores)
            if value<max(.68,threshold-.17):
                break
            scores[max(0,y-th//(4*stride)):y+th//(4*stride)+1,
                   max(0,x-tw//(4*stride)):x+tw//(4*stride)+1]=-1
            px,py=round(x*w/small.shape[1]),round(y*h/small.shape[0])
            hit=None
            if not angle and scale!=1:
                hit=verify_scaled_pixels(screen,model,tw,th,px,py,stride+2)
            if hit is None:
                hit=verify(screen,pixels,gray,px,py,stride+2,threshold,
                           (tw,th)!=(model.width,model.height))
            if hit and hit[0]>=threshold:
                hits.append(position(*hit,tw,th,scale,offset,angle))
    return hits
