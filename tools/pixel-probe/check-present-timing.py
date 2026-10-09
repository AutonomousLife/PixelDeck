"""Apply WSI patches in CI order; exercise extracted timing code and call sites."""
import argparse
import difflib
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--mesa-root', type=Path, default=ROOT/'build/panvk/mesa-driver')
args = parser.parse_args()


def compiler():
    env = dict(os.environ)
    if os.name != 'nt':
        cc = shutil.which('c++')
        assert cc, 'A C++ compiler is required for the extracted-code harness'
        return [cc, '-std=c++17', '-Wall', '-Wextra', '-Werror'], env
    vswhere = Path(env.get('ProgramFiles(x86)', 'C:/Program Files (x86)'))/'Microsoft Visual Studio/Installer/vswhere.exe'
    install = subprocess.check_output([str(vswhere), '-latest', '-products', '*',
        '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
        '-property', 'installationPath'], text=True).strip()
    assert install, 'MSVC is required for the Windows harness'
    vcvars = Path(install)/'VC/Auxiliary/Build/vcvars64.bat'
    setup = subprocess.check_output(f'cmd.exe /d /s /c ""{vcvars}" >nul && set"', text=True)
    env = {k.upper(): v for k, v in env.items()}
    env.update((key.upper(), value) for key, value in (line.split('=', 1)
        for line in setup.splitlines() if '=' in line and not line.startswith('=')))
    cc = shutil.which('cl.exe', path=env['PATH'])
    assert cc, 'vcvars64 did not provide cl.exe'
    return [cc, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX'], env


HARNESS = r'''
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdarg>
#ifndef _WIN32
#include <unistd.h>
#endif
#define MAX2(a,b) ((a) > (b) ? (a) : (b))
typedef int VkResult;
static bool test_enabled;
static uint64_t fake_now = 1;
static unsigned clocks, calls, logs;
static int wanted;
static char output[2048];
static uint64_t os_time_get_nano() { clocks++; errno = EIO; return fake_now; }
#define DEBUG_GET_ONCE_BOOL_OPTION(suffix, name, fallback) \
   static bool debug_get_option_##suffix() { errno = EIO; return test_enabled; }
static int capture(FILE *file, const char *format, ...) {
   assert(file == stderr);
   va_list ap; va_start(ap, format);
   int n = vsnprintf(output, sizeof(output), format, ap);
   va_end(ap); logs++; errno = ERANGE; return n;
}
#define fprintf capture
@HELPER@
#undef fprintf

struct vk_queue { int id; } normal_queue{1}, blit_queue{2};
static vk_queue *queue = &normal_queue;
static int *dev;
static int vk_device_to_handle(int *value) { assert(value == dev); return 17; }
static int fake(unsigned stage) { calls++; fake_now += (stage + 1) * 1000; errno = EDOM; return wanted; }
static int fences[1];
static unsigned fence_count = 1;
static int submit_info;
static const unsigned i = 0, image_index = 0;
static int results[1], image;
static int region;
struct signal_info { unsigned fence_count; int *fences; uint64_t present_id; };
static signal_info image_signal_infos[1] = {{1, fences, 71}};
struct swapchain_type;
static int backend(swapchain_type *, unsigned, uint64_t, int);
static int wait_fences(int device, unsigned count, int *fence, bool all, uint64_t timeout) {
   assert(device == 17 && count == 1 && fence == fences && all && timeout == ~0ull);
   return fake(wanted == 999 ? PIXEL_PRESENT_THROTTLE : PIXEL_PRESENT_FENCE);
}
struct wsi_type { decltype(&wait_fences) WaitForFences; } wsi_object{wait_fences};
static wsi_type *wsi = &wsi_object;
struct swapchain_type {
   struct { vk_queue *queue; } blit;
   int *fences;
   decltype(&backend) queue_present;
} chain{{&blit_queue}, fences, backend};
static swapchain_type *swapchain = &chain;
static int backend(swapchain_type *chain_arg, unsigned index, uint64_t id, int r) {
   assert(chain_arg == swapchain && index == image_index && id == 71 && r == region);
   return fake(PIXEL_PRESENT_BACKEND);
}
static int wsi_invalidate_cpu_image(swapchain_type *chain_arg, int img) {
   assert(chain_arg == swapchain && img == image); return fake(PIXEL_PRESENT_INVALIDATE);
}
static int wsi_queue_submit2_unordered(wsi_type *w, vk_queue *q, int *info, unsigned count, int *f) {
   assert(w == wsi && info == &submit_info && count == 1 && f == fences);
   assert(q == queue || q == &blit_queue);
   return fake(q == queue ? PIXEL_PRESENT_SUBMIT : PIXEL_PRESENT_BLIT);
}
@SITES@
int main() {
   typedef int (*site_fn)();
   site_fn sites[] = {@FUNCTIONS@};
   for (bool flag : {false, true}) {
      test_enabled = flag;
      for (unsigned frame = 0; frame < 240; frame++) {
         wanted = frame % 5 == 0 ? -4 : (frame % 5 == 1 ? 1000001003 : 0);
         errno = EDOM;
         assert(pixel_present_enabled() == test_enabled && errno == EDOM);
         uint64_t start = pixel_present_begin(test_enabled);
         unsigned before = calls;
         for (site_fn site : sites) {
            assert(site() == wanted);
            assert(errno == EDOM);
         }
         pixel_present_end(PIXEL_PRESENT_TOTAL, start, wanted);
         assert(errno == EDOM && calls == before + 6);
      }
      if (!flag) {
         assert(clocks == 0 && logs == 0);
         for (const auto &stage : pixel_present_stats.stages) assert(stage.count == 0);
      }
   }
   assert(logs == 1 && strstr(output, "batch=1"));
   assert(strstr(output, "submit=240/480/2/48"));
   assert(strstr(output, "blit=240/720/3/48"));
   assert(strstr(output, "fence=240/960/4/48"));
   assert(strstr(output, "invalidate=240/1200/5/48"));
   assert(strstr(output, "backend=240/1440/6/48"));
   assert(strstr(output, "throttle=240/960/4/48"));
   assert(strstr(output, "total=240/5760/24/48"));
   for (const auto &stage : pixel_present_stats.stages) assert(stage.count == 0);
   assert(pixel_present_stats.batch == 1);
   puts("PASS: disabled clocks/logs; all calls, arguments, results and errno; batch timings/errors/reset");
}
'''


with tempfile.TemporaryDirectory(prefix='wsi-timing-', dir=ROOT/'build') as name:
    tmp = Path(name)
    relative = 'src/vulkan/wsi/wsi_common.c'
    target = tmp/relative
    target.parent.mkdir(parents=True)
    original = (args.mesa_root/relative).read_text()
    # Exact unpatched input makes already-patched or different revisions fail loudly.
    assert hashlib.sha256(original.encode()).hexdigest() == '2beb2cbfba303567f9c076a9251a4e9ca9bfafd6ffcf9c0a3d7930e431b43787', 'Unexpected pinned WSI source'
    target.write_text(original)
    directory = tmp.relative_to(ROOT).as_posix()
    workflow = (ROOT/'.github/workflows/pixel-panvk.yml').read_text()
    patches = re.findall(r'git -C mesa apply ../(tools/pixel-probe/\S+\.patch)', workflow)
    own_patch = ROOT/'tools/pixel-probe/panvk-present-timing.patch'
    for patch in patches:
        if Path(patch).name == own_patch.name:
            continue
        subprocess.run(['git', 'apply', '--unsafe-paths', f'--directory={directory}',
            f'--include={directory}/{relative}', str(ROOT/patch)], cwd=ROOT, check=True)
    before = target.read_text()
    patch_text = own_patch.read_text()
    assert not any(line.startswith('-') and not line.startswith('--- ') for line in patch_text.splitlines()), 'Timing patch must not remove original statements'
    assert re.findall(r'^\+\+\+ b/(.+)$', patch_text, re.M) == [relative]
    subprocess.run(['git', 'apply', '--unsafe-paths', f'--directory={directory}', str(own_patch)], cwd=ROOT, check=True)
    after = target.read_text()
    helper = re.search(r'/\* Pixel presentation diagnostics:.*?/\* End Pixel presentation diagnostics\. \*/', after, re.S).group()
    sites = re.findall(r'      +uint64_t pixel_(?:invalidate_)?start = pixel_present_begin\(pixel_timing\);\n.*?pixel_present_end\(PIXEL_PRESENT_\w+, pixel_(?:invalidate_)?start, (?:result|results\[i\])\);', after, re.S)
    assert len(sites) == 6
    stripped = after.replace('\n' + helper + '\n\n', '')
    stripped = stripped.replace('#include <errno.h>\n#include "c11/threads.h"\n', '')
    stripped = re.sub(r'^.*(?:const bool pixel_timing|const uint64_t pixel_total_start|uint64_t pixel_(?:invalidate_)?start|pixel_present_end\(PIXEL_PRESENT_).*\n', '', stripped, flags=re.M)
    assert stripped == before, ''.join(difflib.unified_diff(before.splitlines(True), stripped.splitlines(True)))
    functions = []
    for index, site in enumerate(sites):
        result = 'result' if 'VkResult result =' in site else 'results[i]'
        functions.append(f'int site_{index}() {{ const bool pixel_timing = test_enabled;\n{site}\nreturn {result};\n}}')
    harness = HARNESS.replace('@HELPER@', helper).replace('@SITES@', '\n'.join(functions)).replace('@FUNCTIONS@', ','.join(f'site_{i}' for i in range(6)))
    harness = '#include <initializer_list>\n' + harness
    cc, env = compiler()
    for negative in (False, True):
        source = tmp/('negative.cpp' if negative else 'positive.cpp')
        source.write_text(harness.replace('if (!enabled)\n      return 0;', '(void)enabled;') if negative else harness)
        exe = tmp/('negative.exe' if negative else 'positive.exe')
        flags = [f'/Fe:{exe}', f'/Fo:{tmp}/'] if os.name == 'nt' else ['-o', str(exe)]
        built = subprocess.run([*cc, str(source), *flags], cwd=tmp, env=env, capture_output=True, text=True)
        assert built.returncode == 0, built.stdout + built.stderr
        completed = subprocess.run([str(exe)], cwd=tmp, env=env, capture_output=True, text=True)
        assert (completed.returncode != 0) if negative else (completed.returncode == 0), completed.stdout + completed.stderr
        print('PASS: negative control rejects clocks while disabled' if negative else completed.stdout.strip())
    print('PASS: CI patch order, original WSI control flow unchanged, six actual call sites exercised')

