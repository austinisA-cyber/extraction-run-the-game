"""
Gothic Outfit - procedural Blender model generator
==================================================

Builds the gothic corset top + tiered ruffle skirt outfit (garments only, no
character) as clean, UV-mapped, material-assigned meshes.

Pieces
  Top   : corset (back lacing, boning, front buckle straps), bra cups with lace
          overlay + scalloped trim, choker, chest/back harness (X-back through
          O-rings), detached puff sleeves with ruffled cuffs and buckle bands.
  Skirt : waist belt + slanted hip belt (studs, buckles, O-rings), 4 ruffle
          tiers (black / black / red / tattered black lace), long open-front
          tattered lace overskirt, draped chains with cross pendants, thigh
          garter.

A hidden reference mannequin (collection "Reference_Body") is included for
fitting / cloth-sim collisions; it is excluded from renders and exports.

Usage
  Inside Blender : open this file in the Text Editor and press "Run Script".
                   (It rebuilds the outfit collections in the current file.)
  Headless       : blender -b -P build_gothic_outfit.py -- --export <out_dir> [--render]
  Python bpy     : python build_gothic_outfit.py --export <out_dir> [--render]

Units: metres, Z-up, character faces -Y (Blender "Front" view), ~1.68 m body.
"""

import bpy
import bmesh
import math
import os
import random
import sys
from mathutils import Vector, Matrix

TAU = 2.0 * math.pi
UP = Vector((0.0, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Small math helpers
# ---------------------------------------------------------------------------

def clamp(x, a, b):
    return a if x < a else b if x > b else x


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(e0, e1, x):
    t = clamp((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def smax(a, b, k=10.0):
    """Smooth maximum of two positive numbers."""
    return (a ** k + b ** k) ** (1.0 / k)


def wrap_angle(a):
    return (a + math.pi) % TAU - math.pi


def hermite_interp(keys, x):
    """Non-uniform Catmull-Rom interpolation. keys: [(x, value or tuple)]."""
    xs = [k[0] for k in keys]
    vals = [k[1] if isinstance(k[1], tuple) else (k[1],) for k in keys]
    n = len(keys)
    if x <= xs[0]:
        v = vals[0]
    elif x >= xs[-1]:
        v = vals[-1]
    else:
        i = 0
        while xs[i + 1] < x:
            i += 1
        x0, x1 = xs[i], xs[i + 1]
        h = x1 - x0
        t = (x - x0) / h

        def tangent(j):
            a = max(j - 1, 0)
            b = min(j + 1, n - 1)
            return [(vals[b][c] - vals[a][c]) / (xs[b] - xs[a]) for c in range(len(vals[0]))]

        m0, m1 = tangent(i), tangent(i + 1)
        t2, t3 = t * t, t * t * t
        h00 = 2 * t3 - 3 * t2 + 1
        h10 = t3 - 2 * t2 + t
        h01 = -2 * t3 + 3 * t2
        h11 = t3 - t2
        v = tuple(h00 * vals[i][c] + h10 * h * m0[c] + h01 * vals[i + 1][c] + h11 * h * m1[c]
                  for c in range(len(vals[0])))
    return v if len(v) > 1 else v[0]


def catmull_path(ctrl, per_seg=20):
    """Uniform Catmull-Rom through control tuples; returns dense list of tuples."""
    pts = [ctrl[0]] + list(ctrl) + [ctrl[-1]]
    out = []
    dim = len(ctrl[0])
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for s in range(per_seg):
            t = s / per_seg
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[c]) + (-p0[c] + p2[c]) * t +
                                    (2 * p0[c] - 5 * p1[c] + 4 * p2[c] - p3[c]) * t2 +
                                    (-p0[c] + 3 * p1[c] - 3 * p2[c] + p3[c]) * t3)
                             for c in range(dim)))
    out.append(tuple(ctrl[-1]))
    return out


def resample(points, n):
    """Resample a polyline of Vectors to n points evenly spaced by arc length."""
    d = [0.0]
    for a, b in zip(points, points[1:]):
        d.append(d[-1] + (b - a).length)
    total = d[-1]
    out = []
    j = 0
    for i in range(n):
        s = total * i / (n - 1)
        while j < len(d) - 2 and d[j + 1] < s:
            j += 1
        seg = d[j + 1] - d[j]
        t = 0.0 if seg < 1e-12 else (s - d[j]) / seg
        out.append(points[j].lerp(points[j + 1], t))
    return out, total


def any_perp(v):
    a = Vector((0, 0, 1)) if abs(v.z) < 0.9 else Vector((1, 0, 0))
    return v.cross(a).normalized()


# ---------------------------------------------------------------------------
# Body model (only used to fit the garments)
#   point(z, th): elliptical cross-sections, th = 0 is front (-Y), th = +pi/2
#   is the character's left side (+X).  Bust / glute bumps are added on top.
# ---------------------------------------------------------------------------

BODY_KEYS = [
    # z      half-width  half-depth  y-centre
    (0.05, (0.110, 0.060, 0.000)),
    (0.30, (0.130, 0.065, 0.000)),
    (0.45, (0.150, 0.075, 0.000)),
    (0.60, (0.165, 0.090, 0.004)),
    (0.72, (0.170, 0.102, 0.006)),
    (0.80, (0.174, 0.108, 0.008)),
    (0.88, (0.178, 0.110, 0.010)),
    (0.96, (0.156, 0.099, 0.008)),
    (1.04, (0.124, 0.084, 0.004)),
    (1.12, (0.128, 0.087, 0.004)),
    (1.18, (0.134, 0.090, 0.006)),
    (1.26, (0.148, 0.094, 0.010)),
    (1.34, (0.158, 0.088, 0.014)),
    (1.385, (0.160, 0.076, 0.016)),
    (1.42, (0.112, 0.066, 0.018)),
    (1.45, (0.060, 0.056, 0.018)),
    (1.50, (0.055, 0.053, 0.016)),
    (1.56, (0.054, 0.052, 0.012)),
]

BUMPS = [
    # z0,   th0,             sz_below, sz_above, sth,  amp
    (1.250, +0.60, 0.045, 0.075, 0.40, 0.050),   # bust L
    (1.250, -0.60, 0.045, 0.075, 0.40, 0.050),   # bust R
    (0.860, math.pi - 0.45, 0.07, 0.07, 0.45, 0.022),  # glute
    (0.860, math.pi + 0.45, 0.07, 0.07, 0.45, 0.022),
]


def body_params(z):
    return hermite_interp(BODY_KEYS, z)


def body_bump(z, th):
    total = 0.0
    for z0, th0, szb, sza, sth, amp in BUMPS:
        dz = z - z0
        sz = szb if dz < 0 else sza
        dth = wrap_angle(th - th0)
        total += amp * math.exp(-(dz / sz) ** 2 - (dth / sth) ** 2)
    return total


def body_point(z, th):
    a, b, cy = body_params(z)
    s, c = math.sin(th), math.cos(th)
    p = Vector((a * s, cy - b * c, z))
    n2 = Vector((s / a, -c / b, 0.0)).normalized()
    return p + n2 * body_bump(z, th)


def body_normal(z, th):
    h = 1e-4
    dth = body_point(z, th + h) - body_point(z, th - h)
    dz = body_point(z + h, th) - body_point(z - h, th)
    n = dth.cross(dz)
    if n.length < 1e-12:
        return Vector((math.sin(th), -math.cos(th), 0.0))
    return n.normalized()


def surf(z, th, off=0.0):
    return body_point(z, th) + body_normal(z, th) * off


def axis_at(z):
    return Vector((0.0, body_params(z)[2], z))


def horiz_dir(z, th):
    v = body_point(z, th) - axis_at(z)
    v.z = 0.0
    return v.normalized()


def body_radius(z, th, off=0.0):
    v = surf(z, th, off) - axis_at(z)
    v.z = 0.0
    return v.length


# ---------------------------------------------------------------------------
# Mesh building
# ---------------------------------------------------------------------------

