"""Rescale without relying on a rectangular outline, and verify text by stroke."""
import cv2
import numpy as np
from recognition_search import response, peaks


def color_boxes(pixels,color,tolerance=5):
    lo=np.maximum(0,np.asarray(color,dtype=np.int16)-tolerance).astype(np.uint8)
    hi=np.minimum(255,np.asarray(color,dtype=np.int16)+tolerance).astype(np.uint8)
    mask=cv2.inRange(pixels,lo,hi)
    if not mask.any() or mask.all():
        return [],bool(mask.all())
    _,_,regions,_=cv2.connectedComponentsWithStats(mask,connectivity=4)
    return regions[1:],False


def proportional(w,h,model,scales,adaptive):
    if adaptive:
        scale=(w/model.width+h/model.height)/2
        return .6<=scale<=2.1 and abs(w-model.width*scale)<=max(1,.025*w) and abs(h-model.height*scale)<=max(1,.025*h)
    return any(abs(w-model.width*s)<=1 and abs(h-model.height*s)<=1 for s in scales)


def background(pixels):
    border=np.concatenate((pixels[0],pixels[-1],pixels[1:-1,0],pixels[1:-1,-1]))
    color=np.median(border,axis=0).astype(np.uint8)
    return color if (np.abs(border.astype(np.int16)-color).max(axis=1)<=5).mean()>=.98 else None


def glyphs(pixels,color,*,split=True,ink=42):
    diff=np.abs(pixels.astype(np.int16)-color).max(axis=2)
    mask=(diff>=ink).astype(np.uint8)
    if mask.mean()<=.02 or mask.mean()>.38:
        return []
    columns=(mask.any(axis=0)).astype(np.int8)
    bounds=np.flatnonzero(np.diff(np.pad(columns,(1,1))))
    result=[]
    for left,right in zip(bounds[::2],bounds[1::2]):
        piece=mask[:,left:right]
        rows=np.flatnonzero(piece.any(axis=1))
        if right-left<2 or len(rows)<4 or piece.sum()<10:
            return []
        piece=piece[rows[0]:rows[-1]+1]
        h,w=piece.shape
        if split and w/h>1.17:
            lo,hi=round(w*.32),round(w*.68)
            projection=piece.sum(axis=0)
            local=projection[lo:hi]
            cut=lo+int(np.argmin(local)) if len(local) else 0
            if cut>=3 and w-cut>=3 and projection[cut]<=max(2,h*.18):
                for part in (piece[:,:cut],piece[:,cut:]):
                    ys,xs=np.nonzero(part)
                    if ys.size:
                        result.append(part[ys.min():ys.max()+1,xs.min():xs.max()+1])
                continue
        result.append(piece)
    return result


def compare_glyphs(reference,patch,color,threshold,*,split=True,ink=42):
    observed=glyphs(patch,color,split=split,ink=ink)
    if len(reference)<4 or len(reference)!=len(observed):
        return None
    scores=[]
    for a,b in zip(reference,observed):
        ah,aw=a.shape
        bh,bw=b.shape
        if abs((aw/ah)/(bw/bh)-1)>.47:
            return None
        aw=max(3,round(aw/ah*26))
        bw=max(3,round(bw/bh*26))
        width=max(aw,bw)+8
        def normalized(im,w):
            sign=cv2.resize(im.astype(np.float32),(w,26),interpolation=cv2.INTER_LINEAR)
            area=np.zeros((32,width),np.float32)
            off=(width-w)//2
            area[3:29,off:off+w]=sign
            return area
        an,bn=normalized(a,aw),normalized(b,bw)
        core=an[2:-2,2:-2]
        score=float(cv2.matchTemplate(bn,core,cv2.TM_CCORR_NORMED).max())
        scores.append(score)
    if min(scores)<max(.80,threshold-.09) or np.mean(scores)<max(.87,threshold-.03):
        return None
    return float(np.mean(scores))


def text_variants(pixels,color):
    modes=((True,42),(False,42),(True,84),(True,128),(True,163))
    return [(glyphs(pixels,color,split=split,ink=ink),split,ink) for split,ink in modes]


def verify_text(references,patch,color,threshold):
    for reference,split,ink in references:
        score=compare_glyphs(reference,patch,color,threshold,split=split,ink=ink)
        if score is not None:
            return score
    return None


def glyph_candidates(screen,model,threshold,check):
    color=background(model.pixels)
    if color is None:
        return []
    reference=glyphs(model.pixels,color)
    if len(reference)<4:
        return []
    references=text_variants(model.pixels,color)
    check()
    boxes,_=color_boxes(screen.pixels,color)
    matches=[]
    for x,y,w,h,count in boxes:
        if count<.60*w*h or not proportional(w,h,model,(),True):
            continue
        patch=screen.pixels[y:y+h,x:x+w]
        score=verify_text(references,patch,color,threshold)
        if score is not None:
            matches.append((score,int(x),int(y),int(w),int(h)))
    return matches


