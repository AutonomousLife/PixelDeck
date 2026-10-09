"""Check the artifact's ELF alignment, bionic dependencies, and PulseAudio 13 ABI."""
import re
import struct
import subprocess
import sys
from pathlib import Path


def check(root, readelf):
    expected = {"libltdl.so", "libpulse.so", "libpulseaudio.so", "libpulsecommon-13.0.so",
                "libpulsecore-13.0.so", "libsndfile.so"}
    required_imports = {
        "libpulse.so": {"libpulsecommon-13.0.so"},
        "libpulsecommon-13.0.so": {"libsndfile.so"},
        "libpulsecore-13.0.so": {"libpulsecommon-13.0.so", "libpulse.so", "libltdl.so", "libsndfile.so"},
        "libpulseaudio.so": {"libpulsecore-13.0.so", "libpulsecommon-13.0.so", "libpulse.so", "libltdl.so"},
    }
    assert {p.name for p in (root / "lib").glob("*.so")} == expected
    modules = root / "modules/arm64"
    for name in ("module-native-protocol-unix", "libprotocol-native", "module-pipe-source",
                 "module-pipe-sink", "module-aaudio-classic-sink", "module-aaudio-sink",
                 "module-directaudio-sink"):
        assert (modules / f"{name}.so").is_file(), name
    files = sorted(root.glob("lib/*.so")) + sorted(modules.glob("*.so")) + [root / "pactl"]
    allowed = {p.name for p in files} | {"libc.so", "libm.so", "libdl.so", "liblog.so", "libaaudio.so"}
    for path in files:
        data = path.read_bytes()
        assert data[:6] == b"\x7fELF\x02\x01", path
        header = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
        assert header[1] == 183, f"{path}: not AArch64"
        assert header[0] == 3, f"{path}: not shared object / PIE"
        headers = [struct.unpack_from("<IIQQQQQQ", data, header[4] + i * header[8])
                   for i in range(header[9])]
        if path.name in {"libpulseaudio.so", "pactl"}:
            assert any(h[0] == 3 for h in headers), f"{path}: PIE interpreter missing"
        loads = [h for h in headers if h[0] == 1]
        assert loads, path
        for h in loads:
            assert h[7] >= 16384 and h[7] & (h[7] - 1) == 0, f"{path}: LOAD alignment"
            assert (h[3] - h[2]) % h[7] == 0, f"{path}: LOAD offset/address"
        for h in headers:
            if h[0] == 0x6474E552:
                assert (h[3] + h[6]) % 16384 == 0, f"{path}: RELRO end"
            if h[0] == 3:
                interp = data[h[2]:h[2] + h[5]].rstrip(b"\0")
                assert interp == b"/system/bin/linker64", f"{path}: interpreter {interp!r}"
        dynamic = subprocess.check_output([readelf, "-d", str(path)], text=True)
        needed = set(re.findall(r"\(NEEDED\).*?\[([^]]+)\]", dynamic))
        assert needed <= allowed, f"{path}: unexpected imports {needed - allowed}"
        assert required_imports.get(path.name, set()) <= needed, f"{path}: missing PA13 imports"
        assert b"GLIBC_" not in data, f"{path}: glibc dependency"
        if path.name in expected - {"libpulseaudio.so"}:
            soname = re.findall(r"\(SONAME\).*?\[([^]]+)\]", dynamic)
            assert soname == [path.name], f"{path}: SONAME {soname}"
        if path.name.startswith("module-"):
            symbols = subprocess.check_output([readelf, "--dyn-syms", "--wide", str(path)], text=True)
            # PulseAudio's module loader accepts an absent pa__done (e.g. module-detect).
            required = ["pa__init", "pa__get_version"]
            if path.name in {"module-aaudio-classic-sink.so", "module-aaudio-sink.so", "module-directaudio-sink.so"}:
                required.append("pa__done")
            for symbol in required:
                assert re.search(rf"\s(?:\w+_LTX_)?{symbol}$", symbols, re.M), f"{path}: missing {symbol}"
        print(f"PASS {path.relative_to(root)} LOAD/RELRO 16KB; imports={','.join(sorted(needed))}")
    assert b"13.0" in (root / "lib/libpulseaudio.so").read_bytes()
    assert b"libsndfile-1.0.31" in (root / "lib/libsndfile.so").read_bytes()


if __name__ == "__main__":
    check(Path(sys.argv[1]), sys.argv[2])
