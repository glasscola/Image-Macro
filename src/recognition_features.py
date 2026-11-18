"""Cached registration models and screen gradients in physical pixels."""
from functools import lru_cache
import cv2
import numpy as np


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

    def _variant(self, width, height):
        if (width, height) == (self.width, self.height):
            return self.pixels, self.gray
        mode = cv2.INTER_AREA if width < self.width else cv2.INTER_CUBIC
        pixels = cv2.resize(self.pixels, (width, height), interpolation=mode)
        return pixels, cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)


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
