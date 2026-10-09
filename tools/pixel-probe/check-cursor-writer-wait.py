"""Compile the actual cursor producer wait and publication control flow against deterministic poll failures."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "app/src/main/cpp/waylandcomp/src/compositor.c").read_text(encoding="utf-8")
start = source.index("static int cursor_wait_writers(")
opening = source.index("{", start)
depth, end = 1, opening + 1
while depth:
    depth += (source[end] == "{") - (source[end] == "}")
    end += 1
function = source[start:end]
assert "if (cursor_wait_writers(db->fd[0]) != 0) return;" in source
start = source.index("static void cursor_publish_buffer(")
opening = source.index("{", start)
depth, end = 1, opening + 1
while depth:
    depth += (source[end] == "{") - (source[end] == "}")
    end += 1
publish = source[start:end]
assert "close(" not in publish and "wl_buffer_send_release" not in publish
assert source.count("cursor_publish_buffer(s, buffer);\n                wl_buffer_send_release(buffer);") == 1
assert source.count("cursor_publish_buffer(s, buffer);\n        wl_buffer_send_release(buffer);") == 1
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
struct surface {};
struct wl_resource {};
struct wl_shm_buffer {};
struct vkp_image {};
struct dmabuf_buffer { int n_planes=1, width=1, height=1; vkp_image *img; bool import_failed=false; int fd[1]={42}; unsigned format=0; uint64_t modifier=0; unsigned stride[1]={4}, offset[1]={0}; };
static vkp_image image;
static dmabuf_buffer fake_buffer;
static surface *g_cursor_shown;
static int g_cursor_hx, g_cursor_hy, readbacks, publishes;
static uint32_t g_cursor_rb[1];
enum { CURSOR_MAX_PX=1 };
static dmabuf_buffer *get_dmabuf(wl_resource *) { return &fake_buffer; }
static wl_shm_buffer *wl_shm_buffer_get(wl_resource *) { return nullptr; }
static void cursor_publish_shm(wl_shm_buffer *,int,int) {}
static vkp_image *vkp_image_from_dmabuf(int,unsigned,uint64_t,int,int,unsigned,unsigned) { return &image; }
static int vkp_image_readback(vkp_image *,uint32_t *,int) { readbacks++; return 0; }
static void cursor_publish_pixels(const uint8_t *,int,int,size_t,int,int) { publishes++; }
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
@PUBLISH@
static void check(int r, short e, int err, int wanted) {
    now=0; calls=closed=0; result=r; events=e; error=err; interrupt=false;
    assert(cursor_wait_writers(42) == wanted);
    assert(closed == 0 && calls == 1);
    now=0; calls=0; readbacks=publishes=0; g_cursor_shown=nullptr; fake_buffer.img=&image;
    surface s; wl_resource resource;
    cursor_publish_buffer(&s,&resource);
    assert(readbacks == (wanted==0) && publishes == (wanted==0));
    assert(g_cursor_shown == (wanted==0 ? &s : nullptr));
}
int main() {
    assert(cursor_wait_writers(-1) == -1 && calls == 0);
    check(1, POLLIN, 0, 0);
    check(0, 0, 0, -1);
    check(-1, 0, EBADF, -1);
    check(1, POLLERR, 0, -1);
    check(1, POLLIN|POLLERR, 0, -1);
    check(1, POLLHUP, 0, -1);
    check(1, POLLNVAL, 0, -1);
    now=0; calls=closed=0; interrupt=true;
    assert(cursor_wait_writers(42) == -1);
    assert(now == 100000000 && calls == 4 && closed == 0);
    now=0; calls=0; readbacks=publishes=0; fake_buffer.img=&image;
    surface s; wl_resource resource;
    cursor_publish_buffer(&s,&resource);
    assert(now==100000000 && calls==4 && readbacks==0 && publishes==0);
    fake_buffer.fd[0]=-1; calls=0; interrupt=false;
    cursor_publish_buffer(&s,&resource);
    assert(calls==0 && readbacks==0 && publishes==0);
}
'''
ROOT.joinpath("build").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=ROOT/"build", prefix="sync-fd-check-") as directory:
    directory = Path(directory)
    unit, executable = directory/"check.cpp", directory/("check.exe" if os.name == "nt" else "check")
    unit.write_text(harness.replace("@FUNCTION@", function).replace("@PUBLISH@", publish), encoding="utf-8")
    command = (["cl", "/nologo", "/std:c++20", "/EHsc", "/W4", "/WX", str(unit), f"/Fe:{executable}"]
               if os.name == "nt" else ["c++", "-std=c++20", "-Wall", "-Wextra", "-Werror", str(unit), "-o", str(executable)])
    subprocess.run(command, cwd=directory, check=True)
    subprocess.run([str(executable)], check=True)
    incorrect = function[:function.index("    return r > 0")] + "    return r == 0 ? -1 : 0;\n}"
    unit.write_text(harness.replace("@FUNCTION@", incorrect).replace("@PUBLISH@", publish), encoding="utf-8")
    subprocess.run(command, cwd=directory, check=True)
    negative = subprocess.run([str(executable)], capture_output=True)
    assert negative.returncode == 2, "Old error policy unexpectedly passed"
print("PASS: signaled fence only; errors rejected, EINTR bounded, borrowed FD preserved")