class Part:
    """Accumulates geometry in a bmesh and turns it into an object."""

    def __init__(self, name):
        self.name = name
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")

    # -- generic quad grid -------------------------------------------------
    def grid(self, rows, closed_u=False, closed_v=False, center_fn=None,
             skip=None, smooth=True, flip=False):
        """rows[r][c] -> Vector. u runs along c, v along r.
        center_fn(r, face_center) -> point inside; faces are oriented to point away.
        skip(c, r) -> True to leave a hole."""
        bm = self.bm
        R, N = len(rows), len(rows[0])
        verts = [[bm.verts.new(p) for p in row] for row in rows]
        ncu = N if closed_u else N - 1
        ncv = R if closed_v else R - 1
        faces = []
        for r in range(ncv):
            r2 = (r + 1) % R
            for c in range(ncu):
                if skip and skip(c, r):
                    continue
                c2 = (c + 1) % N
                try:
                    f = bm.faces.new((verts[r][c], verts[r][c2], verts[r2][c2], verts[r2][c]))
                except ValueError:
                    continue
                u0, u1 = c / ncu, (c + 1) / ncu
                v0, v1 = r / ncv, (r + 1) / ncv
                for loop, uv in zip(f.loops, ((u0, v0), (u1, v0), (u1, v1), (u0, v1))):
                    loop[self.uv].uv = uv
                f.smooth = smooth
                faces.append((f, r))
        if center_fn is not None and faces:
            score = 0.0
            for f, r in faces:
                f.normal_update()
                fc = f.calc_center_median()
                score += f.normal.dot(fc - center_fn(r, fc))
            if (score < 0) != flip:
                bmesh.ops.reverse_faces(bm, faces=[f for f, _ in faces])
        return [f for f, _ in faces], verts

    # -- sweep a closed 2D profile along a framed path -----------------------
    def sweep(self, pts, normals, profile, closed_path=False, caps=True, smooth=True):
        """pts: list of Vectors, normals: per-point surface normal (profile y),
        profile: closed list of (x, y) in (binormal, normal) space."""
        n = len(pts)
        rows, centers = [], []
        for i in range(n):
            if closed_path:
                t = pts[(i + 1) % n] - pts[i - 1]
            else:
                t = pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]
            t.normalize()
            nn = normals[i] - t * normals[i].dot(t)
            if nn.length < 1e-9:
                nn = any_perp(t)
            nn.normalize()
            b = t.cross(nn).normalized()
            rows.append([pts[i] + b * px + nn * py for px, py in profile])
            cy = sum(p[1] for p in profile) / len(profile)
            cx = sum(p[0] for p in profile) / len(profile)
            centers.append(pts[i] + b * cx + nn * cy)
        faces, verts = self.grid(rows, closed_u=True, closed_v=closed_path,
                                 center_fn=lambda r, fc: centers[r], smooth=smooth)
        if caps and not closed_path:
            for idx, nb in ((0, 1), (n - 1, n - 2)):
                try:
                    f = self.bm.faces.new(verts[idx])
                except ValueError:
                    continue
                f.normal_update()
                if f.normal.dot(centers[idx] - centers[nb]) < 0:
                    bmesh.ops.reverse_faces(self.bm, faces=[f])
                f.smooth = False
        return faces

    def strap(self, pts, normals, width, thick, closed_path=False):
        prof = [(-width / 2, 0.0), (width / 2, 0.0), (width / 2, thick), (-width / 2, thick)]
        return self.sweep(pts, normals, prof, closed_path=closed_path, smooth=False)

    def tube(self, pts, radius, sides=8, closed_path=False, ref=None):
        # parallel-transported frame
        normals = []
        n = len(pts)
        t0 = (pts[1] - pts[0]).normalized()
        nrm = (ref - t0 * ref.dot(t0)).normalized() if ref is not None else any_perp(t0)
        for i in range(n):
            t = (pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized()
            nrm = (nrm - t * nrm.dot(t))
            if nrm.length < 1e-9:
                nrm = any_perp(t)
            nrm.normalize()
            normals.append(nrm.copy())
        prof = [(radius * math.cos(a * TAU / sides), radius * math.sin(a * TAU / sides))
                for a in range(sides)]
        return self.sweep(pts, normals, prof, closed_path=closed_path, smooth=True)

    # -- primitives ----------------------------------------------------------
    def torus(self, center, normal, u_dir, R, r, seg=16, sides=6, stretch=1.0):
        n = normal.normalized()
        u = (u_dir - n * u_dir.dot(n)).normalized()
        v = n.cross(u).normalized()
        rows, cents = [], []
        for i in range(seg):
            a = TAU * i / seg
            c = center + u * (R * math.cos(a)) + v * (R * stretch * math.sin(a))
            rad = (u * math.cos(a) + v * math.sin(a)).normalized()
            rows.append([c + rad * (r * math.cos(TAU * j / sides)) + n * (r * math.sin(TAU * j / sides))
                         for j in range(sides)])
            cents.append(c)
        faces, _ = self.grid(rows, closed_u=True, closed_v=True,
                             center_fn=lambda rr, fc: cents[rr], smooth=True)
        return faces

    def sphere(self, center, radius, useg=8, vseg=5, scale=(1, 1, 1), rot=None):
        m = Matrix.Translation(center)
        if rot is not None:
            m = m @ rot.to_4x4()
        m = m @ Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0))
        res = bmesh.ops.create_uvsphere(self.bm, u_segments=useg, v_segments=vseg,
                                        radius=radius, matrix=m, calc_uvs=True)
        vs = set(res["verts"])
        for f in {f for v in vs for f in v.link_faces}:
            f.smooth = True

    def stud(self, center, normal, radius):
        """Pyramid stud sitting on a surface."""
        n = normal.normalized()
        u = any_perp(n)
        v = n.cross(u)
        bm = self.bm
        base = [bm.verts.new(center + (u * math.cos(a) + v * math.sin(a)) * radius * 1.3)
                for a in (math.pi / 4 + k * math.pi / 2 for k in range(4))]
        tip = bm.verts.new(center + n * radius * 1.2)
        for i in range(4):
            f = bm.faces.new((base[i], base[(i + 1) % 4], tip))
            f.normal_update()
            if f.normal.dot(n) < 0:
                f.normal_flip()
        f = bm.faces.new(base)
        f.normal_update()
        if f.normal.dot(n) > 0:
            f.normal_flip()

    def cross(self, top, up, normal, height, thick):
        """Gothic cross with flared, pointed ends. `top` is the hanging point."""
        up = up.normalized()
        n = (normal - up * normal.dot(up)).normalized()
        right = up.cross(n).normalized()
        # arm outline in units of height; centre of crossing at origin
        hw = 0.055
        arms = [((0, 1), 0.30), ((-1, 0), 0.27), ((0, -1), 0.62), ((1, 0), 0.27)]
        pts2 = []
        for (dx, dy), L in arms:
            D = (dx, dy)
            P = (dy, -dx)  # right-hand side of the arm

            def add(p_amt, d_amt):
                pts2.append((P[0] * p_amt + D[0] * d_amt, P[1] * p_amt + D[1] * d_amt))
            add(hw, hw)
            add(hw, L - 0.13)
            add(0.035, L - 0.10)
            add(0.11, L - 0.07)
            add(0.075, L - 0.02)
            add(0.0, L + 0.05)
            add(-0.075, L - 0.02)
            add(-0.11, L - 0.07)
            add(-0.035, L - 0.10)
            add(-hw, L - 0.13)
        centre = top - up * (0.35 * height)
        bm = self.bm
        vs = [bm.verts.new(centre + right * (x * height) + up * (y * height)) for x, y in pts2]
        f = bm.faces.new(vs)
        f.normal_update()
        if f.normal.dot(n) > 0:
            f.normal_flip()
        ext = bmesh.ops.extrude_face_region(bm, geom=[f])
        new_verts = [e for e in ext["geom"] if isinstance(e, bmesh.types.BMVert)]
        bmesh.ops.translate(bm, vec=n * thick, verts=new_verts)
        faces = list({ff for v in vs + new_verts for ff in v.link_faces})
        bmesh.ops.recalc_face_normals(bm, faces=faces)
        for ff in faces:
            ff.smooth = False
        # raised centre boss
        self.sphere(centre + n * thick, height * 0.05, useg=10, vseg=6, scale=(1, 1, 0.5),
                    rot=Matrix((right, up, n)).transposed())
        # bail ring
        self.torus(top + up * height * 0.035, right, up, height * 0.05, height * 0.012, seg=12, sides=5)

    def buckle(self, center, normal, along, w, h, wire=0.0016):
        n = normal.normalized()
        t = (along - n * along.dot(n)).normalized()
        b = n.cross(t).normalized()
        pts = []
        steps = 32
        for i in range(steps):
            a = TAU * i / steps
            ca, sa = math.cos(a), math.sin(a)
            x = w / 2 * math.copysign(abs(ca) ** 0.35, ca)
            y = h / 2 * math.copysign(abs(sa) ** 0.35, sa)
            pts.append(center + t * x + b * y)
        self.tube(pts, wire, sides=6, closed_path=True, ref=n)
        # centre bar + prong
        self.tube([center - b * (h / 2), center + b * (h / 2)], wire * 0.8, sides=6, ref=n)
        self.tube([center + n * wire, center + t * (w / 2) + n * wire * 1.2], wire * 0.6, sides=5, ref=n)

    def chain(self, path, link_R=0.0045, wire=0.0011, stretch=1.45):
        pitch = 2.0 * (link_R * stretch - wire) * 0.98
        pts, length = resample(path, max(3, int(sum((b - a).length for a, b in zip(path, path[1:])) / pitch) + 1))
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            t = (b - a).normalized()
            p1 = t.cross(UP)
            if p1.length < 1e-6:
                p1 = Vector((1, 0, 0))
            p1.normalize()
            p2 = t.cross(p1).normalized()
            nrm = p1 if i % 2 == 0 else p2
            self.torus((a + b) * 0.5, nrm, nrm.cross(t), link_R, wire, seg=12, sides=4, stretch=stretch)
        return pts

    # -- finalize ------------------------------------------------------------
    def to_object(self, collection, material=None, solidify=0.0, solidify_offset=1.0,
                  subsurf=0, parent=None):
        me = bpy.data.meshes.new(self.name)
        bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts, dist=1e-7)
        self.bm.to_mesh(me)
        self.bm.free()
        me.update()
        ob = bpy.data.objects.new(self.name, me)
        collection.objects.link(ob)
        if material is not None:
            me.materials.append(material)
        if solidify > 0:
            m = ob.modifiers.new("Solidify", "SOLIDIFY")
            m.thickness = solidify
            m.offset = solidify_offset
            m.use_even_offset = True
            m.use_quality_normals = True
        if subsurf > 0:
            m = ob.modifiers.new("Subdivision", "SUBSURF")
            m.levels = subsurf
            m.render_levels = subsurf
        if parent is not None:
            ob.parent = parent
        return ob


