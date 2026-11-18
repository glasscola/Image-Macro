"""Infer an optional candidate scale from near-rectangular outlines."""
import cv2
import numpy as np


def outlines(gray):
    edge=cv2.Canny(gray,40,100)
    contours,_=cv2.findContours(edge,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    boxes=set()
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if min(w,h)<10 or cv2.contourArea(contour)<.74*w*h:
            continue
        boxes.add((x,y,w,h))
    return sorted(boxes)


def outline_candidates(screen,model,check,limit=36):
    if min(model.gray.shape)<16:
        return [],False
    refs=[b for b in outlines(model.gray)
          if b[2]>=.83*model.width and b[3]>=.74*model.height]
    if not refs:
        return [],False
    outer=max(refs,key=lambda b:b[2]*b[3])
    check()
    if not hasattr(screen,'outlines'):
        screen.outlines=outlines(screen.gray)
    candidates=[]
    seen=set()
    ref=cv2.resize(model.gray,(20,10),interpolation=cv2.INTER_AREA)
    refs=(outer,(0,0,model.width,model.height))
    for x,y,w,h in screen.outlines:
        for x0,y0,w0,h0 in refs:
            sx,sy=w/w0,h/h0
            if not .58<=sx<=2.15 or abs(sx-sy)>.09*max(sx,sy):
                continue
            width,height=round(model.width*sx),round(model.height*sy)
            left,top=x-round(x0*sx),y-round(y0*sy)
            box=left,top,width,height
            if box in seen:
                continue
            seen.add(box)
            if left<0 or top<0 or left+width>screen.gray.shape[1] or top+height>screen.gray.shape[0]:
                continue
            area=screen.gray[top:top+height,left:left+width]
            small=cv2.resize(area,(20,10),interpolation=cv2.INTER_AREA)
            score=float(cv2.matchTemplate(small,ref,cv2.TM_CCOEFF_NORMED)[0,0])
            if score>=.64:
                candidates.append((score,*box))
    candidates.sort(reverse=True)
    return candidates[:limit],len(candidates)>limit


def aligned_detail(target,observed,threshold):
    """Tolerate a one-pixel glyph shift while keeping local detail gates."""
    h,w=target.shape
    gh,gw=max(6,h//4),max(8,w//8)
    if min(h,w)<16:
        return None
    a=cv2.GaussianBlur(target,(0,0),.8)
    b=cv2.GaussianBlur(observed,(0,0),.8)
    scores=[]
    for y in range(h//4,3*h//4-gh+1,max(3,h//10)):
        for x in range(w//15,w-w//15-gw+1,max(3,w//25)):
            patch=a[y:y+gh,x:x+gw]
            if patch.std()<10:
                continue
            near=b[max(0,y-1):y+gh+2,max(0,x-1):x+gw+2]
            scores.append(float(cv2.matchTemplate(near,patch,cv2.TM_CCOEFF_NORMED).max()))
    if len(scores)<7 or min(scores) < .65 or np.percentile(scores,15)<.80:
        return None
    a=cv2.GaussianBlur(target,(0,0),1.25)
    b=cv2.GaussianBlur(observed,(0,0),1.25)
    structure=float(cv2.matchTemplate(b,a,cv2.TM_CCOEFF_NORMED)[0,0])
    if structure < max(.84,threshold-.025):
        return None
    return min(1.,structure+.025)
