The original six Android audio prebuilts matched Bannerlator commit
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
The verified rebuild is now bundled in PixelDeck. The Windows helper stages the
complete bundle for Gradle and restores the tracked base bundle afterward.
The matching daemon and classic AAudio sink started on the Pixel 7 Pro and
accepted a vkQuake stereo 44.1 kHz stream. Audible quality remains a human check.
Build: https://github.com/AutonomousLife/PixelDeck/actions/runs/37483885124
Artifact 11421664765 ZIP SHA-256:
`11e6fd13e7dbb538f19149b1d8081576087ff0c418382df2605030cc86478bcf`.
Licenses and provenance are preserved in `docs/licenses/pixel-audio/`; complete
source inputs are included in the artifact, and pinned public URLs allow rebuilding.
