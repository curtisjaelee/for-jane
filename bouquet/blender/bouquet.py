"""
A Bouquet That Blooms for You — procedural Blender bouquet
==========================================================

Builds a hand-tied bouquet of hydrangeas, garden roses, baby's breath,
eucalyptus and a champagne silk bow, entirely in code, then:

  * animates the 28-second opening (darkness → first rose → bouquet → reveal)
  * lights it like a perfume commercial (Cycles, SSS petals, DOF, haze, dust)
  * renders the cinematic fallback film, and/or
  * exports an animated, Draco-compressed bouquet.glb for the web page

Tested with Blender 4.2 LTS → 5.x.

Usage (from a terminal):

  blender --background --python bouquet.py -- --glb
  blender --background --python bouquet.py -- --still 600 --quality preview
  blender --background --python bouquet.py -- --anim --quality final
  blender --background --python bouquet.py -- --save        (keep a .blend)

Or open Blender → Scripting tab → Open bouquet.py → Run Script
(builds the full scene so you can look around, tweak and render by hand).

Options (after the lone "--"):
  --out DIR            where files go (default: ./out next to this script)
  --glb                export out/bouquet.glb (lightweight web version)
  --still SECONDS|Fxx  render one frame, e.g. --still 22 or --still F660
  --anim               render the whole film as PNG frames in out/frames/
  --quality Q          preview | final  (default final)
  --no-volume          skip volumetric haze (much faster renders)
  --font PATH          .ttf/.otf for the titles (e.g. CormorantGaramond-LightItalic.ttf)
  --seed N             change the arrangement (default 20261117)
  --save               save out/bouquet.blend
"""

import bpy
import math
import os
import random
import sys
import argparse
from mathutils import Vector, Matrix, Quaternion

# --------------------------------------------------------------------------
# Personal touches
# --------------------------------------------------------------------------
LINE_OPENING = "Jane, I wanted to give you flowers..."
LINE_REVEAL = "I'm sorry I don't give you enough flowers.\n'Til the day comes when I can buy you a whole garden, these are for you..."
LINE_SIGNATURE = "With love, Curtis"          # a heart is drawn after it

# --------------------------------------------------------------------------
# Timeline (seconds) — identical to the web page so GLB animation lines up
# --------------------------------------------------------------------------
FPS = 30
T = dict(text1_in=1.0, text1_out=4.4, hero=5.0, hero_bloom=(5.6, 11.2), bouquet_from=10.6,
         ribbon=(15.6, 18.6), rotate=(17.4, 26.0), text2=20.0, text3=22.6, end=28.0)
BIND_Y, BOTTOM_Y, DOME = -0.36, -1.0, 0.34
TEXT_DIST = 2.2   # titles float at this distance from the lens (kept inside the depth of field)


def F(t):
    return int(round(t * FPS))


# --------------------------------------------------------------------------
# Arguments
# --------------------------------------------------------------------------
def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="bouquet.py")
    here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
    p.add_argument("--out", default=os.path.join(here, "out"))
    p.add_argument("--glb", action="store_true")
    p.add_argument("--still", default=None)
    p.add_argument("--anim", action="store_true")
    p.add_argument("--quality", default="final", choices=["preview", "final"])
    p.add_argument("--no-volume", action="store_true")
    p.add_argument("--font", default=None)
    p.add_argument("--seed", type=int, default=20261117)
    p.add_argument("--save", action="store_true")
    return p.parse_args(argv)


ARGS = parse_args()
R = random.Random(ARGS.seed)


def rr(a, b):
    return a + (b - a) * R.random()


# --------------------------------------------------------------------------
# Small math helpers
# --------------------------------------------------------------------------
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def lerp(a, b, t):
    return a + (b - a) * t


def smooth(t):
    return t * t * (3 - 2 * t)


def prog(t, a, b):
    return clamp((t - a) / (b - a))


def srgb(h):
    """'#rrggbb' → linear RGB tuple."""
    h = h.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(out)


def mix3(a, b, t):
    return tuple(lerp(a[i], b[i], t) for i in range(3))


def dir_of(th_deg, ph_deg):
    th, ph = math.radians(th_deg), math.radians(ph_deg)
    return Vector((math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph)))


def js2b(v):
    """Web/three.js coordinates (Y up, +Z toward viewer) → Blender world (Z up, −Y toward camera)."""
    return Vector((v[0], -v[2], v[1]))


def catmull(points, n):
    """Uniform Catmull-Rom through points → n+1 samples."""
    pts = [points[0] + (points[0] - points[1])] + list(points) + [points[-1] + (points[-1] - points[-2])]
    segs = len(points) - 1
    out = []
    for k in range(n + 1):
        u = k / n * segs
        i = min(int(u), segs - 1)
        t = u - i
        p0, p1, p2, p3 = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
        t2, t3 = t * t, t * t * t
        out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    return out


def frames_along(pts):
    """Tangents + parallel-transported normals along a polyline."""
    tans = []
    for i in range(len(pts)):
        a, b = pts[max(0, i - 1)], pts[min(len(pts) - 1, i + 1)]
        tans.append((b - a).normalized())
    ref = Vector((0, 0, 1)) if abs(tans[0].z) < .9 else Vector((1, 0, 0))
    n = tans[0].cross(ref).normalized()
    norms = [n]
    for i in range(1, len(pts)):
        n = n - tans[i] * n.dot(tans[i])
        n = n.normalized() if n.length > 1e-8 else norms[-1]
        norms.append(n)
    return tans, norms


# --------------------------------------------------------------------------
# Geometry generators (all in "bouquet space": Y up, the web page's frame)
# --------------------------------------------------------------------------
def petal(len_=1.0, width=.9, cup=.3, bend=.1, curl=0.0, ruffle=.02, rows=12, cols=10, shape="rose", color_fn=None):
    seed = R.random() * 100
    V, UV, COL = [], [], []
    for j in range(rows + 1):
        t = j / rows
        if shape == "rose":
            hw = max(math.sqrt(max(0, 1 - ((t - .56) / .58) ** 2)), .07)
        elif shape == "round":
            hw = math.sqrt(max(0, 1 - ((t - .5) / .5) ** 2))
        elif shape == "floret":
            hw = max(0, math.sin(math.pi * min(t * .95 + .05, 1))) ** .75 * (1 - .15 * t)
        else:  # lance
            hw = max(0, math.sin(math.pi * t)) ** 1.15 * (1 - .25 * t)
        for i in range(cols + 1):
            s = i / cols * 2 - 1
            w = hw * width * .5
            x, y = s * w, len_ * t
            if shape == "rose":
                y -= len_ * .2 * s * s * t ** 2.5 + len_ * .03 * math.exp(-s * s * 30) * t ** 4
            z = cup * s * s * w + bend * len_ * t * t - curl * len_ * max(0, t - .5) ** 2 * (1 + .8 * s * s)
            z += ruffle * len_ * (math.sin(s * 7 + seed) * t ** 2.5 + .5 * math.sin(t * 9 + seed * 1.7) * s * s)
            # a whisper of organic irregularity
            z += .004 * len_ * math.sin(17 * s + 11 * t + seed)
            V.append(Vector((x, y, z)))
            UV.append(((s + 1) / 2, t))
            COL.append(color_fn(t, s) if color_fn else (1, 1, 1))
    Fc = []
    for j in range(rows):
        for i in range(cols):
            a = j * (cols + 1) + i
            Fc.append((a, a + 1, a + cols + 2, a + cols + 1))
    return V, Fc, UV, COL


