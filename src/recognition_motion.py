"""Low-latency scan for screenshots of a moving, registered target."""
import cv2
from recognition_features import Screen
from recognition_search import response
from recognition_verify import verify
from recognition_landmark import landmark_candidates


def moving_matches(frame,templates,threshold,offset,check,*,near=None,scales=(1.,),landmark=False):
    if landmark:
        found_candidates=landmark_candidates(frame,templates,threshold,offset,check,near)
    else:
        found_candidates=[]
    screen=None if landmark else Screen(frame)
    for name,model in ([] if landmark else templates):
        if model.flat:
            continue
        for scale in scales:
            check()
            w,h=round(model.width*scale),round(model.height*scale)
            if min(w,h)<8 or w>frame.width or h>frame.height:
                continue
            pixels,gray=model.variant(w,h)
            # A video viewport at its displayed size is the primary path.
            # For larger desktop frames, shortlist on a half-size image.
            factor=2 if frame.width*frame.height>750000 and min(w,h)>=32 else 1
            if factor==2:
                sample=screen.coarse_gray(2)
                target=cv2.resize(gray,(w//2,h//2),interpolation=cv2.INTER_AREA)
            else:
                sample,target=screen.gray,gray
            scores=response(sample,target)
            for _ in range(6):
                check()
                _,score,_,(x,y)=cv2.minMaxLoc(scores)
                limit=max(.46,threshold-.43) if factor==2 else max(.68,threshold-.14)
                if score<limit:
                    break
                rx,ry=max(1,w//(3*factor)),max(1,h//(3*factor))
                scores[max(0,y-ry):y+ry+1,max(0,x-rx):x+rx+1]=-1
                hit=verify(screen,pixels,gray,x*factor,y*factor,3 if factor==2 else 0,
                           threshold,(w,h)!=(model.width,model.height))
                if not hit or hit[0]+1e-6<threshold:
                    continue
                strength,px,py=hit
                if near and (abs(px+w/2-near[0])>near[2] or abs(py+h/2-near[1])>near[2]):
                    continue
                point=(px+min(w-1,round(w*offset[0])),py+min(h-1,round(h*offset[1])))
                found_candidates.append(dict(score=strength,box=(px,py,w,h),point=point,
                                             scale=scale,asset=name))
    if not found_candidates:
        return dict(found=False,status='not_found',score=0.,box=None,point=None,scale=1.,
                    reason='등록한 모습이 아직 확인되지 않음')
    found_candidates.sort(key=lambda c:c['score'],reverse=True)
    best=found_candidates[0]
    x,y,w,h=best['box']
    for other in found_candidates[1:]:
        a,b,c,d=other['box']
        if abs(a+c/2-x-w/2)>min(w,c)*.5 or abs(b+d/2-y-h/2)>min(h,d)*.5:
            if best['score']-other['score']<=.025:
                return dict(best,found=False,status='ambiguous',reason='움직이는 후보 여러 곳')
            break
    return dict(best,found=True,status='found',reason='발견')
