"""Compile the patched KCPU polling function and reject errored sync files."""
import argparse
import ast
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def compiler():
    # Reuse the established cross-platform compiler discovery, without running
    # the timing checker or importing its command-line parser.
    source = ROOT / 'tools/pixel-probe/check-present-timing.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    definition = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == 'compiler')
    scope = dict(os=os, shutil=shutil, subprocess=subprocess, Path=Path)
    exec(compile(ast.Module(body=[definition], type_ignores=[]), str(source), 'exec'), scope)
    return scope['compiler']()


HARNESS = r'''
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <ctime>
#include <cstdio>
#include <cstdlib>
#undef assert
#define assert(condition) do { if (!(condition)) { std::fprintf(stderr, "check failed at line %d: %s\n", __LINE__, #condition); std::_Exit(2); } } while (0)
struct pollfd { int fd; short events; short revents; };
enum { POLLIN=1, POLLERR=8, POLLHUP=16, POLLNVAL=32, SYNC_IOC_FILE_INFO=77 };
struct sync_file_info {
   char name[32]; int32_t status; uint32_t flags, num_fences, pad;
   uint64_t sync_fence_info;
};
static int poll_result, poll_errno, info_result, info_errno, info_status;
static short events;
static unsigned polls, queries, poll_interrupts, info_interrupts;
static int ppoll(pollfd *pfd, unsigned count, timespec *ts, void *mask) {
   assert(pfd->fd == 19 && pfd->events == POLLIN && count == 1 && !mask);
   assert(ts->tv_sec == 0 && ts->tv_nsec == 20000000);
   polls++;
   if (poll_interrupts) { poll_interrupts--; errno=EINTR; return -1; }
   pfd->revents=events; errno=poll_errno; return poll_result;
}
int ioctl(int fd, int request, sync_file_info *info) {
   assert(fd == 19 && request == SYNC_IOC_FILE_INFO);
   assert(info->flags == 0 && info->num_fences == 0 && info->pad == 0);
   assert(info->sync_fence_info == 0);
   queries++;
   if (info_interrupts) { info_interrupts--; errno=EINTR; return -1; }
   info->status=info_status; errno=info_errno; return info_result;
}
@FUNCTION@
static void reset() {
   polls=queries=poll_interrupts=info_interrupts=0;
   poll_result=1; poll_errno=0; events=POLLIN;
   info_result=info_errno=0; info_status=1;
}
int main() {
   reset(); assert(kbase_kcpu_poll_fence(19,20000000) == 1 && queries == 1);
   reset(); info_status=-110; assert(kbase_kcpu_poll_fence(19,20000000) == -1);
   reset(); info_status=INT32_MIN; assert(kbase_kcpu_poll_fence(19,20000000) == -1);
   reset(); info_status=0; assert(kbase_kcpu_poll_fence(19,20000000) == 0);
   reset(); info_result=-1; info_errno=ENOTTY;
   assert(kbase_kcpu_poll_fence(19,20000000) == -1 && errno == ENOTTY);
   reset(); info_interrupts=1; assert(kbase_kcpu_poll_fence(19,20000000) == 1 && queries == 2);
   reset(); poll_interrupts=1; assert(kbase_kcpu_poll_fence(19,20000000) == 1 && polls == 2);
   reset(); poll_result=0; assert(kbase_kcpu_poll_fence(19,20000000) == 0 && queries == 0);
   reset(); poll_result=-1; poll_errno=EBADF;
   assert(kbase_kcpu_poll_fence(19,20000000) == -1 && queries == 0);
   for (short e : {short(POLLERR), short(POLLHUP), short(POLLNVAL), short(POLLIN|POLLHUP), short(POLLIN|POLLNVAL)}) {
      reset(); events=e; assert(kbase_kcpu_poll_fence(19,20000000) == -1 && queries == 0);
   }
   reset(); events=POLLIN|POLLERR; info_status=-110;
   assert(kbase_kcpu_poll_fence(19,20000000) == -1 && queries == 1);
   return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mesa-root', type=Path, default=ROOT/'build/panvk/mesa-driver')
    args = parser.parse_args()
    relative = Path('src/panfrost/lib/kmod/kbase_kmod.c')
    original = (args.mesa_root/relative).read_text(encoding='utf-8')
    caller = (args.mesa_root/'src/panfrost/vulkan/csf/panvk_vX_gpu_queue.c').read_text(encoding='utf-8')
    # Polling is a wakeup optimization, never the acceptance predicate.
    assert re.search(r'if \(cqs_ret < 0\)\s+kbase_kmod_csf_wait_event', caller)
    assert 'if (cell->seqno >= target_seqno ||' in caller
    assert re.search(r'if \(ret == 1\).*?close\(kbase_dev->kcpu.fence_fd\)', original, re.S)
    assert re.search(r'else if \(ret < 0\).*?goto disable;', original, re.S)
    assert 'if (!kbase_dev->kcpu.valid)\n      goto out;' in original
    assert 'if (is_csf && kcpu_sync && !strcmp(kcpu_sync, "1"))' in original
    cc, env = compiler()
    cc = [flag.replace('c++17', 'c++20') for flag in cc]
    if os.name != 'nt':
        cc.append('-Wno-missing-field-initializers')
    ROOT.joinpath('build').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='kcpu-status-', dir=ROOT/'build') as temp:
        temp = Path(temp)
        dest = temp/relative
        dest.parent.mkdir(parents=True)
        dest.write_text(original, encoding='utf-8')
        subprocess.run(['git', 'apply', '--unsafe-paths', '--directory='+str(temp),
                        str(ROOT/'tools/pixel-probe/panvk-kcpu-fence-status.patch')],
                       cwd=ROOT, check=True, capture_output=True)
        patched = dest.read_text(encoding='utf-8')
        pattern = r'static int\nkbase_kcpu_poll_fence\(.*?\n}\n'
        function = re.search(pattern, patched, re.S).group()
        old_function = re.search(pattern, original, re.S).group()
        assert hashlib.sha256(old_function.encode('utf-8')).hexdigest() == 'a13219276377825b40a50f8e40117d57250885e6e89231e4722b69d157ca8744', 'Pinned polling source changed; re-audit the caller and negative control'
        for label, body, expected_success in [('patched', function, True), ('old-control', old_function, False)]:
            source = temp/(label+'.cpp')
            source.write_text(HARNESS.replace('@FUNCTION@', body).replace('#include <ctime>', '#include <ctime>\n#include <initializer_list>'), encoding='utf-8')
            exe = temp/(label+('.exe' if os.name == 'nt' else ''))
            flags = ['/Fe:'+str(exe)] if os.name == 'nt' else ['-o', str(exe)]
            result = subprocess.run([*cc, str(source), *flags], cwd=temp, env=env, capture_output=True, text=True)
            assert result.returncode == 0, result.stdout+result.stderr
            result = subprocess.run([str(exe)], cwd=temp, env=env, capture_output=True)
            assert (result.returncode == 0) == expected_success, label
    print('KCPU status cases passed; old readiness-only control failed as expected.')


if __name__ == '__main__':
    main()
