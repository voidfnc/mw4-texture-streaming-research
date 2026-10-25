"""ui.py - the small UI kit behind the redesigned window: colours, fonts, anti-aliased shapes (rounded boxes, pills, the progress ring, line icons) and the
widgets built from them (Button, Panel, Ring, Stepper, NavItem). Standard library only: tkinter draws on canvases, and the soft edges come from small PNG images that
are computed here and cached (a plain Tk canvas does not anti-alias its shapes).

Nothing in here knows about the toolkit itself; the window code (homeui.py, ccsgui.py) only composes these pieces.
"""
import base64, math, struct, tkinter as tk, zlib
from tkinter import font as tkfont
from . import i18n

# ------------------------------------------------------------------------------------------------ tokens
BG, BG2, CARD, CARD2, LINE, LINE2 = '#0a0d13', '#0e121a', '#121825', '#171e2d', '#222b3d', '#2d3852'
TEXT, DIM, FAINT = '#eaeef6', '#93a0b8', '#5d6980'
ACCENT, ACCENT2 = '#4c8dff', '#27d3c0'
OK, WARN, BAD = '#3ecf6e', '#f2b63c', '#ef5b5b'
ON_ACCENT = '#04101e'                      # text on the bright gradient buttons

SCALE = 1.0                                # 1.0 at 100 %; init() derives it from Tk when the process is DPI aware


def S(px):
    """A size in design pixels -> device pixels."""
    return int(round(px * SCALE))


def init(root):
    """Call once with the Tk root: derives the scale from tk scaling (1.333 = 96 dpi) so every size follows a DPI-aware process."""
    global SCALE
    try: SCALE = max(1.0, float(root.tk.call('tk', 'scaling')) / (96 / 72))
    except (tk.TclError, ValueError): SCALE = 1.0


# ------------------------------------------------------------------------------------------------ colour helpers
def rgb(h):
    h = h.lstrip('#'); return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def hexc(c): return '#%02x%02x%02x' % tuple(max(0, min(255, int(round(v)))) for v in c[:3])


def mix(a, b, t):
    """Colour between a and b (hex strings); t = 0 gives a, 1 gives b."""
    ca, cb = rgb(a), rgb(b); return hexc([x + (y - x) * t for x, y in zip(ca, cb)])


def lighten(c, t): return mix(c, '#ffffff', t)


def darken(c, t): return mix(c, '#000000', t)


# ------------------------------------------------------------------------------------------------ fonts
_fam = {}


def family(root):
    """The UI font: Segoe UI Variable on Windows 11, else Segoe UI, else whatever Tk calls its default."""
    if not _fam:
        have = set(tkfont.families(root))
        _fam['text'] = next((f for f in ('Segoe UI Variable Text', 'Segoe UI') if f in have), 'TkDefaultFont')
        _fam['head'] = next((f for f in ('Segoe UI Variable Display', 'Segoe UI Semibold', 'Segoe UI') if f in have), _fam['text'])
        _fam['semi'] = 'Segoe UI Semibold' if 'Segoe UI Semibold' in have else _fam['text']
        for k in ('text', 'head', 'semi'): _fam[k] = i18n.font_family_for(i18n.current(), have, _fam[k])        # Chinese / Japanese / Korean: the Windows UI font with those glyphs
    return _fam


def font(root, px, kind='text', bold=False):
    """A Tk font tuple of `px` design pixels (negative size = pixels in Tk, so it follows S())."""
    f = family(root)
    if kind == 'head': return (f['head'], -S(px), 'bold' if bold else 'normal') if f['head'] != 'Segoe UI Semibold' else (f['head'], -S(px))
    if bold: return (f['semi'], -S(px)) if f['semi'] != f['text'] else (f['text'], -S(px), 'bold')
    return (f['text'], -S(px))


# ------------------------------------------------------------------------------------------------ PNG + image cache
def png(w, h, rgba):
    """RGBA bytes (w*h*4, not premultiplied) -> PNG file bytes."""
    stride = w * 4; raw = bytearray()
    for y in range(h): raw.append(0); raw += rgba[y * stride:(y + 1) * stride]
    def chunk(tag, data): return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(bytes(raw), 1)) + chunk(b'IEND', b'')


class _Photo(tk.PhotoImage):
    """A PhotoImage that stays quiet when Python frees it from another thread after the window is gone (Tk then refuses the delete, which is harmless)."""
    def __del__(self):
        try: super().__del__()
        except (RuntimeError, tk.TclError): pass


def photo(master, key, make):
    """A cached tk.PhotoImage; make() -> (w, h, rgba) runs only the first time for this key (the cache lives on the Tk root, so it dies with it)."""
    root = master._root(); cache = root.__dict__.setdefault('_ui_images', {})
    im = cache.get(key)
    if im is None:
        w, h, rgba = make(); im = _Photo(master=root, data=base64.b64encode(png(w, h, rgba))); cache[key] = im
        if len(cache) > CACHE_MAX: _evict(root, cache, key)
    return im


CACHE_MAX = 600                                                         # far more than the window ever shows; stops a runaway (the animations make a new picture per step)


def _evict(root, cache, keep):
    """Drop the oldest cached pictures that nothing shows any more, down to three quarters of CACHE_MAX. A picture a canvas item or a widget still uses is kept however old it is:
    freeing it made Tk answer `image "pyimageNN" doesn't exist` the next time the item was touched (the oldest pictures are the window's permanent ones, the logo, icons, buttons)."""
    drop = len(cache) - CACHE_MAX * 3 // 4; gone = []
    for key, im in cache.items():
        if len(gone) >= drop: break
        if key == keep: continue                                          # the one just made is about to be shown
        try: used = root.tk.getboolean(root.tk.call('image', 'inuse', im.name))
        except tk.TclError: used = True                                  # cannot tell: keep it
        if not used: gone.append(key)
    for key in gone: del cache[key]


def _clamp(v): return 0.0 if v < 0 else 1.0 if v > 1 else v


