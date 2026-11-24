"""Grayscale motion tracking and texture-based reidentification."""
from functools import cached_property

import cv2
import numpy as np


def gray(pixels):
    return cv2.cvtColor(pixels,cv2.COLOR_RGB2GRAY)


def follow(previous, mask, frame, x, y):
    """Estimate translation from foreground corners that survive a round trip."""
    h,w = previous.shape[:2]
    if not (0<=x<=frame.shape[1]-w and 0<=y<=frame.shape[0]-h):
        return None
    source = gray(frame)
    source[y:y+h,x:x+w] = gray(previous)
    valid = np.zeros(source.shape,np.uint8)
    valid[y:y+h,x:x+w] = cv2.erode(mask,np.ones((3,3),np.uint8))
    points = cv2.goodFeaturesToTrack(source,60,.015,5,mask=valid)
    if points is None or len(points)<6:
        return None
    dest = gray(frame)
    forward,ok,_ = cv2.calcOpticalFlowPyrLK(source,dest,points,None)
    if forward is None:
        return None
    reverse,back,_ = cv2.calcOpticalFlowPyrLK(dest,source,forward,None)
    if reverse is None:
        return None
    good = ok.ravel().astype(bool)&back.ravel().astype(bool)
    good &= np.linalg.norm((reverse-points).reshape(-1,2),axis=1)<1.6
    if good.sum()<max(6,len(points)*.35):
        return None
    shifts = (forward-points).reshape(-1,2)[good]
    dx,dy = np.median(shifts,axis=0)
    consistent = np.linalg.norm(shifts-(dx,dy),axis=1)<max(5,min(w,h)*.08)
    if consistent.sum()<max(6,good.sum()*.60):
        return None
    px,py = round(x+dx),round(y+dy)
    if 0<=px<=frame.shape[1]-w and 0<=py<=frame.shape[0]-h:
        return px,py
    return None


class Texture:
    def __init__(self, model):
        self.model = model

    @cached_property
    def features(self):
        mask = cv2.erode(self.model.foreground_mask,np.ones((5,5),np.uint8))
        return detector(320).detectAndCompute(self.model.gray,mask)


def detector(count):
    return cv2.ORB_create(nfeatures=count,edgeThreshold=12,fastThreshold=12)


def texture_candidates(frame, templates, threshold, offset, check):
    # Limit work on a large virtual desktop while retaining full detail in
    # the local confirmation crop.
    factor = max(1.,frame.width/1600,frame.height/1000)
    pixels = gray(np.asarray(frame))
    if factor>1:
        pixels = cv2.resize(pixels,(round(frame.width/factor),round(frame.height/factor)),
                            interpolation=cv2.INTER_AREA)
    check()
    points,descriptors = detector(900).detectAndCompute(pixels,None)
    if descriptors is None or len(descriptors)<2:
        return []
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    results = []
    for name,model in templates:
        check()
        texture = vars(model).get('_motion_texture')
        if texture is None:
            model._motion_texture = texture = Texture(model)
        anchors,reference = texture.features
        if reference is None or len(reference)<8:
            continue
        matches = {}
        for pair in matcher.knnMatch(reference,descriptors,k=2):
            if len(pair)==2 and pair[0].distance<min(50,.77*pair[1].distance):
                match = pair[0]
                prior = matches.get(match.trainIdx)
                if prior is None or match.distance<prior.distance:
                    matches[match.trainIdx] = match
        if len(matches)<8:
            continue
        source = np.float32([anchors[m.queryIdx].pt for m in matches.values()])
        target = np.float32([points[m.trainIdx].pt for m in matches.values()])*factor
        transform,inliers = cv2.estimateAffinePartial2D(source,target,ransacReprojThreshold=3*factor,
                                                        maxIters=300)
        if transform is None or inliers is None:
            continue
        keep = inliers.ravel().astype(bool)
        strength = keep.mean()
        if keep.sum()<8 or strength<max(.58,threshold-.29):
            continue
        spread = np.ptp(source[keep],axis=0)
        if min(spread)<12 or np.max(spread/(model.width,model.height))<.25:
            continue
        scale = float(np.linalg.norm(transform[:,0]))
        if not .45<=scale<=2.4:
            continue
        center = transform @ [model.width/2,model.height/2,1]
        w,h = round(model.width*scale),round(model.height*scale)
        point = transform @ [model.width*offset[0],model.height*offset[1],1]
        if tuple(offset)==(.5,.5):
            nearby = target[keep]
            point = nearby[np.argmin(np.linalg.norm(nearby-np.median(nearby,axis=0),axis=1))]
        px,py = map(round,point)
        if 0<=px<frame.width and 0<=py<frame.height:
            results.append(dict(score=float(strength),box=(round(center[0]-w/2),round(center[1]-h/2),w,h),
                                point=(px,py),scale=scale,asset=name,method='recorded_motion'))
    return results
