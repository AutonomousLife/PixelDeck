The six Android audio prebuilts match Bannerlator commit
`198893a07bfbc850d488d46160fdb734a5d411ac` byte for byte. This build reuses its
stock PulseAudio 13.0 / libtool 2.4.6 / libsndfile 1.0.31 pipeline with both
16 KB linker flags. Source downloads and the upstream script are SHA-256 pinned.

Run the **Pixel audio 16 KB rebuild** workflow, or on Linux with NDK r27c:

```sh
NDK_PATH=/path/to/android-ndk-r27c bash tools/pixel-audio/build.sh
```

The artifact includes the six native binaries, `pactl`, matching modules,
source archives, build scripts, licenses, hashes, and ELF checks.
`pulseaudio.tzst` is the base bundle expected by the normal APK build: it includes
the classic sink and omits DroidDeck's two sinks, which that build injects later.
`pulseaudio-complete.tzst` includes both DroidDeck sinks for direct integration.
All three sink binaries are also provided in `modules/arm64/`.
It does not replace tracked binaries or install anything. Device audio validation
is required before integrating it.