def _over(dst, src):
    """Premultiplied (r, g, b, a) floats: src over dst."""
    k = 1 - src[3]; return (src[0] + dst[0] * k, src[1] + dst[1] * k, src[2] + dst[2] * k, src[3] + dst[3] * k)


def _put(buf, i, c):
    a = c[3]
    if a <= 0.002: return
    buf[i] = min(255, int(c[0] / a + .5)); buf[i + 1] = min(255, int(c[1] / a + .5)); buf[i + 2] = min(255, int(c[2] / a + .5)); buf[i + 3] = min(255, int(a * 255 + .5))


def _layer(color, a): return (color[0] * a, color[1] * a, color[2] * a, a)


# ------------------------------------------------------------------------------------------------ rounded boxes
def _cov(px, py, cx, cy, rad):
    """How much of pixel (px, py) lies inside the disc at (cx, cy) with radius rad (4x4 samples at the edge, exact inside and outside)."""
    d = math.hypot(px + .5 - cx, py + .5 - cy)
    if d + .72 <= rad: return 1.0
    if d - .72 >= rad: return 0.0
    n = 0
    for i in range(4):
        for j in range(4):
            if math.hypot(px + (i + .5) / 4 - cx, py + (j + .5) / 4 - cy) <= rad: n += 1
    return n / 16


def corner_rgba(r, color, which):
    """One r x r corner of a rounded box (which = tl | tr | bl | br) in a single colour, soft at the arc."""
    cr, cg, cb = rgb(color); rows = []
    for y in range(r):
        rows.append([bytes((cr, cg, cb, int(_cov(x, y, r, r, r) * 255 + .5))) for x in range(r)])
    if which in ('tr', 'br'): rows = [row[::-1] for row in rows]
    if which in ('bl', 'br'): rows = rows[::-1]
    return r, r, b''.join(b''.join(row) for row in rows)


