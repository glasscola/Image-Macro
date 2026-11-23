"""Public recognition API and monitor coordinate handling."""
import cv2
import numpy as np
from recognition_features import Model, Screen, rgb
from recognition_search import orientation_candidates, pixel_candidates
from recognition_verify import verify
from recognition_pose import pose_candidates
from recognition_outline import outline_candidates
from recognition_silhouette import contradicts_silhouette, silhouette_candidates, verify_silhouette
from recognition_multiscale import (background,color_boxes,compare_glyphs,glyphs,
                                    exact_anchors,glyph_candidates,proportional,quick_scaled_candidates,small_anchor_candidates,
                                    small_size_candidates,text_variants,tiny_pixels,tiny_size_candidates,verify_text,wide_candidates)


def scale_candidates(configured, source_dpi=96, target_dpi=96):
    scales = list(configured)
    if source_dpi:
        ratio = target_dpi/source_dpi
        scales.extend(ratio*(1+i*.025) for i in range(-2,3))
    return sorted({round(s,5) for s in scales if .2 <= s <= 4})


def _result(status, reason, best=None, second=0):
    return dict(best or dict(score=0., box=None, point=None, scale=1),
                found=status == 'found', status=status, reason=reason, second=second)


def _resolve(matches, incomplete):
    if not matches:
        if incomplete:
            return _result('incomplete', '후보 검사 한도 도달')
        return _result('not_found', '일치하는 이미지 없음')
    matches.sort(key=lambda r:r['score'], reverse=True)
    best = matches[0]
    x,y,w,h = best['box']
    for other in matches[1:]:
        a,b,c,d = other['box']
        if abs(a+c/2-x-w/2) > min(w,c)/2 or abs(b+d/2-y-h/2) > min(h,d)/2:
            if best['score'] - other['score'] <= .025:
                where = '여러 모니터에서 ' if best.get('monitor') != other.get('monitor') else ''
                return _result('ambiguous', where+'후보 여러 개', best, other['score'])
            break
    if incomplete:
        return _result('incomplete', '후보 검사 한도 도달', best)
    return _result('found', '발견', best)


DEFAULT_SCALES = (.8,.9,1.,1.1,1.2)


def _outline_scan(screen,model,threshold,offset,check,budget):
    outlines, outline_limited=outline_candidates(screen,model,check,limit=20*budget)
    verified=[]
    for _,x,y,w,h in outlines:
        candidates=[]
        for width,height in dict.fromkeys((w+dx,h+dy) for dx,dy in
                                          ((0,0),(-1,0),(1,0),(0,-1),(0,1),
                                           (-1,-1),(1,1),(-2,0),(2,0))):
            sx,sy=width/model.width,height/model.height
            if abs(sx-1)<.04 or abs(sx-sy)>.04*max(sx,sy):
                continue
            check()
            pixels, gray=model.variant(width,height)
            hit=verify(screen,pixels,gray,x,y,4,threshold,True,aligned=True)
            if hit is None or hit[0]+1e-6<threshold:
                continue
            score,px,py=hit
            point=(px+min(width-1,round(width*offset[0])),py+min(height-1,round(height*offset[1])))
            candidates.append(dict(score=score,box=(px,py,width,height),point=point,scale=width/model.width))
        if candidates:
            verified.append(max(candidates,key=lambda r:r['score']))
    return _resolve(verified,outline_limited)


def pose_matches(items,model,offset,method=None):
    return [dict(score=score,box=(x,y,w,h),
                 point=(x+min(w-1,round(w*offset[0])),y+min(h-1,round(h*offset[1]))),
                 scale=w/model.width, method=method) for score,x,y,w,h in items]


def silhouette_scan(pixels, model, threshold, scales, offset, check, adaptive):
    if model.silhouette is None:
        return _result('not_found','색상 윤곽 후보 없음')
    low, high = (.30, 2.5) if adaptive else (min(scales)*.95, max(scales)*1.05)
    candidates = silhouette_candidates(pixels,model.silhouette,threshold,check,low,high)
    return _resolve([silhouette_match(hit,model,offset) for hit in candidates],False)


def silhouette_match(hit,model,offset):
    score,x,y,w,h=hit
    reference=model.silhouette
    sx,sy=w/reference.width,h/reference.height
    px=min(model.width-1,round(model.width*offset[0]))-reference.x
    py=min(model.height-1,round(model.height*offset[1]))-reference.y
    return dict(score=score,box=(x,y,w,h),point=(x+round(px*sx),y+round(py*sy)),
                scale=sx,method='silhouette')


