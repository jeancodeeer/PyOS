# The pixel work of OpenGL: filling triangles, lines and points into a
# colour buffer (BGRA bytes, the pygame Surface itself) and a depth buffer.
# These loops run for every pixel, so they are viper (native code).
#
# Triangles come in a batch (all of one glEnd), as whole numbers:
#
#   verts   10 numbers per vertex: x, y (in 1/16 of a pixel), depth (0 near
#           .. DEPTH_MAX far), red, green, blue (0-255, x256), u, v, alpha
#           (0-255) and q. Texture coordinates are given divided by the
#           vertex's distance: u and v are texels x256 x q / 65536, with q
#           = 65536 for the nearest vertex. Dividing again by q at each
#           pixel puts the texture in perspective (no bending).
#   tris    3 vertex numbers per triangle
#   state   flags (below), cull (0 none, 1 back, 2 front, 3 both), front
#           faces go counter-clockwise (1) or not (0), and the rectangle
#           of pixels it may touch: x0, x1, y0, y1
#
# Flags: 1 depth test, 2 depth write, 4 texture, 8 texture x colour,
# 16 the depth test passes when equal too (GL_LEQUAL), 32 blend with alpha.
import micropython

DEPTH_TEST, DEPTH_WRITE, TEXTURE, MODULATE, LEQUAL, BLEND = 1, 2, 4, 8, 16, 32
VERTEX = 10