def path_on_body(ctrl, samples=60):
    """ctrl: [(z, th, off)] -> (points, normals) evenly spaced."""
    dense = catmull_path(ctrl, per_seg=24)
    pts = [surf(z, th, off) for z, th, off in dense]
    nrms = [body_normal(z, th) for z, th, off in dense]
    # resample positions by arc length, carry normals by nearest-index lerp
    d = [0.0]
    for a, b in zip(pts, pts[1:]):
        d.append(d[-1] + (b - a).length)
    total = d[-1]
    out_p, out_n = [], []
    j = 0
    for i in range(samples):
        s = total * i / (samples - 1)
        while j < len(d) - 2 and d[j + 1] < s:
            j += 1
        seg = d[j + 1] - d[j]
        t = 0.0 if seg < 1e-12 else (s - d[j]) / seg
        out_p.append(pts[j].lerp(pts[j + 1], t))
        out_n.append(nrms[j].lerp(nrms[j + 1], t).normalized())
    return out_p, out_n


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

def _principled(mat):
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    return nt, bsdf


def _set(bsdf, name, value):
    if name in bsdf.inputs:
        bsdf.inputs[name].default_value = value


def make_materials():
    mats = {}

    # Leather: dark, semi-gloss with fine grain bump
    m = bpy.data.materials.new("GO_Leather_Black")
    nt, b = _principled(m)
    _set(b, "Base Color", (0.018, 0.016, 0.017, 1))
    _set(b, "Roughness", 0.32)
    _set(b, "Coat Weight", 0.12)
    _set(b, "Coat Roughness", 0.2)
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 900.0
    noise.inputs["Detail"].default_value = 4.0
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.12
    bump.inputs["Distance"].default_value = 0.0005
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    m.diffuse_color = (0.03, 0.03, 0.03, 1)
    mats["leather"] = m

    # Satin / chiffon black
    m = bpy.data.materials.new("GO_Satin_Black")
    nt, b = _principled(m)
    _set(b, "Base Color", (0.014, 0.012, 0.014, 1))
    _set(b, "Roughness", 0.42)
    _set(b, "Sheen Weight", 0.8)
    _set(b, "Sheen Roughness", 0.35)
    _set(b, "Sheen Tint", (0.5, 0.45, 0.5, 1))
    _set(b, "Specular IOR Level", 0.35)
    m.diffuse_color = (0.02, 0.02, 0.02, 1)
    m.use_backface_culling = False
    mats["satin"] = m

    # Blood red satin
    m = bpy.data.materials.new("GO_Satin_Red")
    nt, b = _principled(m)
    _set(b, "Base Color", (0.16, 0.004, 0.012, 1))
    _set(b, "Roughness", 0.5)
    _set(b, "Sheen Weight", 0.7)
    _set(b, "Sheen Tint", (0.9, 0.3, 0.35, 1))
    m.diffuse_color = (0.25, 0.01, 0.02, 1)
    m.use_backface_culling = False
    mats["red"] = m

    # Procedural lace (alpha-cut net + floral blobs)
    def lace(name, color, net_scale, density):
        m = bpy.data.materials.new(name)
        nt, b = _principled(m)
        _set(b, "Base Color", color)
        _set(b, "Roughness", 0.55)
        _set(b, "Sheen Weight", 0.5)
        tc = nt.nodes.new("ShaderNodeTexCoord")
        vor = nt.nodes.new("ShaderNodeTexVoronoi")
        vor.feature = "DISTANCE_TO_EDGE"
        vor.inputs["Scale"].default_value = net_scale
        nt.links.new(tc.outputs["Object"], vor.inputs["Vector"])
        ramp1 = nt.nodes.new("ShaderNodeValToRGB")
        ramp1.color_ramp.elements[0].position = 0.0
        ramp1.color_ramp.elements[0].color = (1, 1, 1, 1)
        ramp1.color_ramp.elements[1].position = 0.06
        ramp1.color_ramp.elements[1].color = (0, 0, 0, 1)
        nt.links.new(vor.outputs["Distance"], ramp1.inputs["Fac"])
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = net_scale * 0.18
        noise.inputs["Detail"].default_value = 3.0
        nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
        ramp2 = nt.nodes.new("ShaderNodeValToRGB")
        ramp2.color_ramp.elements[0].position = density
        ramp2.color_ramp.elements[0].color = (0, 0, 0, 1)
        ramp2.color_ramp.elements[1].position = density + 0.04
        ramp2.color_ramp.elements[1].color = (1, 1, 1, 1)
        nt.links.new(noise.outputs["Fac"], ramp2.inputs["Fac"])
        mx = nt.nodes.new("ShaderNodeMath")
        mx.operation = "MAXIMUM"
        nt.links.new(ramp1.outputs["Color"], mx.inputs[0])
        nt.links.new(ramp2.outputs["Color"], mx.inputs[1])
        nt.links.new(mx.outputs["Value"], b.inputs["Alpha"])
        m.use_backface_culling = False
        for attr, val in (("surface_render_method", "DITHERED"), ("blend_method", "HASHED")):
            try:
                setattr(m, attr, val)
            except (AttributeError, TypeError):
                pass
        m.diffuse_color = (color[0], color[1], color[2], 1)
        return m

    mats["lace"] = lace("GO_Lace_Black", (0.012, 0.010, 0.012, 1), 180.0, 0.64)
    mats["lace_sheer"] = lace("GO_Lace_Sheer", (0.014, 0.010, 0.012, 1), 140.0, 0.68)

    # Antique silver hardware
    m = bpy.data.materials.new("GO_Metal_AntiqueSilver")
    nt, b = _principled(m)
    _set(b, "Metallic", 1.0)
    _set(b, "Roughness", 0.26)
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 250.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.30, 0.29, 0.28, 1)
    ramp.color_ramp.elements[1].color = (0.80, 0.78, 0.75, 1)
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[1].position = 0.6
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    m.diffuse_color = (0.6, 0.6, 0.6, 1)
    mats["metal"] = m

    # Mannequin clay
    m = bpy.data.materials.new("GO_Ref_Clay")
    nt, b = _principled(m)
    _set(b, "Base Color", (0.55, 0.53, 0.52, 1))
    _set(b, "Roughness", 0.7)
    mats["clay"] = m
    return mats


