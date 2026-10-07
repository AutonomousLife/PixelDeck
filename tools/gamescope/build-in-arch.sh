#!/usr/bin/bash
# Runs INSIDE an Arch Linux ARM container (menci/archlinuxarm:base-devel) on an arm64 runner.
# Builds Arch's own gamescope package of the runtime's version with the patches in ./patches
# added, then keeps only the gamescope binary, checks its library needs against the runtime's
# list, and packs it as gamescope.tzst (usr/local/bin/gamescope) for the apk to stage.
set -euxo pipefail
VERSION=${GAMESCOPE_VERSION:-3.16.29}
WORK=/work
cd "$WORK"
# pacman's download sandbox (Landlock + the alpm user) cannot be set up inside the runner's
# container; the packages still come signed from Arch Linux ARM's mirrors.
grep -q '^DisableSandbox' /etc/pacman.conf || sed -i 's/^\[options\]/[options]\nDisableSandbox/' /etc/pacman.conf
# The geo-redirecting mirror answered 500s and connection resets mid-transaction; name a few
# concrete mirrors ahead of it so pacman has somewhere to fall over to.
{ for m in https://ca.us.mirror.archlinuxarm.org https://fl.us.mirror.archlinuxarm.org https://de3.mirror.archlinuxarm.org https://nl.mirror.archlinuxarm.org; do echo "Server = $m/\$arch/\$repo"; done; cat /etc/pacman.d/mirrorlist; } > /etc/pacman.d/mirrorlist.new
mv /etc/pacman.d/mirrorlist.new /etc/pacman.d/mirrorlist
pacman -Syu --noconfirm --needed git sudo zstd binutils curl
if [ -f tools/gamescope/patches/0118-kbase-wayland-dmabuf-v3.patch ]; then
  # Pin the patched wlroots source instead of using an unpatched system library.
  curl -fsSL --retry 3 https://deb.debian.org/debian/pool/main/w/wlroots/wlroots_0.20.2.orig.tar.bz2 -o wlroots-0.20.2.tar.bz2
  echo '20c37b521dc3054b6e9627b79bdd45fc716db9ebc58bdf97e57e84d04b04610f  wlroots-0.20.2.tar.bz2' | sha256sum -c -
fi
# makepkg refuses root; a builder user with passwordless sudo installs the dependencies.
id builder >/dev/null 2>&1 || useradd -m builder
echo 'builder ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/builder
rm -rf pkg && mkdir pkg && cp -r tools/gamescope/patches pkg/ && chown -R builder pkg
# Arch's packaging for exactly this version: the tag is <pkgver>-<pkgrel>; the first rel is tried
# first, later ones after it.
sudo -u builder bash -c "
set -euxo pipefail
cd pkg
for rel in 1 2 3 4; do
  if git clone -q --depth 1 --branch ${VERSION}-\$rel https://gitlab.archlinux.org/archlinux/packaging/packages/gamescope.git arch 2>/dev/null; then break; fi
done
test -f arch/PKGBUILD
cd arch
grep -q '^pkgver=${VERSION}$' PKGBUILD
cp ../patches/*.patch .
# Add our patches to the source list and apply them after Arch's own prepare() steps.
PATCHES=\$(ls *.patch | sort)
{ echo; echo 'source+=('; for p in \$PATCHES; do echo \"  \$p\"; done; echo ')'; for p in \$PATCHES; do echo \"sha256sums+=('SKIP')\"; done; } >> PKGBUILD
cat >> PKGBUILD <<'PREP'

_droiddeck_prepare() {
  # Arch's own prepare() leaves the shell inside the checkout; start from a known place.
  cd \"\$srcdir/gamescope\"
  if [ -f \"\$srcdir/0118-kbase-wayland-dmabuf-v3.patch\" ]; then
    mkdir -p subprojects/wlroots
    tar -xjf /work/wlroots-0.20.2.tar.bz2 --strip-components=1 -C subprojects/wlroots
  fi
  for p in \$(ls \"\$srcdir\"/*.patch | sort); do
    echo \"applying \$(basename \"\$p\")\"
    patch -p1 --no-backup-if-mismatch < \"\$p\"
  done
}
if declare -f prepare >/dev/null; then
  eval \"\$(declare -f prepare | sed 's/^prepare ()/_arch_prepare ()/')\"
  prepare() { _arch_prepare; _droiddeck_prepare; }
else
  prepare() { _droiddeck_prepare; }
fi
PREP
makepkg -A -s --noconfirm --skipchecksums --skippgpcheck  # -A: the PKGBUILD lists x86_64 only; Arch Linux ARM builds the same file
ls -l *.pkg.tar.*
"
cd "$WORK"
rm -rf out && mkdir -p out/usr/local/bin
PKG=$(ls pkg/arch/gamescope-*.pkg.tar.* | grep -v -- '-debug-' | head -1)
tar --use-compress-program=unzstd -xf "$PKG" -C out --strip-components=2 usr/bin/gamescope
mv out/gamescope out/usr/local/bin/gamescope
chmod 755 out/usr/local/bin/gamescope
strip --strip-unneeded out/usr/local/bin/gamescope || true
# Every NEEDED library must be one the runtime ships, or the binary would not load there.
NEEDED=$(readelf -d out/usr/local/bin/gamescope | sed -n 's/.*NEEDED.*\[\(.*\)\]/\1/p')
echo "NEEDED: $NEEDED"
MISSING=""
for lib in $NEEDED; do grep -qx "$lib" tools/gamescope/runtime-sonames.txt || MISSING="$MISSING $lib"; done
if [ -n "$MISSING" ]; then echo "ERROR: not in the runtime:$MISSING"; exit 3; fi
(cd out && tar --use-compress-program='zstd -19' -cf ../gamescope.tzst usr)
sha256sum gamescope.tzst | tee gamescope.tzst.sha256
ls -l gamescope.tzst out/usr/local/bin/gamescope