def independent_scan(screen,model,threshold,offset,check, *, wide=False):
    glyph=glyph_candidates(screen,model,threshold,check)
    if glyph:
        return _resolve(pose_matches(glyph,model,offset,'glyph'),False)
    if wide:
        candidates=small_size_candidates(screen,model,threshold,check)
        if not candidates:
            candidates=wide_candidates(screen,model,threshold,check)
        return _resolve(pose_matches(candidates,model,offset),False)
    return _result('not_found','추가 후보 없음')


def _scan(frame, model, threshold, scales, offset, check, recovery=True, adaptive=False, budget=1):
    if model.flat:
        boxes,uniform=color_boxes(rgb(frame),model.pixels[0,0],max(1,round((1-threshold)*85)))
        if uniform:
            return _result('insufficient','화면 전체가 같은 색이라 위치를 구분할 수 없음')
        items=[(1.,int(x),int(y),int(w),int(h)) for x,y,w,h,count in boxes
               if count>=.96*w*h and proportional(w,h,model,scales,adaptive)]
        return _resolve(pose_matches(items,model,offset),False)
    screen = Screen(frame)
    sizes = {}
    for scale in scales:
        w,h = max(4,round(model.width*scale)),max(4,round(model.height*scale))
        if w <= frame.width and h <= frame.height:
            sizes.setdefault((w,h),scale)
    if not sizes:
        return _result('not_found', '이미지가 검색 영역보다 큼')
    lo,hi,_,_ = cv2.minMaxLoc(screen.gray)
    if hi == lo and model.gray.std() >= 3:
        return _result('not_found','화면에 대상의 밝기 무늬가 없음')

    def scan(sizes, directions, native=False, broad=False):
        matches = []
        incomplete = False
        for (w,h),scale in sizes.items():
            check()
            pixels, gray = model.variant(w,h)
            if directions:
                (positions, limited), stride = orientation_candidates(screen, pixels, check,budget)
            else:
                (positions, limited), stride = pixel_candidates(screen, gray, threshold, check, native=native, broad=broad,budget=budget)
            incomplete |= limited
            seen = set()
            for x,y in positions:
                check()
                verified = verify(screen, pixels,gray,x*stride,y*stride,
                                  stride+2 if stride>1 else 0,threshold,(w,h)!=(model.width,model.height))
                if verified is None:
                    continue
                score,a,b = verified
                if score+1e-6 >= threshold and (a,b) not in seen:
                    seen.add((a,b))
                    # Offset=1 must stay inside the matched rectangle.
                    point = (a+min(w-1,round(w*offset[0])), b+min(h-1,round(h*offset[1])))
                    matches.append(dict(score=score, box=(a,b,w,h), point=point, scale=scale))
        return matches, incomplete

    matches, limited = scan(sizes, False)
    result = _resolve(matches, limited)
    if result['status']=='incomplete' and result['score']>=.985:
        # Independently verify the same scale at native resolution with a
        # high candidate floor. Weak coarse peaks cannot hide exact duplicates.
        w,h=result['box'][2:]
        _,gray=model.variant(w,h)
        positions,_=pixel_candidates(screen,gray,.999,check,native=True,precise=True,budget=budget)
        strong=[]
        for x,y in positions[0]:
            pixels,gray=model.variant(w,h)
            v=verify(screen,pixels,gray,x,y,0,.985)
            if v and v[0]>=.985:
                strong.append((v[0],v[1],v[2],w,h))
        if strong:
            result=_resolve(pose_matches(strong,model,offset),positions[1])
    if result['status'] in ('found','ambiguous') or not recovery:
        return result
    if min(model.width,model.height)<12:
        tiny=tiny_size_candidates(screen,model,check,scales,adaptive)
        r=_resolve(pose_matches(tiny,model,offset,'tiny_rgb'),False)
        if r['status'] in ('found','ambiguous'):
            return r
    if adaptive:
        result=independent_scan(screen,model,threshold,offset,check)
        if result['status'] in ('found','ambiguous'):
            return result
    # A rescue scan uses original-pixel gradients, independent of the
    # downsampled intensity response. Reuse its maps across all scales.
    extra = dict(sizes)
    if adaptive:
        for s in (.75,1.25,1.5,1.75,2):
            w,h = max(4,round(model.width*s)),max(4,round(model.height*s))
            if w <= frame.width and h <= frame.height:
                extra.setdefault((w,h),s)
    extra_only = {size:scale for size,scale in extra.items() if size not in sizes}
    enlarged, extra_limited = scan(extra_only, False, broad=True)
    result = _resolve(enlarged,extra_limited)
    if result['status'] in ('found','ambiguous'):
        return result
    if adaptive:
        result=_outline_scan(screen,model,threshold,offset,check,budget)
        if result['status'] in ('found','ambiguous'):
            return result
        extra_limited |= result['status']=='incomplete'
    if adaptive:
        result=independent_scan(screen,model,threshold,offset,check,wide=True)
        if result['status'] in ('found','ambiguous'):
            return result
    recovered, rescue_limited = scan(sizes, True)
    if recovered:
        return _resolve(matches+recovered, limited or rescue_limited)
    skipped = {size:scale for size,scale in sizes.items()
               if min(size)>=24 and screen.gray.size>500000 and (len(sizes)<=2 or threshold>=.98)}
    if skipped:
        native, native_limited = scan(skipped, False, native=True)
        return _resolve(native, native_limited)
    return _resolve(matches, limited or rescue_limited or extra_limited)


