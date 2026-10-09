"""Compile the actual zero-copy DMA-BUF writer wait against deterministic poll failures."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "app/src/main/cpp/waylandcomp/src/ahb_swapchain.c").read_text(encoding="utf-8")
start = source.index("static int wait_dmabuf_writers(")
opening = source.index("{", start)
depth, end = 1, opening + 1
while depth:
    depth += (source[end] == "{") - (source[end] == "}")
    end += 1
function = source[start:end]
assert "if (wait_dmabuf_writers(dmabuf_fd) != 0) return -1;" in source
harness = r'''
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#undef assert
#define assert(condition) do { if (!(condition)) { std::fputs("check failed\n", stderr); std::exit(2); } } while (0)
enum { POLLIN=1, POLLERR=8, POLLHUP=16, POLLNVAL=32 };
struct pollfd { int fd; short events, revents; };
static int64_t now;
static int calls, closed, result, error;
static short events;
static bool interrupt;
static int64_t now_ns() { return now; }
static int poll(pollfd *p, unsigned count, int timeout) {
    assert(count == 1 && p->fd == 42 && p->events == POLLIN);
    assert(timeout > 0 && timeout <= 100);
    calls++; now += 25000000;
    p->revents = events;
    errno = interrupt ? EINTR : error;
    return interrupt ? -1 : result;
}

@FUNCTION@
static void check(int r, short e, int err, int wanted) {
    now=0; calls=closed=0; result=r; events=e; error=err; interrupt=false;
    assert(wait_dmabuf_writers(42) == wanted);
    assert(closed == 0 && calls == 1);
}
int main() {
    assert(wait_dmabuf_writers(-1) == -1 && calls == 0);
    check(1, POLLIN, 0, 0);
    check(0, 0, 0, -1);
    check(-1, 0, EBADF, -1);
    check(1, POLLERR, 0, -1);
    check(1, POLLIN|POLLERR, 0, -1);
    check(1, POLLHUP, 0, -1);
    check(1, POLLNVAL, 0, -1);
    now=0; calls=closed=0; interrupt=true;
    assert(wait_dmabuf_writers(42) == -1);
    assert(now == 100000000 && calls == 4 && closed == 0);
}
'''
ROOT.joinpath("build").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=ROOT/"build", prefix="sync-fd-check-") as directory:
    directory = Path(directory)
    unit, executable = directory/"check.cpp", directory/("check.exe" if os.name == "nt" else "check")
    unit.write_text(harness.replace("@FUNCTION@", function), encoding="utf-8")
    command = (["cl", "/nologo", "/std:c++20", "/EHsc", "/W4", "/WX", str(unit), f"/Fe:{executable}"]
               if os.name == "nt" else ["c++", "-std=c++20", "-Wall", "-Wextra", "-Werror", str(unit), "-o", str(executable)])
    subprocess.run(command, cwd=directory, check=True)
    subprocess.run([str(executable)], check=True)
    incorrect = function[:function.index("    return r > 0")] + "    return r == 0 ? -1 : 0;\n}"
    unit.write_text(harness.replace("@FUNCTION@", incorrect), encoding="utf-8")
    subprocess.run(command, cwd=directory, check=True)
    negative = subprocess.run([str(executable)], capture_output=True)
    assert negative.returncode == 2, "Old error policy unexpectedly passed"
print("PASS: signaled fence only; errors rejected, EINTR bounded, borrowed FD preserved")