def tube(points, radius, n=48, radial=8, taper=0.25, color=(1, 1, 1)):
    pts = catmull(points, n)
    tans, norms = frames_along(pts)
    V, Fc, UV, COL = [], [], [], []
    for i, p in enumerate(pts):
        u = i / n
        r = radius * (1 - taper * u)
        nn = norms[i]
        bn = tans[i].cross(nn)
        for k in range(radial):
            a = k / radial * math.tau
            V.append(p + (nn * math.cos(a) + bn * math.sin(a)) * r)
            UV.append((k / radial, u))
            shade = lerp(.6, 1, smooth(clamp(u * 1.6)))
            COL.append(tuple(c * shade for c in color))
    for i in range(n):
        for k in range(radial):
            a, b = i * radial + k, i * radial + (k + 1) % radial
            Fc.append((a, b, b + radial, a + radial))
    return V, Fc, UV, COL


def ribbon_strip(points, width, width_dir, n=64):
    pts = catmull(points, n)
    tans, _ = frames_along(pts)
    V, Fc, UV = [], [], []
    for i, p in enumerate(pts):
        u = i / n
        w = width_dir(u, tans[i], p)
        w = (w - tans[i] * w.dot(tans[i])).normalized()
        hw = width * .5 * (1 + .06 * math.sin(u * 20))
        V += [p - w * hw, p + w * hw]
        UV += [(0, u), (1, u)]
    for i in range(n):
        a = i * 2
        Fc.append((a, a + 1, a + 3, a + 2))
    return V, Fc, UV, None


def icosphere_data(subdiv=1):
    t = (1 + 5 ** .5) / 2
    V = [Vector(v).normalized() for v in [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]]
    Fc = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
          (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    for _ in range(subdiv):
        cache, nf = {}, []

        def mid(a, b):
            key = (min(a, b), max(a, b))
            if key not in cache:
                V.append(((V[a] + V[b]) / 2).normalized())
                cache[key] = len(V) - 1
            return cache[key]
        for a, b, c in Fc:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            nf += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        Fc = nf
    return V, Fc


class MeshBuilder:
    """Accumulates many little pieces into one mesh (one draw call on the web)."""

    def __init__(self):
        self.V, self.F, self.UV, self.COL = [], [], [], []

    def add(self, data, matrix=Matrix.Identity(4), color_mul=(1, 1, 1)):
        V, Fc, UV, COL = data
        o = len(self.V)
        self.V += [matrix @ v for v in V]
        self.F += [tuple(i + o for i in f) for f in Fc]
        self.UV += UV if UV else [(0, 0)] * len(V)
        cols = COL if COL else [(1, 1, 1)] * len(V)
        self.COL += [(c[0] * color_mul[0], c[1] * color_mul[1], c[2] * color_mul[2]) for c in cols]
        return self

    def data(self):
        return self.V, self.F, self.UV, self.COL


# --------------------------------------------------------------------------
# Blender object helpers
# --------------------------------------------------------------------------
def new_mesh(name, data, material=None, smooth_shade=True):
    V, Fc, UV, COL = data
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in V], [], Fc)
    me.update()
    if UV:
        uvl = me.uv_layers.new(name="UVMap")
        vi = [0] * len(me.loops)
        me.loops.foreach_get("vertex_index", vi)
        flat = []
        for i in vi:
            flat += UV[i]
        uvl.data.foreach_set("uv", flat)
    if COL:
        ca = me.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
        flat = []
        for c in COL:
            flat += (c[0], c[1], c[2], 1.0)
        ca.data.foreach_set("color", flat)
        try:
            me.color_attributes.active_color = ca
            me.color_attributes.render_color_index = 0
        except Exception:
            pass
    if smooth_shade:
        me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    if material:
        me.materials.append(material)
    return me


def new_obj(name, data_block, parent=None, coll=None):
    ob = bpy.data.objects.new(name, data_block)
    (coll or BOUQUET).objects.link(ob)
    if parent:
        ob.parent = parent
    return ob


def empty(name, parent=None, coll=None):
    return new_obj(name, None, parent, coll)


def key(ob, path, frame, value=None, index=-1, interp="BEZIER"):
    if value is not None:
        if index >= 0:
            getattr(ob, path)[index] = value
        else:
            setattr(ob, path, value)
    ob.keyframe_insert(data_path=path, frame=frame, index=index)
    if interp != "BEZIER":
        set_interp(ob, path, interp)


def iter_fcurves(id_block):
    ad = id_block.animation_data
    if not ad or not ad.action:
        return []
    act = ad.action
    if hasattr(act, "fcurves") and len(getattr(act, "fcurves", [])):
        return list(act.fcurves)
    out = []  # layered actions (Blender 4.4+/5.x)
    for layer in getattr(act, "layers", []):
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                out += list(bag.fcurves)
    return out


def set_interp(ob, path, interp):
    for fc in iter_fcurves(ob):
        if fc.data_path == path:
            for kp in fc.keyframe_points:
                kp.interpolation = interp


def grow_keys(ob, t0, t1, overshoot=1.06):
    """Scale 0 → 1 with a soft botanical overshoot."""
    ob.scale = (0, 0, 0)
    key(ob, "scale", F(t0) - 1)
    key(ob, "scale", F(t0))
    if overshoot > 1:
        ob.scale = (overshoot,) * 3
        key(ob, "scale", F(lerp(t0, t1, .72)))
    ob.scale = (1, 1, 1)
    key(ob, "scale", F(t1))


def aim(ob, target):
    d = (Vector(target) - ob.location).normalized()
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = d.to_track_quat("-Z", "Y")


# --------------------------------------------------------------------------
# Materials (Principled BSDF, names valid for Blender 4.x and 5.x)
# --------------------------------------------------------------------------
def set_in(node, names, value):
    for n in names if isinstance(names, (list, tuple)) else [names]:
        if n in node.inputs:
            node.inputs[n].default_value = value
            return True
    return False