def match(frame, template, threshold=.9, scales=(1.,), offset=(.5,.5), check=None,
          *, recovery=True, adaptive=None, budget=1):
    model = template if isinstance(template, Model) else Model(template)
    scales = tuple(scales)
    if adaptive is None:
        adaptive = tuple(sorted(set(scales))) == DEFAULT_SCALES
    check=check or (lambda:None)
    if recovery=='tiny':
        items=tiny_size_candidates(Screen(frame),model,check,scales,adaptive)
        return _resolve(pose_matches(items,model,offset,'tiny_rgb'),False)
    if recovery=='anchors':
        found,limited=exact_anchors(frame,model,check,budget)
        return _resolve(pose_matches(found,model,offset),limited)
    if recovery=='quick_scaled':
        if min(frame.size)<4:
            return _result('not_found','검색 영역이 작음')
        if adaptive:
            scales=tuple(sorted(set(scales)|{.5,.625,.67,.75,1.25,1.5}))
        items,limited=quick_scaled_candidates(Screen(frame),model,scales,threshold,check)
        return _resolve(pose_matches(items,model,offset),limited)
    if recovery in ('small','wide'):
        if not adaptive or model.flat:
            return _result('not_found','추가 후보 없음')
        screen=Screen(frame)
        items=(small_size_candidates(screen,model,threshold,check) if recovery=='small'
               else wide_candidates(screen,model,threshold,check))
        return _resolve(pose_matches(items,model,offset),False)
    if recovery=='glyph':
        return (independent_scan(Screen(frame),model,threshold,offset,check)
                if adaptive and not model.flat else _result('not_found','추가 후보 없음'))
    if recovery=='outline':
        return (_outline_scan(Screen(frame),model,threshold,offset,check,budget)
                if adaptive and not model.flat else _result('not_found','보완 후보 없음'))
    if recovery=='silhouette' or (recovery is True and model.silhouette is not None):
        shape = silhouette_scan(rgb(frame),model,threshold,scales,offset,check,adaptive)
        if recovery=='silhouette' or shape['status'] in ('found','ambiguous'):
            return shape
    return _scan(frame,model,threshold,scales,offset,check,recovery,adaptive,budget)


