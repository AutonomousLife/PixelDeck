#!/usr/bin/env bash
# Reuse the exact Bannerlator pipeline that produced DroidDeck's six audio prebuilts.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
WORK="$REPO/build/pixel-audio"
OUT="$WORK/artifact"
: "${NDK_PATH:?set NDK_PATH to Android NDK r27c (27.2.12479018)}"
grep -q 'Pkg.Revision = 27.2.12479018' "$NDK_PATH/source.properties"
mkdir -p "$WORK/.src" "$OUT/sources" "$OUT/licenses"
cd "$WORK"
BANNER_COMMIT=198893a07bfbc850d488d46160fdb734a5d411ac
BANNER_URL="https://raw.githubusercontent.com/The412Banner/Bannerlator/$BANNER_COMMIT"
fetch() {
  local name=$1 digest=$2 url=$3
  if [[ ! -f "$name" ]]; then
    curl -fsSL --retry 3 --connect-timeout 20 --max-time 120 "$url" -o "$name"
  fi
  echo "$digest  $name" | sha256sum -c -
}
fetch .src/libtool-2.4.6.tar.gz e3bd4d5d3d025a36c21dd6af7ea818a2afcd4dfc1ea5a17b39d7854bcd0c06e3 https://mirrors.kernel.org/gnu/libtool/libtool-2.4.6.tar.gz
fetch .src/libsndfile-1.0.31.tar.bz2 a8cfb1c09ea6e90eff4ca87322d4168cdbe5035cb48717b40bf77e751cc02163 https://github.com/libsndfile/libsndfile/releases/download/1.0.31/libsndfile-1.0.31.tar.bz2
fetch .src/pulseaudio-13.0.tar.xz 961b23ca1acfd28f2bc87414c27bb40e12436efcf2158d29721b1e89f3f28057 https://old-releases.ubuntu.com/ubuntu/pool/main/p/pulseaudio/pulseaudio_13.0.orig.tar.xz
fetch build-stack.original.sh da7651367650ade8d70480263b1649c76381bd35aab6d309ad367f24b9ed7467 "$BANNER_URL/native/pulseaudio-android/build-stack.sh"
fetch module-aaudio-classic-sink.c 362945d72b9e1e7f5baddb426e1ce5c0c781db3b2495ab71ecec6560aa85cedf "$BANNER_URL/native/pulseaudio-android/pulseaudio-module/module-aaudio-sink.c"
fetch "$OUT/licenses/Bannerlator-GPL-3.0.txt" c8264e42ef8f1b8f6e9d7086bbf778472e2bc636018437d5821f6ee76f411ed1 "$BANNER_URL/LICENSE"
# Apply only the two linker flags; all source/configure inputs remain those of the shipped ABI.
python3 - <<'PY'
from pathlib import Path
p = Path('build-stack.original.sh').read_text()
old = 'export LDFLAGS="-L$ROOT_DIR/lib"'
assert p.count(old) == 1
Path('build-stack.sh').write_text(p.replace(old, old[:-1] + ' -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384"'))
PY
# The original script skips installed dependencies. A new link configuration needs a clean prefix.
[[ "$PWD" == "$REPO/build/pixel-audio" ]]
rm -rf root-arm64 output
bash build-stack.sh
ROOT_DIR="$WORK/root-arm64"
PA_SRC="$WORK/.src/pulseaudio-13.0"
TOOLCHAIN="$NDK_PATH/toolchains/llvm/prebuilt/linux-x86_64/bin"
CC="$TOOLCHAIN/aarch64-linux-android26-clang"
mkdir -p "$OUT/lib" "$OUT/modules/arm64"
cp -L output/arm64/*.so "$OUT/lib/"
cp -L "$ROOT_DIR/bin/pactl" "$OUT/pactl"
cp -L "$ROOT_DIR"/lib/pulse-13.0/modules/*.so "$OUT/modules/arm64/"
build_sink() {
  local source=$1 name=$2 extra=$3
  "$CC" -O2 -shared -fPIC -DHAVE_CONFIG_H -Wno-error=int-conversion \
    -Wno-error=implicit-function-declaration -Wno-error=implicit-int \
    -Wno-error=incompatible-pointer-types -Wno-error=incompatible-function-pointer-types \
    -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384 \
    -I"$PA_SRC/build-arm64" -I"$PA_SRC/src" -I"$ROOT_DIR/include" \
    -o "$OUT/modules/arm64/$name.so" "$source" \
    -L"$ROOT_DIR/lib/pulseaudio" -L"$ROOT_DIR/lib" \
    -lpulsecore-13.0 -lpulsecommon-13.0 -lpulse $extra
}
build_sink "$WORK/module-aaudio-classic-sink.c" module-aaudio-classic-sink -laaudio
build_sink "$REPO/tools/aaudio-sink/module-aaudio-sink.c" module-aaudio-sink -laaudio
build_sink "$REPO/tools/aaudio-sink/module-directaudio-sink.c" module-directaudio-sink ""
find "$OUT/lib" "$OUT/modules" -name '*.so' -exec "$TOOLCHAIN/llvm-strip" --strip-unneeded {} +
"$TOOLCHAIN/llvm-strip" --strip-unneeded "$OUT/pactl"
python3 "$REPO/tools/pixel-audio/check.py" "$OUT" "$TOOLCHAIN/llvm-readelf" | tee "$OUT/ELF-CHECK.txt"
cp .src/*.tar.* build-stack.original.sh build-stack.sh module-aaudio-classic-sink.c "$OUT/sources/"
cp "$REPO/tools/pixel-audio/build.sh" "$REPO/tools/pixel-audio/check.py" "$REPO/tools/aaudio-sink/"*.c "$OUT/sources/"
cp "$PA_SRC/build-arm64/config.h" "$OUT/sources/pulseaudio-config.h"
cp "$PA_SRC/LICENSE" "$OUT/licenses/PulseAudio-LICENSE.txt"
cp "$PA_SRC/LGPL" "$OUT/licenses/PulseAudio-LGPL-2.1.txt"
cp "$WORK/.src/libsndfile-1.0.31/COPYING" "$OUT/licenses/libsndfile-COPYING.txt"
cp "$WORK/.src/libtool-2.4.6/COPYING" "$OUT/licenses/libtool-COPYING.txt"
cp "$WORK/.src/libtool-2.4.6/libltdl/COPYING.LIB" "$OUT/licenses/libltdl-COPYING.LIB.txt"
cat > "$OUT/PROVENANCE.txt" <<EOF
Bannerlator: https://github.com/The412Banner/Bannerlator/tree/$BANNER_COMMIT/native/pulseaudio-android
PixelDeck source: $(git -C "$REPO" rev-parse HEAD)
PulseAudio 13.0, libtool 2.4.6, libsndfile 1.0.31; pristine source archives included.
Android arm64-v8a, bionic, API 26, NDK r27c 27.2.12479018.
Pipeline change: max-page-size=16384 and common-page-size=16384 in LDFLAGS.
Classic AAudio sink: Tom Yan / BrunoSX, adaptive changes from Bannerlator (LGPL-2.1-or-later).
AAudio and DirectAudio sink source: PixelDeck tools/aaudio-sink, copied into sources/.
No deployment or replacement of repository prebuilts occurs in this build.
EOF
cd "$OUT"
# The normal APK build injects the two DroidDeck sink modules into its base bundle.
# Keep that input contract, and also supply a complete bundle for direct integration.
tar --use-compress-program='zstd -19' -cf pulseaudio.tzst \
  --exclude=modules/arm64/module-aaudio-sink.so \
  --exclude=modules/arm64/module-directaudio-sink.so modules pactl
tar --use-compress-program='zstd -19' -cf pulseaudio-complete.tzst modules pactl
find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
