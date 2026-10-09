# gamescope patches carried by the app

Built by `.github/workflows/build-gamescope.yml` on top of the exact gamescope the Linux runtime
ships (3.16.29, Arch Linux ARM's package, same build options), and staged from the apk over
`/usr/local/bin/gamescope` at each session start - the hosted runtime image is never touched.
The binary's shared-library needs are checked against `runtime-sonames.txt`, the runtime's own
library list, before anything is published.

- `0002-steamcompmgr-fallback-appid-focus.patch` - Armada (armada-os/armada), verbatim.
- `0009-fix-arm64-steam-night-mode.patch` - Armada, verbatim: the ARM64 client packs the
  night-mode property differently; the slider did nothing.
- `0019-steamcompmgr-arm64-virtual-white.patch` - Armada, verbatim: the colour-temperature
  slider's (x, y) arrives as one 64-bit element from the ARM64 client; y is recovered from x.
- `0020-color-p3-red-is-wide-gamut.patch` - Armada, verbatim.
- `0100-realtime-queue-and-gamepad-cursor.patch` - this app, two of Armada's ported by hand onto
  3.16.29: realtime-priority Vulkan queues on request (`GAMESCOPE_FORCE_VULKAN_REALTIME=1`)
  without CAP_SYS_NICE, which proot can never have (a no-op on KGSL Turnip, which has a single
  submit-queue priority); and the gamepad-driven cursor sprite following the X pointer that XTest
  moves (it sat frozen). The X pointer is asked for only while a cursor image is drawn - every
  vblank while shown, every 50 ms while hidden for inactivity - since each ask is a blocking round
  trip to Xwayland on the paint thread; with no image, wlserver's position is used as upstream does.
- `0110-wayland-backend-touch.patch` - this app: the nested Wayland backend bound only the host's
  pointer and keyboard, so a finger on the phone's screen never reached Steam. It now binds
  `wl_touch` too and hands each finger to wlserver's touch path (`wlserver_touchdown` / `motion` /
  `up`) - the one a Steam Deck's touchscreen drives - so what a touch does follows the client's
  touch mode (Steam's Big Picture sets Passthrough: a real touch, rows scroll under a finger).
  Finger ids are offset by one, since the nested pointer already moves wlserver's touch 0.
- `0111-wayland-pointer-warps-in-passthrough.patch` - this app: the nested pointer's motion goes to
  wlserver as touch 0, and in Passthrough (Big Picture's touch mode) a motion for a touch that is not
  down moves nothing - so in the app's touchpad mode the Steam client saw no hover and a click landed
  wherever the pointer had last been. The motion now always warps the real pointer as well
  (`bAlwaysWarpCursor`), which the other touch modes did already.
- `0112-restore-iconified-game-on-resume.patch` - this app: the Steam menu is an overlay that
  takes input without changing the focus window, and a fullscreen wine game minimizes itself when
  it loses input. gamescope only takes a window out of iconic when the focus window changes, and
  wine will not activate a window it believes iconic, so after Resume the game stayed minimized: a
  black screen with its small caption in the top-left corner (Titanfall 2, GE-Proton 11). The
  iconify request is remembered and the window goes back to NormalState before input returns to it,
  then focus is handed over again. `GAMESCOPE_RESTORE_FOCUS_WINDOW` on the root window asks for the
  same restore from outside (the session script's resume watcher).

- `0113-steam-overlay-keeps-game-keyboard-focus.patch` - this app: the Steam client opens the Quick
  Access Menu and Steam menu over a game with `STEAM_INPUT_FOCUS` 1, which moves X keyboard focus to
  its overlay; wine then deactivates the game and a fullscreen game minimizes itself, freezing
  behind the menu instead of running on as on a Steam Deck. Steam's own overlay taking input now
  keeps keyboard focus on the game, as mode 2 does; its input comes from the controller through
  Steam Input, not the X keyboard. The pointer warps gamescope makes as input moves to Steam and
  back are skipped around it, since the game - still taking input - saw them as a mouse jump.

Sixteen more of Armada's patches are DRM/lease/HDR-on-KMS work for a native display, which this
app's Wayland-hosted gamescope never reaches, or need a newer gamescope than the runtime has.

- `0117-preserve-current-swapchain-override.patch` - preserve the current window binding when
  an older protocol swapchain sharing its Wayland surface is destroyed. Snapshot ownership
  before clearing resource pointers; current-owner destruction still removes its own binding.
  Run `python tools/gamescope/check-swapchain-override.py --source-dir PATH_TO_3.16.29_CHECKOUT`
  to check exact-source applicability and the old/new swapchain lifetime regression.

- `0119-retire-destroyed-surface-commits.patch` - queued and held commits carry a surface
  generation, checked with the Wayland lock before dereferencing it. Surface destruction
  discards outstanding presentation feedback, including feedback already moved into a
  commit; dead queued buffers still release their lock once. This fixes a source lifetime
  bug; it has not been established as the cause of the observed heap-corruption exit.
  Run `python tools/gamescope/check-surface-lifetime.py --source-dir PATH_TO_3.16.29_CHECKOUT`
  for exact-source patch checks and the actual-function AddressSanitizer regression.

- `0120-keep-x11-surface-associations-consistent.patch` - preserve the Wayland
  destruction owner while a surface remains an X11 main surface; clear retired
  override forward pointers and detach previous owners during reassociation.
  Session 19 ASan captured a freed `wlr_surface` read from
  `handle_presented_for_window` / `get_wl_surface_info`. The actual association
  routines reproduce the lost-owner condition and pass after this patch;
  the original routines fail. Phone stability after this change is unverified.
  Run `python tools/pixel-probe/check-x11-surface-associations.py --source
  PATCHED_WLSERVER_CPP --old-source PRE_PATCH_WLSERVER_CPP` to test retirement,
  shared main/override ownership, replacement and transfer.