def search_regions(frame, template, regions, origin, configured, source_dpi,
                   threshold, offset, check=None, *, budget=1, quick=False, fast=False):
    if not regions:
        raise RuntimeError('검색 가능한 모니터 없음')
    model = template if isinstance(template, Model) else Model(template)
    configured = tuple(configured)
    adaptive = tuple(sorted(set(configured))) == DEFAULT_SCALES
    prepared = []
    crops = {}
    full_pixels = None
    for region in regions:
        x,y,w,h = region['rect']
        ox,oy = origin
        box = (x-ox,y-oy,x-ox+w,y-oy+h)
        scales = scale_candidates(configured, source_dpi,region['dpi'])
        prepared.append((region,box,scales))

    def crop_for(box):
        if box not in crops:
            crops[box]=frame.crop(box)
        return crops[box]

    def examine(recovery):
        nonlocal full_pixels
        found, failures = [], []
        pixels = None
        if recovery in ('silhouette','fast_anchors','small_anchors'):
            if full_pixels is None:
                full_pixels = rgb(frame)
            pixels = full_pixels
        for region,box,scales in prepared:
            if pixels is not None:
                l,t,r,b=box
                view=pixels[t:b,l:r] if 0<=l<r<=frame.width and 0<=t<b<=frame.height else rgb(crop_for(box))
                if recovery=='small_anchors':
                    if min(model.width,model.height)<=26:
                        if adaptive:
                            common = {.8,1.25,1.5}
                            if source_dpi:
                                common.add(region['dpi']/source_dpi)
                        else:
                            common = scales
                    else:
                        common = (.5,1.25)
                    items,limited=small_anchor_candidates(view,model,sorted(s for s in common if .2<=s<=4),
                                                           check or (lambda:None),budget)
                    r=_resolve(pose_matches(items,model,offset,'scaled_rgb'),limited)
                elif recovery=='fast_anchors':
                    candidates,limited=exact_anchors(view,model,check or (lambda:None),budget,
                                                      maximum=8000,candidate_limit=24)
                    r=_resolve(pose_matches(candidates,model,offset,'exact_rgb'),limited)
                else:
                    r=silhouette_scan(view,model,threshold,scales,offset,check or (lambda:None),adaptive)
            else:
                crop = crop_for(box)
                r = match(crop,model,threshold,scales,offset,check,recovery=recovery,adaptive=adaptive,budget=budget)
                if r['found'] and r.get('method')!='silhouette':
                    if contradicts_silhouette(crop,model,r['box']):
                        r = _result('not_found','글자 안쪽 모양이 다름')
            r['monitor'] = region['device']
            if r['box']:
                x,y,_,_ = region['rect']
                a,b,w,h = r['box']
                px,py = r['point']
                r.update(box=(x+a,y+b,w,h),point=(x+px,y+py))
            if r['status'] == 'ambiguous':
                return r
            (found if r['found'] else failures).append(r)
        limited = any(r['status']=='incomplete' for r in failures)
        if found:
            return _resolve(found,limited)
        return next((r for r in failures if r['status']=='incomplete'),failures[0])

    has_silhouette=model.silhouette is not None
    if 1. in configured and not model.flat and (fast or max(model.width,model.height)<=80):
        anchors=examine('fast_anchors' if fast else 'anchors')
        if anchors['status'] in ('found','ambiguous'):
            return anchors
    if has_silhouette:
        shape=examine('silhouette')
        if shape['status'] in ('found','ambiguous'):
            return shape
    small = 4<=min(model.width,model.height)<=26
    short_text = adaptive and has_silhouette and max(model.width,model.height)<=360
    if fast and quick and not model.flat and (small or short_text):
        scaled=examine('small_anchors')
        if scaled['status'] in ('found','ambiguous'):
            return scaled
    if fast and quick and not model.flat and min(model.width,model.height)>=24:
        scaled=examine('quick_scaled')
        if scaled['status'] in ('found','ambiguous'):
            return scaled
    if fast and quick and len(prepared)>1 and not model.flat and 1. in configured:
        return _result('incomplete','원본 크기 검색 완료 · 다른 크기 계속 확인 중')
    if fast and min(model.width,model.height)>=24 and (min(model.width,model.height)>=160 or len(prepared)==1):
        pose=[]
        for region,box,_ in prepared:
            x,y,_,_=region['rect']
            for hit in pose_candidates(crop_for(box),model,threshold,offset,check or (lambda:None)):
                if contradicts_silhouette(crop_for(box),model,hit['box']):
                    continue
                a,b,w,h=hit['box']
                px,py=hit['point']
                pose.append(dict(hit,box=(a+x,b+y,w,h),point=(px+x,py+y),monitor=region['device'],method='pose'))
        if pose:
            return _resolve(pose,False)
        if quick and min(model.width,model.height)>=160:
            return _result('incomplete','빠른 검색 완료 · 새 화면 확인 중')
    result=examine(False)
    if result['status'] in ('found','ambiguous','insufficient'):
        return result
    if quick and fast:
        return _result('incomplete','빠른 검색 완료 · 새 화면 확인 중')
    glyph=examine('glyph') if adaptive else _result('not_found','추가 후보 없음')
    if glyph['status'] in ('found','ambiguous'):
        return glyph
    outline=examine('outline')
    if outline['status'] in ('found','ambiguous'):
        return outline
    if not quick and not model.flat and min(model.width,model.height)<12:
        tiny=examine('tiny')
        if tiny['status'] in ('found','ambiguous'):
            return tiny
    if adaptive and not quick and not model.flat:
        broad=examine('small' if min(model.width,model.height)<24 else 'wide')
        if broad['status'] in ('found','ambiguous'):
            return broad
    if quick:
        # Keep the first polling pass short. A later full pass checks
        # additional size presets and orientation candidates.
        return _result('incomplete','기본 후보 확인 · 정밀 검색 대기')
    return examine(True)


