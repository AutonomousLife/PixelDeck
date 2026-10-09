"""Check the pinned-source swapchain patch and compile its private/public boundary."""
from pathlib import Path
import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile

args = argparse.ArgumentParser()
args.add_argument('--source-dir', type=Path, default=Path('build/panvk'))
args.add_argument('--compiler')
opts = args.parse_args()
root = Path(__file__).resolve().parents[2]
patch = root/'tools/gamescope/patches/0117-preserve-current-swapchain-override.patch'
expected = {
    'cpp': 'f06ec27f40e0197e870bca86340267e64357ab36835f749aaf7246f3f809043d',
    'hpp': 'f76acd3b3c25700e235864d56cca5373ef85198d9264624286ef18087416223f',
}
patch_tool = shutil.which('patch') or 'C:/Program Files/Git/usr/bin/patch.exe'
compiler = opts.compiler or shutil.which('clang++') or shutil.which('g++')
if not compiler:
    sdk = Path(os.environ.get('LOCALAPPDATA', ''))/'Android/Sdk/ndk'
    compilers = sorted(sdk.glob('*/toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe'))
    compiler = str(compilers[-1]) if compilers else None
if not compiler:
    raise SystemExit('A C++ compiler is required; pass --compiler PATH')

def function(text, name):
    start = text.index(name)
    opening = text.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]

with tempfile.TemporaryDirectory(prefix='gamescope-owner-') as tmp:
    tmp = Path(tmp)
    for ext, digest in expected.items():
        source = opts.source_dir/f'gamescope-3.16.29-wlserver.{ext}'
        if not source.exists():
            source = opts.source_dir/f'src/wlserver.{ext}'
        data = source.read_bytes().replace(b'\r\n', b'\n')
        assert hashlib.sha256(data).hexdigest() == digest, f'Wrong pinned {ext} source'
        dest = tmp/f'src/wlserver.{ext}'
        dest.parent.mkdir(exist_ok=True)
        dest.write_bytes(data)
    subprocess.run([patch_tool, '-p1', '--batch', '--fuzz=0'], cwd=tmp, input=patch.read_bytes(), check=True)
    source = (tmp/'src/wlserver.cpp').read_text(encoding='utf8')
    header = (tmp/'src/wlserver.hpp').read_text(encoding='utf8')
    clear = function(source, 'bool gamescope_xwayland_server_t::clear_content_override_swapchain(')
    handler = function(source, 'static void gamescope_swapchain_handle_resource_destroy(')
    declaration = next(line.strip() for line in header.splitlines() if 'bool clear_content_override_swapchain(' in line)
    assert header.index(declaration) < header.index('private:') < header.index('content_overrides;')
    assert source.count('server->clear_content_override_swapchain( resource )') == 1
    assert 'server->clear_content_override_swapchain( resource ) || owns_content_override' in handler
    assert 'if ( owns_content_override )\n\t\t\tgamescope_swapchain_destroy_co( resource );' in handler
    assert clear.index('owns_content_override = true;') < clear.index('iter.second->gamescope_swapchain = nullptr;')
    # Compile the actual changed function bodies using the pinned header's
    # public declaration and private member boundary, with platform types stubbed.
    unit = '''#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <unordered_map>
#include <vector>
struct wl_resource {};
struct wlserver_content_override { wl_resource *gamescope_swapchain; };
class gamescope_xwayland_server_t {
public:
''' + declaration + '''
private:
std::unordered_map<uint32_t, wlserver_content_override *> content_overrides;
};
struct wlserver_wl_surface_info { std::vector<wl_resource *> gamescope_swapchains; };
void *wl_resource_get_user_data(wl_resource *);
gamescope_xwayland_server_t *wlserver_get_xwayland_server(size_t);
static void gamescope_swapchain_destroy_co(wl_resource *);
''' + clear + '\n' + handler + '\n'
    path = tmp/'check.cpp'
    path.write_text(unit, encoding='utf8')
    command = [compiler, '-std=c++20', '-fsyntax-only']
    if 'ndk' in compiler.lower():
        command += ['--target=aarch64-linux-android26']
    subprocess.run(command + [str(path)], check=True)
    # Prove this compiler check rejects the access that broke the first build.
    path.write_text(unit + '\nvoid invalid_access(gamescope_xwayland_server_t &s) { (void)s.content_overrides; }\n', encoding='utf8')
    failure = subprocess.run(command + [str(path)], capture_output=True, text=True)
    assert failure.returncode and 'private' in failure.stderr

# Ownership must be captured before pointer clearing; clearing every server
# must run even after a previous server returned true.
def clear_owner(bindings, resource):
    owned = False
    for co in bindings.values():
        if co['resource'] is resource:
            owned = True
            co['resource'] = None
    return owned

def destroy(servers, resource, surface):
    owned = False
    for bindings in servers:
        owned = clear_owner(bindings, resource) or owned
    if owned and surface:
        for bindings in servers:
            for xid, co in list(bindings.items()):
                if co['surface'] == surface:
                    del bindings[xid]

old, new, other = object(), object(), object()
fixed = [{1: {'surface': 'S', 'resource': new}, 2: {'surface': 'T', 'resource': other}}]
destroy(fixed, old, 'S')
assert fixed[0][1]['resource'] is new and fixed[0][2]['resource'] is other
destroy(fixed, new, 'S')
assert 1 not in fixed[0] and fixed[0][2]['resource'] is other
fixed = [{1: {'surface': 'S', 'resource': new}}, {2: {'surface': 'S', 'resource': new}}]
destroy(fixed, new, None)
assert all(co['resource'] is None for server in fixed for co in server.values())
fixed = [{1: {'surface': 'S', 'resource': None}}]
destroy(fixed, old, 'S')
assert fixed[0][1]['resource'] is None
print('PASS: exact pinned source/header; no-fuzz patch; changed C++ bodies compile; private access rejected; shared-surface ownership, cleanup and all-server pointer clearing checked')