# ---------------------------------------------------------------------------
# TOP
# ---------------------------------------------------------------------------

CORSET_GAP = 0.13  # back lacing opening, radians either side of back centre


def corset_z(th):
    """(bottom, top) edge heights of the corset for body angle th."""
    a = abs(wrap_angle(th))
    front = max(0.0, 1.0 - a / 0.45)
    back = smoothstep(1.6, math.pi, a)
    bottom = 1.010 - 0.030 * front ** 1.5 - 0.008 * back
    # top: point between the cups, dips under them, lower at back
    under_cup = math.exp(-((a - 0.62) / 0.35) ** 2)
    top = 1.190 + 0.028 * front ** 2 - 0.012 * under_cup - 0.022 * back
    return bottom, top


def build_corset(part, piping, hw, rng):
    N, M = 128, 26
    th0, th1 = -math.pi + CORSET_GAP, math.pi - CORSET_GAP
    seams = [0.0, 0.42, -0.42, 0.95, -0.95, 1.5, -1.5, 2.1, -2.1, 2.65, -2.65]
    rows = []
    for r in range(M):
        v = r / (M - 1)
        row = []
        for c in range(N):
            th = lerp(th0, th1, c / (N - 1))
            zb, zt = corset_z(th)
            z = lerp(zb, zt, v)
            groove = sum(math.exp(-(wrap_angle(th - s) / 0.018) ** 2) for s in seams)
            off = 0.005 - 0.0012 * groove + 0.0008 * math.sin(math.pi * v)
            row.append(surf(z, th, off))
        rows.append(row)
    part.grid(rows, center_fn=lambda r, fc: axis_at(fc.z))

    # piping on top / bottom edges and along the lacing opening
    for which in (0, 1):
        pts = []
        for c in range(N):
            th = lerp(th0, th1, c / (N - 1))
            z = corset_z(th)[which]
            pts.append(surf(z, th, 0.0075))
        piping.tube(pts, 0.0022, sides=6)
    for th in (th0, th1):
        zb, zt = corset_z(th)
        pts = [surf(lerp(zb, zt, i / 20), th, 0.0075) for i in range(21)]
        piping.tube(pts, 0.0022, sides=6)

    # front buckle straps
    for k, z in enumerate((1.145, 1.095, 1.045)):
        ctrl = [(z + 0.004 * math.cos(t * 2), t, 0.0095) for t in (-0.95, -0.5, 0.0, 0.5, 0.95)]
        pts, nrms = path_on_body(ctrl, samples=50)
        piping.strap(pts, nrms, 0.016, 0.0028)
        bth = 0.34 if k % 2 == 0 else -0.34
        bz = z + 0.004 * math.cos(bth * 2)
        hw.buckle(surf(bz, bth, 0.0135), body_normal(bz, bth),
                  body_normal(bz, bth + 0.01).cross(UP) * -1 + (surf(bz, bth + 0.01) - surf(bz, bth)),
                  0.020, 0.024)
        for sth in (-0.85, -0.62, 0.62, 0.85):
            sz = z + 0.004 * math.cos(sth * 2)
            hw.stud(surf(sz, sth, 0.0122), body_normal(sz, sth), 0.0026)

    # front cross emblems between the straps
    for z, h in ((1.128, 0.034), (1.075, 0.030)):
        hw.cross(surf(z, 0.0, 0.0085), UP, body_normal(z, 0.0), h, 0.0022)
    # small side crosses
    for th in (-0.72, 0.72):
        hw.cross(surf(1.128, th, 0.0085), UP, body_normal(1.128, th), 0.024, 0.0018)

    # back lacing: grommets + criss-cross lace + hanging tails
    gth = math.pi - CORSET_GAP - 0.045
    zs = [lerp(1.025, 1.150, i / 6) for i in range(7)]
    for z in zs:
        for s in (1, -1):
            th = s * gth
            hw.torus(surf(z, th, 0.0082), body_normal(z, th), UP, 0.0034, 0.0012, seg=12, sides=5)
    for i in range(len(zs) - 1):
        for s in (1, -1):
            a = surf(zs[i], s * gth, 0.0095)
            b = surf(zs[i + 1], -s * gth, 0.0095)
            mid = (a + b) * 0.5 + Vector((0, 0.004, 0))
            piping.tube([a, mid, b], 0.0014, sides=6)
    # bow tails from the top grommets
    for s in (1, -1):
        top = surf(zs[-1], s * gth, 0.0095)
        tail = [top + Vector((s * 0.004 * k, 0.003 + 0.002 * k, -0.018 * k - 0.002 * k * k)) for k in range(6)]
        piping.tube(tail, 0.0014, sides=6)
        loop = [top + Vector((s * (0.012 * math.sin(a)), 0.006 + 0.004 * math.sin(a), 0.012 * (1 - math.cos(a)) * 0.6))
                for a in [i * TAU / 16 for i in range(17)]]
        piping.tube(loop, 0.0014, sides=6)


def cup_edges(s):
    """Return z_bot, z_top for cup parameter s in [0 (centre), 1 (side)]."""
    z_bot = 1.192 - 0.022 * math.sin(math.pi * s) ** 0.8
    z_top = 1.226 + 0.074 * (1 - (1 - s) ** 2)
    return z_bot, z_top


def build_cups(cups, lace, side_sign):
    th_in, th_out = 0.07, 1.14
    N, M = 34, 24
    rows = []
    for r in range(M):
        v = r / (M - 1)
        row = []
        for c in range(N):
            s = c / (N - 1)
            th = side_sign * lerp(th_in, th_out, s)
            zb, zt = cup_edges(s)
            row.append(surf(lerp(zb, zt, v), th, 0.0100))
        rows.append(row)
    cups.grid(rows, center_fn=lambda r, fc: axis_at(fc.z))

    # lace overlay over the cup
    rows = []
    for r in range(M):
        v = r / (M - 1)
        row = []
        for c in range(N):
            s = c / (N - 1)
            th = side_sign * lerp(th_in, th_out, s)
            zb, zt = cup_edges(s)
            row.append(surf(lerp(zb, zt, v), th, 0.0138))
        rows.append(row)
    lace.grid(rows, center_fn=lambda r, fc: axis_at(fc.z))

    # scalloped lace trim along the top edge (stands up slightly, flares out)
    rows = []
    Ns = 90
    for r in range(6):
        v = r / 5
        row = []
        for c in range(Ns):
            s = c / (Ns - 1)
            th = side_sign * lerp(th_in, th_out, s)
            zb, zt = cup_edges(s)
            sc = 0.55 + 0.45 * abs(math.sin(math.pi * s * 8.5))
            h = 0.018 * sc * v
            row.append(surf(zt - 0.002 + h, th, 0.0132 + 0.004 * v * v))
        rows.append(row)
    lace.grid(rows, center_fn=lambda r, fc: axis_at(fc.z))


