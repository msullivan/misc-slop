#!/usr/bin/env python3
"""Build the page for publishing as a Claude artifact.

Artifacts allow inline scripts and files fetched from beside the page, so
this folds the page's own JavaScript modules into one inline module (with
the worker as a blob) and leaves the simulator and creature data as files.

usage: tools/build_artifact.py OUT_DIR
Writes OUT_DIR/menagerie.html plus copies of mg.wasm and data/*.json.
"""
import json
import os
import re
import shutil
import sys

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web")


def read(name):
    with open(os.path.join(WEB, name)) as f:
        return f.read()


def strip_module(src):
    """Drop local imports and `export` keywords so modules can be pasted together."""
    src = re.sub(r"^import [^;]*? from '\./[^']+';\n", "", src, flags=re.M)
    return re.sub(r"^export ", "", src, flags=re.M)


def main():
    out_dir = sys.argv[1]
    os.makedirs(os.path.join(out_dir, "data"), exist_ok=True)
    html = read("index.html")
    page = html[html.index("<!--PAGE-->") + len("<!--PAGE-->") : html.index("<!--/PAGE-->")]

    engine = strip_module(read("engine.js"))
    worker = strip_module(read("worker.js"))
    nursery = strip_module(read("nursery.js"))
    app = read("app.js")
    cdn_imports = "".join(re.findall(r"^import [^;]*? from '(?!\./)[^']+';\n", app, flags=re.M))
    app = re.sub(r"^import [^;]*;\n", "", app, flags=re.M)

    # The worker needs the engine too; give it its own copy as a blob.
    worker_src = engine + "\n" + worker
    bundle = "\n".join(
        [
            cdn_imports,
            engine,
            nursery,
            "workerFactory.make = () => new Worker(URL.createObjectURL(new Blob([%s], { type: 'text/javascript' })), { type: 'module' });"
            % json.dumps(worker_src),
            app,
        ]
    )
    assert "</script" not in bundle.lower()
    tag = '<script type="module" src="app.js"></script>'
    assert tag in page
    page = page.replace(tag, '<script type="module">\n' + bundle + "\n</script>")
    with open(os.path.join(out_dir, "menagerie.html"), "w") as f:
        f.write(page.strip() + "\n")
    with open(os.path.join(out_dir, "bundle.mjs"), "w") as f:
        f.write(bundle)

    shutil.copy(os.path.join(WEB, "mg.wasm"), os.path.join(out_dir, "mg.wasm"))
    files = {"mg.wasm": "mg.wasm"}
    for name in sorted(os.listdir(os.path.join(WEB, "data"))):
        if name.endswith(".json"):
            shutil.copy(os.path.join(WEB, "data", name), os.path.join(out_dir, "data", name))
            files[f"data/{name}"] = f"data/{name}"
    with open(os.path.join(out_dir, "files.json"), "w") as f:
        json.dump(files, f, indent=1)
    total = sum(os.path.getsize(os.path.join(out_dir, p)) for p in files)
    print(f"page {os.path.getsize(os.path.join(out_dir, 'menagerie.html')) / 1e3:.0f} kB, files {total / 1e6:.1f} MB: {', '.join(files)}")


if __name__ == "__main__":
    main()