class Shape:
    """A filled rounded rectangle on a canvas: four soft corner images and three plain rectangles. Corners are r pixels; the box is [x0, x1) x [y0, y1)."""
    def __init__(self, cv, x0, y0, x1, y1, r, color, tag='shape'):
        self.cv, self.tag = cv, tag; self.color = color; self.ids = []
        self.place(x0, y0, x1, y1, r)

    def place(self, x0, y0, x1, y1, r):
        cv = self.cv
        for i in self.ids: cv.delete(i)
        self.ids = []; w, h = x1 - x0, y1 - y0; r = max(0, min(r, w // 2, h // 2)); self.r = r
        if r == 0:
            self.ids.append(cv.create_rectangle(x0, y0, x1, y1, fill=self.color, width=0, tags=self.tag)); self.corners = []; self.rects = [self.ids[0]]; return
        self.corners = [cv.create_image(x, y, anchor='nw', image=photo(cv, ('corner', r, self.color, k), lambda k=k: corner_rgba(r, self.color, k)), tags=self.tag)
                        for k, x, y in (('tl', x0, y0), ('tr', x1 - r, y0), ('bl', x0, y1 - r), ('br', x1 - r, y1 - r))]
        self.rects = []
        if w - 2 * r > 0: self.rects.append(cv.create_rectangle(x0 + r, y0, x1 - r, y1, fill=self.color, width=0, tags=self.tag))
        if h - 2 * r > 0:
            self.rects.append(cv.create_rectangle(x0, y0 + r, x0 + r, y1 - r, fill=self.color, width=0, tags=self.tag))
            self.rects.append(cv.create_rectangle(x1 - r, y0 + r, x1, y1 - r, fill=self.color, width=0, tags=self.tag))
        self.ids = self.corners + self.rects

    def recolor(self, color):
        if color == self.color: return
        self.color = color
        for i in self.rects: self.cv.itemconfigure(i, fill=color)
        for k, i in zip(('tl', 'tr', 'bl', 'br'), self.corners): self.cv.itemconfigure(i, image=photo(self.cv, ('corner', self.r, color, k), lambda k=k: corner_rgba(self.r, color, k)))


def round_box(cv, x0, y0, x1, y1, r, fill, border=None, tag='shape'):
    """A rounded rectangle with an optional 1 px border (an outer shape in the border colour, the fill one pixel inside). Returns (outer or None, inner)."""
    if border:
        outer = Shape(cv, x0, y0, x1, y1, r, border, tag); return outer, Shape(cv, x0 + 1, y0 + 1, x1 - 1, y1 - 1, max(0, r - 1), fill, tag)
    return None, Shape(cv, x0, y0, x1, y1, r, fill, tag)


# ------------------------------------------------------------------------------------------------ pills (buttons) and glow
def _sdf(px, py, w, h, r):
    """Signed distance of the pixel centre to the rounded rectangle [0, w) x [0, h): negative inside."""
    qx = abs(px + .5 - w / 2) - (w / 2 - r); qy = abs(py + .5 - h / 2) - (h / 2 - r)
    return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r


def pill_rgba(w, h, c1, c2=None, border=None, bw=1, vert=0.0, radius=None):
    """A pill (fully round ends, or the given corner radius) w x h: filled c1 (a left-to-right gradient to c2), optional border, optional lighter top (vert). Soft edges."""
    r = h / 2.0 if radius is None else float(radius); f1, f2 = rgb(c1), rgb(c2 or c1); bc = rgb(border) if border else None
    buf = bytearray(w * h * 4); cap = int(math.ceil(r)) + 1
    grad = [tuple(f1[k] + (f2[k] - f1[k]) * x / max(1, w - 1) for k in range(3)) for x in range(w)]
    for y in range(h):
        hl = vert * max(0.0, 1 - y / (h * .55)); base = 4 * w * y
        for x in range(w):
            near_edge = x < cap or x >= w - cap or y < bw + 1 or y >= h - bw - 1
            g = grad[x]; col = (g[0] + (255 - g[0]) * hl, g[1] + (255 - g[1]) * hl, g[2] + (255 - g[2]) * hl)
            if not near_edge: buf[base + 4 * x:base + 4 * x + 4] = bytes((int(col[0] + .5), int(col[1] + .5), int(col[2] + .5), 255)); continue
            d = _sdf(x, y, w, h, r); acc = (0, 0, 0, 0)
            if bc: acc = _over(acc, _layer(bc, _clamp(.5 - d))); acc = _over(acc, _layer(col, _clamp(.5 - (d + bw))))
            else: acc = _over(acc, _layer(col, _clamp(.5 - d)))
            _put(buf, base + 4 * x, acc)
    return w, h, bytes(buf)


def glow_rgba(w, h, pad, color, strength=0.35, sigma=10.0, dy=6):
    """A soft shadow/glow under a pill: (w + 2 pad) x (h + 2 pad); the pill itself sits at (pad, pad)."""
    W, H = w + 2 * pad, h + 2 * pad; c = rgb(color); buf = bytearray(W * H * 4); r = h / 2.0
    for y in range(H):
        for x in range(W):
            d = _sdf(x - pad, y - pad - dy, w, h, r)
            if d > sigma * 2.2: continue
            a = strength * math.exp(-(max(d, 0) / sigma) ** 2)
            if a > .004: buf[4 * (y * W + x):4 * (y * W + x) + 4] = bytes((c[0], c[1], c[2], int(a * 255)))
    return W, H, bytes(buf)


# ------------------------------------------------------------------------------------------------ the progress ring
def ring_rgba(size, frac, thick, c1, c2, track, inner, rot=0.0, halo=None, halo_a=0.0, sigma=9.0, pad=None):
    """The status ring: a track, an arc of `frac` of the circle (clockwise from the top, shifted by rot turns) with round ends and a c1 -> c2 gradient, a filled inner
    disc and an optional soft halo around the arc. size x size pixels, radius chosen so the halo fits."""
    S_ = size; c = S_ / 2.0; hw = thick / 2.0; pad = (sigma * 2.4 if halo else 2) if pad is None else pad; R = c - pad - hw
    buf = bytearray(S_ * S_ * 4); fr = _clamp(frac); full = fr >= .9995; a0 = -math.pi / 2 + 2 * math.pi * rot; a1 = a0 + 2 * math.pi * fr
    p0 = (c + R * math.cos(a0), c + R * math.sin(a0)); p1 = (c + R * math.cos(a1), c + R * math.sin(a1))
    col1, col2, trk, inn = rgb(c1), rgb(c2), rgb(track), rgb(inner); hc = rgb(halo) if halo else None
    outer = R + hw + 1.5 + (sigma * 2.4 if halo else 0)
    for y in range(S_):
        dy = y + .5 - c
        if abs(dy) > outer: continue
        xo = math.sqrt(outer * outer - dy * dy); ri = R - hw - 1.2
        xi = math.sqrt(ri * ri - dy * dy) if abs(dy) < ri else 0.0
        if xi > 1:
            x_in0, x_in1 = int(c - xi) + 1, int(c + xi) - 1; row = bytes((inn[0], inn[1], inn[2], 255)) * max(0, x_in1 - x_in0 + 1); base = 4 * (y * S_ + x_in0); buf[base:base + len(row)] = row
        else: x_in0, x_in1 = int(c), int(c) - 1
        for x in list(range(max(0, int(c - xo)), min(S_, x_in0))) + list(range(max(0, x_in1 + 1), min(S_, int(c + xo) + 1))):
            dx = x + .5 - c; d = math.hypot(dx, dy); acc = (0, 0, 0, 0)
            ang = math.atan2(dy, dx); phi = ((ang - a0) % (2 * math.pi)) / (2 * math.pi); on_arc = full or phi <= fr
            if hc and halo_a > 0 and abs(d - R) < outer - R:
                dd = abs(d - R) if on_arc else min(math.hypot(x + .5 - p0[0], y + .5 - p0[1]), math.hypot(x + .5 - p1[0], y + .5 - p1[1]))
                ha = halo_a * math.exp(-(max(dd - hw, 0) / sigma) ** 2)
                if ha > .004: acc = _over(acc, _layer(hc, ha))
            ci = _clamp(R - hw + .5 - d)
            if ci > 0: acc = _over(acc, _layer(inn, ci))
            rc = _clamp(hw + .5 - abs(d - R))
            if rc > 0: acc = _over(acc, _layer(trk, rc))
            ac = rc if on_arc else 0.0
            if fr > 0 and not full: ac = max(ac, _clamp(hw + .5 - math.hypot(x + .5 - p0[0], y + .5 - p0[1])), _clamp(hw + .5 - math.hypot(x + .5 - p1[0], y + .5 - p1[1])))
            if ac > 0 and fr > 0:
                t = _clamp(((dx + dy) / (2 * R) + 1) / 2); acc = _over(acc, _layer(tuple(col1[k] + (col2[k] - col1[k]) * t for k in range(3)), ac))
            _put(buf, 4 * (y * S_ + x), acc)
    return S_, S_, bytes(buf)


def halo_rgba(size, thick, color, alpha=1.0, sigma=9.0, pad=None):
    """Only the soft halo of a full ring (for a pulse: scale its alpha with scale_alpha)."""
    c = size / 2.0; hw = thick / 2.0; pad = sigma * 2.4 if pad is None else pad; R = c - pad - hw; hc = rgb(color); buf = bytearray(size * size * 4); reach = sigma * 2.4 + hw
    for y in range(size):
        dy = y + .5 - c
        if abs(dy) > R + reach: continue
        for x in range(size):
            d = math.hypot(x + .5 - c, dy); dd = abs(d - R)
            if dd > reach: continue
            a = alpha * math.exp(-(max(dd - hw, 0) / sigma) ** 2)
            if a > .004: buf[4 * (y * size + x):4 * (y * size + x) + 4] = bytes((hc[0], hc[1], hc[2], int(a * 255)))
    return size, size, bytes(buf)


def scale_alpha(rgba, k):
    """The same image with every alpha multiplied by k (0..1): fast (a byte translation), used for the pulse."""
    buf = bytearray(rgba); table = bytes(min(255, int(i * k + .5)) for i in range(256)); buf[3::4] = buf[3::4].translate(table); return bytes(buf)


# ------------------------------------------------------------------------------------------------ line icons
def _arc(cx, cy, r, a0, a1, n=18):
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def _circle(cx, cy, r): return _arc(cx, cy, r, 0, 360, 28)


ICONS = {                                      # polylines on a 24 x 24 grid
    'power': [[(12, 2.5), (12, 12)], _arc(12, 12.93, 9, -44.7, 224.7, 30)],
    'check': [[(20, 6), (9, 17), (4, 12)]],
    'folder': [[(3, 17), (3, 7), (5, 5), (9, 5), (11, 7), (19, 7), (21, 9), (21, 17), (19, 19), (5, 19), (3, 17)]],
    'download': [[(12, 3), (12, 15)], [(7, 11), (12, 16), (17, 11)], [(5, 21), (19, 21)]],
    'sliders': [[(4, 6), (13, 6)], [(17, 6), (20, 6)], [(4, 12), (7, 12)], [(11, 12), (20, 12)], [(4, 18), (15, 18)], [(19, 18), (20, 18)], _circle(15, 6, 2), _circle(9, 12, 2), _circle(17, 18, 2)],
    'help': [_circle(12, 12, 9), [(9.5, 9.3), (10.2, 7.9), (11.6, 7.2), (13.1, 7.5), (14.2, 8.6), (14.3, 10), (13.4, 11.1), (12.4, 11.8), (12, 13.5)], [(12, 17), (12.02, 17)]],
    'disk': [[(5, 13), (7, 5), (17, 5), (19, 13)], [(3, 15), (5, 13), (19, 13), (21, 15), (21, 18), (19, 20), (5, 20), (3, 18), (3, 15)], [(7, 16.5), (7.02, 16.5)]],
    'wifi': [_arc(12, 19.14, 10, -134.4, -45.6, 12), _arc(12, 19.07, 5, -134.4, -45.6, 8), [(12, 19), (12.02, 19)]],
    'alert': [[(12, 3), (22, 20), (2, 20), (12, 3)], [(12, 10), (12, 14)], [(12, 17), (12.02, 17)]],
    'shield': [[(12, 3), (4, 6), (4, 12), (8, 18), (12, 21), (16, 18), (20, 12), (20, 6), (12, 3)], [(9, 12), (11, 14), (15, 10)]],
    'pause': [[(8, 5), (8, 19)], [(16, 5), (16, 19)]],
    'play': [[(7, 4), (20, 12), (7, 20), (7, 4)]],
    'bolt': [[(13, 2), (4, 14), (11, 14), (10, 22), (19, 10), (12, 10), (13, 2)]],
    'chart': [[(4, 19), (4, 5)], [(4, 19), (20, 19)], [(7, 15), (11, 10), (14, 13), (19, 6)]],
    'list': [[(8, 6), (20, 6)], [(8, 12), (20, 12)], [(8, 18), (20, 18)], [(4, 6), (4.02, 6)], [(4, 12), (4.02, 12)], [(4, 18), (4.02, 18)]],
    'arrow': [[(5, 12), (19, 12)], [(13, 6), (19, 12), (13, 18)]],
    'back': [[(19, 12), (5, 12)], [(11, 6), (5, 12), (11, 18)]],
    'x': [[(6, 6), (18, 18)], [(18, 6), (6, 18)]],
    'home': [[(3, 11), (12, 3), (21, 11)], [(5, 10), (5, 20), (19, 20), (19, 10)]],
    'gamepad': [[(6, 8), (18, 8), (21, 12), (21, 17), (18, 18), (16, 15), (8, 15), (6, 18), (3, 17), (3, 12), (6, 8)], [(8, 10.5), (8, 13.5)], [(6.5, 12), (9.5, 12)], [(16, 11.5), (16.02, 11.5)], [(18, 13), (18.02, 13)]],
    'refresh': [_arc(12, 12, 8, -30, 250, 22), [(20.5, 5), (20, 10), (15, 9.5)]],
    'globe': [_circle(12, 12, 9), [(3, 12), (21, 12)], [(12, 3), (8.5, 7.5), (7.8, 12), (8.5, 16.5), (12, 21)], [(12, 3), (15.5, 7.5), (16.2, 12), (15.5, 16.5), (12, 21)]],
    'trash': [[(4, 7), (20, 7)], [(9, 7), (9, 4), (15, 4), (15, 7)], [(6, 7), (7, 20), (17, 20), (18, 7)]],
}


def icon_rgba(name, px, color, width=1.8):
    """A line icon of the given pixel size and stroke colour (anti-aliased by distance to the stroke), as RGBA bytes."""
    k = px / 24.0; w = width * k; cov = [0.0] * (px * px); half = w / 2.0
    for line in ICONS[name]:
        pts = [(x * k, y * k) for x, y in line]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            x0, x1 = int(max(0, min(ax, bx) - half - 1)), int(min(px - 1, max(ax, bx) + half + 1)); y0, y1 = int(max(0, min(ay, by) - half - 1)), int(min(px - 1, max(ay, by) + half + 1))
            dx, dy = bx - ax, by - ay; L2 = dx * dx + dy * dy or 1e-9
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    t = _clamp(((x + .5 - ax) * dx + (y + .5 - ay) * dy) / L2); d = math.hypot(x + .5 - (ax + t * dx), y + .5 - (ay + t * dy)); v = _clamp(half + .5 - d)
                    if v > cov[y * px + x]: cov[y * px + x] = v
    c = rgb(color); buf = bytearray(px * px * 4)
    for i, v in enumerate(cov):
        if v > 0: buf[4 * i:4 * i + 4] = bytes((c[0], c[1], c[2], int(v * 255 + .5)))
    return px, px, bytes(buf)


def icon(master, name, px, color, width=1.8):
    return photo(master, ('icon', name, S(px), color, width), lambda: icon_rgba(name, S(px), color, width))


# ------------------------------------------------------------------------------------------------ animation ticker
class Ticker:
    """One shared timer for every animation. Jobs are fn(seconds); the timer only runs while at least one job exists. enabled = False (reduce motion) runs none."""
    def __init__(self, root, fps=24):
        self.root, self.jobs, self.after_id, self.enabled, self.ms, self.t0 = root, {}, None, True, int(1000 / fps), None

    def add(self, key, fn):
        if not self.enabled: return
        import time
        if self.t0 is None: self.t0 = time.time()
        self.jobs[key] = fn
        if self.after_id is None: self.after_id = self.root.after(self.ms, self._tick)

    def remove(self, key): self.jobs.pop(key, None)

    def set_enabled(self, on):
        self.enabled = bool(on)
        if not on: self.jobs.clear()

    def _tick(self):
        import time
        self.after_id = None; now = time.time() - (self.t0 or time.time())
        for key, fn in list(self.jobs.items()):
            try: fn(now)
            except tk.TclError: self.jobs.pop(key, None)                 # the widget is gone
        if self.jobs:
            try: self.after_id = self.root.after(self.ms, self._tick)
            except tk.TclError: pass


# ------------------------------------------------------------------------------------------------ widgets
class Button(tk.Canvas):
    """A pill button. kind = primary (gradient) | secondary (outlined) | ghost (text only, tint on hover) | warn (amber gradient). Keyboard: Tab, Space and Enter."""
    KINDS = dict(primary=dict(c1=ACCENT, c2=ACCENT2, fg=ON_ACCENT, glow=ACCENT), warn=dict(c1=WARN, c2='#f08a3c', fg=ON_ACCENT, glow=WARN),
                 secondary=dict(c1=CARD2, c2=None, fg=TEXT, border=LINE2), ghost=dict(c1=None, c2=None, fg=DIM))

    def __init__(self, parent, text, command=None, kind='secondary', icon_name=None, height=44, bg=BG, minwidth=0, px=15, pad=26):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, takefocus=1, cursor='hand2')
        self.text, self.command, self.kind, self.icon_name, self.h, self.px, self.pad, self.minw = text, command, kind, icon_name, S(height), px, S(pad), S(minwidth)
        self.state_, self.hover, self.down, self.has_focus = 'normal', False, False, False; self.spec = self.KINDS[kind]; self._items = []
        self.f = font(self, px, bold=True); self._draw()
        self.bind('<Enter>', lambda e: self._set(hover=True)); self.bind('<Leave>', lambda e: self._set(hover=False, down=False))
        self.bind('<ButtonPress-1>', lambda e: self._set(down=True)); self.bind('<ButtonRelease-1>', self._release)
        self.bind('<FocusIn>', lambda e: self._set(has_focus=True)); self.bind('<FocusOut>', lambda e: self._set(has_focus=False))
        self.bind('<space>', lambda e: self.invoke()); self.bind('<Return>', lambda e: self.invoke())

    # ---- public
    def cget_text(self): return self.text

    def set_text(self, text, icon_name=None):
        if text != self.text or (icon_name is not None and icon_name != self.icon_name):
            self.text = text
            if icon_name is not None: self.icon_name = icon_name
            self._draw()

    def set_kind(self, kind):
        if kind != self.kind: self.kind = kind; self.spec = self.KINDS[kind]; self._draw()

    def enable(self, on=True): self._set(state='normal' if on else 'disabled')

    def is_enabled(self): return self.state_ == 'normal'

    def invoke(self):
        if self.state_ == 'normal' and self.command: self.command()

    # ---- drawing
    def _width(self):
        tw = tkfont.Font(self, font=self.f).measure(i18n.t(self.text)); iw = S(self.px + 5) if self.icon_name else 0
        return max(self.minw, tw + iw + 2 * self.pad)

    def _look(self):
        sp = self.spec; st = self.state_
        if st == 'disabled': return dict(c1=CARD, c2=None, border=None, fg=FAINT)
        c1, c2, border, fg = sp['c1'], sp['c2'], sp.get('border'), sp['fg']
        if self.kind == 'ghost':
            return dict(c1=CARD if self.hover else None, c2=None, border=LINE if self.has_focus else None, fg=TEXT if self.hover else DIM)
        if self.down: c1, c2 = darken(c1, .12), darken(c2, .12) if c2 else None
        elif self.hover: c1, c2 = lighten(c1, .10), lighten(c2, .10) if c2 else None
        if self.has_focus: border = '#ffffff' if self.kind in ('primary', 'warn') else ACCENT
        return dict(c1=c1, c2=c2, border=border, fg=fg)

    def _draw(self):
        for i in self._items: self.delete(i)
        self._items = []; w, h = self._width(), self.h; look = self._look(); glow = self.spec.get('glow') and self.state_ == 'normal'; pad = S(16) if glow else 0
        self.configure(width=w + 2 * pad, height=h + 2 * pad)
        if glow:
            self._items.append(self.create_image(0, 0, anchor='nw', image=photo(self, ('glow', w, h, pad, self.spec['glow']), lambda: glow_rgba(w, h, pad, self.spec['glow'], .30, S(11), S(5)))))
        if look['c1']:
            bw = 2 if self.has_focus and look['border'] else 1
            self._items.append(self.create_image(pad, pad, anchor='nw', image=photo(self, ('pill', w, h, look['c1'], look['c2'], look['border'], bw, .10 if self.spec.get('c2') else 0.0), lambda: pill_rgba(w, h, look['c1'], look['c2'], look['border'], bw, .10 if self.spec.get('c2') else 0.0))))
        tw = tkfont.Font(self, font=self.f).measure(i18n.t(self.text)); iw = S(self.px + 5) if self.icon_name else 0; x = pad + (w - (tw + iw)) / 2; after = self.icon_name == 'arrow'      # an arrow points on: it follows the text
        if self.icon_name and not after:
            self._items.append(self.create_image(x, pad + h / 2, anchor='w', image=icon(self, self.icon_name, self.px + 1, look['fg'], 2.0))); x += iw
        self._items.append(self.create_text(x, pad + h / 2 - 1, anchor='w', text=self.text, fill=look['fg'], font=self.f))
        if after: self._items.append(self.create_image(x + tw + S(6), pad + h / 2, anchor='w', image=icon(self, 'arrow', self.px + 1, look['fg'], 2.0)))

    def _set(self, **kw):
        changed = False
        for k, v in kw.items():
            attr = 'state_' if k == 'state' else k
            if getattr(self, attr) != v: setattr(self, attr, v); changed = True
        if changed:
            self.configure(cursor='hand2' if self.state_ == 'normal' else 'arrow'); self._draw()

    def _release(self, e):
        was = self.down; self._set(down=False)
        if was and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height(): self.invoke()


class Panel(tk.Canvas):
    """A rounded card: `body` is the frame to put widgets in. The height follows the content; the width follows the parent."""
    def __init__(self, parent, bg=BG, fill=CARD, border=LINE, r=16, padx=18, pady=16, shrink=False):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, height=10); self.shrink = shrink
        self.fill, self.border, self.r, self.px, self.py = fill, border, S(r), S(padx), S(pady); self._cw = self._ch = 0; self._shapes = None; self.hover_fill = None
        self.body = tk.Frame(self, bg=fill); self._win = self.create_window(self.px, self.py, anchor='nw', window=self.body)
        self.bind('<Configure>', self._redraw); self.body.bind('<Configure>', self._fit); self._pending = []; self._dead = False
        self._pending.append(self.after_idle(self._after_layout))             # twice: the first idle lets the geometry managers run, the second reads the size they came to

    def _after_layout(self):
        if not self._dead: self._pending.append(self.after_idle(self._fit))

    def destroy(self):
        self._dead = True
        for a in self._pending:
            try: self.after_cancel(a)
            except tk.TclError: pass
        super().destroy()

    def _fit(self, e=None):
        if self._dead: return
        try:
            h = self.body.winfo_reqheight() + 2 * self.py
            if abs(int(self['height']) - h) > 0: self.configure(height=h)
            if self.shrink:
                w = self.body.winfo_reqwidth() + 2 * self.px
                if abs(int(self['width']) - w) > 0: self.configure(width=w)
        except tk.TclError: pass                                                     # the card was thrown away before its idle callback ran

    def _redraw(self, e=None):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4 or (w, h) == (self._cw, self._ch): return
        self._cw, self._ch = w, h; self.delete('shape'); self._shapes = round_box(self, 0, 0, w, h, self.r, self.fill, self.border); self.tag_lower('shape')
        if not self.shrink: self.itemconfigure(self._win, width=max(10, w - 2 * self.px))

    def style(self, fill=None, border=None):
        """Change the colours later (selected / hover)."""
        self.fill = fill or self.fill; self.border = border or self.border
        if self._shapes:
            if self._shapes[0]: self._shapes[0].recolor(self.border)
            self._shapes[1].recolor(self.fill)
        self.body.configure(bg=self.fill)
        for w in _walk(self.body):
            if isinstance(w, (tk.Label, tk.Frame)) and w.cget('bg') in (CARD, CARD2, '#141d33'): w.configure(bg=self.fill)