def build_choker_and_harness(harness, hw):
    # choker band
    zc = 1.474
    pts = [surf(zc, TAU * i / 72, 0.0035) for i in range(72)]
    nrms = [body_normal(zc, TAU * i / 72) for i in range(72)]
    harness.strap(pts, nrms, 0.034, 0.0035, closed_path=True)
    # studs along the choker
    for i in range(18):
        th = TAU * (i + 0.5) / 18
        if abs(wrap_angle(th)) < 0.35:
            continue
        for dz in (-0.009, 0.009):
            hw.stud(surf(zc + dz, th, 0.0072), body_normal(zc + dz, th), 0.0022)
    # front buckle, O-ring and hanging cross
    n0 = body_normal(zc, 0.0)
    hw.buckle(surf(zc, 0.0, 0.0078), n0, Vector((1, 0, 0)), 0.024, 0.030)
    ring_c = surf(1.447, 0.0, 0.010)
    hw.torus(ring_c, n0, Vector((1, 0, 0)), 0.0085, 0.0019)
    hw.cross(ring_c - UP * 0.009, UP, n0 + Vector((0, 0, 0.1)), 0.050, 0.0030)

    W, T = 0.014, 0.0028
    # centre strap: choker ring -> sternum O-ring -> cup gore
    for ctrl in ([(1.452, 0.0, 0.006), (1.40, 0.0, 0.006), (1.355, 0.0, 0.006)],
                 [(1.325, 0.0, 0.007), (1.27, 0.0, 0.009), (1.215, 0.0, 0.012)]):
        p, n = path_on_body(ctrl, 30)
        harness.strap(p, n, W * 0.85, T)
    ring2 = 1.340
    hw.torus(surf(ring2, 0.0, 0.009), body_normal(ring2, 0.0), Vector((1, 0, 0)), 0.011, 0.0022)

    for s in (1, -1):
        # halter V: choker side -> outer top of cup
        p, n = path_on_body([(1.462, s * 0.50, 0.004), (1.40, s * 0.45, 0.006), (1.34, s * 0.70, 0.008),
                             (1.305, s * 1.02, 0.013), (1.285, s * 1.16, 0.014)], 60)
        harness.strap(p, n, W, T)
        hw.torus(surf(1.284, s * 1.17, 0.0165), body_normal(1.284, s * 1.17), UP, 0.0075, 0.0018)
        # sternum ring -> shoulder -> over shoulder crest -> back ring -> opposite lower back
        p, n = path_on_body([(1.342, s * 0.12, 0.009), (1.36, s * 0.55, 0.007), (1.375, s * 1.0, 0.006),
                             (1.402, s * 1.35, 0.006), (1.412, s * math.pi / 2, 0.006),
                             (1.40, s * (math.pi - 1.3), 0.006), (1.35, s * (math.pi - 0.75), 0.007),
                             (1.29, s * (math.pi - 0.15), 0.008), (1.27, s * math.pi, 0.009),
                             (1.215, s * (math.pi + 0.45), 0.008), (1.172, s * (math.pi + 0.95), 0.0085)], 120)
        harness.strap(p, n, W, T)
        # buckle on the front shoulder strap
        bz, bth = 1.372, s * 0.92
        hw.buckle(surf(bz, bth, 0.0095), body_normal(bz, bth),
                  surf(1.40, s * 1.35) - surf(1.36, s * 0.55), 0.018, 0.020)
        for k in range(3):
            th = s * (0.35 + 0.18 * k)
            z = 1.36 + 0.004 * k
            hw.stud(surf(z, th, 0.0092), body_normal(z, th), 0.0022)

    # bra back band (runs under the X straps, above the corset back)
    for s in (1, -1):
        p, n = path_on_body([(1.212, s * 1.08, 0.0105), (1.206, s * 1.5, 0.0065), (1.198, s * 2.2, 0.0055),
                             (1.194, s * 2.8, 0.0055), (1.193, s * math.pi, 0.0055)], 50)
        harness.strap(p, n, 0.020, 0.0024)
    for dz in (-0.005, 0.005):
        hw.stud(surf(1.193 + dz, math.pi - 0.05, 0.008), body_normal(1.193, math.pi), 0.0018)

    # back: choker -> back ring
    p, n = path_on_body([(1.460, math.pi, 0.004), (1.40, math.pi, 0.006), (1.28, math.pi, 0.009)], 40)
    harness.strap(p, n, W * 0.85, T)
    hw.torus(surf(1.27, math.pi, 0.0125), body_normal(1.27, math.pi), UP, 0.012, 0.0024)
    hw.cross(surf(1.44, math.pi, 0.0075), UP, body_normal(1.44, math.pi), 0.036, 0.0022)


# --- sleeves -----------------------------------------------------------------

ARM_ANGLE = math.radians(28.0)
SLEEVE_R = [(0.075, 0.075), (0.086, 0.066), (0.097, 0.058), (0.114, 0.058), (0.16, 0.080),
            (0.25, 0.091), (0.33, 0.081), (0.372, 0.060), (0.39, 0.042), (0.422, 0.042),
            (0.45, 0.053), (0.50, 0.069), (0.548, 0.086)]
SLEEVE_A = [(0.075, 0.007), (0.09, 0.003), (0.10, 0.0), (0.115, 0.0), (0.14, 0.004),
            (0.25, 0.0055), (0.35, 0.004), (0.385, 0.0), (0.425, 0.0), (0.445, 0.004),
            (0.548, 0.013)]
ARM_R = [(0.0, 0.050), (0.12, 0.046), (0.26, 0.040), (0.30, 0.035), (0.36, 0.036),
         (0.50, 0.028), (0.56, 0.026)]


def arm_frame(s):
    S = Vector((s * 0.172, 0.006, 1.372))
    d = Vector((s * math.sin(ARM_ANGLE), 0.0, -math.cos(ARM_ANGLE)))
    e_side = Vector((s * math.cos(ARM_ANGLE), 0.0, math.sin(ARM_ANGLE)))
    e_fwd = Vector((0.0, -1.0, 0.0))
    return S, d, e_side, e_fwd


def build_sleeve(part, straps, hw, s, seed):
    S, d, e_side, e_fwd = arm_frame(s)
    N, M = 64, 72
    t0, t1 = 0.075, 0.548
    rows, cents = [], []
    for r in range(M):
        t = lerp(t0, t1, r / (M - 1))
        base = hermite_interp(SLEEVE_R, t)
        amp = hermite_interp(SLEEVE_A, t)
        # gravity: the puff sags a little toward -Z (in arm frame ~ along d)
        sag = 0.012 * math.sin(math.pi * clamp((t - 0.12) / 0.26, 0, 1))
        row = []
        for c in range(N):
            ph = TAU * c / N
            freq = 16 if t > 0.12 else 22
            wob = 0.8 * math.sin(3 * ph + seed + 6 * t)
            R = base + amp * math.sin(freq * ph + wob)
            radial = e_side * math.cos(ph) + e_fwd * math.sin(ph)
            # hem of cuff ripples along the arm too
            tt = t + (0.006 * math.sin(14 * ph + seed) if t > 0.53 else 0.0)
            row.append(S + d * (tt + sag) + radial * R)
        rows.append(row)
        cents.append(S + d * t)
    part.grid(rows, closed_u=True, center_fn=lambda r, fc: cents[r])

    # buckle bands
    for tb, w in ((0.105, 0.017), (0.396, 0.012), (0.414, 0.012)):
        R = hermite_interp(SLEEVE_R, tb) + 0.0035
        pts, nrms = [], []
        for c in range(64):
            ph = TAU * c / 64
            radial = e_side * math.cos(ph) + e_fwd * math.sin(ph)
            pts.append(S + d * tb + radial * R)
            nrms.append(radial)
        straps.strap(pts, nrms, w, 0.0026, closed_path=True)
        ph = -0.6
        radial = e_side * math.cos(ph) + e_fwd * math.sin(ph)
        tang = (e_side * -math.sin(ph) + e_fwd * math.cos(ph))
        hw.buckle(S + d * tb + radial * (R + 0.0045), radial, tang, w * 1.25, w * 1.5)
        for ph2 in (0.9, 1.9, 2.9, 3.9):
            radial = e_side * math.cos(ph2) + e_fwd * math.sin(ph2)
            hw.stud(S + d * tb + radial * (R + 0.0026), radial, 0.002)
    # little dangling cross on the upper band
    ph = 0.25
    radial = e_side * math.cos(ph) + e_fwd * math.sin(ph)
    R = hermite_interp(SLEEVE_R, 0.105) + 0.008
    hw.torus(S + d * 0.112 + radial * R, radial, d, 0.005, 0.0012)
    hw.cross(S + d * 0.118 + radial * (R + 0.002), -d, radial, 0.030, 0.0018)