def wide_candidates(screen,model,threshold,check):
    """Coarse scale grid, followed by a native-pixel geometry refinement."""
    if min(model.width,model.height)<26:
        return []
    color=background(model.pixels)
    if color is not None and len(glyphs(model.pixels,color))>=4:
        # If the text channel was unable to verify each glyph, do not
        # accept a weaker whole-image similarity as evidence.
        return []
    factor=8 if min(model.width,model.height)>=105 else 4
    coarse=screen.coarse_gray(factor)
    proposals=[]
    for i in range(13,39):
        check()
        s=i/20
        w,h=round(model.width*s),round(model.height*s)
        cw,ch=round(w/factor),round(h/factor)
        if min(cw,ch)<5 or cw>coarse.shape[1] or ch>coarse.shape[0]:
            continue
        needle=cv2.resize(model.gray,(cw,ch),interpolation=cv2.INTER_AREA)
        scores=response(coarse,needle)
        if scores.size==0:
            continue
        positions,_=peaks(scores.copy(),cw,ch,.68,3,check)
        proposals.extend((float(scores[y,x]),x*factor+w/2,y*factor+h/2,s)
                          for x,y in positions)
    proposals.sort(reverse=True)
    groups=[]
    for score,cx,cy,s in proposals:
        close=next((items for items in groups if abs(items[0][1]-cx)<model.width*s*.20
                    and abs(items[0][2]-cy)<model.height*s*.20),None)
        if close is None:
            if len(groups)<6:
                groups.append([(score,cx,cy,s)])
        elif len(close)<2:
            close.append((score,cx,cy,s))
    found=[]
    for group in groups:
        best=None
        for _,cx,cy,s in group:
            radius=factor+4
            # Search the scale on the small local window. Expensive native
            # detail checks are only applied to the leading local variants.
            look=[]
            for shift in range(-5,6):
                check()
                scale=s+shift*.005
                if abs(scale-1.)<.035:
                    continue
                w,h=round(model.width*scale),round(model.height*scale)
                x,y=round(cx-w/2),round(cy-h/2)
                a,b=max(0,x-radius),max(0,y-radius)
                c,d=min(screen.gray.shape[1],x+w+radius),min(screen.gray.shape[0],y+h+radius)
                if c-a<w or d-b<h:
                    continue
                pixels,gray=model.variant(w,h)
                _,raw,_,(dx,dy)=cv2.minMaxLoc(response(screen.gray[b:d,a:c],gray))
                if raw>=max(.66,threshold-.13):
                    look.append((raw,a+dx,b+dy,w,h))
            for raw,x,y,w,h in sorted(look,reverse=True)[:3]:
                from recognition_verify import verify
                pixels,gray=model.variant(w,h)
                hit=verify(screen,pixels,gray,x,y,0,threshold,True)
                if hit and hit[0]+1e-6>=threshold:
                    candidate=(hit[0],hit[1],hit[2],w,h)
                    if best is None or candidate>best:
                        best=candidate
        if best is not None:
            found.append(best)
    return found


def quick_scaled_candidates(screen,model,scales,threshold,check):
    """Propose common scales cheaply and verify them in the original pixels."""
    from recognition_verify import verify
    from recognition_silhouette import verify_silhouette

    limit = max(.94,threshold)
    found, limited = [], False
    sizes = dict.fromkeys((round(model.width*s),round(model.height*s)) for s in scales)
    for w,h in sizes:
        check()
        if (w,h)==(model.width,model.height):
            continue
        preferred = 8 if min(w,h)>=104 else 4
        factor = preferred if screen.gray.size>=500_000 else 2
        if min(w,h)<6*factor:
            factor=2
        if min(w,h)<12:
            continue
        coarse = screen.coarse_gray(factor)
        cw,ch=w//factor,h//factor
        if min(cw,ch)<6 or cw>coarse.shape[1] or ch>coarse.shape[0]:
            continue
        pixels,gray=model.variant(w,h)
        needle=cv2.resize(gray,(cw,ch),interpolation=cv2.INTER_AREA)
        coords,pending=peaks(response(coarse,needle),cw,ch,.81,5,check)
        limited |= pending
        for x,y in coords:
            hit=verify(screen,pixels,gray,x*factor,y*factor,factor+2,limit,True)
            if hit is None:
                continue
            score,left,top = hit
            if score<limit and score>=threshold and model.silhouette is not None:
                # A short, reduced label can lose a pixel at a stroke edge.
                # Require independent agreement of the foreground shape.
                patch = screen.pixels[top:top+h,left:left+w]
                ratio = min(w/model.width,h/model.height)
                shape = verify_silhouette(patch,model.silhouette,threshold,ratio*.89,ratio*1.11)
                if shape is not None:
                    score = min(limit,max(score,shape[0]))
            if score>=limit:
                found.append((score,left,top,w,h))
        # A strictly verified size is enough for this pass. Continue checking
        # other positions at this size before returning to resolve duplicates.
        if found and max(item[0] for item in found)>=.985:
            break
    return found, limited


