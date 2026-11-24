"""Low-latency scan for screenshots of a moving, registered target."""
import cv2
from recognition_features import Screen
from recognition_search import response
from recognition_verify import verify
from recognition_landmark import landmark_candidates, landmark_model
from recognition_articulated import marked_candidates, recorded_marks
from motion_features import texture_candidates
from motion_capture import masked_hits


def moving_matches(frame,templates,threshold,offset,check,*,near=None,scales=(1.,),landmark=False):
    if landmark:
        found_candidates=landmark_candidates(frame,templates,threshold,offset,check,near)
    else:
        found_candidates=[]
    screen=None if landmark else Screen(frame)
    recorded = [(name,model) for name,model in templates if hasattr(model,'foreground_mask')]
    if recorded and not landmark:
        deferred = []
        for name,model in recorded:
            mark = landmark_model(model) if (
                model.width>=80 and model.height>=80) else []
            centered = bool(mark and min(mark[2][2:])>=20)
            landmarks = []
            if centered or max(model.width,model.height)>=160:
                landmarks = marked_candidates(frame,name,model,threshold,offset,check,near)
                found_candidates.extend(landmarks)
            if not landmarks and (centered or max(model.width,model.height)<160 or len(scales)>2
                                  or len(recorded_marks(model))<3):
                deferred.append((name,model))
        for scale in scales:
            if found_candidates:
                break
            for name,model in deferred:
                w,h = round(model.width*scale),round(model.height*scale)
                if min(w,h)<8 or w>frame.width or h>frame.height:
                    continue
                pixels,_ = model.variant(w,h)
                mask = cv2.resize(model.foreground_mask,(w,h),interpolation=cv2.INTER_NEAREST)
                for score,x,y in masked_hits(screen.pixels,pixels,mask,threshold,check):
                    if near and (abs(x+w/2-near[0])>near[2] or abs(y+h/2-near[1])>near[2]):
                        continue
                    px,py = min(w-1,round(w*offset[0])),min(h-1,round(h*offset[1]))
                    if not mask[py,px]:
                        _,_,_,closest = cv2.minMaxLoc(cv2.distanceTransform(mask,cv2.DIST_L2,3))
                        px,py = closest
                    found_candidates.append(dict(score=score,box=(x,y,w,h),point=(x+px,y+py),
                                                 scale=scale,asset=name,method='recorded_motion'))
        if not found_candidates or max(hit['score'] for hit in found_candidates)<.985:
            recovered = [hit for name,model in deferred
                         if max(model.width,model.height)<160
                         for hit in marked_candidates(frame,name,model,threshold,offset,check,near)]
            if recovered:
                found_candidates = recovered
        if not found_candidates and (near or len(scales)>2):
            for hit in texture_candidates(frame,recorded,threshold,offset,check):
                x,y,w,h = hit['box']
                if not near or (abs(x+w/2-near[0])<=near[2] and abs(y+h/2-near[1])<=near[2]):
                    found_candidates.append(hit)
    for name,model in ([] if landmark else templates):
        if model.flat or hasattr(model,'foreground_mask'):
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


def search_appearances(frame, templates, threshold, offset, check, *, near=None,
                       scales=(1.,), landmark=False):
    """Search a primary appearance first, then recover with the recorded poses."""
    options = dict(near=near, scales=scales, landmark=landmark)
    primary = moving_matches(frame, templates[:1], threshold, offset, check, **options)
    if len(templates) == 1 or primary['status'] == 'ambiguous':
        return primary
    if primary['found'] and (near is not None or primary['score'] >= max(.92, threshold)):
        return primary
    alternatives = moving_matches(frame, templates[1:], threshold, offset, check, **options)
    if not primary['found']:
        return alternatives
    if alternatives['status'] == 'ambiguous':
        return alternatives
    if not alternatives['found']:
        return primary
    x,y,w,h = primary['box']
    a,b,c,d = alternatives['box']
    separated = (abs(a+c/2-x-w/2)>min(w,c)*.5 or abs(b+d/2-y-h/2)>min(h,d)*.5)
    if separated and abs(alternatives['score']-primary['score'])<=.025:
        return dict(primary,found=False,status='ambiguous',reason='움직이는 후보 여러 곳')
    return max((primary, alternatives),key=lambda hit:hit['score'])
