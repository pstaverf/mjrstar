# Game media caching and Crash positioning

## Crash movement fix

The previous trajectory started at `(3%,97%)`, but `crashRocketPos` clamped the sprite to at least `20%` left and at most `70%` top. Both coordinates stayed clamped through most low-multiplier rounds (until approximately x3), making a live rocket appear stationary.

The trajectory now starts at the existing visible anchor `(20%,70%)`. Its span preserves the previous high-end destination `(85%,18%)`. Rocket and trail endpoints move together immediately above x1, including short rounds. Existing rocket skins, canvas rendering, gradients, backend outcomes, multipliers, cashout and betting restrictions are retained. Missing/non-numeric skin angles fall back to the original 42-degree art orientation instead of generating NaN transforms. This is a positioning fix, not a replacement visual theme or a change to game odds.

## Two cache layers, shared by games

### Persistent public-media cache

`sw.js` previously used an over-escaped media-extension regular expression. Normal `.lottie`, `.png` and `.gif` paths fell through to network-first instead of cache-first.

The corrected service worker uses:

- `mjrstar-media-v1`: cache-first, on-demand public images, animations, fonts and supported media under the explicit public asset directories. The pinned dotLottie 0.80.0 CDN JS/WASM runtime is also eligible; arbitrary external URLs are not.
- `mjrstar-static-v33`: separate network-first app-shell cache with offline fallback. HTML/JS/CSS are not served permanently from the media cache.
- A 256-entry persistent media limit, with oldest-entry eviction after completed writes. Known Content-Length values above 6 MiB are not stored; unknown/compressed lengths are not a strict decoded-byte budget.
- Concurrent cold requests for the same canonical URL share one fetch and receive independent response bodies. A slow cache write for one asset does not serialize all other games' asset writes.
- Placeholder, failed, redirected, HTML-as-media and private/no-store responses are not cached. Range requests bypass the service worker.
- Successful network loading still works if CacheStorage is unavailable or its quota is exhausted.

Public cache keys retain only the explicit `v` query parameter, not credentials, Telegram initData or auth headers. Public static routes do not depend on user query parameters. `/api` and `/api/*`, including images/private support attachments, are never intercepted or cached. Other non-public routes are not cached. Activation removes only obsolete `mjrstar-static-*` and `mjrstar-media-*` caches, not unrelated applications' caches.

### In-memory Lottie bytes

All six existing dotLottie player-construction paths use the shared loader in `app.js`, including lazy canvases and game-specific players:

- Immutable source bytes are cached with an 8 MiB / 128-entry LRU limit; individual byte-cache entries are at most 2 MiB.
- Concurrent loads of the same animation share one request, including before a service worker controls the page.
- Each player receives its own ArrayBuffer copy. Canvas/player instances, playback position, random results and game state are never shared or cached.
- Disconnected canvases and existing game lifecycle checks are still honored by their callers.
- Failed, empty, HTML and placeholder byte responses do not poison the in-memory cache. Native player error handling is retained when the byte loader cannot supply data. A failed runtime-module import can be retried later.

Caching is on demand, not a bulk download of every game's assets at startup. First loads still need network access; repeat visits can reuse bytes. Decoding/rendering and live API latency are not eliminated by an asset cache.

## Deployment / invalidation

Deploy `app.js`, `index.html` and `sw.js` together. Bootstrap version: `majorstars-media-flight-20261107-9`. The existing service-worker update/controller reload logic remains in place. Persistent media survives shell-only updates. **When changing bytes at an existing unversioned media URL, bump `MEDIA_CACHE` or add/change its `v` query parameter.** This is required to avoid stale media. The byte cache resets on reload and respects full source URLs.

Do not use the old `or.zip` as a current deployment package. No production deployment was performed by these changes.

## Verification and limits

Full local suite: **168 Python tests and 11 Node regression suites passed**, plus JS syntax and whitespace checks.

New tests:

- `tests/test_crash_flight_visual.js`: motion at x1.01/x1.1, matching trail/rocket endpoint, finite default rotation, final crash position.
- `tests/test_lottie_binary_cache.js`: single-flight, independent player buffers, six player paths, bad-response recovery and LRU count/byte eviction.
- `tests/test_media_cache.js`: persistent cache-first hits, 20 concurrent cold requests with one mocked network call, pinned runtime, API/private exclusions, safe keys, placeholder/error filtering, quota/offline fallback, bounded entries, no cross-game slow-write blocking and release cleanup.

These use Node VM/browser API mocks, not a real Telegram WebView. The installed dotLottie 0.80.0 package's types and constructor source were inspected to verify ArrayBuffer input support and asynchronous constructor initialization. No device FPS, real browser paint, offline WebView or production load-time measurements are claimed. Existing backend payment/game tests do not prove real provider E2E behavior.
