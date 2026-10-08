# Execution plan and status (2026-10-08)

Source plan: `PLAN-2026-10-08.md` (the handoff). This file records what was done, how each
item was checked, and what is still blocked. Status words mean:

- **Done, tested**: a headless test or a read-through of the code confirms it.
- **Done, unverified**: the change is in, but no build or device here confirmed it.
- **Blocked (device)**: needs the Pixel 7 Pro connected, a human, or Chas's Steam account.
- **Blocked (owner)**: needs a decision or a secret only the owner has.
- **Deferred**: large, risky without a device, or needs its own session.

## Milestones

| Milestone | Status | Notes |
|---|---|---|
| M0 Clean branch | Done, tested | Bring-up section committed (`9f32b57`), `.serena/` ignored, branch pushed. |
| M1 Staging correctness | Done, unverified | Gradle now stages desktop items; `pixel-build.py` refreshes on digest change; 4 tests pass. The APK-diff proof needs an Android SDK and Gradle deps, neither available here. |
| M2 Swap-blocking attribution | Blocked (device) | Needs the phone for traces. See the four steps in the bring-up doc. |
| M3 First library game | Blocked (device) | Needs the phone and Chas's Steam account. |
| M4 Release trust | Partly done | Debug surfaces moved to a debug overlay and tested. Real release key and updater change still need the owner. |
| M5 Stable 60 | Deferred | Depends on M2 results. |

## Backlog

| # | Task | Status | How it was checked |
|---|---|---|---|
| 1 | Commit bring-up section, ignore `.serena/` | Done, tested | Commit `9f32b57`. |
| 2 | Push the branch | Done, tested | Pushed `a11f620..9f32b57`; in sync with origin. |
| 3 | Extend staged assets (`app/build.gradle`) | Done, unverified | Copy rules mirror the CI install paths in `build.yml`. Gradle could not run offline here. |
| 4 | Digest stamp and stale refresh (`pixel-build.py`) | Done, tested | `test_pixel_build.py`: changed digest replaces stale file; unchanged digest keeps a local edit. |
| 5 | Swap-child trace instrumentation | Deferred | Needs Gamescope patch changes, a native CI rebuild, and a device to validate. |
| 6 | Run the 4-step attribution on the phone | Blocked (device) | See M2. |
| 7 | Steam library game launch test | Blocked (device) | See M3. |
| 8 | Physical input and audible audio check | Blocked (device) | Needs a human with the phone. |
| 9 | Move debug surfaces into a debug overlay | Done, tested | Components moved to `app/src/debug/AndroidManifest.xml`. `test_release_manifest.py` fails on the old manifest and passes now. |
| 10 | Real release key and updater check | Blocked (owner) | Release builds are signed with the public AOSP testkey, and `RELEASE_SIGNER` is that key's hash, so the updater accepts testkey APKs. Rejecting them now would stop updates for current builds. Needs the owner's decision and the real key in CI secrets. |
| 11 | Confirm the HUD fix | Done, tested | Read-through: desktop frames go to `onDisplayFrame`, which never updates `lastFrameNanos`. Not checked on a device. |
| 12 | Finish the 10-06 review | Done, tested | `GpuInfo.kt` comment mismatch on `ADRENO_UNKNOWN` (recorded, not changed); unused imports in `FrontEndSetup.kt` (recorded, not changed); `DriverPairsTest.kt` not run. |
| 13 | Steam GL plan (4.3 vs 3.3) | Deferred | Needs a PanVK build and device tests. |
| 14 | DXVK `geometryShader` investigation | Deferred | Mesa patch work. |
| 15 | Reconcile README build instructions | Done, tested | README now says the Linux build needs JDK 17 and that JDK 21 also builds the project. |
| 16 | Decide on the phantom-process setting | Blocked (owner) | The device-wide `settings_enable_monitor_phantom_procs=false` is still on the test phone. Restoring it is `adb shell settings delete global settings_enable_monitor_phantom_procs`, which needs the phone and the owner's decision. |
| 17 | Split the large files | Deferred | Too risky without device tests for `compositor.c`. |
| 18 | Keep local copies of expiring CI artifacts | Done, tested | `build/pixel-probe/upstream-ci.zip` and the three pinned component archives are present locally. |

## Open decisions for the owner

1. Whether to reject testkey APKs in the updater now (breaks current self-updates) or wait for the real release key (item 10).
2. Whether to restore the phantom-process setting on the test phone (item 16).
3. Whether a phone lock scope is wanted for ADB work.
4. Whether to resolve the `ADRENO_UNKNOWN` comment mismatch and the unused imports (item 12).

## Verification log

- `python -m unittest tools/tests/test_pixel_build.py tools/tests/test_release_manifest.py`: 7 tests pass.
- Full Python suite: 153 tests run; 48 failures or errors, identical to a clean `HEAD` worktree. The failures are Linux-only or environment-specific (for example `fcntl` on Windows).
- The old manifest fails `test_release_manifest.py`'s agent check, so the test does detect the problem it targets.

## Build status (2026-10-08, later session)

- **SDK:** installed under the AgentBox profile by `tools/pixel-probe/bootstrap_sdk.py` (NDK 27.3.13750724, CMake 3.22.1) and a checksum-verified install of platform 34 and build-tools 35.0.0. The owner's SDK folder is not readable from this account.
- **Staging:** `tools/pixel-build.py` completes its staging step on this PC.
- **Gradle `:app:assembleDebug`: blocked.** Every attempt fails in `:app:compileDebugJavaWithJavac` with `java.nio.file.AccessDeniedException` on `app/build/intermediates/compile_and_runtime_not_namespaced_r_class_jar/debug/processDebugResources/R.jar`. The stack trace shows it is raised when `jdk.zipfs` closes that jar. Attempts that did not clear it: a normal rerun, stopping the Gradle daemons this account had started, `--no-daemon` with `-Dorg.gradle.vfs.watch=false`, `:app:clean`, and a second JDK 21 build (Eclipse Adoptium). The file opens for reading and for exclusive write from PowerShell, so the lock is not a simple open handle.
- **Consequence:** the APK byte-comparison proof for item 3 is not done yet. The Oct 7 APK predates `HostProcess` and `SessionPhase`, so it cannot be used to check the current source.
- **Next actions:** try JDK 17, check whether Windows Defender or Controlled Folder Access is locking the file during the zip close, and find out whether the lock occurs on the owner's account. Do not change security settings to get past it.
