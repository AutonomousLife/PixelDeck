#!/usr/bin/env python3
"""Install the two pinned native-build SDK packages from Google's checked archives."""
import hashlib
import os
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

sdk = Path(os.environ.get("ANDROID_HOME", str(Path.home() / "AppData/Local/Android/Sdk"))).resolve()
metadata = ET.fromstring(urllib.request.urlopen(
    "https://dl.google.com/android/repository/repository2-1.xml", timeout=30).read())
for package, strip in [("ndk;27.3.13750724", True), ("cmake;3.22.1", False)]:
    dest = sdk.joinpath(*package.split(";")).resolve()
    if (dest / "source.properties").exists():
        print("Already installed:", dest, flush=True)
        continue
    spec = next(p for p in metadata.findall("remotePackage") if p.get("path") == package)
    archive = next(a for a in spec.findall("archives/archive") if a.findtext("host-os") == "windows")
    filename = archive.findtext("complete/url")
    cached = sdk / ".temp" / "pixeldeck" / filename
    cached.parent.mkdir(parents=True, exist_ok=True)
    if not cached.exists():
        print("Downloading:", filename, flush=True)
        urllib.request.urlretrieve("https://dl.google.com/android/repository/" + filename, cached)
    with cached.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha1").hexdigest()
    if digest != archive.findtext("complete/checksum"):
        raise RuntimeError("Google SDK archive checksum mismatch: " + str(cached))
    print("Extracting:", dest, flush=True)
    with zipfile.ZipFile(cached) as z:
        for item in z.infolist():
            name = item.filename.split("/", 1)[1] if strip else item.filename
            target = (dest / name).resolve()
            if not target.is_relative_to(dest):
                raise RuntimeError("Archive path escapes SDK package: " + item.filename)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(item) as src, target.open("wb") as out:
                    import shutil
                    shutil.copyfileobj(src, out)
    if not (dest / "source.properties").exists():
        (dest / "source.properties").write_text("Pkg.Revision=" + package.split(";")[1] + "\n")
    print("Installed:", package, flush=True)
