"""Reproducible local microbenchmarks. Only temporary fixture databases are used.
Run: PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/benchmark_runtime.py
"""
import asyncio
import gzip
import json
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_runtime_performance import RuntimePerformanceTests


async def main():
    fixture = RuntimePerformanceTests('test_idle_live_ticks_do_not_rewrite_rounds')
    await fixture.asyncSetUp()
    try:
        await fixture.stop_live()
        await fixture.seed_support(200)
        db = fixture.runtime.db()
        backend = fixture.backend
        user = SimpleNamespace(id=42)
        async def old_support_read():
            async with db.execute('SELECT id,admin_read,user_read FROM webapp_support_tickets WHERE user_id=42 ORDER BY updated_at DESC,id DESC LIMIT 200') as cur:
                rows = await cur.fetchall()
            for row in rows:
                async with db.execute('SELECT text FROM webapp_support_messages WHERE ticket_id=? AND deleted=0 ORDER BY id DESC LIMIT 1', (row[0],)) as cur:
                    await cur.fetchone()
                async with db.execute("SELECT COUNT(*) FROM webapp_support_messages WHERE ticket_id=? AND author='staff' AND id>?", (row[0], row[2])) as cur:
                    await cur.fetchone()
        async def new_support_read():
            await backend.support_snapshot(db, user)
        async def measure(callback):
            times, counts = [], []
            for _ in range(5):
                statements = []
                await db.set_trace_callback(statements.append)
                start = time.perf_counter()
                await callback()
                times.append((time.perf_counter() - start) * 1000)
                await db.set_trace_callback(None)
                counts.append(sum(q.lstrip().upper().startswith('SELECT') for q in statements))
            return {'median_ms': round(statistics.median(times), 3), 'select_queries': counts[-1], 'runs': 5}
        report = {'scope': 'Local isolated microbenchmark; not production throughput or Telegram/browser E2E', 'support_200_tickets': {'before_n_plus_one': await measure(old_support_read), 'after_batched': await measure(new_support_read)}}
        backend.realtime_public_cache = (0, [])
        statements = []
        await db.set_trace_callback(statements.append)
        start = time.perf_counter()
        for _ in range(64):
            await backend.realtime_snapshot(42)
        elapsed = (time.perf_counter() - start) * 1000
        await db.set_trace_callback(None)
        report['websocket_64_snapshots'] = {'elapsed_ms': round(elapsed, 3), 'select_queries': sum(q.lstrip().upper().startswith(('SELECT', 'WITH')) for q in statements), 'before_expected_queries': 256, 'note': 'One viewer simulated repeatedly; no private balance cache. Public game phases shared for 500ms.'}
        report['gzip_assets'] = {}
        for name in ('app.js', 'styles.css', 'app_shell.html', 'support.js', 'index.html'):
            data = (ROOT / name).read_bytes()
            start = time.perf_counter()
            packed = gzip.compress(data, compresslevel=6, mtime=0)
            report['gzip_assets'][name] = {'source_bytes': len(data), 'gzip_bytes': len(packed), 'reduction_percent': round((1 - len(packed) / len(data)) * 100, 1), 'cold_compress_ms': round((time.perf_counter() - start) * 1000, 3)}
        print(json.dumps(report, indent=2, ensure_ascii=False))
    finally:
        await fixture.asyncTearDown()


if __name__ == '__main__':
    asyncio.run(main())
