# PixelDeck (experimental)

PixelDeck is a Tensor-device port of [DroidDeck](https://github.com/Droid-Deck/DroidDeck).
On a locked Pixel 7 Pro running Android 17, stock GLES and Vulkan hardware-buffer
import/render/readback/presentation have passed. Linux PanVK GPU readback and
a 600-frame cube test inside patched Gamescope have also passed. Native ARM64
vkQuake with free LibreQuake data completed a Vulkan benchmark at 42.1 engine FPS
at 1280×720; the current copied display path showed about 32–34 FPS. Steam has
rendered its Big Picture sign-in screen on the phone using software OpenGL after
fixing Gamescope's copied XRGB alpha handling. Steam login and
Proton/Windows games remain untested. The upstream requirements below do not yet
describe Pixel support. See [bring-up results](docs/development/pixel7pro-bringup.md).
Reused copied buffers now refresh each frame, and the Vulkan game demo visibly
advances through its 3D level on the phone at about 33 display FPS. Input still
needs a device check.

For the Windows development loop, install JDK 21, Python 3.14+, GitHub CLI,
Android SDK platform 34
and build-tools 35.0.0, then run:

```powershell
python tools/pixel-probe/bootstrap_sdk.py
python tools/pixel-build.py --serial YOUR_DEVICE_SERIAL
python tools/droiddeckctl --package dev.pixeldeck.launcher --serial YOUR_DEVICE_SERIAL state
```

The full-app helper stages checksum-pinned upstream Linux prebuilts and the fixed
Pixel runtime/Gamescope components, then uses incremental Gradle/NDK builds.
Keep `build/pixel-probe/upstream-ci.zip` and `build/pixel-components/*.zip`:
Actions artifacts expire. Changed Linux native components need their matching
Linux CI build; this helper rebuilds Android native/Java/Kotlin code and scripts.
PanVK remains an explicit experimental driver import. When selected, it uses
Gamescope's SDL backend and software OpenGL, including OpenGL games;
Vulkan remains on the Mali GPU. The helper refuses changed Pixel native sources
until their CI artifacts and pins are rebuilt. Other Linux native components
still come from the pinned upstream APK.

Steam requires Developer options → **Restrict child processes** to be off.
The connected test phone uses `settings_enable_monitor_phantom_procs=false`;
the default process monitor killed Steam sessions. The bundled audio stack has
been rebuilt with 16 KB alignment, including matching modules; all 22 APK native
libraries pass the alignment check. An old Android warning dialog can survive an
update and need dismissal once. This is an experimental debug build.

The original DroidDeck README follows, with its upstream credits and instructions.

---

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="artwork/droiddeck-banner-dark.svg">
    <img alt="DroidDeck" src="artwork/droiddeck-banner-light.svg" width="100%">
  </picture>
</p>

DroidDeck brings the SteamOS experience to Android: Valve's Steam client in Big Picture on your Adreno handheld, with Windows games through Valve's ARM64 Proton.

<p align="center"><a href="https://discord.gg/JRGAvawjsm"><img src="https://img.shields.io/badge/Discord-Join%20the%20community-5865F2?logo=discord&logoColor=white" alt="Join the DroidDeck Discord"></a></p>

<p align="center"><img src="docs/releases/media/0.2.0/launch-into-steam.gif" width="80%" alt="Tapping DroidDeck on the Android home screen and landing in Steam Big Picture"></p>

> Note: DroidDeck does not have a stand-alone website. Do not click on any download links from websites claiming to be the DroidDeck team. 

## Requirements and install

Use Android 9 or newer on a supported Adreno device (730 or newer, or 8xx). Mali, Xclipse, PowerVR, and Adreno 710 are unsupported. No root is required. Allow about 3 GB for the runtime and 1.1 GB more for the desktop and emulators. Install the APK from [Releases](https://github.com/Droid-Deck/DroidDeck/releases), install the Linux runtime, then press **Play** and sign in. Steam downloads on first launch. Install **Desktop & apps** to use the desktop and emulators. The **Store** installs Linux apps and games from Flathub (ARM64 builds) with Flatpak; with additional options to install Appimages and set up scripts.

Before Steam launches, you must turn off **Restrict child processes** in Developer options. If this option is not available in developer settings (Android 12 and 13 devices), first launch of Steam will present a "Fix it for me" button, which will help automate the setup process.

## Community

Join the [DroidDeck Discord](https://discord.gg/JRGAvawjsm) for help, Preview builds, and device reports. Bug reports go in its **#bug-reports** forum; attach the session folder from `Download/DroidDeck/` so the logs come with it.

## Build

Run `tools/build_local.sh` with Docker, Java 17, the Android SDK/NDK, and `zstd` installed. It builds the ARM64 audio sinks from PulseAudio 13.0 and packages them into the APK at `app/build/outputs/apk/release/app-release.apk`. Set `DROIDDECK_PA13_SOURCE_DIR` to an existing PulseAudio 13.0 source directory to skip downloading it. To install the APK on an attached device, run `tools/deploy_local.sh`.

## Limits

Compatibility and performance vary by device; hardware validation is limited. Desktop compositing uses software rendering. Firefox sandboxing is reduced under proot. See the session logs in `Download/DroidDeck/` when diagnosing problems.

## Credits and licence

GPL-3.0. Runtime, shim, input, and controller work build on WinNative and Bannerlator (maxjivi05). LSFG frame generation is from the work of Camille LaVey and the [Eden](https://eden-emu.dev) emulator project, following [lsfg-vk](https://github.com/PancakeTAS/lsfg-vk), ported to WinNative and DroidDeck by [@maxjivi05](https://github.com/maxjivi05); it needs your own copy of [Lossless Scaling](https://store.steampowered.com/app/993090/) and ships none of its shaders. x86 AppImages, and any whose own runtime cannot unpack them, are unpacked with [uruntime](https://github.com/VHSgunzo/uruntime) by VHSgunzo (MIT), shipped unmodified with its licence. See [LICENSE](LICENSE). Steam and Proton belong to Valve Corporation; this project is not affiliated with Valve.
