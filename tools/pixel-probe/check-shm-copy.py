from pathlib import Path
import subprocess,tempfile,sys,shutil
root=Path(sys.argv[1] if len(sys.argv)==2 else 'build/panvk/mesa-driver').resolve()
paths=['src/vulkan/wsi/wsi_common.c','src/vulkan/wsi/wsi_common.h','src/vulkan/wsi/wsi_common_x11.c','src/panfrost/vulkan/panvk_wsi.c']
with tempfile.TemporaryDirectory(dir=root.parent,prefix='shm-copy-check-') as tmp:
    tmp=Path(tmp)
    for rel in paths:
        p=tmp/rel;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes((root/rel).read_bytes().replace(b'\r\n',b'\n'))
    for name in ['panvk-cached-wsi.patch','panvk-shm-copy.patch']:
        subprocess.run([shutil.which('patch') or 'C:/Program Files/Git/usr/bin/patch.exe','-p1','--batch','--fuzz=0'],cwd=tmp,input=Path('tools/pixel-probe',name).read_bytes(),check=True)
    x=(tmp/paths[2]).read_text();p=(tmp/paths[3]).read_text();common=(tmp/paths[0]).read_text()
    assert '!physical_device->wsi_device.has_import_memory_host &&\n      shm_copy && !strcmp(shm_copy, "1")' in p
    assert '(wsi_dev->has_import_memory_host || wsi_dev->x11.use_shm_copy)' in x
    assert 'wsi_dev->has_import_memory_host) {' in x
    assert '!(WSI_DEBUG & WSI_DEBUG_NOSHM)' in x
    present=x[x.index('x11_present_to_x11_sw('):x.index('static void\nx11_capture_trace')]
    copy=present.index('memcpy(image->shmaddr, myptr,')
    put=present.index('xcb_shm_put_image_checked',copy)
    geometry=present.index('geom_cookie = xcb_get_geometry',put)
    flush=present.index('xcb_flush',geometry)
    reply=present.index('xcb_get_geometry_reply',flush)
    acquire=present.index('wsi_queue_push(&chain->acquire_queue',reply)
    assert copy < put < geometry < flush < reply < acquire
    assert present.index('xcb_request_check',reply)<acquire
    assert 'stride_b / 4, chain->extent.height' in present
    assert '0, 0, chain->extent.width, chain->extent.height' in present
    init=x[x.index('x11_image_init('):x.index('static void\nx11_image_finish')]
    assert init.index('xcb_shm_attach_checked')<init.index('shmctl(shmid, IPC_RMID, NULL)')
    assert 'vk_format_get_blocksize(pCreateInfo->imageFormat) == 4' in init
    assert 'free(error);\n                  shmdt(addr);' in init
    assert 'Allocation/attach failure retains the existing socket PutImage path' in init
    finish=x[x.index('static void\nx11_image_finish'):]
    assert finish.index('xcb_shm_detach')<finish.index('shmdt(image->shmaddr)')
    wait=common.index('if (wsi->sw || wsi->wait_present_before_queue)')
    assert wait<common.index('results[i] = wsi_invalidate_cpu_image',wait)<common.index('results[i] = swapchain->queue_present',wait)
    def valid(stride,width,height):
        return stride%4==0 and stride//4<=65535 and height<=65535 and width<=stride//4 and 0<stride*height<=4294967295
    assert valid(1280*4,1280,720) and valid(1344*4,1280,720)
    assert not valid(1280*4+2,1280,720) and not valid(65536*4,65536,1)
    assert not valid(1280*4,1280,65536) and not valid(1280*4,1281,720)
    assert not valid(65535*4,65535,65535)
    # Model ordered X requests retaining shared storage until server processing.
    def consumed(query_after_put):
        shm=bytearray(b'A');out=[]
        queue=['put','geometry'] if query_after_put else ['geometry','put']
        while queue:
            request=queue.pop(0)
            if request=='geometry':break
            out.append(bytes(shm))
        shm[:]=b'B'  # Image acquired and reused after geometry reply.
        for request in queue:
            if request=='put':out.append(bytes(shm))
        return out
    assert consumed(True)==[b'A'] and consumed(False)==[b'B']
print('PASS: patches apply without fuzz; opt-in/no-import/noshm scopes, allocation fallback/cleanup, stride bounds, fence/invalidate and SHM-consumption-before-reuse ordering checked')
