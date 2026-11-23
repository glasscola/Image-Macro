"""Cached registration models and screen gradients in physical pixels."""
from functools import cached_property, lru_cache

from PIL import Image
import cv2
import numpy as np
from recognition_silhouette import build_silhouette


def rgb(image):
    return np.asarray(image.convert("RGB") if image.mode != "RGB" else image)


def gradients(pixels):
    best = np.zeros(pixels.shape[:2], np.float32)
    angle = np.zeros_like(best)
    for channel in cv2.split(pixels):
        dx = cv2.Sobel(channel, cv2.CV_32F, 1, 0)
        dy = cv2.Sobel(channel, cv2.CV_32F, 0, 1)
        strength, direction = cv2.cartToPolar(dx, dy, angleInDegrees=True)
        use = strength > best
        best[use] = strength[use]
        angle[use] = direction[use]
    bins = (np.floor((angle + 11.25) / 22.5).astype(np.uint8) & 7)
    return best, bins


class Model:
    def __init__(self, image):
        self.pixels = rgb(image)
        self.width, self.height = image.size
        self.gray = cv2.cvtColor(self.pixels, cv2.COLOR_RGB2GRAY)
        self.flat = bool(np.max(np.ptp(self.pixels, axis=(0, 1))) < 8)
        self.variant = lru_cache(maxsize=16)(self._variant)
        self.anchor_variant = lru_cache(maxsize=12)(self._anchor_variant)

    def _anchor_variant(self, width, height, resampling):
        resized = Image.fromarray(self.pixels).resize((width,height),resampling)
        return Model(resized)

    def _variant(self, width, height):
        if (width, height) == (self.width, self.height):
            return self.pixels, self.gray
        mode = cv2.INTER_AREA if width < self.width else cv2.INTER_CUBIC
        pixels = cv2.resize(self.pixels, (width, height), interpolation=mode)
        return pixels, cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)

    @cached_property
    def silhouette(self):
        return None if self.flat else build_silhouette(self.pixels)

    @cached_property
    def anchor_colors(self):
        h,w=self.height,self.width
        flat=self.pixels.reshape(-1,3).astype(np.int16)
        sample = flat[::max(1,len(flat)//2048)]
        center = np.median(sample,axis=0)
        def bins(colors):
            return (colors[:,0]//16)*256 + (colors[:,1]//16)*16 + colors[:,2]//16
        frequency = np.bincount(bins(sample),minlength=4096)
        def distinct_indices(colors):
            contrast = np.abs(colors-center).max(axis=1)
            return contrast / np.sqrt(1+frequency[bins(colors)])
        coordinates=[]
        stride = max(1,len(flat)//24000)
        best = int(np.argmax(distinct_indices(flat[::stride]))) * stride
        coordinates.append(divmod(best,w))
        # A flat screen can satisfy many copies of one rare template color.
        # Also anchor colors well separated from that first color.
        first = flat[best]
        separation = np.abs(flat[::stride]-first).max(axis=1)
        alternate = int(np.argmax(separation)) * stride
        coordinates.append(divmod(alternate,w))
        for area in np.array_split(np.arange(h),3):
            zone=flat[area[0]*w:(area[-1]+1)*w]
            stride=max(1,len(zone)//12000)
            best=int(np.argmax(distinct_indices(zone[::stride])))*stride+area[0]*w
            coordinates.append(divmod(best,w))
        if min(h,w)>=24:
            edges=cv2.Laplacian(self.gray,cv2.CV_16S)
            for ys in np.array_split(np.arange(h),3):
                for xs in np.array_split(np.arange(w),2):
                    grad=np.abs(edges[ys[0]:ys[-1]+1,xs[0]:xs[-1]+1])
                    at_y,at_x=np.unravel_index(np.argmax(grad),grad.shape)
                    coordinates.append((ys[0]+at_y,xs[0]+at_x))
        colors=[]
        for y,x in dict.fromkeys(coordinates):
            color=self.pixels[y,x].astype(np.int16)
            colors.append((y,x,np.maximum(0,color-4).astype(np.uint8),
                           np.minimum(255,color+4).astype(np.uint8)))
        return colors


class Screen:
    def __init__(self, image):
        self.pixels = rgb(image)
        self.gray = cv2.cvtColor(self.pixels, cv2.COLOR_RGB2GRAY)
        self.coarse = {}
        self.maps = None

    def coarse_gray(self, factor=2):
        if factor not in self.coarse:
            height, width = self.gray.shape
            even = self.gray[:height // factor * factor, :width // factor * factor]
            self.coarse[factor] = cv2.resize(even, (width // factor, height // factor),
                                             interpolation=cv2.INTER_AREA)
        return self.coarse[factor]
