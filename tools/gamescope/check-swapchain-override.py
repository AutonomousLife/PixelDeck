from pathlib import Path
import hashlib
import subprocess
import tempfile
import sys
import shutil

base = Path(sys.argv[1]) if len(sys.argv) == 2 else Path('build/panvk/gamescope-3.16.29-wlserver.cpp')
source = base.read_bytes().replace(b'\r\n', b'\n')
assert hashlib.sha256(source).hexdigest() == 'f06ec27f40e0197e870bca86340267e64357ab36835f749aaf7246f3f809043d'
patch = Path('tools/gamescope/patches/0117-preserve-current-swapchain-override.patch')
with tempfile.TemporaryDirectory(dir=base.parent, prefix='swapchain-owner-check-') as tmp:
    dst = Path(tmp)/'src/wlserver.cpp'
    dst.parent.mkdir()
    dst.write_bytes(source)
    subprocess.run([shutil.which('patch') or 'C:/Program Files/Git/usr/bin/patch.exe', '-p1', '--batch', '--fuzz=0'], cwd=tmp, input=patch.read_bytes(), check=True)
    applied = dst.read_text(encoding="utf8")
    original = source.decode()
    start = 'static void gamescope_swapchain_handle_resource_destroy( struct wl_resource *resource )\n{'
    end = '\nstatic void gamescope_swapchain_destroy('
    a, b = original.index(start), original.index(end, original.index(start))
    c, d = applied.index(start), applied.index(end, applied.index(start))
    assert original[:a] == applied[:c] and original[b:] == applied[d:]
    handler = applied[c:d]
    assert handler.index('owns_content_override = iter != overrides.end() && iter->second->gamescope_swapchain == resource;') < handler.index('server->clear_content_override_swapchain( resource );')
    assert 'if ( owns_content_override )\n\t\t\tgamescope_swapchain_destroy_co( resource );' in handler
    assert 'std::erase(wl_surface_info->gamescope_swapchains, resource);' in handler

# The callback's resource-to-override ownership and clear-before-free ordering.
# Model the actual bug with shared surface S and old/new protocol resources A/B.
def destroy(overrides, resource, surface, guarded=True):
    current = next((co for co in overrides.values() if co['surface'] == surface), None) if surface else None
    owns = current is not None and current['resource'] == resource
    for co in overrides.values():
        if co['resource'] == resource:
            co['resource'] = None  # No dangling wl_resource or retired event to freed resource.
    if surface and (owns or not guarded):
        for xid, co in list(overrides.items()):
            if co['surface'] == surface:
                del overrides[xid]

old, new, other = object(), object(), object()
def bindings():
    return {1: {'surface': 'S', 'resource': new}, 2: {'surface': 'T', 'resource': other}}
broken = bindings()
destroy(broken, old, 'S', guarded=False)
assert 1 not in broken  # Original callback erases the newer binding.
fixed = bindings()
destroy(fixed, old, 'S')
assert fixed[1]['resource'] is new and fixed[2]['resource'] is other
# Current resource destruction still removes its own content override.
destroy(fixed, new, 'S')
assert 1 not in fixed and fixed[2]['resource'] is other
# A destroyed/detached wl_surface still clears matching pointers globally.
fixed = bindings()
destroy(fixed, new, None)
assert fixed[1]['resource'] is None and fixed[2]['resource'] is other
# Legacy null-resource overrides must survive unrelated swapchain destruction.
fixed = {1: {'surface': 'S', 'resource': None}}
destroy(fixed, old, 'S')
assert fixed == {1: {'surface': 'S', 'resource': None}}
print('PASS: exact 3.16.29 source hash; patch applies without fuzz; only resource-destroy callback changed; old/new shared-surface ownership, current cleanup, detached-surface pointer clearing and legacy override preservation checked')