def _walk(w):
    yield w
    for c in w.winfo_children(): yield from _walk(c)


class Ring(tk.Canvas):
    """The status ring with text or an icon in the middle. set(kind, frac, icon, big, small): kind = off | on | work | full | warn | ok | prog (frac is the progress)."""
    TONE = dict(off=(('#2a3347', '#2a3347'), None, FAINT), on=((ACCENT, ACCENT2), ACCENT2, ACCENT2), work=((ACCENT, ACCENT2), ACCENT, ACCENT), full=((ACCENT, ACCENT2), ACCENT, TEXT),
                warn=((WARN, WARN), WARN, WARN), ok=((ACCENT, ACCENT2), OK, OK), prog=((ACCENT, ACCENT2), None, TEXT))

    def __init__(self, parent, d=220, thick=10, bg=BG, ticker=None):
        self.d, self.thick, self.pad = S(d), S(thick), S(26)
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, width=self.d + 2 * self.pad, height=self.d + 2 * self.pad)
        self.ticker, self.cfg = ticker, None; self._halo = self._ring = self._ic = None; self._texts = []; self._pulse_on = False; self._spin_on = False
        self.sz = self.d + 2 * self.pad

    def set(self, kind='off', frac=0.0, icon_name=None, big='', small='', halo=None):
        cfg = (kind, round(frac, 3), icon_name, big, small)
        if cfg == self.cfg: return
        self.cfg = cfg; (c1, c2), hcol, fg = self.TONE[kind]
        self._pulse(False); self._spin(False)
        for i in (self._ic,) + tuple(self._texts):
            if i: self.delete(i)
        self._texts = []; self._ic = None
        track = {'warn': '#3a2d10', 'ok': '#16301f'}.get(kind, '#1a2233')
        if kind == 'off': frac = 0.0
        elif kind in ('on', 'full', 'warn', 'ok'): frac = 1.0 if kind != 'warn' else 0.0
        elif kind == 'work': frac = 0.28
        self._draw_ring(kind, frac, c1, c2, track, hcol)
        cx = cy = self.sz / 2
        if icon_name:
            self._ic = self.create_image(cx, cy - (S(10) if small else 0), image=icon(self, icon_name, 60 if not small else 54, fg, 2.0))
        if big:
            self._texts.append(self.create_text(cx, cy - (S(8) if small else 0), text=big, fill=TEXT, font=font(self, 42, 'head', True)))
        if small:
            self._texts.append(self.create_text(cx, cy + (S(30) if big else S(34)), text=small, fill=fg if not big else DIM, font=font(self, 13 if big else 12, bold=not big)))
        if kind == 'on': self._pulse(True)
        if kind == 'work': self._spin(True)

    def _draw_ring(self, kind, frac, c1, c2, track, hcol, rot=0.0, hv=0.30):
        size, thick = self.sz, self.thick
        if self._halo: self.delete(self._halo); self._halo = None
        if self._ring: self.delete(self._ring); self._ring = None
        if hcol and kind != 'work':
            self._halo = self.create_image(0, 0, anchor='nw', image=self._halo_image(hcol, hv))
        self._ring = self.create_image(0, 0, anchor='nw', image=photo(self, ('ring', size, round(frac, 3), thick, c1, c2, track, round(rot, 3)),
                                                                      lambda: ring_rgba(size, frac, thick, c1, c2, track, '#0f1420', rot, None, 0.0, pad=self.pad)))

    def _halo_image(self, color, k):
        size, thick = self.sz, self.thick
        base = photo(self, ('halo-base', size, thick, color), lambda: halo_rgba(size, thick, color, 1.0, S(9), self.pad))        # kept so the variants can be made from it
        raw = self._base_bytes(color)
        return photo(self, ('halo', size, thick, color, round(k, 2)), lambda: (size, size, scale_alpha(raw, k)))

    def _base_bytes(self, color):
        root = self._root(); store = root.__dict__.setdefault('_ui_halo_raw', {}); key = (self.sz, self.thick, color)
        if key not in store: store[key] = halo_rgba(self.sz, self.thick, color, 1.0, S(9), self.pad)[2]
        return store[key]

    def _pulse(self, on):
        if on == self._pulse_on: return
        self._pulse_on = on
        if not self.ticker: return
        if not on: self.ticker.remove(id(self) * 3 + 1); return
        hcol = self.TONE[self.cfg[0]][1]; steps = (0.20, 0.27, 0.34, 0.27)
        def tick(t):
            if self._halo and self.winfo_viewable(): self.itemconfigure(self._halo, image=self._halo_image(hcol, steps[int(t * 2.2) % 4]))
        self.ticker.add(id(self) * 3 + 1, tick)

    def _spin(self, on):
        if on == self._spin_on: return
        self._spin_on = on
        if not self.ticker: return
        if not on: self.ticker.remove(id(self) * 3 + 2); return
        size, thick = self.sz, self.thick; (c1, c2), _, _ = self.TONE['work']
        def tick(t):
            rot = (int(t * 7) % 12) / 12.0
            if self._ring and self.winfo_viewable(): self.itemconfigure(self._ring, image=photo(self, ('ring', size, 0.28, thick, c1, c2, '#1a2233', round(rot, 3)), lambda: ring_rgba(size, .28, thick, c1, c2, '#1a2233', '#0f1420', rot, None, 0.0, pad=self.pad)))
        self.ticker.add(id(self) * 3 + 2, tick)


