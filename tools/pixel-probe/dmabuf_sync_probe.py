#!/usr/bin/env python3
"""Run inside the phone guest: probe sync-file ioctls on a private 4 KiB DMA-BUF.

This checks kernel plumbing only. No GPU work is submitted, so the exported
fence must already be signaled; it does not prove producer synchronization.
"""
import fcntl
import json
import os
import select
import struct

DMA_HEAP_IOCTL_ALLOC = 0xC0184800
DMA_BUF_IOCTL_EXPORT_SYNC_FILE = 0xC0086202
DMA_BUF_IOCTL_IMPORT_SYNC_FILE = 0x40086203


def probe():
    owned = []
    result = {"schema": 1, "heap": "/dev/dma_heap/system", "gpuWorkSubmitted": False}
    stage = "open_heap"
    try:
        heap = os.open(result["heap"], os.O_RDONLY | os.O_CLOEXEC)
        owned.append(heap)
        stage = "allocate"
        allocation = bytearray(struct.pack("=QIIQ", 4096, 0, os.O_RDWR | os.O_CLOEXEC, 0))
        fcntl.ioctl(heap, DMA_HEAP_IOCTL_ALLOC, allocation, True)
        buffer = struct.unpack("=QIIQ", allocation)[1]
        owned.append(buffer)
        for flags, name in [(1, "read"), (2, "write"), (3, "read_write")]:
            stage = "export_" + name
            export = bytearray(struct.pack("=Ii", flags, -1))
            fcntl.ioctl(buffer, DMA_BUF_IOCTL_EXPORT_SYNC_FILE, export, True)
            fence = struct.unpack("=Ii", export)[1]
            if fence < 0:
                raise RuntimeError("export returned no fence")
            owned.append(fence)
            stage = "poll_" + name
            poll = select.poll()
            poll.register(fence, select.POLLIN)
            events = poll.poll(0)
            if not events or not events[0][1] & select.POLLIN or events[0][1] & select.POLLERR:
                raise RuntimeError("empty-work fence is not successfully signaled")
            stage = "import_" + name
            fcntl.ioctl(buffer, DMA_BUF_IOCTL_IMPORT_SYNC_FILE, struct.pack("=Ii", flags, fence))
            result[name] = {"export": True, "signaled": True, "import": True}
            os.close(owned.pop())
        result["ok"] = True
    except (OSError, RuntimeError) as error:
        result.update(ok=False, failedStage=stage, error=str(error))
    finally:
        for fd in reversed(owned):
            os.close(fd)
    return result


if __name__ == "__main__":
    result = probe()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["ok"] else 1)
