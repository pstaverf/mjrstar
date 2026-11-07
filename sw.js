const STATIC_CACHE = 'mjrstar-static-v31';
const MEDIA_EXT_RE = /\.(gif|png|jpe?g|webp|svg|ico|woff2?|ttf|otf|lottie)(\?.*)?$/i;
const NETWORK_TIMEOUT_MS = 10000;

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

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(STATIC_CACHE).then((cache) =>
            Promise.all(PRELOADER_ROCKET_GIFS.map((path) =>
                fetch(path, {
                    cache: 'reload'
                }).then((res) => {
                    if (res && res.ok && !res.headers.has("X-MjrStar-Placeholder")) return cache.put(path, res);
                }).catch(() => {})
            ))
        ).then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
        .then((keys) => Promise.all(keys.filter((k) => k !== STATIC_CACHE).map((k) => caches.delete(k))))
        .then(() => self.clients.claim())
    );
});

function fetchWithTimeout(req, ms, opts) {





    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('sw fetch timeout')), ms);
        fetch(req, opts).then(
            (res) => {
                clearTimeout(timer);
                resolve(res);
            },
            (err) => {
                clearTimeout(timer);
                reject(err);
            }
        );
    });
}

self.addEventListener('fetch', (event) => {
    const req = event.request;
    if (req.method !== 'GET') return;

    const url = new URL(req.url);
    if (url.origin !== self.location.origin) return;
    if (url.pathname.startsWith('/api/')) return;
    if (req.mode === 'navigate' && url.pathname !== '/' && url.pathname !== '/index.html' && url.pathname !== '/app' && url.pathname !== '/app/') return;

    if (MEDIA_EXT_RE.test(url.pathname)) {
        event.respondWith(
            caches.open(STATIC_CACHE).then((cache) =>
                cache.match(req).then((cached) => {
                    if (cached) return cached;
                    return fetchWithTimeout(req, NETWORK_TIMEOUT_MS, {
                        cache: 'reload'
                    }).then((res) => {
                        if (res && res.ok && !res.headers.has("X-MjrStar-Placeholder")) cache.put(req, res.clone());
                        return res;
                    }).catch(() => cached);
                })
            )
        );
        return;
    }

    event.respondWith(
        fetchWithTimeout(req, NETWORK_TIMEOUT_MS).then((res) => {
            if (res && res.ok) {
                const clone = res.clone();
                caches.open(STATIC_CACHE).then((cache) => cache.put(req, clone));
            }
            return res;
        }).catch(() => caches.match(req).then((cached) => {
            if (cached) return cached;
            if (req.mode === 'navigate' || (req.headers.get('accept') || '').indexOf('text/html') !== -1) {
                return new Response(OFFLINE_FALLBACK_HTML, {
                    status: 200,
                    headers: {
                        'Content-Type': 'text/html; charset=utf-8'
                    }
                });
            }
            return new Response('', {
                status: 503,
                statusText: 'Offline'
            });
        }))
    );
});