class Stepper(tk.Canvas):
    """The strip 'Game found - Turn on - Play - Done': steps before `cur` are ticked, `cur` is lit, the rest are dim. cur == len(labels) ticks them all."""
    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, height=S(40), width=S(560)); self.sig = None

    def set(self, labels, cur):
        sig = (tuple(labels), cur)
        if sig == self.sig: return
        self.sig = sig; self.delete('all'); r = S(13); gap = S(64); fnt = font(self, 14); fb = font(self, 14, bold=True); m = tkfont.Font(self, font=fnt); total = 0
        widths = [m.measure(i18n.t(t)) for t in labels]; total = sum(2 * r + S(10) + w for w in widths) + gap * (len(labels) - 1); x = (S(560) - total) / 2 if int(self['width']) >= total else 0
        self.configure(width=max(S(560), total + S(20))); x = (int(self['width']) - total) / 2; y = S(20)
        for i, (t, w) in enumerate(zip(labels, widths)):
            done, now = i < cur, i == cur
            if done: round_box(self, int(x), y - r, int(x) + 2 * r, y + r, r, OK)
            elif now: round_box(self, int(x) - 3, y - r - 3, int(x) + 2 * r + 3, y + r + 3, r + 3, '#16253f'); round_box(self, int(x), y - r, int(x) + 2 * r, y + r, r, BG, ACCENT)
            else: round_box(self, int(x), y - r, int(x) + 2 * r, y + r, r, BG, LINE2)
            if done: self.create_image(x + r, y, image=icon(self, 'check', 14, '#06180d', 2.4))
            else: self.create_text(x + r, y, text=str(i + 1), fill=ACCENT if now else FAINT, font=font(self, 12))
            self.create_text(x + 2 * r + S(10), y, anchor='w', text=t, fill=TEXT if now else DIM if done else FAINT, font=fb if now else fnt)
            x += 2 * r + S(10) + w
            if i < len(labels) - 1: self.create_rectangle(x + S(14), y - 1, x + gap - S(14), y, fill=OK if i < cur else LINE, width=0); x += gap


