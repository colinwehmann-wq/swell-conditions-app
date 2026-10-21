#!/usr/bin/env python3
"""Draw the site's home-screen icons: a deep-water square with two white swells.

  python3 tools/make_icons.py

Writes sitegen/assets/apple-touch-icon.png (180 px), icon-192.png and icon-512.png. Pure standard library, so
there is nothing to install, and re-running it gives byte-identical files. The icons are full-bleed squares: iPhones
and Android both round or mask them themselves.
"""
import math
import os
import struct
import zlib

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sitegen", "assets")
SIZES = {"apple-touch-icon.png": 180, "icon-192.png": 192, "icon-512.png": 512}

TOP = (31, 95, 140)        # #1f5f8c, the colour of a break's photo-less hero
BOTTOM = (10, 24, 38)      # #0a1826
WHITE = (255, 255, 255)
SAMPLES = 3                # supersampling per axis, for smooth edges


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def wave_distance(x, y, size, centre, phase):
    """How far (in pixels) the point is from a sine swell crossing the icon at height `centre` (a fraction of size)."""
    amp = 0.085 * size
    y_wave = centre * size + amp * math.sin((x / size) * 2 * math.pi * 1.25 + phase)
    return abs(y - y_wave)


def pixel(px, py, size):
    """Colour of one sample: the gradient, then each swell where it is within half a stroke."""
    colour = mix(TOP, BOTTOM, py / size)
    for centre, phase, strength in ((0.40, 0.0, 1.0), (0.62, 1.6, 0.8)):
        half = 0.036 * size
        d = wave_distance(px, py, size, centre, phase)
        if d < half:
            colour = mix(colour, WHITE, strength)
    return colour


def render(size):
    rows = []
    for y in range(size):
        row = bytearray([0])                                   # PNG filter type 0 for this scanline
        for x in range(size):
            r = g = b = 0.0
            for sy in range(SAMPLES):
                for sx in range(SAMPLES):
                    c = pixel(x + (sx + 0.5) / SAMPLES, y + (sy + 0.5) / SAMPLES, size)
                    r, g, b = r + c[0], g + c[1], b + c[2]
            n = SAMPLES * SAMPLES
            row += bytes((round(r / n), round(g / n), round(b / n)))
        rows.append(bytes(row))
    return b"".join(rows)


def png(size):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)       # 8-bit RGB
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(render(size), 9)) + chunk(b"IEND", b"")


def main():
    for name, size in SIZES.items():
        path = os.path.join(ASSETS, name)
        with open(path, "wb") as f:
            f.write(png(size))
        print("wrote %s (%d px, %d bytes)" % (os.path.relpath(path), size, os.path.getsize(path)))


if __name__ == "__main__":
    main()