# ---------------------------------------------------------------------------
# SKIRT
# ---------------------------------------------------------------------------

def silhouette(z, th):
    """Outer bell silhouette radius of the skirt (horizontal, from body axis)."""
    zc = max(z, 0.88)
    base = body_radius(zc, th, 0.015)
    bell = 0.30 * (1.0 - math.exp(-max(0.0, 0.955 - z) / 0.085))
    return base * (1.0 + bell)


class Tier:
    def __init__(self, name, z_top, hem_f, hem_b, off, folds, amp, mat,
                 jag=0.0, teeth=0, seed=0, ripple=0.005):
        self.name, self.z_top, self.hem_f, self.hem_b = name, z_top, hem_f, hem_b
        self.off, self.folds, self.amp, self.mat = off, folds, amp, mat
        self.jag, self.teeth, self.seed, self.ripple = jag, teeth, seed, ripple
        rng = random.Random(seed)
        self.tooth_rand = [0.35 + 0.65 * rng.random() for _ in range(max(teeth, 1))]

    def hem(self, th):
        z = lerp(self.hem_f, self.hem_b, (1 - math.cos(th)) / 2)
        z += self.ripple * math.sin(self.folds * th + 0.7 * math.sin(3 * th + self.seed))
        if self.teeth:
            x = (th % TAU) / TAU * self.teeth
            i = int(x) % self.teeth
            tri = 1.0 - abs(2.0 * (x - int(x)) - 1.0)
            z -= self.jag * self.tooth_rand[i] * tri ** 1.6
        return z

    def u(self, z, th):
        return clamp((self.z_top - z) / max(1e-6, self.z_top - self.hem(th)), 0.0, 1.0)

    def radius(self, z, th, with_folds=True):
        u = self.u(z, th)
        eps = -0.012 + 0.040 * u ** 1.6
        r = smax(silhouette(z, th) + eps, body_radius(z, th, self.off), 12.0)
        a = self.amp * u ** 0.8
        if with_folds:
            r += a * math.sin(self.folds * th + 0.7 * math.sin(3 * th + self.seed))
        return r, a

    def point(self, z, th):
        r, _ = self.radius(z, th)
        return axis_at(z) + horiz_dir(z, th) * r + Vector((0, 0, 0))


def build_tier(part, tier, N=200, M=20):
    rows = []
    for r in range(M):
        v = r / (M - 1)
        row = []
        for c in range(N):
            th = TAU * c / N
            z = lerp(tier.z_top, tier.hem(th), v)
            p = tier.point(z, th)
            p.z = z
            row.append(p)
        rows.append(row)
    part.grid(rows, closed_u=True, center_fn=lambda r, fc: axis_at(fc.z))


class Overskirt:
    """Long, open-front, tattered lace high-low layer under the ruffle tiers."""
    th0 = 1.0
    z_top = 0.935

    def __init__(self, seed=11):
        rng = random.Random(seed)
        self.teeth = 15
        self.tooth_rand = [0.4 + 0.6 * rng.random() for _ in range(self.teeth)]
        self.slits = []
        for i in range(12):
            u = (i + 0.5 + 0.35 * (rng.random() - 0.5)) / 12
            self.slits.append((u, lerp(0.35, 0.6, rng.random())))

    def th(self, u):
        return lerp(self.th0, TAU - self.th0, u)

    def hem(self, u):
        th = self.th(u)
        w = smoothstep(0.0, 0.14, u) * smoothstep(0.0, 0.14, 1 - u)
        z = lerp(0.72, 0.34, w) + 0.03 * math.cos(th) * w
        x = u * self.teeth
        i = min(int(x), self.teeth - 1)
        tri = 1.0 - abs(2.0 * (x - int(x)) - 1.0)
        z -= 0.085 * self.tooth_rand[i] * tri ** 1.4 * (0.3 + 0.7 * w)
        return z

    def radius(self, z, th):
        k = clamp((0.80 - z) / 0.30, 0.0, 1.0)
        r = smax(silhouette(z, th) - 0.030 + 0.020 * k, body_radius(z, th, 0.010), 12.0)
        a = 0.004 + 0.020 * k
        return r, a

    def point(self, z, th, seed=0.0):
        r, a = self.radius(z, th)
        r += a * math.sin(19 * th + 0.9 * math.sin(2 * th + 1.3))
        p = axis_at(z) + horiz_dir(z, th) * r
        p.z = z
        return p


def build_overskirt(part, ov, N=220, M=44):
    rows = []
    for r in range(M):
        v = r / (M - 1)
        row = []
        for c in range(N):
            u = c / (N - 1)
            th = ov.th(u)
            z = lerp(ov.z_top, ov.hem(u), v ** 0.9)
            row.append(ov.point(z, th))
        rows.append(row)
    slit_cols = {}
    for u, frac in ov.slits:
        c = int(u * (N - 1))
        for cc in (c, c + 1):
            slit_cols[cc] = frac

    def skip(c, r):
        f = slit_cols.get(c)
        return f is not None and r / (M - 1) > 1 - f

    part.grid(rows, center_fn=lambda r, fc: axis_at(fc.z), skip=skip)


def skirt_outer(z, th, tiers):
    """Radius just outside every skirt layer at (z, th)."""
    best = body_radius(z, th, 0.02)
    for t in tiers:
        if t.hem(th) - 0.01 <= z <= t.z_top + 0.01:
            r, a = t.radius(z, th, with_folds=False)
            best = max(best, r + a)
    return best


def polar_theta(p):
    """Inverse of the body ellipse param for a world point (approximate)."""
    a, b, cy = body_params(clamp(p.z, 0.05, 1.56))
    return math.atan2(p.x / a, -(p.y - cy) / b)


def push_out(p, tiers, clearance=0.005):
    th = polar_theta(p)
    need = skirt_outer(p.z, th, tiers) + clearance
    c = axis_at(p.z)
    v = p - c
    v.z = 0.0
    if v.length < need:
        v = v.normalized() * need if v.length > 1e-6 else horiz_dir(p.z, th) * need
        return Vector((c.x + v.x, c.y + v.y, p.z))
    return p


