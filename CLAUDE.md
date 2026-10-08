# Agent instructions

## Shared PC control (SilverPC)
Chas uses this PC too, and several AI agents share it. Human first: Chas always wins.

- Before any action that uses the mouse, keyboard, screen, window focus, or launches a game/GUI app on SilverPC, run `pccontrol acquire -Agent <you> -Project <project> -Reason "<why>" -Wait`. Use a unique name such as `claude-SonsCraft` or `codex-PixelDeck`.
- Release with `pccontrol release -Agent <you>` as soon as done.
- Between GUI steps (before each click/keystroke batch or game launch), run `pccontrol check -Agent <you>`. If it exits non-zero (5 = Chas is using the PC or paused agents), stop GUI actions immediately, release, and go back to code-only work. Do not fight Chas for the mouse.
- Code edits, builds, and headless tests do not need the lock. Prefer headless tests.
- Heavy GPU work (launching a game, GPU benchmarks) uses `-Scope gpu`, or `-Scope gui,gpu` if it also needs the screen.
- You only get a turn after Chas has not touched the mouse/keyboard for 3 minutes, and never while he has paused agents. Exit codes from acquire: 2 = another agent has it, 3 = Chas is active, 4 = paused. `-Wait` waits for you; if your shell times out, just run it again.
- Holding longer than 30 min? Run acquire again to renew. See who has it: `pccontrol status`.
- If `pccontrol` is not found, use the full path: `C:\Users\Silver\agent-tools\control-queue\pccontrol.cmd` (cmd/PowerShell) or `/c/Users/Silver/agent-tools/control-queue/pccontrol` (Git Bash). Never type bare `control` - that opens Windows Control Panel.