@micropython.viper
def triangles(color: ptr8, depth: ptr32, width: int, verts: ptr32, tris: ptr32, count: int,
              tex: ptr8, tw: int, th: int, state: ptr32):
    sign = 0x80000000                   # to read 32-bit numbers with their sign
    flags = int(state[0])
    cull = int(state[1])
    ccw = int(state[2])
    cx0 = int(state[3])
    cx1 = int(state[4])
    cy0 = int(state[5])
    cy1 = int(state[6])
    test = flags & 1
    write = flags & 2
    textured = flags & 4
    modulate = flags & 8
    lequal = flags & 16
    blend = flags & 32
    tmask = tw - 1
    hmask = th - 1
    n = 0
    while n < count:
        i0 = int(tris[n * 3]) * 10
        i1 = int(tris[n * 3 + 1]) * 10
        i2 = int(tris[n * 3 + 2]) * 10
        n += 1
        X0 = (int(verts[i0]) ^ sign) - sign
        Y0 = (int(verts[i0 + 1]) ^ sign) - sign
        X1 = (int(verts[i1]) ^ sign) - sign
        Y1 = (int(verts[i1 + 1]) ^ sign) - sign
        X2 = (int(verts[i2]) ^ sign) - sign
        Y2 = (int(verts[i2 + 1]) ^ sign) - sign
        den = (X1 - X0) * (Y2 - Y0) - (X2 - X0) * (Y1 - Y0)
        if den == 0:
            continue
        # on screen y points down: counter-clockwise for OpenGL is den < 0
        neg = 1 if den < 0 else 0
        front = 1 if neg == ccw else 0
        if cull == 3 or (cull == 1 and front == 0) or (cull == 2 and front == 1):
            continue
        if den < 0:                     # go round the same way every time
            t = i1
            i1 = i2
            i2 = t
            t = X1
            X1 = X2
            X2 = t
            t = Y1
            Y1 = Y2
            Y2 = t
            den = 0 - den
        # the pixels to visit
        minx = X0 if X0 < X1 else X1
        minx = minx if minx < X2 else X2
        maxx = X0 if X0 > X1 else X1
        maxx = maxx if maxx > X2 else X2
        miny = Y0 if Y0 < Y1 else Y1
        miny = miny if miny < Y2 else Y2
        maxy = Y0 if Y0 > Y1 else Y1
        maxy = maxy if maxy > Y2 else Y2
        minx = minx >> 4
        maxx = maxx >> 4
        miny = miny >> 4
        maxy = maxy >> 4
        if minx < cx0:
            minx = cx0
        if maxx > cx1:
            maxx = cx1
        if miny < cy0:
            miny = cy0
        if maxy > cy1:
            maxy = cy1
        if minx > maxx or miny > maxy:
            continue
        px = minx * 16 + 8              # the centre of the first pixel
        py = miny * 16 + 8
        # edge functions: >= 0 inside; their steps for one pixel right and down
        e0 = (py - Y0) * (X1 - X0) - (px - X0) * (Y1 - Y0)
        e0x = (Y0 - Y1) * 16
        e0y = (X1 - X0) * 16
        e1 = (py - Y1) * (X2 - X1) - (px - X1) * (Y2 - Y1)
        e1x = (Y1 - Y2) * 16
        e1y = (X2 - X1) * 16
        e2 = (py - Y2) * (X0 - X2) - (px - X2) * (Y0 - Y2)
        e2x = (Y2 - Y0) * 16
        e2y = (X0 - X2) * 16
        # each value (depth, colour, texture) is a plane over the triangle:
        # its value at the first pixel and its steps right and down, x65536
        ay = Y2 - Y0
        by = Y1 - Y0
        bx = X1 - X0
        cx = X2 - X0
        ox = px - X0
        oy = py - Y0
        k = 2
        while k < 10:
            if k == 8:
                k = 9                       # (8 is alpha: the same for the whole triangle)
            f0 = (int(verts[i0 + k]) ^ sign) - sign
            d1 = ((int(verts[i1 + k]) ^ sign) - sign) - f0
            d2 = ((int(verts[i2 + k]) ^ sign) - sign) - f0
            scale = 4096 if k == 2 else 256
            sx = (d1 * ay - d2 * by) * 16 * scale // den
            sy = (d2 * bx - d1 * cx) * 16 * scale // den
            st = f0 * scale + (sx * ox + sy * oy) // 16
            if k == 2:
                z0 = st
                zx = sx
                zy = sy
            elif k == 3:
                r0 = st
                rx = sx
                ry = sy
            elif k == 4:
                g0 = st
                gx = sx
                gy = sy
            elif k == 5:
                b0 = st
                bx_ = sx
                by_ = sy
            elif k == 6:
                u0 = st
                ux = sx
                uy = sy
            elif k == 7:
                v0 = st
                vx = sx
                vy = sy
            else:
                q0 = st
                qx = sx
                qy = sy
            k += 1
        alpha = int(verts[i0 + 8])
        y = miny
        while y <= maxy:
            a = e0
            b = e1
            c = e2
            z = z0
            r = r0
            g = g0
            bl = b0
            u = u0
            v = v0
            q = q0
            x = minx
            seen = 0
            while x <= maxx:
                if (a | b | c) >= 0:
                    seen = 1
                    o = y * width + x
                    zz = z >> 12
                    if test == 0 or zz < int(depth[o]) or (lequal and zz == int(depth[o])):
                        if write:
                            depth[o] = zz
                        cr = r >> 16
                        cg = g >> 16
                        cb = bl >> 16
                        if textured:
                            qq = q if q > 0 else 1
                            t = ((((v << 8) // qq) & hmask) * tw + (((u << 8) // qq) & tmask)) * 4
                            if modulate:
                                cr = (cr * int(tex[t]) + 128) >> 8
                                cg = (cg * int(tex[t + 1]) + 128) >> 8
                                cb = (cb * int(tex[t + 2]) + 128) >> 8
                            else:
                                cr = int(tex[t])
                                cg = int(tex[t + 1])
                                cb = int(tex[t + 2])
                        if cr > 255:
                            cr = 255
                        if cg > 255:
                            cg = 255
                        if cb > 255:
                            cb = 255
                        if cr < 0:
                            cr = 0
                        if cg < 0:
                            cg = 0
                        if cb < 0:
                            cb = 0
                        o4 = o * 4
                        if blend:
                            na = 255 - alpha
                            cb = (cb * alpha + int(color[o4]) * na) >> 8
                            cg = (cg * alpha + int(color[o4 + 1]) * na) >> 8
                            cr = (cr * alpha + int(color[o4 + 2]) * na) >> 8
                        color[o4] = cb
                        color[o4 + 1] = cg
                        color[o4 + 2] = cr
                        color[o4 + 3] = 255
                elif seen:
                    break                   # past the right edge of this row
                a += e0x
                b += e1x
                c += e2x
                z += zx
                r += rx
                g += gx
                bl += bx_
                u += ux
                v += vx
                q += qx
                x += 1
            e0 += e0y
            e1 += e1y
            e2 += e2y
            z0 += zy
            r0 += ry
            g0 += gy
            b0 += by_
            u0 += uy
            v0 += vy
            q0 += qy
            y += 1


@micropython.viper
def line(color: ptr8, depth: ptr32, width: int, height: int, x: int, y: int, z: int,
         dx: int, dy: int, n: int, zstep: int, bgr: int, flags: int):
    """A line of n + 1 pixels from (x, y): each step adds dx/dy (in 1/65536
    of a pixel) and zstep to the depth (also x65536)."""
    cb = bgr & 255
    cg = (bgr >> 8) & 255
    cr = (bgr >> 16) & 255
    i = 0
    while i <= n:
        px = x >> 16
        py = y >> 16
        if px >= 0 and px < width and py >= 0 and py < height:
            o = py * width + px
            zz = z >> 16
            if (flags & 1) == 0 or zz <= int(depth[o]):
                if flags & 2:
                    depth[o] = zz
                color[o * 4] = cb
                color[o * 4 + 1] = cg
                color[o * 4 + 2] = cr
                color[o * 4 + 3] = 255
        x += dx
        y += dy
        z += zstep
        i += 1


@micropython.viper
def fill32(buf: ptr32, count: int, value: int):
    """Set count 32-bit words to value (clearing colour or depth)."""
    i = 0
    while i < count:
        buf[i] = value
        i += 1


@micropython.viper
def rgb_to_rgba(src: ptr8, dst: ptr8, count: int):
    i = 0
    while i < count:
        dst[i * 4] = src[i * 3]
        dst[i * 4 + 1] = src[i * 3 + 1]
        dst[i * 4 + 2] = src[i * 3 + 2]
        dst[i * 4 + 3] = 255
        i += 1