def build_skirt_hardware(belts, hw, garter, tiers):
    # -- waist belt (straight) ----------------------------------------------
    zb = 0.950
    N = 96
    pts = [surf(zb, TAU * i / N, 0.027) for i in range(N)]
    nrms = [body_normal(zb, TAU * i / N) for i in range(N)]
    belts.strap(pts, nrms, 0.034, 0.0038, closed_path=True)
    for i in range(40):
        th = TAU * (i + 0.5) / 40
        if abs(wrap_angle(th + 0.25)) < 0.12:
            continue
        hw.stud(surf(zb, th, 0.0312), body_normal(zb, th), 0.0028)
    bth = -0.25
    hw.buckle(surf(zb, bth, 0.0335), body_normal(zb, bth),
              surf(zb, bth + 0.02) - surf(zb, bth), 0.034, 0.042, wire=0.0022)

    # -- slanted hip belt over the first ruffle -------------------------------
    def hip_z(th):
        return 0.912 + 0.020 * math.sin(th + 0.7)

    def hip_pt(th, extra=0.0):
        z = hip_z(th)
        r = skirt_outer(z, th, tiers) + 0.002 + extra
        p = axis_at(z) + horiz_dir(z, th) * r
        p.z = z
        return p

    pts = [hip_pt(TAU * i / N) for i in range(N)]
    nrms = [horiz_dir(hip_z(TAU * i / N), TAU * i / N) for i in range(N)]
    belts.strap(pts, nrms, 0.026, 0.0035, closed_path=True)
    for i in range(32):
        th = TAU * (i + 0.5) / 32
        hw.stud(hip_pt(th, 0.0036), horiz_dir(hip_z(th), th), 0.0024)
    bth = 0.62
    hw.buckle(hip_pt(bth, 0.0055), horiz_dir(hip_z(bth), bth), hip_pt(bth + 0.02) - hip_pt(bth),
              0.028, 0.034, wire=0.002)

    # -- O-rings and chains ---------------------------------------------------
    def ring_at(th, belt="waist"):
        if belt == "waist":
            p = surf(zb - 0.017, th, 0.034)
            n = body_normal(zb, th)
        else:
            p = hip_pt(th, 0.005) - UP * 0.013
            n = horiz_dir(hip_z(th), th)
        hw.torus(p - UP * 0.006, n, UP, 0.0075, 0.0017)
        return p - UP * 0.013

    def drape(a, b, sag, n=40):
        out = []
        for i in range(n):
            t = i / (n - 1)
            p = a.lerp(b, t) - UP * (sag * 4 * t * (1 - t))
            out.append(push_out(p, tiers, 0.006))
        return out

    def hang(a, length, n=30, swing=0.0):
        out = []
        for i in range(n):
            t = i / (n - 1)
            p = a - UP * (length * t) + horiz_dir(a.z, polar_theta(a)) * (swing * t * t)
            out.append(push_out(p, tiers, 0.006))
        return out

    # front swags
    swags = [((-0.95, "hip"), (0.35, "waist"), 0.070),
             ((-0.55, "waist"), (1.05, "hip"), 0.115),
             ((-1.25, "waist"), (-0.35, "hip"), 0.050),
             ((math.pi - 0.85, "waist"), (math.pi + 0.75, "hip"), 0.080),
             ((math.pi - 1.15, "hip"), (math.pi + 0.40, "waist"), 0.125)]
    rings = {}
    for (tha, ba), (thb, bb), sag in swags:
        for th, bl in ((tha, ba), (thb, bb)):
            if (th, bl) not in rings:
                rings[(th, bl)] = ring_at(th, bl)
        hw.chain(drape(rings[(tha, ba)], rings[(thb, bb)], sag))

    # dangling chains with crosses
    for th, bl, length, h in ((0.35, "waist", 0.20, 0.060), (-0.55, "waist", 0.11, 0.045),
                              (1.05, "hip", 0.30, 0.070), (-0.95, "hip", 0.07, 0.040),
                              (math.pi + 0.35, "waist", 0.24, 0.060), (math.pi - 0.5, "hip", 0.16, 0.050)):
        a = rings.get((th, bl)) or ring_at(th, bl)
        path = hang(a, length)
        end = hw.chain(path)[-1]
        th2 = polar_theta(end)
        hw.cross(end, UP, horiz_dir(end.z, th2), h, 0.0028)

    # -- thigh garter (character's right leg, -X) ------------------------------
    gz = 0.615
    cx, cy = -0.090, 0.004
    ra, rb = 0.074, 0.078
    N = 64
    pts, nrms = [], []
    for i in range(N):
        a = TAU * i / N
        dvec = Vector((math.sin(a) * ra, -math.cos(a) * rb, 0.0))
        nrm = Vector((math.sin(a) / ra, -math.cos(a) / rb, 0.0)).normalized()
        pts.append(Vector((cx, cy, gz)) + dvec + nrm * 0.002)
        nrms.append(nrm)
    garter.strap(pts, nrms, 0.022, 0.0032, closed_path=True)
    # lace ruffle on the garter band
    rows = []
    for k in range(4):
        v = k / 3
        row = []
        for i in range(N * 2):
            a = TAU * i / (N * 2)
            nrm = Vector((math.sin(a) / ra, -math.cos(a) / rb, 0.0)).normalized()
            base = Vector((cx, cy, gz)) + Vector((math.sin(a) * ra, -math.cos(a) * rb, 0.0))
            wave = 0.004 * math.sin(26 * a) * v
            row.append(base + nrm * (0.004 + 0.008 * v + wave) + UP * (0.011 + 0.014 * v))
        rows.append(row)
    garter.grid(rows, closed_u=True, center_fn=lambda r, fc: Vector((cx, cy, fc.z)))
    a_b = -0.7  # buckle front-outer
    nb = Vector((math.sin(a_b) / ra, -math.cos(a_b) / rb, 0.0)).normalized()
    pb = Vector((cx, cy, gz)) + Vector((math.sin(a_b) * ra, -math.cos(a_b) * rb, 0.0)) + nb * 0.0075
    hw.buckle(pb, nb, Vector((math.cos(a_b), math.sin(a_b), 0.0)), 0.020, 0.028)
    # suspender strap from under the skirt down to the garter, with O-ring
    a_s = -0.25
    ns = Vector((math.sin(a_s) / ra, -math.cos(a_s) / rb, 0.0)).normalized()
    ps = Vector((cx, cy, gz + 0.011)) + Vector((math.sin(a_s) * ra, -math.cos(a_s) * rb, 0.0)) + ns * 0.004
    top = Vector((-0.115, -0.105, 0.80))
    ringp = top.lerp(ps, 0.45) + ns * 0.004
    for a, b in ((top, ringp + UP * 0.009), (ringp - UP * 0.009, ps)):
        path = [a.lerp(b, i / 11) for i in range(12)]
        garter.strap(path, [ns] * 12, 0.014, 0.0028)
    hw.torus(ringp, ns, UP, 0.0085, 0.002)
    hw.cross(ringp - UP * 0.01 + ns * 0.004, UP, ns, 0.030, 0.002)


# ---------------------------------------------------------------------------
# Reference mannequin (hidden)
# ---------------------------------------------------------------------------

def build_mannequin(part):
    N, M = 64, 60
    rows = []
    for r in range(M):
        z = lerp(0.78, 1.60, r / (M - 1))
        rows.append([body_point(z, TAU * c / N) for c in range(N)])
    part.grid(rows, closed_u=True, center_fn=lambda r, fc: axis_at(fc.z))
    part.sphere(Vector((0, 0.015, 1.655)), 0.095, useg=24, vseg=16, scale=(0.92, 1.1, 1.2))
    # legs
    leg_r = [(0.86, 0.095), (0.75, 0.085), (0.62, 0.073), (0.47, 0.050), (0.38, 0.052),
             (0.25, 0.043), (0.10, 0.030), (0.05, 0.030)]
    for s in (1, -1):
        rows, cents = [], []
        for r in range(40):
            z = lerp(0.88, 0.05, r / 39)
            c = Vector((s * (0.092 - 0.010 * (0.86 - z) / 0.81), 0.006, z))
            rad = hermite_interp(leg_r, z)
            rows.append([c + Vector((math.sin(a) * rad, -math.cos(a) * rad * 1.05, 0))
                         for a in (TAU * k / 32 for k in range(32))])
            cents.append(c)
        part.grid(rows, closed_u=True, center_fn=lambda r, fc, cents=cents: cents[r])
        S, d, e_side, e_fwd = arm_frame(s)
        rows, cents = [], []
        for r in range(40):
            t = lerp(-0.02, 0.56, r / 39)
            rad = hermite_interp(ARM_R, t)
            rows.append([S + d * t + (e_side * math.cos(a) + e_fwd * math.sin(a)) * rad
                         for a in (TAU * k / 24 for k in range(24))])
            cents.append(S + d * t)
        part.grid(rows, closed_u=True, center_fn=lambda r, fc, cents=cents: cents[r])
        part.sphere(S + d * 0.62, 0.045, useg=16, vseg=10, scale=(0.6, 1.0, 1.4))


# ---------------------------------------------------------------------------
# Scene assembly
# ---------------------------------------------------------------------------