class NavItem(tk.Frame):
    """A row of the side navigation: icon, label, a bar on the left when selected."""
    def __init__(self, parent, text, icon_name, command, bg=BG2):
        super().__init__(parent, bg=bg, cursor='hand2'); self.bg, self.command, self.sel, self.label = bg, command, False, text
        self.bar = tk.Frame(self, width=S(3), bg=bg); self.bar.pack(side='left', fill='y')
        self.icon_name = icon_name; self.img = tk.Label(self, bg=bg, image=icon(self, icon_name, 18, DIM)); self.img.pack(side='left', padx=(S(12), S(10)), pady=S(9))
        self.lbl = tk.Label(self, text=text, bg=bg, fg=DIM, font=font(self, 14), anchor='w'); self.lbl.pack(side='left', fill='x', expand=True)
        for w in (self, self.img, self.lbl): w.bind('<Button-1>', lambda e: self.command()); w.bind('<Enter>', lambda e: self._paint(True)); w.bind('<Leave>', lambda e: self._paint(False))
        self.dot = None

    def select(self, on):
        self.sel = on; self._paint(False)

    def mark(self, text=None):
        """A little text/prefix (the spotlight arrow) shown before the label."""
        self.lbl.configure(text=(text or '') + self.label)

    def _paint(self, hover):
        bgc = CARD if (self.sel or hover) else self.bg; fg = TEXT if (self.sel or hover) else DIM
        for w in (self, self.img, self.lbl): w.configure(bg=bgc)
        self.lbl.configure(fg=fg, font=font(self, 14, bold=self.sel)); self.bar.configure(bg=ACCENT if self.sel else bgc)
        self.img.configure(image=icon(self, self.icon_name, 18, ACCENT if self.sel else (TEXT if hover else DIM)))