def principled(name, base=None, rough=.5, sss=0.0, sss_radius=(1, .4, .3), sss_scale=.01, sheen=0.0, sheen_tint=(1, 1, 1),
               coat=0.0, metallic=0.0, spec=.5, aniso=0.0, transmission=0.0, use_vcol=False, image=None, normal_image=None,
               random_tint=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    set_in(bsdf, "Roughness", rough)
    set_in(bsdf, "Metallic", metallic)
    set_in(bsdf, ["Specular IOR Level", "Specular"], spec)
    if base:
        set_in(bsdf, "Base Color", (*base, 1))
    if sss:
        set_in(bsdf, ["Subsurface Weight", "Subsurface"], sss)
        set_in(bsdf, "Subsurface Radius", Vector(sss_radius))
        set_in(bsdf, "Subsurface Scale", sss_scale)
    if sheen:
        set_in(bsdf, ["Sheen Weight", "Sheen"], sheen)
        set_in(bsdf, "Sheen Tint", (*sheen_tint, 1) if "Sheen Tint" in bsdf.inputs and bsdf.inputs["Sheen Tint"].type == "RGBA" else 0.5)
    if coat:
        set_in(bsdf, ["Coat Weight", "Clearcoat"], coat)
    if aniso:
        set_in(bsdf, "Anisotropic", aniso)
    if transmission:
        set_in(bsdf, ["Transmission Weight", "Transmission"], transmission)
    color_src = None
    if use_vcol:
        vc = nt.nodes.new("ShaderNodeVertexColor")
        vc.layer_name = "Col"
        vc.location = (-600, 200)
        color_src = vc.outputs["Color"]
    if image:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.location = (-600, 300)
        color_src = tex.outputs["Color"]
    if normal_image:
        nt_ = nt.nodes.new("ShaderNodeTexImage")
        nt_.image = normal_image
        nt_.location = (-600, -200)
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.location = (-300, -200)
        nm.inputs["Strength"].default_value = .8
        nt.links.new(nt_.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if color_src is not None:
        if random_tint > 0:
            # render-only richness: per-object brightness drift (Cycles)
            oi = nt.nodes.new("ShaderNodeObjectInfo")
            oi.location = (-800, -50)
            mr = nt.nodes.new("ShaderNodeMapRange")
            mr.location = (-600, -50)
            mr.inputs["To Min"].default_value = 1 - random_tint
            mr.inputs["To Max"].default_value = 1 + random_tint * .4
            nt.links.new(oi.outputs["Random"], mr.inputs["Value"])
            mul = nt.nodes.new("ShaderNodeMath")
            mul.operation = "MULTIPLY"
            mix = nt.nodes.new("ShaderNodeVectorMath")
            mix.operation = "SCALE"
            mix.location = (-350, 150)
            nt.links.new(color_src, mix.inputs[0])
            nt.links.new(mr.outputs["Result"], mix.inputs["Scale"])
            nt.links.new(mix.outputs["Vector"], bsdf.inputs["Base Color"])
        else:
            nt.links.new(color_src, bsdf.inputs["Base Color"])
        if sss and "Subsurface Color" in bsdf.inputs:
            nt.links.new(color_src, bsdf.inputs["Subsurface Color"])
    return m


def emission_mat(name, color, strength, alpha_anim=False):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*color, 1)
    em.inputs["Strength"].default_value = strength
    if alpha_anim:
        tr = nt.nodes.new("ShaderNodeBsdfTransparent")
        mx = nt.nodes.new("ShaderNodeMixShader")
        mx.name = "Fade"
        mx.inputs[0].default_value = 0
        nt.links.new(tr.outputs[0], mx.inputs[1])
        nt.links.new(em.outputs[0], mx.inputs[2])
        nt.links.new(mx.outputs[0], out.inputs["Surface"])
    else:
        nt.links.new(em.outputs[0], out.inputs["Surface"])
    try:
        m.blend_method = "BLEND"
    except Exception:
        pass
    return m


def vein_images(name, base_hex, vein_hex, sides, curve, size=512):
    """Leaf colour + normal map with midrib and side veins (numpy)."""
    import numpy as np
    u = np.linspace(0, 1, size)[None, :].repeat(size, 0)
    v = np.linspace(0, 1, size)[:, None].repeat(size, 1)
    d = np.abs(u - .5)
    mid = np.exp(-(d / .008) ** 2)
    phase = (v - curve * d ** .8) * (sides + 1)
    side = np.exp(-(((phase % 1.0) - .5) / .05) ** 2) * np.clip((d - .015) / .03, 0, 1) * np.clip(1 - d / .5, 0, 1)
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 1, (size // 16, size // 16))
    noise = np.kron(noise, np.ones((16, 16)))[:size, :size] * .025
    h = mid * 1.0 + side * .55
    base, vein = np.array(srgb(base_hex)), np.array(srgb(vein_hex))
    col = base[None, None, :] * (1 + noise[..., None]) * (1 - .12 * v[..., None])
    col = col * (1 - h[..., None] * .7) + vein[None, None, :] * h[..., None] * .7
    rgba = np.concatenate([np.clip(col, 0, 1), np.ones((size, size, 1))], -1)
    gy, gx = np.gradient(-h * 2.0)
    n = np.stack([-gx * 6, -gy * 6, np.ones_like(h)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    nrm = np.concatenate([n * .5 + .5, np.ones((size, size, 1))], -1)
    imgs = []
    for suffix, arr, cs in (("color", rgba, "sRGB"), ("normal", nrm, "Non-Color")):
        im = bpy.data.images.new(f"{name}_{suffix}", size, size, alpha=False)
        try:
            im.colorspace_settings.name = cs
        except Exception:
            pass
        px = arr.astype(np.float32)
        if cs == "sRGB":  # we computed linear colour; Blender expects sRGB-encoded pixels for an sRGB image
            px[..., :3] = np.where(px[..., :3] <= .0031308, px[..., :3] * 12.92, 1.055 * np.power(px[..., :3], 1 / 2.4) - .055)
        im.pixels.foreach_set(px.ravel())
        im.pack()
        imgs.append(im)
    return imgs


# --------------------------------------------------------------------------
# Scene reset
# --------------------------------------------------------------------------
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.fps = FPS
    sc.frame_start = 0
    sc.frame_end = F(T["end"])
    return sc


SCENE = reset_scene()
BOUQUET = bpy.data.collections.new("Bouquet")
SCENE.collection.children.link(BOUQUET)
STAGE = bpy.data.collections.new("Stage")
SCENE.collection.children.link(STAGE)
WEB = ARGS.glb and not (ARGS.anim or ARGS.still)   # lighter geometry when only exporting for the web

# --------------------------------------------------------------------------
# Palettes & materials
# --------------------------------------------------------------------------
ROSE = {
    "ivory": dict(inner=srgb("#e3c49a"), mid=srgb("#f4e4cd"), edge=srgb("#fff9f0")),
    "blush": dict(inner=srgb("#d4848e"), mid=srgb("#efbcbc"), edge=srgb("#fbe5df")),
    "hero": dict(inner=srgb("#d98a96"), mid=srgb("#f0b3b8"), edge=srgb("#fcdfd9")),
}
HYD = {
    "pink": dict(florets=[srgb(h) for h in ("#f1b3c3", "#f6c8d3", "#e8a6bf", "#f9dce3", "#dcb0d0", "#f3bfcf")], heart=srgb("#3a2329")),
    "blue": dict(florets=[srgb(h) for h in ("#a8c1ea", "#bccff0", "#c5c0ea", "#d7e3f7", "#9bb3e0", "#b4c8ee")], heart=srgb("#222a3c")),
}

MAT_PETAL = principled("Petal", rough=.55, sss=.35, sss_radius=(1, .35, .3), sss_scale=.004, sheen=.5, spec=.35, use_vcol=True)
MAT_FLORET = principled("Floret", rough=.6, sss=.3, sss_radius=(.8, .6, 1), sss_scale=.003, sheen=.4, spec=.3, use_vcol=True,
                        random_tint=0 if WEB else .18)
MAT_SEPAL = principled("Sepal", base=srgb("#4f6b3f"), rough=.6, sss=.1, sss_scale=.003)
MAT_STEM = principled("Stem", rough=.5, sss=.1, sss_scale=.002, use_vcol=True)
MAT_BABY = principled("BabysBreath", base=srgb("#fbf7f0"), rough=.75, sss=.4, sss_scale=.002, sheen=.5)
MAT_RIBBON = principled("Ribbon", base=srgb("#e3cba4"), rough=.28, metallic=.08, sheen=1.0, sheen_tint=srgb("#fff1d8"), coat=.3,
                        aniso=.6, spec=.6)
euc_col, euc_nrm = vein_images("Eucalyptus", "#7a9488", "#b9c9c0", 6, .28)
grn_col, grn_nrm = vein_images("Greenery", "#55744a", "#9fbb7c", 8, .2)
MAT_EUC = principled("Eucalyptus", rough=.7, sss=.15, sss_scale=.003, sheen=.35, image=euc_col, normal_image=euc_nrm)
MAT_GREEN = principled("Greenery", rough=.45, sss=.2, sss_scale=.003, coat=.2, image=grn_col, normal_image=grn_nrm)
HEART_MATS = {k: principled(f"HydrangeaHeart_{k}", base=v["heart"], rough=.95) for k, v in HYD.items()}


def rose_color(pal, t, k):
    c = mix3(pal["inner"], pal["mid"], smooth(clamp(t / .55)))
    c = mix3(c, pal["edge"], smooth(prog(t, .45, 1)))
    ao = lerp(.5, 1, smooth(clamp(t / .42))) * lerp(.84, 1, k)
    return tuple(x * ao for x in c)


def add_thickness(ob, thickness):
    if WEB:
        return
    m = ob.modifiers.new("Thickness", "SOLIDIFY")
    m.thickness = thickness
    m.offset = 0
    s = ob.modifiers.new("Smooth", "SUBSURF")
    s.levels = 0
    s.render_levels = 1


# --------------------------------------------------------------------------
# Flowers
# --------------------------------------------------------------------------
def make_rose(name, parent, radius, pal, openness, detail, bloom_window):
    head = empty(name, parent)
    head.empty_display_size = radius
    n = int(round(rr(26, 33)))
    b0, b1 = bloom_window
    for i in range(n):
        k = i / (n - 1)
        phi = i * 2.39996 + rr(-.15, .15)
        ln = radius * lerp(.5, 1.12, k ** .6) * rr(.92, 1.08)
        wd = ln * lerp(.85, 1.3, k) * rr(.9, 1.1)
        data = petal(ln, wd, cup=lerp(1.15, .45, k), bend=lerp(.55, .12, k), curl=lerp(0, .7, k * k) * openness,
                     ruffle=.025, rows=int(12 * detail), cols=int(10 * detail), shape="rose",
                     color_fn=lambda t, s, k=k: rose_color(pal, t, k))
        ob = new_obj(f"{name}_Petal_{i:02d}", new_mesh(f"{name}_Petal_{i:02d}", data, MAT_PETAL), head)
        add_thickness(ob, .0011)
        r = radius * lerp(.03, .2, k)
        ob.location = (math.cos(phi) * r, -radius * .22 * k * k, math.sin(phi) * r)
        ob.rotation_mode = "ZXY"         # == three.js 'YXZ'
        beta = math.atan2(-math.cos(phi), -math.sin(phi))
        closed = lerp(-.24, .04, k) + rr(-.02, .02)
        opened = lerp(.05, 1.3, k ** 1.15) * openness + rr(-.07, .07)
        roll = rr(-.08, .08)
        delay = 1 - k
        ta = lerp(b0, b1, delay * .55)
        tb = lerp(b0, b1, delay * .55 + .45)
        ob.rotation_euler = (-closed, beta, roll)
        key(ob, "rotation_euler", F(ta))
        ob.rotation_euler = (-opened, beta, roll)
        key(ob, "rotation_euler", F(tb))
    for i in range(5):  # sepals
        data = petal(radius * .75, radius * .22, cup=.2, bend=-.1, shape="lance", ruffle=.01)
        ob = new_obj(f"{name}_Sepal_{i}", new_mesh(f"{name}_Sepal_{i}", data, MAT_SEPAL), head)
        phi = i / 5 * math.tau + rr(-.2, .2)
        ob.rotation_mode = "ZXY"
        ob.rotation_euler = (-rr(1.9, 2.4), math.atan2(-math.cos(phi), -math.sin(phi)), 0)
        ob.location = (0, -radius * .28, 0)
    V, Fc = icosphere_data(2)
    rec = new_obj(f"{name}_Receptacle", new_mesh(f"{name}_Receptacle", ([v * radius * .2 for v in V], Fc, None, None), MAT_SEPAL), head)
    rec.location = (0, -radius * .3, 0)
    rec.scale = (1, .8, 1)
    return head


FLORET_DATA = []
for variant in range(3):
    mb = MeshBuilder()
    nP = 5 if variant == 2 else 4
    res = 4 if WEB else 6
    for i in range(nP):
        d = petal(1, rr(.85, 1.05), cup=.25, bend=.18, shape="floret", rows=res, cols=res, ruffle=.04,
                  color_fn=lambda t, s: mix3(srgb("#dfe8cc"), (1, 1, 1), smooth(clamp(t * 2.2))))
        m = Matrix.Rotation(i / nP * math.tau + rr(-.15, .15), 4, "Y") @ Matrix.Rotation(-math.pi / 2, 4, "X")
        mb.add(d, m)
    FLORET_DATA.append(mb.data())
FLORET_MESHES = {}


def floret_mesh(variant, pal_name, ci):
    key_ = (variant, pal_name, ci)
    if key_ not in FLORET_MESHES:
        col = HYD[pal_name]["florets"][ci]
        V, Fc, UV, COL = FLORET_DATA[variant]
        FLORET_MESHES[key_] = new_mesh(f"Floret_{pal_name}_{variant}_{ci}", (V, Fc, UV, [tuple(c[j] * col[j] for j in range(3)) for c in COL]), MAT_FLORET)
    return FLORET_MESHES[key_]


def make_hydrangea(name, parent, radius, pal_name, count, start, end):
    head = empty(name, parent)
    head.empty_display_size = radius
    pal = HYD[pal_name]
    V, Fc = icosphere_data(3)
    heart = new_obj(f"{name}_Heart", new_mesh(f"{name}_Heart", ([v * radius * .8 for v in V], Fc, None, None), HEART_MATS[pal_name]), head)
    grow_keys(heart, start, lerp(start, end, .8), overshoot=1)
    cap = math.radians(118)
    cos_min = math.cos(cap)
    mb = MeshBuilder() if WEB else None
    for i in range(count):
        ct = 1 - (i + .5) / count * (1 - cos_min)
        st = math.sqrt(max(0, 1 - ct * ct))
        ph = i * 2.39996
        nrm = Vector((st * math.cos(ph), ct, st * math.sin(ph)))
        depth = rr(.9, 1.03)
        jitter = (nrm + Vector((rr(-.25, .25), rr(-.25, .25), rr(-.25, .25)))).normalized()
        q = Vector((0, 1, 0)).rotation_difference(jitter) @ Quaternion((0, 1, 0), rr(0, math.tau))
        s = radius * rr(.13, .17)
        variant, ci = R.randrange(3), R.randrange(len(pal["florets"]))
        loc = nrm * radius * depth
        if WEB:
            shade = lerp(.62, 1.04, (depth - .9) / .13)
            col = pal["florets"][ci]
            mb.add(FLORET_DATA[variant], Matrix.LocRotScale(loc, q, (s, s, s)), tuple(c * shade for c in col))
        else:
            ob = new_obj(f"{name}_Floret_{i:03d}", floret_mesh(variant, pal_name, ci), head)
            ob.location = loc
            ob.rotation_mode = "QUATERNION"
            ob.rotation_quaternion = q
            th = math.acos(ct) / cap
            delay = th * .55 + rr(0, .35)
            t0 = lerp(start, end, delay * .62)
            t1 = lerp(start, end, delay * .62 + .38)
            ob.scale = (0, 0, 0)
            key(ob, "scale", F(t0))
            ob.scale = (s * 1.12,) * 3
            key(ob, "scale", F(lerp(t0, t1, .7)))
            ob.scale = (s,) * 3
            key(ob, "scale", F(t1))
    if WEB:
        V, Fc, UV, COL = mb.data()
        ob = new_obj(f"{name}_Florets", new_mesh(f"{name}_Florets", (V, Fc, UV, COL), MAT_FLORET), head)
        grow_keys(ob, start + .2, end, overshoot=1.04)
    return head


# --------------------------------------------------------------------------
# Build the bouquet
# --------------------------------------------------------------------------
ROOT = empty("Bouquet")                 # converts bouquet space (Y up) → Blender (Z up)
ROOT.rotation_euler = (math.pi / 2, 0, 0)
TURN = empty("Turn", ROOT)               # the slow reveal turn
TILT = empty("Tilt", TURN)
TILT.rotation_euler = (.1, 0, 0)

LAYOUT = [
    ("rose", 13, 100, .118, "hero", True),
    ("hyd", 38, 28, .165, "blue"), ("hyd", 42, 150, .17, "pink"), ("hyd", 31, 243, .16, "blue"),
    ("hyd", 42, 322, .165, "pink"), ("hyd", 66, 88, .15, "pink"), ("hyd", 16, 285, .14, "blue"),
    ("hyd", 72, 205, .145, "blue"), ("hyd", 74, 345, .14, "blue"),
    ("rose", 26, 52, .095, "ivory"), ("rose", 30, 128, .1, "blush"), ("rose", 54, 56, .092, "blush"),
    ("rose", 57, 124, .1, "ivory"), ("rose", 58, 196, .095, "ivory"), ("rose", 56, 4, .09, "ivory"),
    ("rose", 47, 287, .095, "blush"), ("rose", 30, 196, .088, "blush"), ("rose", 22, 345, .09, "ivory"),
    ("rose", 75, 160, .088, "blush"), ("rose", 77, 22, .09, "blush"), ("rose", 70, 250, .09, "ivory"),
    ("rose", 76, 120, .085, "ivory"),
]
STEM_GREEN = srgb("#5d7a45")


def stem_object(name, points, radius, color, t0, dur, n=48, radial=8):
    base = points[0]
    data = tube([p - base for p in points], radius, n=n, radial=radial, color=color)
    ob = new_obj(name, new_mesh(name, data, MAT_STEM), TILT)
    ob.location = base
    grow_keys(ob, t0, t0 + dur, overshoot=1)
    return ob


hero_dir = dir_of(13, 100)
HERO_HEAD = None
for idx, entry in enumerate(LAYOUT):
    kind, th, ph, radius, pal = entry[:5]
    hero = len(entry) > 5
    d = dir_of(th + rr(-3, 3), ph + rr(-4, 4))
    pos = d * (DOME * ((1.1 if hero else 1.03) if kind == "rose" else .96) + rr(-.012, .012))
    face = (d * .82 + Vector((0, .3, 0))).normalized()
    start = T["hero"] if hero else T["bouquet_from"] + .35 + math.acos(clamp(d.dot(hero_dir), -1, 1)) * 2.1 + rr(0, .5)
    name = "Flower_Hero" if hero else f"Flower_{'Rose' if kind == 'rose' else 'Hydrangea'}_{idx:02d}"
    if kind == "rose":
        bloom = T["hero_bloom"] if hero else (start + .25, start + 3.4)
        head = make_rose(name, TILT, radius, ROSE[pal], 1 if hero else rr(.75, 1.05), 1.6 if hero else 1, bloom)
    else:
        head = make_hydrangea(name, TILT, radius, pal, int(round(radius * (1500 if WEB else 2000))), start + .25, start + 4.0)
    head["kind"] = "rose" if kind == "rose" else "hydrangea"
    head["hero"] = bool(hero)
    head["radius"] = radius
    head.location = pos
    head.rotation_mode = "QUATERNION"
    head.rotation_quaternion = Vector((0, 1, 0)).rotation_difference(face) @ Quaternion((0, 1, 0), rr(0, math.tau))
    if hero:
        HERO_HEAD = head
        head.scale = (0, 0, 0)
        key(head, "scale", F(start))
        head.scale = (1, 1, 1)
        key(head, "scale", F(start + 1.2))
    else:
        grow_keys(head, start, start + .85, overshoot=1.08)
    # hand-tied spiral stems
    ang = math.atan2(pos.z, pos.x) + 1.1
    spread = math.hypot(pos.x, pos.z) / DOME
    bot = Vector((math.cos(ang) * .085 * spread + rr(-.01, .01), BOTTOM_Y + rr(-.05, .03), math.sin(ang) * .085 * spread))
    bind = Vector((math.cos(ang - .9) * .03 * spread, BIND_Y, math.sin(ang - .9) * .03 * spread))
    base = pos - face * radius * .55
    mid = bind.lerp(base, .5) + Vector((0, -.02, 0)) - face * .03
    s_t0 = T["hero"] - 1.6 if hero else start - 1.3
    stem_object(f"Stem_{idx:02d}", [bot, bot.lerp(bind, .5), bind, mid, base], .0065 if kind == "rose" else .0085,
                STEM_GREEN, s_t0, 1.6 if hero else 1.2)


def leaf_quat(tangent, side, up, twist):
    y = (tangent * .45 + side).normalized()
    z = (up - y * up.dot(y)).normalized()
    x = y.cross(z).normalized()
    z = x.cross(y).normalized()
    m = Matrix((x, y, z)).transposed()
    return m.to_quaternion() @ Quaternion((0, 1, 0), twist)


EUC_LEAF = petal(1, .95, cup=.18, bend=.06, shape="round", rows=10, cols=10, ruffle=.015)
LANCE_LEAF = petal(1, .32, cup=.3, bend=.1, curl=.1, shape="lance", rows=12, cols=6, ruffle=.01)


def sprig(name, points, stem_r, stem_col, leaf_data, leaf_mat, leaves, t0, dur):
    """Stem + leaves as one object that grows from its base."""
    base = points[0]
    stem = tube([p - base for p in points], stem_r, n=40, radial=6, color=stem_col)
    ob = new_obj(name, new_mesh(name, stem, MAT_STEM), TILT)
    ob.location = base
    pts = catmull([p - base for p in points], 200)
    tans, _ = frames_along(pts)
    mb = MeshBuilder()
    for (u, sign, size, twist) in leaves:
        i = int(u * 200)
        p, tg = pts[i], tans[i]
        side = tg.cross(Vector((0, 1, 0))).normalized() * sign
        up = side.cross(tg).normalized() * sign
        q = leaf_quat(tg, side, up, twist)
        mb.add(leaf_data, Matrix.LocRotScale(p, q, (size, size, size)))
    lo = new_obj(name + "_Leaves", new_mesh(name + "_Leaves", mb.data(), leaf_mat), ob)
    add_thickness(lo, .0006)
    grow_keys(ob, t0, t0 + dur, overshoot=1.03)
    return ob


for e in range(11):  # silver-dollar eucalyptus
    ph, th = e / 11 * 360 + rr(-12, 12), rr(70, 102)
    d = dir_of(th, ph)
    t0 = T["bouquet_from"] + 1.4 + rr(0, 3.2)
    pts = [Vector((d.x * .06, BIND_Y + .04, d.z * .06)), d * DOME * .7 + Vector((0, -.02, 0)),
           d * DOME * 1.25 + Vector((0, rr(-.12, .02), 0)), d * DOME * 1.6 + Vector((0, rr(-.26, -.08), 0))]
    leaves = []
    for k in range(9):
        u = .32 + k / 9 * .66
        size = lerp(.062, .028, k / 9) * rr(.85, 1.15)
        leaves += [(u, -1, size, rr(-.4, .4)), (u, 1, size, rr(-.4, .4))]
    sprig(f"Eucalyptus_{e:02d}", pts, .0032, srgb("#7d6f5e"), EUC_LEAF, MAT_EUC, leaves, t0, 2.2)

for e in range(14):  # delicate greenery
    ph, th = e / 14 * 360 + rr(-10, 10) + 13, rr(48, 96)
    d = dir_of(th, ph)
    t0 = T["bouquet_from"] + 1.8 + rr(0, 3)
    pts = [d * DOME * .55 + Vector((0, -.05, 0)), d * DOME * 1.05, d * DOME * 1.38 + Vector((0, rr(-.05, .08), 0))]
    leaves = [(.35 + k / 7 * .62, 1 if k % 2 else -1, lerp(.085, .05, k / 7) * rr(.8, 1.2), rr(-.3, .3)) for k in range(7)]
    sprig(f"Greenery_{e:02d}", pts, .0022, srgb("#4c6b3a"), LANCE_LEAF, MAT_GREEN, leaves, t0, 1.8)

ICO1 = icosphere_data(1)
for b in range(30):  # baby's breath
    d = dir_of(rr(6, 80), rr(0, 360))
    t0 = T["bouquet_from"] + 2.6 + rr(0, 3.4)
    base = d * DOME * .82
    tip = d * DOME * rr(1.2, 1.42) + Vector((rr(-.03, .03), rr(0, .05), rr(-.03, .03)))
    stems = MeshBuilder().add(tube([Vector(), (tip - base) * .5 + Vector((rr(-.01, .01), .01, rr(-.01, .01))), tip - base], .0011, n=10, radial=4, color=srgb("#7f9467")))
    blossoms = MeshBuilder()
    for k in range(int(round(rr(4, 7)))):
        bt = tip - base + Vector((rr(-.045, .045), rr(-.01, .045), rr(-.045, .045)))
        stems.add(tube([(tip - base) * .75, bt], .0008, n=4, radial=3, color=srgb("#7f9467")))
        for f in range(int(round(rr(5, 9)))):
            fp = bt + Vector((rr(-.011, .011), rr(-.007, .011), rr(-.011, .011)))
            s = rr(.0042, .0068)
            blossoms.add((ICO1[0], ICO1[1], None, None), Matrix.LocRotScale(fp, Quaternion((rr(-1, 1), rr(-1, 1), rr(-1, 1), rr(-1, 1))).normalized(), (s, s, s)))
    ob = new_obj(f"BabysBreath_{b:02d}", new_mesh(f"BabysBreath_{b:02d}", stems.data(), MAT_STEM), TILT)
    ob.location = base
    new_obj(f"BabysBreath_{b:02d}_Blossoms", new_mesh(f"BabysBreath_{b:02d}_Blossoms", blossoms.data(), MAT_BABY), ob)
    grow_keys(ob, t0, t0 + 1.4, overshoot=1.04)

# --- the champagne silk bow -------------------------------------------------
RIB = empty("Ribbon", TILT)
y, Rr, W = BIND_Y - .04, .05, .045
rib = MeshBuilder()
for w in range(2):
    pts = [Vector((math.cos(a) * (Rr + w * .003), y - w * .03 + math.sin(a) * .006, math.sin(a) * (Rr + w * .003)))
           for a in [i / 16 * math.tau for i in range(17)]]
    rib.add(ribbon_strip(pts, W, lambda u, tg, p: Vector((0, 1, 0)), 80))
Cn = Vector((0, y - .012, Rr + .008))
ta = math.radians(58)
nrm = Vector((0, -math.sin(ta), math.cos(ta)))
for sx in (-1, 1):
    pts = []
    for i in range(25):
        a = i / 24 * math.tau
        pts.append(Cn + Vector((sx * .085 * (1 - math.cos(a)) * .5 * (1 + .25 * math.sin(a)),
                                .05 * math.sin(a) * math.cos(ta) + .012 * (1 - math.cos(a)),
                                .05 * math.sin(a) * math.sin(ta) + .015 * (1 - math.cos(a)))))
    rib.add(ribbon_strip(pts, W * .92, lambda u, tg, p, sx=sx: nrm + Vector((sx * .2 * math.sin(u * math.tau), 0, 0)), 72))
for sx in (-1, 1):
    pts = [Cn, Cn + Vector((sx * .025, -.07, .012)), Cn + Vector((sx * .055, -.16, .02)), Cn + Vector((sx * .07, -.25, .006))]
    rib.add(ribbon_strip(pts, W * .85, lambda u, tg, p: tg.cross(Vector((0, 0, 1))) + Vector((0, 0, .3 * math.sin(u * 4))), 48))
V, Fc = icosphere_data(2)
rib.add((V, Fc, None, None), Matrix.LocRotScale(Cn + Vector((0, 0, .004)), None, (.019 * 1.2, .019 * .9, .019 * .7)))
rob = new_obj("Ribbon_Silk", new_mesh("Ribbon_Silk", rib.data(), MAT_RIBBON), RIB)
add_thickness(rob, .0007)
r0, r1 = T["ribbon"]
RIB.location = (0, .16, 0)
RIB.scale = (0, 0, 0)
key(RIB, "location", F(r0))
key(RIB, "scale", F(r0) - 1)
RIB.scale = (.75, 1, .75)
key(RIB, "scale", F(r0))
RIB.location = (0, 0, 0)
RIB.scale = (1, 1, 1)
key(RIB, "location", F(r1))
key(RIB, "scale", F(r1))

# --- the slow turn of the reveal ----------------------------------------------
TURN.rotation_euler = (0, -.12, 0)
key(TURN, "rotation_euler", F(T["rotate"][0]))
TURN.rotation_euler = (0, .55, 0)
key(TURN, "rotation_euler", F(T["rotate"][1]))

bpy.context.view_layer.update()


# --------------------------------------------------------------------------
# GLB export (web)
# --------------------------------------------------------------------------
def export_glb(path):
    lc = bpy.context.view_layer.layer_collection.children[BOUQUET.name]
    bpy.context.view_layer.active_layer_collection = lc
    want = dict(filepath=path, export_format="GLB", use_active_collection=True, export_apply=True,
                export_animations=True, export_animation_mode="SCENE", export_anim_scene_split_object=False,
                export_frame_range=True, export_force_sampling=True, export_optimize_animation_size=True,
                export_nla_strips_merged_animation_name="Bloom", export_extras=True,
                export_cameras=False, export_lights=False, export_yup=True, export_image_format="WEBP",
                export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=7,
                export_draco_position_quantization=14, export_draco_normal_quantization=10,
                export_draco_texcoord_quantization=12, export_draco_color_quantization=10,
                export_vertex_color="MATERIAL", export_all_vertex_colors=False)
    props = bpy.ops.export_scene.gltf.get_rna_type().properties.keys()
    kw = {k: v for k, v in want.items() if k in props}
    try:
        bpy.ops.export_scene.gltf(**kw)
    except Exception as e:  # e.g. Draco library missing in some builds
        print("Draco export failed, retrying uncompressed:", e)
        kw.pop("export_draco_mesh_compression_enable", None)
        bpy.ops.export_scene.gltf(**kw)
    print(f"Exported {path} ({os.path.getsize(path) / 1e6:.1f} MB)")


# --------------------------------------------------------------------------
# Stage: camera, lights, haze, dust, titles
# --------------------------------------------------------------------------
def build_stage(aspect):
    sc = SCENE
    hero_world = HERO_HEAD.matrix_world.translation.copy()
    hero_js = Vector((hero_world.x, hero_world.z, -hero_world.y)) + Vector((0, .118 * .25, 0))

    # --- world: warm charcoal
    world = bpy.data.worlds.new("Charcoal")
    sc.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (*srgb("#0e0a09"), 1)
    bg.inputs["Strength"].default_value = 1.0

    # --- warm-charcoal backdrop: a soft pool of light far behind the bouquet
    bm = emission_mat("Backdrop", (1, 1, 1), 1)
    nt = bm.node_tree
    em = next(n for n in nt.nodes if n.type == "EMISSION")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    gr = nt.nodes.new("ShaderNodeTexGradient")
    gr.gradient_type = "SPHERICAL"
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (.16, .2, 1)
    mp.inputs["Location"].default_value = (0, .06, 0)
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*srgb("#050404"), 1)
    ramp.color_ramp.elements[1].color = (*srgb("#2a1d17"), 1)
    ramp.color_ramp.elements[1].position = .85
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], gr.inputs["Vector"])
    nt.links.new(gr.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], em.inputs["Color"])
    bd = new_obj("Backdrop", new_mesh("Backdrop", ([Vector((x, y_, 0)) for x, y_ in ((-7, -5), (7, -5), (7, 5), (-7, 5))], [(0, 1, 2, 3)], None, None), bm), coll=STAGE)
    bd.location = js2b(Vector((0, .1, -4.2)))
    bd.rotation_euler = (math.pi / 2, 0, 0)
    bd.visible_shadow = False
    try:
        bd.visible_volume_scatter = False
    except Exception:
        pass

    # --- camera (same shots as the web page)
    cam_data = bpy.data.cameras.new("Camera")
    cam_data.sensor_fit = "VERTICAL"
    cam_data.angle_y = math.radians(30)
    cam_data.clip_start = .02
    cam = new_obj("Camera", cam_data, coll=STAGE)
    sc.camera = cam
    tgt = empty("CamTarget", coll=STAGE)
    con = cam.constraints.new("TRACK_TO")
    con.target = tgt
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"
    cam_data.dof.use_dof = True
    cam_data.dof.focus_object = tgt
    cam_data.dof.aperture_fstop = 2.4
    cam_data.dof.aperture_blades = 7
    tv = math.tan(math.radians(15))
    shots = [(0, Vector((0, .3, 0)), Vector((0, .1, 1)), .9, 1.1),
             (4.6, hero_js, Vector((.42, .38, 1)), .3, .3),
             (11.0, hero_js + Vector((0, .015, 0)), Vector((.12, .3, 1)), .165, .165),
             (15.6, Vector((0, .17, .02)), Vector((-.2, .34, 1)), .48, .48),
             (17.6, Vector((0, .14, .02)), Vector((-.14, .3, 1)), .52, .52),
             (25.4, Vector((0, -.34, 0)), Vector((0, .14, 1)), .62, .96)]
    for t, target, dvec, hw, hh in shots:
        dist = max(hh / tv, hw / (tv * aspect))
        cam.location = js2b(target + dvec.normalized() * dist)
        tgt.location = js2b(target)
        key(cam, "location", F(t))
        key(tgt, "location", F(t))
    for t, fs in ((0, 16), (4.4, 16), (5.4, 2.0), (11, 1.6), (17.6, 2.4), (19.2, 2.8), (20.6, 6.5)):
        cam_data.dof.aperture_fstop = fs
        cam_data.dof.keyframe_insert("aperture_fstop", frame=F(t))

    # --- lights
    def light(name, kind, color, pos_js, aim_js, size=1.0, spot=None):
        ld = bpy.data.lights.new(name, kind)
        ld.color = color
        if kind == "AREA":
            ld.shape = "DISK"
            ld.size = size
        elif kind == "SPOT":
            ld.spot_size, ld.spot_blend = spot
            ld.shadow_soft_size = size
        else:
            ld.shadow_soft_size = size
        ob = new_obj(name, ld, coll=STAGE)
        ob.location = js2b(pos_js)
        aim(ob, js2b(aim_js))
        return ld

    def energy_keys(ld, pts):
        for t, e in pts:
            ld.energy = e
            ld.keyframe_insert("energy", frame=F(t))

    key_l = light("Key", "AREA", (1, .84, .66), Vector((-2.2, 2.9, 1.9)), Vector((0, -.05, 0)), size=2.2)
    fill_l = light("Fill", "AREA", (1, .62, .72), Vector((2.4, .2, 1.6)), Vector((0, 0, 0)), size=2.5)
    rim_l = light("Rim", "AREA", (1, .78, .47), Vector((.6, 1.6, -2.6)), Vector((0, .1, 0)), size=1.4)
    hero_l = light("HeroSpot", "SPOT", (1, .9, .8), hero_js + Vector((.25, 1.9, .55)), hero_js, size=.08, spot=(math.radians(30), .7))
    sweep_l = light("Sweep", "POINT", (1, .89, .75), Vector((-1.6, .7, 1.4)), Vector((0, 0, 0)), size=.3)
    energy_keys(key_l, [(0, 0), (10.4, 0), (15.2, 520)])
    energy_keys(fill_l, [(0, 0), (4.5, 0), (6.6, 25), (10.4, 25), (15.2, 90)])
    energy_keys(rim_l, [(0, 0), (10.4, 0), (15.2, 380)])
    energy_keys(hero_l, [(0, 0), (4.5, 0), (6.6, 160), (11.5, 160), (16, 55)])
    energy_keys(sweep_l, [(0, 0), (17.8, 0), (21.1, 70), (24.5, 0)])
    so = bpy.data.objects["Sweep"]
    so.location = js2b(Vector((-1.6, .7, 1.4)))
    key(so, "location", F(17.8))
    so.location = js2b(Vector((1.6, .7, 1.4)))
    key(so, "location", F(24.5))

    # --- volumetric haze
    if not ARGS.no_volume and ARGS.quality == "final":
        V, Fc = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)], \
            [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        vm = bpy.data.materials.new("Haze")
        vm.use_nodes = True
        nt = vm.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        pv = nt.nodes.new("ShaderNodeVolumePrincipled")
        pv.inputs["Density"].default_value = .035
        pv.inputs["Color"].default_value = (1, .92, .85, 1)
        pv.inputs["Anisotropy"].default_value = .35
        nt.links.new(pv.outputs[0], out.inputs["Volume"])
        hz = new_obj("Haze", new_mesh("Haze", ([Vector(v) * 4.5 for v in V], Fc, None, None), vm, smooth_shade=False), coll=STAGE)

    # --- floating dust motes
    dm = emission_mat("Dust", srgb("#ffd2a0"), 5)
    V, Fc = icosphere_data(1)
    mote = new_mesh("Mote", (V, Fc, None, None), dm)
    for i in range(320 if ARGS.quality == "final" else 160):
        ob = new_obj(f"Dust_{i:03d}", mote, coll=STAGE)
        s = rr(.0009, .0024) if R.random() > .05 else rr(.004, .007)
        ob.scale = (s, s, s)
        p0 = Vector((rr(-2.2, 2.2), rr(-1.5, 1.7), rr(-1.6, 2.4)))
        drift = Vector((rr(.1, .3), rr(.3, .9), rr(-.15, .15)))
        ob.location = js2b(p0)
        key(ob, "location", 0, interp="LINEAR")
        ob.location = js2b(p0 + drift)
        key(ob, "location", F(T["end"]), interp="LINEAR")
        ob.visible_shadow = False

    # --- titles (parented to the camera)
    font = None
    if ARGS.font and os.path.exists(ARGS.font):
        font = bpy.data.fonts.load(ARGS.font)

    def title(name, text, size, y, t_in, t_out=None, color=srgb("#f4e8d8")):
        cu = bpy.data.curves.new(name, "FONT")
        cu.body = text
        cu.size = size
        cu.align_x = "CENTER"
        cu.align_y = "CENTER"
        if font:
            cu.font = font
        mat = emission_mat(name + "_Mat", color, 2.2, alpha_anim=True)
        cu.materials.append(mat)
        ob = new_obj(name, cu, coll=STAGE)
        ob.parent = cam
        ob.location = (0, y * TEXT_DIST, -TEXT_DIST)
        ob.scale = (TEXT_DIST,) * 3
        fade = mat.node_tree.nodes["Fade"].inputs[0]
        for t, v in [(t_in, 0), (t_in + 2.2, 1)] + ([(t_out, 1), (t_out + 1.6, 0)] if t_out else []):
            fade.default_value = v
            fade.keyframe_insert("default_value", frame=F(t))
        return ob, mat

    title("Title_Opening", LINE_OPENING, .026, 0, T["text1_in"], T["text1_out"])
    title("Title_Reveal", LINE_REVEAL, .019, -.158, T["text2"])
    sig, sig_mat = title("Title_Signature", LINE_SIGNATURE, .017, -.208, T["text3"], color=srgb("#f1d9cf"))
    bpy.context.view_layer.update()
    # a small heart after the signature
    hpts = []
    for i in range(48):
        a = i / 48 * math.tau
        hpts.append(Vector((16 * math.sin(a) ** 3, 13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a), 0)) * .00042)
    hm = bpy.data.meshes.new("Heart")
    hm.from_pydata([tuple(p) for p in hpts], [], [list(range(48))])
    hmat = emission_mat("Heart_Mat", srgb("#e45a6e"), 2.4, alpha_anim=True)
    hm.materials.append(hmat)
    heart = new_obj("Title_Heart", hm, coll=STAGE)
    heart.parent = cam
    heart.location = ((sig.dimensions.x / TEXT_DIST / 2 + .012) * TEXT_DIST, -.2075 * TEXT_DIST, -TEXT_DIST)
    heart.scale = (TEXT_DIST,) * 3
    fade = hmat.node_tree.nodes["Fade"].inputs[0]
    for t, v in ((T["text3"] + .6, 0), (T["text3"] + 2.8, 1)):
        fade.default_value = v
        fade.keyframe_insert("default_value", frame=F(t))


