import asyncio
import gzip
import time
from unittest.mock import patch
import static_assets
import os
from pathlib import Path
import tempfile
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from static_assets import accepts_gzip, static_response


class StaticAssetsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.asset = self.root / 'app.js'
        self.body = b'const value = "MajorStars";\n' * 1000
        self.asset.write_bytes(self.body)
        async def handler(request):
            return await static_response(request, self.asset, self.root / 'cache')
        app = web.Application()
        app.router.add_get('/app.js', handler)
        self.client = TestClient(TestServer(app), auto_decompress=False)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.directory.cleanup()

    async def test_gzip_roundtrip_etag_and_identity(self):
        response = await self.client.get('/app.js', headers={'Accept-Encoding': 'gzip'})
        compressed = await response.read()
        self.assertEqual(response.headers['Content-Encoding'], 'gzip')
        self.assertIn('javascript', response.headers['Content-Type'])
        self.assertEqual(response.headers['Vary'], 'Accept-Encoding')
        self.assertEqual(gzip.decompress(compressed), self.body)
        self.assertLess(len(compressed), len(self.body) // 4)
        response = await self.client.get('/app.js', headers={'Accept-Encoding': 'gzip', 'If-None-Match': response.headers['ETag']})
        self.assertEqual(response.status, 304)
        self.assertEqual(await response.read(), b'')
        response = await self.client.get('/app.js', headers={'Accept-Encoding': 'gzip;q=0, identity'})
        self.assertNotIn('Content-Encoding', response.headers)
        self.assertEqual(await response.read(), self.body)

    async def test_changed_source_invalidates_cached_variant(self):
        response = await self.client.get('/app.js', headers={'Accept-Encoding': 'gzip'})
        await response.read()
        stamp = self.asset.stat().st_mtime_ns
        updated = self.body.replace(b'MajorStars', b'OtherStars')
        self.asset.write_bytes(updated)
        os.utime(self.asset, ns=(stamp + 1000000000, stamp + 1000000000))
        response = await self.client.get('/app.js', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(gzip.decompress(await response.read()), updated)

    async def test_range_and_unwritable_cache_fallback(self):
        response = await self.client.get('/app.js', headers={'Accept-Encoding': 'gzip', 'Range': 'bytes=0-9'})
        self.assertEqual(response.status, 206)
        self.assertEqual(await response.read(), self.body[:10])
        # A file where a directory is expected simulates a read-only cache deployment.
        blocked = self.root / 'cache'
        blocked.write_text('not a directory')
        response = await self.client.get('/app.js', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(response.status, 200)
        self.assertNotIn('Content-Encoding', response.headers)
        self.assertEqual(await response.read(), self.body)

    async def test_concurrent_cold_requests_compress_once(self):
        original = static_assets.gzip_variant
        def slow_build(*args):
            time.sleep(0.03)
            return original(*args)
        with patch('static_assets.gzip_variant', side_effect=slow_build) as build:
            responses = await asyncio.gather(*(self.client.get('/app.js', headers={'Accept-Encoding': 'gzip'}) for _ in range(16)))
            for response in responses:
                self.assertEqual(gzip.decompress(await response.read()), self.body)
            self.assertEqual(build.call_count, 1)

    def test_encoding_negotiation(self):
        for value in ['gzip', 'br, gzip;q=0.5', '*;q=1']:
            self.assertTrue(accepts_gzip(value))
        for value in ['', 'br', 'gzip;q=0,*;q=1', 'gzip;q=bad', 'gzip;q=nan', 'gzip;q=2']:
            self.assertFalse(accepts_gzip(value))