def recheck(frame, model, previous, threshold, offset, check=None):
    """Only search nearby pixels at the previously measured size."""
    x,y,w,h = previous['box']
    _,_,old_w,old_h = previous['box']
    if check:
        check()
    if previous.get('method')=='silhouette':
        left,top=max(0,x-6),max(0,y-6)
        area=frame.crop((left,top,min(frame.width,x+w+6),min(frame.height,y+h+6)))
        scale=previous['scale']
        hit=verify_silhouette(rgb(area),model.silhouette,threshold,scale*.91,scale*1.10)
        if hit is None:
            return _result('not_found','글자 윤곽 위치를 다시 확인할 수 없음')
        score,a,b,width,height=hit
        return _resolve([silhouette_match((score,a+left,b+top,width,height),model,offset)],False)
    if previous.get('method')=='pose':
        hits=pose_candidates(frame,model,threshold,offset,check or (lambda:None),
                             local=(previous['scale'],previous.get('angle',0)))
        if model.silhouette is not None and hits:
            pixels = rgb(frame)
            hits = [hit for hit in hits if not contradicts_silhouette(pixels,model,hit['box'])]
        return _resolve(hits,False)
    screen = Screen(frame)
    if previous.get('method') in ('exact_rgb','scaled_rgb'):
        reference=model.pixels
        if previous['method']=='scaled_rgb':
            from PIL import Image
            reference=model.anchor_variant(w,h,Image.Resampling.LANCZOS).pixels
        patch=screen.pixels[y:y+h,x:x+w]
        if patch.shape==reference.shape and cv2.norm(patch,reference,cv2.NORM_INF)<=5:
            point=x+min(w-1,round(w*offset[0])),y+min(h-1,round(h*offset[1]))
            return _result('found','발견',dict(previous,point=point))
    if previous.get('method')=='tiny_rgb':
        pixels=tiny_pixels(model,w,h)
        patch=screen.pixels[y:y+h,x:x+w]
        if patch.shape==pixels.shape and np.abs(pixels.astype(np.int16)-patch).max()<=12:
            point=x+min(w-1,round(w*offset[0])),y+min(h-1,round(h*offset[1]))
            return _result('found','발견',dict(previous,point=point))
        return _result('not_found','작은 이미지 위치를 다시 확인할 수 없음')
    if previous.get('method')=='glyph':
        color=background(model.pixels)
        patch=screen.pixels[y:y+h,x:x+w]
        if color is not None and patch.shape[:2]==(h,w):
            score=verify_text(text_variants(model.pixels,color),patch,color,threshold)
            if score is not None:
                point=x+min(w-1,round(w*offset[0])),y+min(h-1,round(h*offset[1]))
                return _result('found','발견',dict(previous,score=score,point=point))
        return _result('not_found','글자 위치를 다시 확인할 수 없음')
    pixels, gray = model.variant(old_w,old_h)
    resized=(w,h)!=(model.width,model.height)
    candidate=verify(screen,pixels,gray,x,y,4,threshold,resized)
    if (candidate is None or candidate[0]+1e-6<threshold) and abs(w/model.width-1)>=.04:
        candidate=verify(screen,pixels,gray,x,y,4,threshold,True,aligned=True)
    if candidate is None or candidate[0]+1e-6<threshold:
        candidate=verify(screen,pixels,gray,x,y,8,threshold,resized)
    if candidate and candidate[0]+1e-6 >= threshold:
        score,a,b = candidate
        if contradicts_silhouette(screen.pixels,model,(a,b,w,h)):
            return _result('not_found','글자 안쪽 모양이 다름')
        point = a+min(w-1,round(w*offset[0])), b+min(h-1,round(h*offset[1]))
        return _result('found','발견',dict(score=score, box=(a,b,w,h),point=point,scale=previous['scale']))
    return _result('not_found','최근 화면에서 대상이 이동하거나 사라짐')