class ProgressBar(tk.Canvas):
    """A thin rounded progress bar: set(0..1). The filled part is the blue-to-teal gradient."""
    def __init__(self, parent, bg=BG, h=8):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, height=S(h)); self.h, self.frac = S(h), 0.0; self.bind('<Configure>', lambda e: self._draw())

    def set(self, frac):
        frac = _clamp(frac)
        if abs(frac - self.frac) > 0.0005: self.frac = frac; self._draw()

    def _draw(self):
        w = self.winfo_width()
        if w < 8: return
        self.delete('all'); round_box(self, 0, 0, w, self.h, self.h // 2, '#1a2233'); fw = int(w * self.frac)
        if fw >= self.h: self.create_image(0, 0, anchor='nw', image=photo(self, ('bar', fw, self.h), lambda: pill_rgba(fw, self.h, ACCENT, ACCENT2)))


class Segmented(tk.Canvas):
    """A row of choices where exactly one is on. options = [(value, label)]; command(value) runs on a click. enable(False) greys it out."""
    def __init__(self, parent, options, value, command, bg=BG, px=14, h=38):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, cursor='hand2'); self.options, self.value, self.command, self.px, self.h, self.on = list(options), value, command, px, S(h), True; self._hit = []
        self.bind('<Button-1>', self._click); self._draw()

    def set(self, value):
        if value != self.value: self.value = value; self._draw()

    def enable(self, on=True):
        if on != self.on: self.on = on; self.configure(cursor='hand2' if on else 'arrow'); self._draw()

    def _draw(self):
        self.delete('all'); f = font(self, self.px); m = tkfont.Font(self, font=f); ws = [m.measure(i18n.t(lab)) + 2 * S(18) for _, lab in self.options]; g = S(4); total = sum(ws) + 2 * g; self.configure(width=total, height=self.h)
        round_box(self, 0, 0, total, self.h, S(12), BG2, LINE); x = g; self._hit = []
        for (val, lab), w in zip(self.options, ws):
            sel = val == self.value
            if sel: round_box(self, x, g, x + w, self.h - g, S(9), CARD2 if self.on else CARD, LINE2)
            self.create_text(x + w / 2, self.h / 2 - 1, text=lab, fill=(TEXT if sel else DIM) if self.on else FAINT, font=font(self, self.px, bold=sel)); self._hit.append((x, x + w, val)); x += w

    def _click(self, e):
        if not self.on: return
        for a, b, val in self._hit:
            if a <= e.x < b:
                if val != self.value: self.value = val; self._draw(); self.command(val)
                return


