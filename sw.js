const STATIC_CACHE = 'mjrstar-static-v34';
// Independent of shell releases. Bump this epoch if an existing media URL changes bytes.
const MEDIA_CACHE = 'mjrstar-media-v1';
const MEDIA_MAX_ENTRIES = 256;
const MEDIA_MAX_ENTRY_BYTES = 6 * 1024 * 1024;
const MEDIA_EXT_RE = /\.(gif|png|jpe?g|webp|avif|svg|ico|woff2?|ttf|otf|lottie|json|tgs|mp4|webm|mp3|ogg|wav)$/i;
const NETWORK_TIMEOUT_MS = 10000;
const PLAYER_CDN = 'https://cdn.jsdelivr.net/npm/@lottiefiles/dotlottie-web@0.80.0/dist/';
const PUBLIC_ROOTS = ['/lottie/', '/images/', '/fonts/', '/ИграHiLo/', '/ИграКено/', '/ИграРулетка/', '/Капча/', '/cryptobot/', '/tonkeeper/', '/xrocket/'];
const SHELL_PATHS = new Set(['/', '/index.html', '/app', '/app/', '/app_shell.html', '/app.js', '/styles.css', '/guard.js', '/game_names.js', '/support.js', '/support.css', '/admin.js', '/gadmin.js', '/srv_panel.js', '/srv_panel.css']);
const mediaPending = new Map();
let mediaWrites = Promise.resolve();

const OFFLINE_FALLBACK_HTML = `<!doctype html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="color-scheme" content="dark">
<title>MjrStar</title>
<style>
@font-face{font-family:'Unbounded';src:url('/fonts/Unbounded-Regular.ttf') format('truetype');font-weight:400;font-style:normal;font-display:swap}
@font-face{font-family:'Montserrat';src:url('/fonts/Montserrat-SemiBold.ttf') format('truetype');font-weight:400 900;font-style:normal;font-display:swap}
*{box-sizing:border-box;-webkit-user-select:none;user-select:none;-webkit-touch-callout:none;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:#020203}
body{min-height:100vh;min-height:100dvh;display:flex;align-items:center;justify-content:center;padding:24px;font-family:'Montserrat','Segoe UI',-apple-system,BlinkMacSystemFont,sans-serif;color:#f5f3ee}
.card{width:100%;max-width:380px;background:linear-gradient(180deg,rgba(255,255,255,.06),rgba(255,255,255,.02));border:1px solid rgba(255,255,255,.09);border-radius:32px;padding:34px 24px 26px;text-align:center;box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 24px 60px rgba(0,0,0,.6);animation:in .5s cubic-bezier(.22,1,.36,1) both}
@keyframes in{from{opacity:0;transform:translateY(14px) scale(.97)}to{opacity:1;transform:none}}
.art{position:relative;width:132px;height:132px;margin:0 auto 6px}
.art img,.art canvas{position:absolute;left:0;top:0;width:100%;height:100%;object-fit:contain;transition:opacity .3s}
.art canvas{opacity:0}
.art.live canvas{opacity:1}
.art.live img{opacity:0}
h1{margin:10px 0 10px;font:400 19px/1.25 'Unbounded','Montserrat','Segoe UI',sans-serif;color:#f5f3ee}
p{margin:0 0 26px;font-size:13.5px;line-height:1.6;color:#6d7180;font-weight:500}
button{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;padding:16px 20px;border:0;border-radius:999px;background:linear-gradient(180deg,#ffd08a 0%,#f2b565 42%,#d98a45 100%);color:#1a1206;font-family:inherit;font-weight:800;font-size:14.5px;cursor:pointer;box-shadow:inset 0 1px 0 rgba(255,255,255,.55),0 14px 30px rgba(201,123,59,.35);transition:transform .15s,filter .15s}
button:active{transform:scale(.97);filter:brightness(.95)}
button svg{width:19px;height:19px;flex:0 0 auto}
@media (prefers-reduced-motion:reduce){.card{animation:none}}
</style>
</head>
<body>
<div class="card">
<div class="art" id="art"><img src="/lottie/images/ПредупреждениеОшибка.png" alt=""><canvas id="cv" width="264" height="264"></canvas></div>
<h1>Не удалось загрузить страницу</h1>
<p>Похоже, пропало подключение к интернету или сервер временно недоступен. Проверьте соединение и попробуйте ещё раз.</p>
<button type="button" onclick="location.reload()"><svg viewBox="0 0 24 24" fill="none"><path d="M20 12a8 8 0 1 1-2.6-5.9M20 4v4.5h-4.5" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>Обновить страницу</button>
</div>
<script type="module">
window.addEventListener('online',function(){location.reload()});
try{var cdn='https://cdn.jsdelivr.net/npm/@lottiefiles/dotlottie-web@0.80.0/dist/';var mod=await import(cdn+'index.js');mod.DotLottie.setWasmUrl(cdn+'dotlottie-player.wasm');var pl=new mod.DotLottie({canvas:document.getElementById('cv'),src:'/lottie/images/ПредупреждениеОшибка.lottie',loop:true,autoplay:true});pl.addEventListener('load',function(){document.getElementById('art').classList.add('live')})}catch(e){}
</script>
</body>
</html>`;

