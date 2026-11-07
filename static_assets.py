"""On-demand gzip variants for public text assets, without blocking the event loop.

Only call this after the application's static-file allowlist check. No API responses
or private files should be routed here. Variants are keyed by source stat metadata.
"""
import asyncio
import gzip
import hashlib
import mimetypes
import os
from pathlib import Path
import tempfile

from aiohttp import web


def accepts_gzip(value):
    encodings = {}
    for part in value.lower().split(','):
        tokens = part.strip().split(';')
        if not tokens[0]:
            continue
        quality = 1.0
        for token in tokens[1:]:
            if token.strip().startswith('q='):
                try:
                    quality = float(token.strip()[2:])
                except ValueError:
                    quality = 0
        encodings[tokens[0].strip()] = quality
    return 0 < encodings.get('gzip', encodings.get('*', 0)) <= 1


def variant_target(path, cache_root, stat):
    key = hashlib.sha256(f'{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}'.encode()).hexdigest()
    return cache_root / (key + path.suffix)


def gzip_variant(path, cache_root):
    stat = path.stat()
    target = variant_target(path, cache_root, stat)
    if target.exists():
        return target
    cache_root.mkdir(parents=True, exist_ok=True)
    data = gzip.compress(path.read_bytes(), compresslevel=6, mtime=0)
    # FileResponse infers content type from the original suffix; Content-Encoding is explicit.
    with tempfile.NamedTemporaryFile(dir=cache_root, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(data)
            output.close()
            os.utime(temporary, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return target


# Coalesce concurrent cold requests for the same asset. Completed tasks never retain a loop.
_pending = {}


async def shared_gzip_variant(path, cache_root):
    target = variant_target(path, cache_root, path.stat())
    if target.exists():
        return target
    key = (asyncio.get_running_loop(), str(target))
    task = _pending.get(key)
    if task is None:
        task = asyncio.create_task(asyncio.to_thread(gzip_variant, path, cache_root))
        _pending[key] = task
        def complete(done):
            _pending.pop(key, None)
            if not done.cancelled():
                done.exception()  # Consume errors even if the requesting client disconnected.
        task.add_done_callback(complete)
    return await asyncio.shield(task)


async def static_response(request, path, cache_root=None):
    path = Path(path)
    headers = {'Cache-Control': 'no-cache', 'Vary': 'Accept-Encoding'}
    if path.suffix.lower() in {'.js', '.css', '.html'} and 'Range' not in request.headers and accepts_gzip(request.headers.get('Accept-Encoding', '')):
        try:
            variant = await shared_gzip_variant(path, cache_root or path.parent / '.cache' / 'http-static')
            headers['Content-Encoding'] = 'gzip'
            headers['Content-Type'] = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
            return web.FileResponse(variant, headers=headers)
        except OSError:
            # Read-only deployments remain usable without the optimization.
            pass
    return web.FileResponse(path, headers=headers)