def system_reduces_motion():
    """True when Windows has its own 'animation effects' switched off (Settings > Accessibility > Visual effects)."""
    try:
        import ctypes
        flag = ctypes.c_int(1); ok = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(flag), 0)           # SPI_GETCLIENTAREAANIMATION
        return bool(ok) and not flag.value
    except Exception:
        return False


class Scroll(tk.Frame):
    """A page that scrolls vertically when its content is taller than the window (mouse wheel too, except over a list or a text box, which scroll themselves).
    Put the widgets into `.body`. The body is at least as tall as the window, so widgets that expand still fill it."""
    SELF_SCROLLING = ('Text', 'Treeview', 'Listbox', 'TCombobox', 'Combobox')

    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg); from tkinter import ttk
        self.cv = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0); self.sb = ttk.Scrollbar(self, orient='vertical', command=self.cv.yview); self.cv.configure(yscrollcommand=self._set)
        self.cv.pack(side='left', fill='both', expand=True); self.body = ttk.Frame(self.cv, padding=(2, 6)); self._win = self.cv.create_window(0, 0, anchor='nw', window=self.body)
        self.body.bind('<Configure>', lambda e: self._fit()); self.cv.bind('<Configure>', lambda e: self._fit()); self.bind('<Enter>', self._enter); self.bind('<Leave>', self._leave)

    def _fit(self):
        w, h = self.cv.winfo_width(), self.cv.winfo_height()
        if w < 2: return
        self.cv.itemconfigure(self._win, width=w, height=max(h, self.body.winfo_reqheight())); self.cv.configure(scrollregion=(0, 0, w, max(h, self.body.winfo_reqheight())))

    def _set(self, a, b):
        if float(a) <= 0.0 and float(b) >= 1.0: self.sb.pack_forget()
        else:
            if not self.sb.winfo_ismapped(): self.sb.pack(side='right', fill='y')
        self.sb.set(a, b)

    def _enter(self, e=None): self.bind_all('<MouseWheel>', self._wheel)

    def _leave(self, e=None):
        x, y = self.winfo_pointerxy()
        if self.winfo_containing(x, y) is None or not str(self.winfo_containing(x, y)).startswith(str(self)): self.unbind_all('<MouseWheel>')

    def _wheel(self, e):
        if getattr(e.widget, 'winfo_class', lambda: '')() in self.SELF_SCROLLING: return
        if self.sb.winfo_ismapped(): self.cv.yview_scroll(-1 if e.delta > 0 else 1, 'units')