const PRELOADER_ROCKET_GIFS = [
    'images/legacy_icons/cryptogame_avatar.jpg',
    'fonts/Unbounded-Regular.ttf', 'fonts/Unbounded-Medium.ttf', 'fonts/Montserrat-SemiBold.ttf',
    'lottie/NavBar/РазделЛидеры.lottie',
    'lottie/NavBar/РазделБаланс.lottie',
    'lottie/NavBar/РазделПрофиль.lottie',
    'lottie/NavBar/РазделПомощь.lottie',
    'lottie/images/ПредупреждениеОшибка.lottie',
    'lottie/images/ПредупреждениеОшибка.png'
];

function isPublicMedia(url) {
    if (url.href.startsWith(PLAYER_CDN)) return /\.(js|wasm)$/i.test(url.pathname);
    if (url.origin !== self.location.origin) return false;
    try {
        const path = decodeURIComponent(url.pathname);
        return MEDIA_EXT_RE.test(path) && PUBLIC_ROOTS.some(root => path.startsWith(root));
    } catch (error) { return false; }
}

function publicCacheKey(url) {
    const clean = new URL(url);
    clean.hash = '';
    // Static assets are not personalised. Keep their explicit version only;
    // never persist Telegram initData, cookies or auth headers in a cache key.
    const version = clean.searchParams.get('v');
    clean.search = '';
    if (version !== null) clean.searchParams.set('v', version);
    return new Request(clean.href, {credentials: 'omit'});
}

function cacheable(response) {
    return response && response.status === 200 && !response.redirected &&
        !response.headers.has('X-MjrStar-Placeholder') &&
        !/no-store|private/i.test(response.headers.get('Cache-Control') || '');
}

function fetchWithTimeout(req, ms, opts) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), ms);
    return fetch(req, Object.assign({}, opts, {signal: controller.signal})).finally(() => clearTimeout(timer));
}

async function saveMedia(cache, key, response) {
    try {
        // A slow stream for one asset must not block writes for every other game.
        await cache.put(key, response);
        // Serialize eviction only; completed writes converge on the entry bound.
        mediaWrites = mediaWrites.then(async () => {
            const keys = await cache.keys();
            for (let index = 0; index < keys.length - MEDIA_MAX_ENTRIES; index++) await cache.delete(keys[index]);
        }).catch(() => {});
        await mediaWrites;
    } catch (error) {} // Quota/disabled storage must not break successful loading.
}

async function mediaResponse(req) {
    const key = publicCacheKey(req.url);
    let cache;
    try {
        cache = await caches.open(MEDIA_CACHE);
        const cached = await cache.match(key);
        if (cached) return cached;
    } catch (error) {} // Network fallback also works with CacheStorage disabled.
    let task = mediaPending.get(key.url);
    if (!task) {
        task = (async () => {
            const response = await fetchWithTimeout(key, NETWORK_TIMEOUT_MS);
            if (cache && cacheable(response) && !/text\/html/i.test(response.headers.get('Content-Type') || '') &&
                Number(response.headers.get('Content-Length') || 0) <= MEDIA_MAX_ENTRY_BYTES) {
                await saveMedia(cache, key, response.clone());
            }
            return response;
        })();
        mediaPending.set(key.url, task);
    }
    try {
        return (await task).clone();
    } finally {
        if (mediaPending.get(key.url) === task) mediaPending.delete(key.url);
    }
}

self.addEventListener('install', event => {
    event.waitUntil(Promise.all(PRELOADER_ROCKET_GIFS.map(path =>
        mediaResponse(new Request(new URL(path, self.location.origin + '/').href)).catch(() => {})
    )).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
    event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key =>
        (key.startsWith('mjrstar-static-') && key !== STATIC_CACHE) ||
        (key.startsWith('mjrstar-media-') && key !== MEDIA_CACHE)
    ).map(key => caches.delete(key)))).catch(() => {}).then(() => self.clients.claim()));
});

async function shellResponse(req) {
    const key = publicCacheKey(req.url);
    try {
        const response = await fetchWithTimeout(req, NETWORK_TIMEOUT_MS);
        if (cacheable(response)) {
            try {
                const cache = await caches.open(STATIC_CACHE);
                await cache.put(key, response.clone());
            } catch (error) {}
        }
        return response;
    } catch (error) {
        try {
            const cache = await caches.open(STATIC_CACHE);
            const cached = await cache.match(key);
            if (cached) return cached;
        } catch (cacheError) {}
        if (req.mode === 'navigate') {
            return new Response(OFFLINE_FALLBACK_HTML, {status: 200, headers: {'Content-Type': 'text/html; charset=utf-8'}});
        }
        return new Response('', {status: 503, statusText: 'Offline'});
    }
}

self.addEventListener('fetch', event => {
    const req = event.request;
    if (req.method !== 'GET' || req.headers.has('Range')) return;
    const url = new URL(req.url);
    // Never intercept payments, balances, game state, WebSocket handshakes,
    // private support photos or any other API, even if its URL ends in .png.
    if (url.origin === self.location.origin && (url.pathname === '/api' || url.pathname.startsWith('/api/'))) return;
    if (isPublicMedia(url)) {
        event.respondWith(mediaResponse(req).catch(() => new Response('', {status: 503, statusText: 'Offline'})));
    } else if (url.origin === self.location.origin && SHELL_PATHS.has(url.pathname)) {
        event.respondWith(shellResponse(req));
    }
});