def setup_render(quality):
    sc = SCENE
    sc.render.engine = "CYCLES"
    cy = sc.cycles
    final = quality == "final"
    sc.render.resolution_x, sc.render.resolution_y = (1920, 1080) if final else (960, 540)
    sc.render.resolution_percentage = 100
    cy.samples = 384 if final else 48
    cy.use_denoising = True
    try:
        cy.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    cy.use_adaptive_sampling = True
    cy.max_bounces, cy.diffuse_bounces, cy.glossy_bounces, cy.transmission_bounces = 8, 3, 3, 6
    cy.transparent_max_bounces = 16
    cy.caustics_reflective = cy.caustics_refractive = False
    cy.volume_step_rate = 2.0 if final else 4.0
    sc.render.use_persistent_data = True
    sc.render.film_transparent = False
    try:
        sc.view_settings.view_transform = "AgX"
        sc.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        try:
            sc.view_settings.look = "Medium High Contrast"
        except Exception:
            pass
    sc.view_settings.exposure = .25
    sc.render.image_settings.file_format = "PNG"
    # GPU if available
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for dev_type in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
            try:
                prefs.compute_device_type = dev_type
                prefs.get_devices()
                if any(d.type == dev_type for d in prefs.devices):
                    for d in prefs.devices:
                        d.use = True
                    cy.device = "GPU"
                    print("Cycles device:", dev_type)
                    break
            except Exception:
                continue
    except Exception:
        pass


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    os.makedirs(ARGS.out, exist_ok=True)
    if ARGS.glb:
        export_glb(os.path.join(ARGS.out, "bouquet.glb"))
    if WEB and not ARGS.save:
        return
    final = ARGS.quality == "final"
    aspect = 16 / 9
    build_stage(aspect)
    setup_render(ARGS.quality)
    if ARGS.save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(ARGS.out, "bouquet.blend"))
    if ARGS.still:
        s = ARGS.still
        fr = int(s[1:]) if s.upper().startswith("F") else F(float(s))
        SCENE.frame_set(fr)
        SCENE.render.filepath = os.path.join(ARGS.out, f"still_{fr:04d}.png")
        bpy.ops.render.render(write_still=True)
        print("Wrote", SCENE.render.filepath)
    if ARGS.anim:
        os.makedirs(os.path.join(ARGS.out, "frames"), exist_ok=True)
        SCENE.render.filepath = os.path.join(ARGS.out, "frames", "frame_")
        bpy.ops.render.render(animation=True)
        print("Frames written. Encode with:\n  ffmpeg -framerate 30 -i out/frames/frame_%04d.png "
              "-c:v libx264 -pix_fmt yuv420p -crf 17 -preset slow -movflags +faststart bouquet_cinematic.mp4")


if __name__ == "__main__":
    main()
