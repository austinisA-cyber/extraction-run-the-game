"""
Generate the gothic outfit with Meshy (https://www.meshy.ai) from the character sheet.

Two Meshy multi-image-to-3D jobs are run, one per garment, using the
front + back product views cropped from the sheet (see ./input):

    top   : input/top_front.png   + input/top_back.png
    skirt : input/skirt_front.png + input/skirt_back.png

Each job's textured GLB/FBX is downloaded to ./output. If Blender's `bpy`
is importable (or this is run inside Blender), both GLBs are also combined
into output/gothic_outfit_meshy.blend.

Usage
    export MESHY_API_KEY=msy_...            # from https://www.meshy.ai/settings/api
    python meshy_outfit.py                  # both pieces
    python meshy_outfit.py --only skirt     # one piece
    python meshy_outfit.py --single         # front image only (image-to-3d endpoint)
    python meshy_outfit.py --polycount 60000 --triangles

Only the Python standard library is required (bpy optional for the .blend step).
Each job costs Meshy credits.
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.meshy.ai/openapi/v1"
HERE = os.path.dirname(os.path.abspath(__file__))
PIECES = {
    "top": ["top_front.png", "top_back.png"],
    "skirt": ["skirt_front.png", "skirt_back.png"],
}


def data_uri(path):
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


def request(method, url, key, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit("Meshy API %s %s -> HTTP %d: %s" % (method, url, e.code, e.read().decode(errors="replace")))


def download(url, path):
    with urllib.request.urlopen(url, timeout=600) as r, open(path, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)


def run_piece(name, key, args):
    images = [os.path.join(HERE, "input", n) for n in PIECES[name]]
    body = {
        "should_remesh": True,
        "should_texture": True,
        "enable_pbr": True,
        "topology": "triangle" if args.triangles else "quad",
        "target_polycount": args.polycount,
    }
    if args.single:
        endpoint = "image-to-3d"
        body["image_url"] = data_uri(images[0])
    else:
        endpoint = "multi-image-to-3d"
        body["image_urls"] = [data_uri(p) for p in images]

    task_id = request("POST", "%s/%s" % (API, endpoint), key, body)["result"]
    print("[%s] task %s created (%s)" % (name, task_id, endpoint))

    last = None
    while True:
        task = request("GET", "%s/%s/%s" % (API, endpoint, task_id), key)
        status, progress = task.get("status"), task.get("progress")
        if (status, progress) != last:
            print("[%s] %s %s%%" % (name, status, progress))
            last = (status, progress)
        if status == "SUCCEEDED":
            break
        if status in ("FAILED", "CANCELED", "EXPIRED"):
            sys.exit("[%s] task %s: %s" % (name, status, (task.get("task_error") or {}).get("message")))
        time.sleep(10)

    out_dir = os.path.join(HERE, "output")
    os.makedirs(out_dir, exist_ok=True)
    saved = {}
    for fmt, url in (task.get("model_urls") or {}).items():
        if fmt in ("glb", "fbx") and url:
            path = os.path.join(out_dir, "meshy_%s.%s" % (name, fmt))
            download(url, path)
            saved[fmt] = path
            print("[%s] saved %s" % (name, path))
    if task.get("thumbnail_url"):
        download(task["thumbnail_url"], os.path.join(out_dir, "meshy_%s_thumb.png" % name))
    with open(os.path.join(out_dir, "meshy_%s_task.json" % name), "w") as f:
        json.dump(task, f, indent=2)
    return saved


def combine_in_blender(glbs):
    try:
        import bpy
    except ImportError:
        print("bpy not available - skipping .blend step (import the GLBs via File > Import > glTF).")
        return
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for name, path in glbs.items():
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=path)
        col = bpy.data.collections.new("Meshy_" + name)
        bpy.context.scene.collection.children.link(col)
        for ob in set(bpy.data.objects) - before:
            for c in list(ob.users_collection):
                c.objects.unlink(ob)
            col.objects.link(ob)
    out = os.path.join(HERE, "output", "gothic_outfit_meshy.blend")
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print("saved", out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=sorted(PIECES))
    ap.add_argument("--single", action="store_true", help="use only the front image (image-to-3d)")
    ap.add_argument("--polycount", type=int, default=60000)
    ap.add_argument("--triangles", action="store_true", help="triangle topology instead of quads")
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = ap.parse_args(argv)

    key = os.environ.get("MESHY_API_KEY")
    if not key:
        sys.exit("Set MESHY_API_KEY (https://www.meshy.ai/settings/api).")
    glbs = {}
    for name in ([args.only] if args.only else list(PIECES)):
        saved = run_piece(name, key, args)
        if "glb" in saved:
            glbs[name] = saved["glb"]
    if glbs:
        combine_in_blender(glbs)


if __name__ == "__main__":
    main()