def new_collection(name, parent):
    old = bpy.data.collections.get(name)
    if old is not None:
        for ob in list(old.objects):
            bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.collections.remove(old)
    col = bpy.data.collections.new(name)
    parent.children.link(col)
    return col


def build(scene=None):
    scene = scene or bpy.context.scene
    rng = random.Random(1234)
    old_root = bpy.data.objects.get("Gothic_Outfit")
    if old_root is not None:
        bpy.data.objects.remove(old_root, do_unlink=True)
    mats = make_materials()
    root_col = new_collection("Gothic_Outfit", scene.collection)
    top_col = new_collection("Outfit_Top", root_col)
    skirt_col = new_collection("Outfit_Skirt", root_col)
    ref_col = new_collection("Reference_Body", scene.collection)

    root = bpy.data.objects.new("Gothic_Outfit", None)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.2
    root_col.objects.link(root)

    # ---- top
    corset = Part("Top_Corset")
    top_straps = Part("Top_Straps")
    top_hw = Part("Top_Hardware")
    build_corset(corset, top_straps, top_hw, rng)
    cups = Part("Top_Bra_Cups")
    lace = Part("Top_Bra_Lace")
    for s in (1, -1):
        build_cups(cups, lace, s)
    harness = Part("Top_Harness")
    build_choker_and_harness(harness, top_hw)
    sleeve_straps = Part("Top_Sleeve_Straps")
    sleeves = []
    for s, nm in ((1, "L"), (-1, "R")):
        sp = Part("Top_Sleeve_" + nm)
        build_sleeve(sp, sleeve_straps, top_hw, s, seed=2.0 + s)
        sleeves.append(sp)

    corset.to_object(top_col, mats["leather"], solidify=0.0035, subsurf=1, parent=root)
    top_straps.to_object(top_col, mats["leather"], parent=root)
    cups.to_object(top_col, mats["satin"], solidify=0.0025, subsurf=1, parent=root)
    lace.to_object(top_col, mats["lace"], subsurf=1, parent=root)
    harness.to_object(top_col, mats["leather"], parent=root)
    for sp in sleeves:
        sp.to_object(top_col, mats["satin"], solidify=0.0018, subsurf=1, parent=root)
    sleeve_straps.to_object(top_col, mats["leather"], parent=root)
    top_hw.to_object(top_col, mats["metal"], parent=root)

    # ---- skirt
    tiers = [
        Tier("Skirt_Ruffle_1", 0.948, 0.862, 0.850, 0.022, 34, 0.010, "satin", seed=1),
        Tier("Skirt_Ruffle_2", 0.915, 0.815, 0.798, 0.019, 30, 0.013, "satin", seed=2),
        Tier("Skirt_Ruffle_3_Red", 0.885, 0.772, 0.752, 0.016, 28, 0.015, "red",
             jag=0.018, teeth=30, seed=3),
        Tier("Skirt_Ruffle_4_Lace", 0.860, 0.742, 0.715, 0.013, 26, 0.016, "lace",
             jag=0.045, teeth=26, seed=4),
    ]
    for t in tiers:
        p = Part(t.name)
        build_tier(p, t)
        thick = 0.0 if t.mat == "lace" else 0.0016
        p.to_object(skirt_col, mats[t.mat], solidify=thick, subsurf=1, parent=root)
    ov = Overskirt()
    p = Part("Skirt_Overskirt_Tattered")
    build_overskirt(p, ov)
    p.to_object(skirt_col, mats["lace_sheer"], subsurf=1, parent=root)

    belts = Part("Skirt_Belts")
    skirt_hw = Part("Skirt_Hardware")
    garter = Part("Skirt_Garter")
    build_skirt_hardware(belts, skirt_hw, garter, tiers)
    belts.to_object(skirt_col, mats["leather"], parent=root)
    garter.to_object(skirt_col, mats["leather"], parent=root)
    skirt_hw.to_object(skirt_col, mats["metal"], parent=root)

    # garter lace ruffle got leather; give it its own lace slot
    g = bpy.data.objects["Skirt_Garter"]
    g.data.materials.append(mats["lace"])
    # faces belonging to the ruffle are the ones above the band
    for poly in g.data.polygons:
        if poly.center.z > 0.615 + 0.0115:
            poly.material_index = 1

    # ---- reference mannequin
    man = Part("Ref_Mannequin")
    build_mannequin(man)
    mob = man.to_object(ref_col, mats["clay"], subsurf=1)
    mob.hide_render = True
    mob.hide_set(True) if bpy.context.view_layer.objects.get(mob.name) else None
    mob.display_type = "SOLID"
    lc = bpy.context.view_layer.layer_collection.children.get("Reference_Body")
    if lc is not None:
        lc.hide_viewport = True
    return root


# ---------------------------------------------------------------------------
# Headless export / preview render
# ---------------------------------------------------------------------------

def setup_preview(scene):
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 64
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 900
    scene.render.resolution_y = 1350
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    world = bpy.data.worlds.new("GO_World")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.02, 0.02, 0.024, 1)
    bg.inputs["Strength"].default_value = 1.0
    scene.world = world

    def area(name, loc, energy, size, color=(1, 1, 1)):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy = energy
        ld.size = size
        ld.color = color
        ob = bpy.data.objects.new(name, ld)
        ob.location = loc
        d = Vector((0, 0, 0.95)) - Vector(loc)
        ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        scene.collection.objects.link(ob)

    area("Key", (-1.6, -2.4, 2.2), 260, 1.8)
    area("Fill", (2.2, -1.8, 1.2), 70, 2.5, (0.85, 0.88, 1.0))
    area("RimL", (-1.8, 2.2, 1.9), 320, 1.2, (1.0, 0.8, 0.8))
    area("RimR", (1.9, 2.0, 1.6), 260, 1.2)
    area("Front", (0.0, -3.0, 0.9), 40, 3.0)
    area("BackFill", (0.0, 3.0, 0.9), 40, 3.0)

    cd = bpy.data.cameras.new("PreviewCam")
    cd.type = "ORTHO"
    cd.ortho_scale = 1.36
    cam = bpy.data.objects.new("PreviewCam", cd)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


def render_views(scene, cam, out_dir, views):
    paths = []
    target = Vector((0.0, 0.0, 0.93))
    for name, yaw in views:
        a = math.radians(yaw)
        cam.location = target + Vector((math.sin(a) * 4.0, -math.cos(a) * 4.0, 0.0))
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        path = os.path.join(out_dir, "preview_%s.png" % name)
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        paths.append(path)
    return paths


def export(out_dir, render=False):
    os.makedirs(out_dir, exist_ok=True)
    scene = bpy.context.scene
    # glTF: outfit only (mannequin excluded)
    bpy.ops.object.select_all(action="DESELECT")
    for ob in bpy.data.collections["Gothic_Outfit"].all_objects:
        ob.select_set(True)
    bpy.ops.export_scene.gltf(filepath=os.path.join(out_dir, "gothic_outfit.glb"),
                              export_format="GLB", use_selection=True, export_apply=True,
                              export_yup=True)
    bpy.ops.export_scene.fbx(filepath=os.path.join(out_dir, "gothic_outfit.fbx"),
                             use_selection=True, use_mesh_modifiers=True, axis_forward="-Z",
                             axis_up="Y", apply_scale_options="FBX_SCALE_ALL")
    if render:
        cam = setup_preview(scene)
        views = [("front", 0), ("three_quarter", 35), ("side", 90), ("back", 180)]
        only = os.environ.get("GO_VIEWS")
        if only:
            views = [v for v in views if v[0] in only.split(",")]
        render_views(scene, cam, out_dir, views)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "gothic_outfit.blend"), compress=True)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    if "--export" in argv:
        out_dir = os.path.abspath(argv[argv.index("--export") + 1])
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        scene.unit_settings.system = "METRIC"
        build(scene)
        export(out_dir, render="--render" in argv)
        print("Gothic outfit written to", out_dir)
        sys.stdout.flush()
        # the standalone bpy module can crash during interpreter teardown; everything is saved
        os._exit(0)
    else:
        build()


if __name__ == "__main__":
    main()