def small_size_candidates(screen,model,threshold,check):
    """A few common display ratios whose rounded dimensions matter on icons."""
    if not 10<=min(model.width,model.height)<24:
        return []
    from recognition_verify import verify
    matches=[]
    sizes=set()
    for scale in (1.3333,1.625,1.65,1.6667,.6667,1.875):
        check()
        w,h=round(model.width*scale),round(model.height*scale)
        if (w,h) in sizes or w>screen.gray.shape[1] or h>screen.gray.shape[0]:
            continue
        sizes.add((w,h))
        pixels,gray=model.variant(w,h)
        coords,limited=peaks(response(screen.gray,gray),w,h,max(.96,threshold),12,check)
        if limited:
            continue
        for x,y in coords:
            hit=verify(screen,pixels,gray,x,y,0,threshold,True)
            if hit and hit[0]>=max(.965,threshold):
                matches.append((hit[0],hit[1],hit[2],w,h))
    return matches



def exact_anchors(frame,model,check,budget=1,*,maximum=80, candidate_limit=800):
    """Find near-identical native sizes by intersecting a few color anchors."""
    if model.flat or min(model.width,model.height)<4 or max(model.width,model.height)>maximum:
        return [],False
    pixels=np.asarray(frame)
    h,w=model.pixels.shape[:2]
    rows,cols=pixels.shape[0]-h+1,pixels.shape[1]-w+1
    if rows<=0 or cols<=0:
        return [],False
    anchors=model.anchor_colors
    grid=None
    for y,x,low,high in anchors:
        check()
        allowed=cv2.inRange(pixels[y:y+rows,x:x+cols],low,high)
        grid=allowed if grid is None else cv2.bitwise_and(grid,allowed)
        remaining=cv2.countNonZero(grid)
        if not remaining:
            return [],False
        if remaining<=min(8,candidate_limit*budget):
            break
    expected=cv2.countNonZero(grid)
    if expected>candidate_limit*budget:
        return [],True
    positions=cv2.findNonZero(grid)
    matches=[]
    for x,y in positions.reshape(-1,2):
        check()
        patch=pixels[y:y+h,x:x+w]
        if cv2.norm(patch,model.pixels,cv2.NORM_INF)<=5:
            matches.append((1.,int(x),int(y),w,h))
    return matches,False


def small_anchor_candidates(pixels, model, scales, check, budget):
    """Verify common icon and label sizes in the original screen pixels."""
    from PIL import Image
    sizes = dict.fromkeys((max(4,round(model.width*s)),max(4,round(model.height*s)))
                          for s in scales if s != 1)
    found, limited = [], False
    for w,h in sizes:
        if (w,h)==(model.width,model.height):
            continue
        if h>pixels.shape[0] or w>pixels.shape[1]:
            continue
        variant = model.anchor_variant(w,h,Image.Resampling.LANCZOS)
        hits, pending = exact_anchors(pixels,variant,check,budget,maximum=max(w,h),
                                      candidate_limit=24)
        found.extend(hits)
        limited |= pending
    return found, limited


def tiny_pixels(model,width,height):
    from PIL import Image
    return np.asarray(Image.fromarray(model.pixels).resize((width,height),Image.Resampling.BICUBIC))


def tiny_size_candidates(screen,model,check,scales,adaptive):
    if min(model.width,model.height)>=12:
        return []
    ordered=list(scales)
    if adaptive:
        ordered.extend((.72,.83,1.17,1.33,1.65,.65,.75,1.25,1.5,1.75))
        ordered.extend(i/40 for i in range(26,75))
    sizes=dict.fromkeys((max(4,round(model.width*s)),max(4,round(model.height*s))) for s in ordered)
    results=[]
    for w,h in sizes:
        if w>screen.gray.shape[1] or h>screen.gray.shape[0]:
            continue
        check()
        from PIL import Image
        from recognition_features import Model
        pixels=tiny_pixels(model,w,h)
        variant=Model(Image.fromarray(pixels))
        candidates,limited=exact_anchors(screen.pixels,variant,check)
        if not limited:
            results.extend(candidates)
    return results
