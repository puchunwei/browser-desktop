"""Capture a disposable Xorg source using only production's existing libX11.

Test helper, never installed in the shipping image. Writes raw PPM for Pillow in
our throwaway client. A source/decoded comparison must use identical geometry.
"""
import ctypes as C
import os
from pathlib import Path
import sys

class XImage(C.Structure):
    _fields_ = [(n,t) for n,t in [
        ('width',C.c_int),('height',C.c_int),('xoffset',C.c_int),('format',C.c_int),
        ('data',C.c_void_p),('byte_order',C.c_int),('bitmap_unit',C.c_int),
        ('bitmap_bit_order',C.c_int),('bitmap_pad',C.c_int),('depth',C.c_int),
        ('bytes_per_line',C.c_int),('bits_per_pixel',C.c_int)]]

session = dict(line.split('=',1) for line in Path('/run/browser-desktop/session').read_text().splitlines())
os.environ.update({k:session[k] for k in ('DISPLAY','XAUTHORITY')})
x = C.CDLL('libX11.so.6')
x.XOpenDisplay.argtypes = [C.c_char_p]; x.XOpenDisplay.restype = C.c_void_p
x.XDefaultRootWindow.argtypes = [C.c_void_p]; x.XDefaultRootWindow.restype = C.c_ulong
x.XDisplayWidth.argtypes = [C.c_void_p,C.c_int]; x.XDisplayHeight.argtypes = [C.c_void_p,C.c_int]
x.XGetImage.argtypes = [C.c_void_p,C.c_ulong,C.c_int,C.c_int,C.c_uint,C.c_uint,C.c_ulong,C.c_int]
x.XGetImage.restype = C.POINTER(XImage)
x.XDestroyImage.argtypes = [C.POINTER(XImage)]
x.XCloseDisplay.argtypes = [C.c_void_p]
d = x.XOpenDisplay(None)
assert d, 'Xorg unavailable'
try:
    width,height = x.XDisplayWidth(d,0), x.XDisplayHeight(d,0)
    image = x.XGetImage(d,x.XDefaultRootWindow(d),0,0,width,height,0xffffffff,2)
    assert image and image.contents.bits_per_pixel == 32 and image.contents.byte_order == 0
    try:
        stride = image.contents.bytes_per_line
        raw = C.string_at(image.contents.data, stride*height)
        rgb = bytearray(width*height*3)
        for row in range(height):
            source = raw[row*stride:row*stride+width*4]
            offset = row*width*3
            rgb[offset:offset+width*3:3] = source[2::4]
            rgb[offset+1:offset+width*3:3] = source[1::4]
            rgb[offset+2:offset+width*3:3] = source[0::4]
        with open(sys.argv[1], 'wb') as output:
            output.write(f'P6\n{width} {height}\n255\n'.encode()); output.write(rgb)
    finally:
        x.XDestroyImage(image)
finally:
    x.XCloseDisplay(d)
