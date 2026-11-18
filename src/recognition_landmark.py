"""Compare the shape of a selected colored mark and the color around it."""
import cv2
import numpy as np


def contour_mask(pixels,color,tolerance):
    c=np.asarray(color,dtype=np.int16)
    return cv2.inRange(pixels,np.maximum(0,c-tolerance).astype(np.uint8),
                       np.minimum(255,c+tolerance).astype(np.uint8))


def components(mask):
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask,connectivity=8)
    for i in range(1,count):
        x,y,w,h,area=map(int,stats[i])
        if w<9 or h<9 or area<50:
            continue
        yield x,y,w,h,area,(labels[y:y+h,x:x+w]==i).astype(np.uint8)


def signature(shape):
    contours,_=cv2.findContours(shape,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    return max(contours,key=cv2.contourArea) if contours else None


def ring_pixels(frame,shape,x,y,w,h):
    n=max(3,round(min(w,h)*.12))
    a,b=max(0,x-n),max(0,y-n)
    c,d=min(frame.shape[1],x+w+n),min(frame.shape[0],y+h+n)
    local=np.zeros((d-b,c-a),np.uint8)
    local[y-b:y-b+h,x-a:x-a+w]=shape
    outer=cv2.dilate(local,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(n*2+1,n*2+1)))
    # Exclude compression fringes bordering the mark.
    inner=cv2.dilate(local,np.ones((3,3),np.uint8))
    return frame[b:d,a:c][outer>inner]


def make_landmark(model):
    p=model.pixels
    h,w=p.shape[:2]
    if min(h,w)<24:
        return None
    cx,cy=w//2,h//2
    color=np.median(p[cy-2:cy+3,cx-2:cx+3].reshape(-1,3),axis=0)
    mask=contour_mask(p,color,17)
    for x,y,bw,bh,area,shape in components(mask):
        if not (x<=cx<x+bw and y<=cy<y+bh and shape[cy-y,cx-x]):
            continue
        if x<=1 or y<=1 or x+bw>=w-1 or y+bh>=h-1 or area<.035*w*h:
            return None
        ring=ring_pixels(p,shape,x,y,bw,bh)
        if len(ring)<45:
            return None
        surround=np.median(ring,axis=0)
        if np.max(np.abs(surround-color))<37:
            return None
        consistent=(np.max(np.abs(ring.astype(np.int16)-surround),axis=1)<=32).mean()
        if consistent<.48:
            return None
        return color,surround,(x,y,bw,bh),area,signature(shape)
    return None


def landmark_model(model):
    if not hasattr(model,'_color_landmark'):
        model._color_landmark=make_landmark(model)
    return model._color_landmark


def landmark_candidates(frame,templates,threshold,offset,check,near=None):
    pixels=np.asarray(frame)
    result=[]
    for uid,model in templates:
        ref=landmark_model(model)
        if ref is None:
            continue
        color,surround,box,area,contour=ref
        if contour is None:
            continue
        rx,ry,rw,rh=box
        check()
        mask=contour_mask(pixels,color,19)
        for x,y,w,h,count,shape in components(mask):
            scale=(count/area)**.5
            if not .45<=scale<=2.3:
                continue
            if abs(max(w,h)/min(w,h)-max(rw,rh)/min(rw,rh))>.55:
                continue
            # Match proportions independent of clockwise/counterclockwise rotation.
            other=signature(shape)
            if other is None:
                continue
            distance=cv2.matchShapes(contour,other,cv2.CONTOURS_MATCH_I1,0)
            if distance>.22:
                continue
            ring=ring_pixels(pixels,shape,x,y,w,h)
            if len(ring)<40:
                continue
            context=(np.max(np.abs(ring.astype(np.int16)-surround),axis=1)<=31).mean()
            if context<.63:
                continue
            # The crop center is on the colored mark; retain that physical
            # center across rotations. Apply any user offset from the mark.
            cx,cy=x+w/2,y+h/2
            if near and (abs(cx-near[0])>near[2] or abs(cy-near[1])>near[2]):
                continue
            px=round(cx+(offset[0]-.5)*w)
            py=round(cy+(offset[1]-.5)*h)
            px=min(x+w-1,max(x,px))
            py=min(y+h-1,max(y,py))
            score=float(1.-distance*.8-(1.-context)*.10-min(.045,abs(np.log(scale))*.048))
            if score<threshold:
                continue
            result.append(dict(score=score,box=(x,y,w,h),point=(px,py),
                               scale=scale,asset=uid,method='landmark'))
    return result
