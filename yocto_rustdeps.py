#!/usr/bin/python3
"""
Generate BitBake SRC_URI lines and per-crate sha256sum entries from Cargo.lock.

Requires:
- python3
- system python3-toml (module name: toml)
- requests (install with: python3 -m pip install --user requests)

Usage:
    python3 cargo_lock_to_bitbake_with_checksums.py Cargo.lock
"""
import argparse
import hashlib
import os
import sys
import tempfile
import requests
try:
    import tomllib as toml_reader  # py3.11+
except ModuleNotFoundError:  # pragma: no cover
    import toml as toml_reader

CRATES_IO_DL = "https://crates.io/api/v1/crates/{name}/{vers}/download"

def load_lock(path):
    # tomllib requires binary mode, while the external "toml" module expects text.
    try:
        with open(path, "rb") as f:
            data = toml_reader.load(f)
    except TypeError:
        with open(path, "r", encoding="utf-8") as f:
            data = toml_reader.load(f)
    return data.get("package", [])

def unique_packages(pkgs):
    seen = set()
    out = []
    for p in pkgs:
        name = p.get("name")
        version = p.get("version")
        if not name or not version:
            continue
        key = (name, version)
        if key in seen:
            continue
        seen.add(key)
        out.append((name, version))
    return out

def download_crate(name, version, dest_dir):
    url = CRATES_IO_DL.format(name=name, vers=version)
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    fname = os.path.join(dest_dir, f"{name}-{version}.crate")
    # If file already exists, reuse it
    if os.path.exists(fname):
        return fname
    with open(fname, "wb") as fh:
        for chunk in r.iter_content(8192):
            if chunk:
                fh.write(chunk)
    return fname

def sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def main():
    p = argparse.ArgumentParser(description="Generate BitBake SRC_URI and checksum lines from Cargo.lock")
    p.add_argument("lockfile", help="Path to Cargo.lock")
    p.add_argument("--cache-dir", default=None, help="Directory to cache downloaded .crate files (default: temp dir)")
    args = p.parse_args()

    try:
        pkgs = load_lock(args.lockfile)
    except Exception as e:
        print(f"# ERROR reading Cargo.lock: {e}", file=sys.stderr)
        sys.exit(1)

    pkgs = unique_packages(pkgs)
    if not pkgs:
        print("# no packages found in Cargo.lock", file=sys.stderr)
        sys.exit(1)

    cache_dir = args.cache_dir or tempfile.mkdtemp(prefix="crates-")
    os.makedirs(cache_dir, exist_ok=True)

    for name, version in pkgs:
        try:
            path = download_crate(name, version, cache_dir)
        except Exception as e:
            print(f"# ERROR downloading {name} {version}: {e}", file=sys.stderr)
            # still print SRC_URI line without checksum
            print(f'SRC_URI += " crate://crates.io/{name}/{version} "')
            continue
        sha = sha256_of_file(path)
        var = f"{name}-{version}.sha256sum"
        print(f'SRC_URI += " crate://crates.io/{name}/{version} "')
        print(f'SRC_URI[{var}] = "{sha}"')

if __name__ == "__main__":
    main()
