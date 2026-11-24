"""Recognize independently moving parts of recorded artwork."""
import math

import cv2
import numpy as np

from recognition_features import Model
from recognition_landmark import components, contour_mask, landmark_candidates, landmark_model
from PIL import Image


def recorded_marks(model, *, pastel=True):
    """Cache distinctive color shapes with their surrounding context."""
    cache = vars(model).setdefault('_recorded_marks', {})
    if pastel in cache:
        return cache[pastel]
    center = landmark_model(model)
    if center and min(center[2][2:]) >= 20:
        cache[pastel] = [(model, 0, 0)]
        return cache[pastel]

    pixels = model.pixels
    mask = model.foreground_mask
    h,w = mask.shape
    foreground_pixels = pixels[mask != 0]
    bins = foreground_pixels//(16 if pastel else 24)
    colors, counts = np.unique(bins,axis=0,return_counts=True)
    choices = []
    for index in np.argsort(counts)[-(20 if pastel else 12):][::-1]:
        if pastel:
            color = np.median(foreground_pixels[(bins==colors[index]).all(axis=1)],axis=0)
        else:
            color = colors[index].astype(np.int16)*24+12
        regions = cv2.bitwise_and(contour_mask(pixels,color,17 if pastel else 23),mask*255)
        for x,y,bw,bh,area,shape in components(regions):
            if min(bw,bh)<14 or area>.33*mask.sum():
                continue
            distance = cv2.distanceTransform(shape,cv2.DIST_L2,3)
            _,radius,_,(px,py) = cv2.minMaxLoc(distance)
            cx,cy = x+px,y+py
            extent_x = max(cx-x,x+bw-cx)+max(6,bw//6)
            extent_y = max(cy-y,y+bh-cy)+max(6,bh//6)
            if pastel:
                extent_x = min(extent_x,cx,w-cx-1)
                extent_y = min(extent_y,cy,h-cy-1)
            left,top = cx-extent_x,cy-extent_y
            right,bottom = cx+extent_x+1,cy+extent_y+1
            if left<0 or top<0 or right>w or bottom>h or radius<6:
                continue
            patch = Model(Image.fromarray(pixels[top:bottom,left:right]))
            if pastel:
                patch.min_landmark_contrast = 27
            feature = landmark_model(patch)
            if feature is not None:
                fx,fy,fw,fh = feature[2]
                choices.append((feature[3],patch,left,top,left+fx+fw/2,top+fy+fh/2))
    marks = []
    centers = []
    for _,patch,left,top,x,y in sorted(choices,key=lambda item:item[0],reverse=True):
        if all(np.hypot(x-px,y-py)>=18 for px,py in centers):
            marks.append((patch,left,top))
            centers.append((x,y))
        if len(marks)>=4:
            break
    cache[pastel] = marks
    return marks


def marked_candidates(frame, name, model, threshold, offset, check, near, *, pastel=True):
    marks = recorded_marks(model,pastel=pastel)
    centered_mark = len(marks)==1 and marks[0][0] is model
    if len(marks)<2 and not centered_mark:
        return marked_candidates(frame,name,model,threshold,offset,check,near,pastel=False) if pastel else []
    reduce = frame.width*frame.height>=1_000_000
    sample = frame.resize((frame.width//2,frame.height//2),Image.Resampling.BILINEAR) if reduce else frame
    pixel_x,pixel_y = frame.width/sample.width,frame.height/sample.height
    observations = []
    for index,(patch,left,top) in enumerate(marks):
        rx,ry,rw,rh = landmark_model(patch)[2]
        ax,ay = left+rx+rw/2,top+ry+rh/2
        reduced_patch = patch.anchor_variant(patch.width//2,patch.height//2,Image.Resampling.BILINEAR) if reduce else patch
        if reduce and hasattr(patch,'min_landmark_contrast'):
            reduced_patch.min_landmark_contrast = patch.min_landmark_contrast
        if reduce and landmark_model(reduced_patch) is None:
            continue
        for hit in landmark_candidates(sample,[(name,reduced_patch)],max(.83,threshold-.07),(.5,.5),check,
                                       deformable=True):
            x,y,w,h = hit['box']
            observations.append((index,complex(ax,ay),complex((x+w/2)*pixel_x,(y+h/2)*pixel_y),hit))

    results = []
    for index,origin,position,hit in observations:
        transforms = [(hit['scale'],hit['score'],None)] if centered_mark else []
        for other_index,other_origin,other_position,other in observations:
            if other_index<=index or abs(other_position-position)<10:
                continue
            transform = (other_position-position)/(other_origin-origin)
            scale = abs(transform)
            if abs(math.atan2(transform.imag,transform.real))>math.radians(46):
                continue
            if not all(.65<=scale/item['scale']<=1.48 for item in (hit,other)):
                continue
            transforms.append((transform,(hit['score']+other['score'])/2,other_index))
        ox,oy = min(model.width-1,round(model.width*offset[0])),min(model.height-1,round(model.height*offset[1]))
        if not model.foreground_mask[oy,ox]:
            _,_,_,(ox,oy) = cv2.minMaxLoc(cv2.distanceTransform(model.foreground_mask,cv2.DIST_L2,3))
        for transform,score,paired in transforms:
            if centered_mark and not .70<=abs(transform)<=1.65:
                continue
            center = position + (complex(model.width/2,model.height/2)-origin)*transform
            if near and (abs(center.real-near[0])>near[2] or abs(center.imag-near[1])>near[2]):
                continue
            scale = abs(transform)
            support = 1
            if paired is not None:
                tolerance = max(6, min(model.width,model.height)*scale*.09)
                supporting = {i:location for i,anchor,location,_ in observations
                                 if i not in (index,paired)
                                 and abs(position+(anchor-origin)*transform-location)<=tolerance
                                 and abs(location-position)>tolerance}
                support = 2+len(supporting)
            w,h = round(model.width*scale),round(model.height*scale)
            x,y = round(center.real-w/2),round(center.imag-h/2)
            point = position if tuple(offset)==(.5,.5) else position+(complex(ox,oy)-origin)*transform
            if support>=3 and tuple(offset)==(.5,.5):
                paired_origin = next((anchor for i,anchor,_,_ in observations if i==paired),origin)
                anchors = {i:anchor for i,anchor,_,_ in observations}
                parts = [(origin,position),(paired_origin,position+(paired_origin-origin)*transform)]
                parts.extend((anchors[i],loc) for i,loc in supporting.items())
                # A point between verified features on the lower part of the
                # registration crop is less exposed to motion at its edges.
                (a,p),(b,q) = sorted(parts,key=lambda part:part[0].imag)[-2:]
                middle = (a+b)/2
                if abs(a.imag-b.imag)<model.height*.18 and abs(a.real-b.real)>model.width*.12 and (
                        model.foreground_mask[int(middle.imag),int(middle.real)]):
                    point = (p+q)/2
                else:
                    point = q
            px,py = round(point.real),round(point.imag)
            if 0<=px<frame.width and 0<=py<frame.height:
                results.append(dict(score=score,support=support,box=(x,y,w,h),point=(px,py),scale=scale,
                                    asset=name,method='recorded_motion'))
    strongest = max((candidate['support'] for candidate in results),default=0)
    if not results and pastel and not centered_mark:
        return marked_candidates(frame,name,model,threshold,offset,check,near,pastel=False)
    return [candidate for candidate in results if candidate['support']==strongest]
