(function() {
    if (window.__guardLoaded) return;
    window.__guardLoaded = true;
    var host = String(location.hostname || "");
    if (host === "localhost" || host === "127.0.0.1" || host === "[::1]" || /\.localhost$|\.test$/.test(host)) return;

    var started = Date.now();
    var tripped = false;
    var strikes = 0;
    var cleanSince = Date.now();
    var overlay = null;
    var scrollHooked = false;
    var STRIKES_NEEDED = 2;
    var SLOW_MS = 700;
    var CHECK_MS = 1500;
    var CLEAR_AFTER_MS = 8000;
    var REPORT_GAP_MS = 60000;
    var lastReport = 0;
    var pending = false;
    var serverStaff = false;
    var markerKey = "__gt";
    var LOTTIE_URL = "/lottie/images/ПредупреждениеОшибка.lottie";
    var DOTLOTTIE_CDN = "https://cdn.jsdelivr.net/npm/@lottiefiles/dotlottie-web@0.80.0/dist/";
    var FALLBACK_ICON = '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><defs><linearGradient id="gdg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffd9a0"/><stop offset="1" stop-color="#c97b3b"/></linearGradient></defs><path d="M32 6 4 56h56L32 6Z" fill="none" stroke="url(#gdg)" stroke-width="4" stroke-linejoin="round"/><path d="M32 24v16" stroke="url(#gdg)" stroke-width="4" stroke-linecap="round"/><circle cx="32" cy="47" r="2.6" fill="#f2b565"/></svg>';

    var CSS = [
        ".gd-root{position:fixed;left:0;top:0;right:0;bottom:0;z-index:2147483647;display:flex;align-items:center;justify-content:center;padding:24px;box-sizing:border-box;overflow:hidden;touch-action:none;overscroll-behavior:none;-webkit-user-select:none;user-select:none;background:var(--bg-0,#020203);font-family:var(--font-body,'Montserrat','Segoe UI',-apple-system,BlinkMacSystemFont,sans-serif);color:var(--text-0,#f5f3ee);animation:gdFade .35s ease both}",
        ".gd-root:before{content:'';position:absolute;left:0;top:0;right:0;bottom:0;background:radial-gradient(900px 520px at 50% -8%,rgba(242,181,101,.20),transparent 62%),radial-gradient(760px 520px at 50% 108%,rgba(201,123,59,.24),transparent 64%),radial-gradient(520px 380px at 8% 62%,rgba(138,78,36,.16),transparent 70%)}",
        ".gd-root:after{content:'';position:absolute;left:0;top:0;right:0;bottom:0;background-image:radial-gradient(rgba(255,255,255,.06) 1px,transparent 1px);background-size:22px 22px;opacity:.55;-webkit-mask-image:radial-gradient(circle at 50% 45%,#000 0,transparent 72%);mask-image:radial-gradient(circle at 50% 45%,#000 0,transparent 72%)}",
        ".gd-glow{position:absolute;left:50%;top:44%;width:360px;height:360px;margin:-180px 0 0 -180px;border-radius:50%;background:radial-gradient(circle,rgba(242,181,101,.34),rgba(242,181,101,0) 68%);filter:blur(6px);animation:gdPulse 3.2s ease-in-out infinite;pointer-events:none}",
        ".gd-card{position:relative;width:100%;max-width:340px;box-sizing:border-box;padding:26px 22px 22px;border-radius:30px;text-align:center;background:linear-gradient(180deg,rgba(22,22,28,.78),rgba(10,10,14,.84));border:1px solid rgba(255,255,255,.09);box-shadow:0 30px 80px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.07);-webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);animation:gdRise .5s cubic-bezier(.2,.8,.2,1) both}",
        ".gd-icon{width:132px;height:132px;margin:-4px auto 6px;display:flex;align-items:center;justify-content:center}",
        ".gd-icon canvas,.gd-icon svg{width:100%;height:100%;display:block}",
        ".gd-chip{display:inline-block;margin:0 0 14px;padding:7px 12px;border-radius:999px;font:800 10px/1 var(--font-display,'Unbounded','Montserrat',sans-serif);letter-spacing:.08em;text-transform:uppercase;color:var(--gold-1,#f2b565);background:rgba(242,181,101,.1);border:1px solid rgba(242,181,101,.28)}",
        ".gd-title{margin:0 0 10px;font:800 19px/1.25 var(--font-display,'Unbounded','Montserrat',sans-serif);letter-spacing:-.01em;color:var(--text-0,#f5f3ee)}",
        ".gd-text{margin:0 0 20px;font:600 14px/1.5 var(--font-body,'Montserrat','Segoe UI',sans-serif);color:var(--text-1,#b9bcc6)}",
        ".gd-btn{display:block;width:100%;padding:15px;border:0;border-radius:999px;font:900 15px/1 var(--font-body,'Montserrat','Segoe UI',sans-serif);color:var(--ac-1a1206,#1a1206);background:var(--grad-gold,linear-gradient(135deg,#ffd9a0,#f2b565 55%,#c97b3b));box-shadow:0 10px 28px rgba(242,181,101,.28);cursor:pointer;-webkit-tap-highlight-color:transparent;transition:transform .15s ease,filter .15s ease}",
        ".gd-btn:active{transform:scale(.97);filter:brightness(.95)}",
        "html.gd-lock,html.gd-lock body{overflow:hidden!important;overscroll-behavior:none!important;touch-action:none!important}",
        "@keyframes gdFade{from{opacity:0}to{opacity:1}}",
        "@keyframes gdRise{from{opacity:0;transform:translateY(18px) scale(.96)}to{opacity:1;transform:none}}",
        "@keyframes gdPulse{0%,100%{opacity:.55;transform:scale(.94)}50%{opacity:1;transform:scale(1.06)}}",
        "@media (prefers-reduced-motion:reduce){.gd-root,.gd-card,.gd-glow{animation:none}}"
    ].join("");

    function markerGet() {
        try {
            return localStorage.getItem(markerKey) === "1";
        } catch (e) {
            return false;
        }
    }

    function markerSet(on) {
        try {
            if (on) localStorage.setItem(markerKey, "1");
            else localStorage.removeItem(markerKey);
        } catch (e) {}
    }

    var staleFlag = markerGet();

    function isStaff() {
        return window.__ADM0__ === 1 || window.__staffUser === true;
    }

    function post(kind) {
        try {
            fetch("/api/security/tamper", {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    kind: kind
                }),
                keepalive: true
            }).catch(function() {});
        } catch (e) {}
    }

    function ensureStyle() {
        if (document.getElementById("gd-style")) return;
        var s = document.createElement("style");
        s.id = "gd-style";
        s.textContent = CSS;
        (document.head || document.documentElement).appendChild(s);
    }

    function stopScroll(e) {
        if (!tripped) return;
        if (e.type === "keydown") {
            var code = e.keyCode;
            var onBtn = e.target && e.target.closest && e.target.closest(".gd-root");
            if (onBtn && (code === 13 || code === 32)) return;
            if (code === 32 || (code >= 33 && code <= 40)) e.preventDefault();
            return;
        }
        e.preventDefault();
    }

    function lockPage() {
        try {
            document.documentElement.classList.add("gd-lock");
            if (document.body) {
                document.body.inert = true;
                document.body.setAttribute("aria-hidden", "true");
            }
        } catch (e) {}
        if (scrollHooked) return;
        scrollHooked = true;
        document.addEventListener("touchmove", stopScroll, {
            passive: false,
            capture: true
        });
        document.addEventListener("wheel", stopScroll, {
            passive: false,
            capture: true
        });
        document.addEventListener("keydown", stopScroll, true);
    }

    function unlockPage() {
        try {
            document.documentElement.classList.remove("gd-lock");
            if (document.body) {
                document.body.inert = false;
                document.body.removeAttribute("aria-hidden");
            }
        } catch (e) {}
    }

    function loadDotLottie() {
        if (typeof window.loadDotLottie === "function") return window.loadDotLottie();
        return import (DOTLOTTIE_CDN + "index.js").then(function(mod) {
            mod.DotLottie.setWasmUrl(DOTLOTTIE_CDN + "dotlottie-player.wasm");
            return mod.DotLottie;
        });
    }

    function mountIcon(box) {
        var root = document.documentElement.classList;
        if (root.contains("lite-ui") || root.contains("perf-low")) {
            box.innerHTML = FALLBACK_ICON;
            return;
        }
        var canvas = document.createElement("canvas");
        canvas.width = 512;
        canvas.height = 512;
        box.appendChild(canvas);
        var settled = false;

        function fallback() {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            box.innerHTML = FALLBACK_ICON;
        }
        var timer = setTimeout(fallback, 5000);
        try {
            loadDotLottie().then(function(DotLottie) {
                if (settled) return;
                var dl = new DotLottie({
                    canvas: canvas,
                    src: encodeURI(LOTTIE_URL),
                    loop: true,
                    autoplay: true,
                    renderConfig: {
                        autoResize: true,
                        devicePixelRatio: Math.min(Math.max(window.devicePixelRatio || 1, 1.5), 2),
                        freezeOnOffscreen: false
                    }
                });
                dl.addEventListener("load", function() {
                    settled = true;
                    clearTimeout(timer);
                });
                dl.addEventListener("loadError", fallback);
            }).catch(fallback);
        } catch (e) {
            fallback();
        }
    }

    function buildOverlay() {
        var root = document.createElement("div");
        root.className = "gd-root";
        root.setAttribute("data-guard", "1");
        root.setAttribute("role", "alertdialog");
        root.setAttribute("aria-modal", "true");
        var glow = document.createElement("div");
        glow.className = "gd-glow";
        var card = document.createElement("div");
        card.className = "gd-card";
        var icon = document.createElement("div");
        icon.className = "gd-icon";
        var chip = document.createElement("div");
        chip.className = "gd-chip";
        chip.textContent = "Игра приостановлена";
        var title = document.createElement("h2");
        title.className = "gd-title";
        title.textContent = "Обнаружены инструменты разработчика";
        var text = document.createElement("p");
        text.className = "gd-text";
        text.textContent = "Закройте их и перезапустите приложение. Пока они открыты, играть нельзя.";
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "gd-btn";
        btn.textContent = "Перезапустить";
        btn.addEventListener("click", function() {
            location.reload();
        });
        card.appendChild(icon);
        card.appendChild(chip);
        card.appendChild(title);
        card.appendChild(text);
        card.appendChild(btn);
        root.appendChild(glow);
        root.appendChild(card);
        root._icon = icon;
        return root;
    }

    function showOverlay() {
        ensureStyle();
        lockPage();
        if (overlay && document.documentElement.contains(overlay)) return;
        overlay = buildOverlay();
        document.documentElement.appendChild(overlay);
        mountIcon(overlay._icon);
    }

    function hideOverlay() {
        if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
        overlay = null;
        unlockPage();
    }

    function report() {
        pending = true;
        fetch("/api/security/tamper", {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                kind: "devtools"
            }),
            keepalive: true
        }).then(function(r) {
            return r.json();
        }).then(function(d) {
            pending = false;
            if (d && d.staff) {
                serverStaff = true;
                clearInterval(timer);
                return;
            }
            if (d && d.blocked) {
                tripped = true;
                window.__guardTripped = true;
                cleanSince = Date.now();
                markerSet(true);
                showOverlay();
            }
        }).catch(function() {
            pending = false;
        });
    }

    function trip() {
        if (isStaff() || serverStaff || pending) return;
        var now = Date.now();
        if (tripped && now - lastReport < REPORT_GAP_MS) return;
        lastReport = now;
        report();
    }

    function measure() {
        var t = Date.now();
        (function() {
            debugger;
        })();
        return Date.now() - t;
    }

    function tick() {
        if (document.hidden || isStaff() || serverStaff) return;
        var slow = measure() > SLOW_MS;
        if (slow) {
            strikes += 1;
            cleanSince = Date.now();
            if (strikes >= STRIKES_NEEDED) trip();
        } else {
            strikes = 0;
            if (tripped && Date.now() - cleanSince > CLEAR_AFTER_MS) {
                tripped = false;
                staleFlag = false;
                window.__guardTripped = false;
                markerSet(false);
                hideOverlay();
                post("clear");
            } else if (staleFlag && !tripped && Date.now() - started > CLEAR_AFTER_MS + 1000) {
                staleFlag = false;
                markerSet(false);
                post("clear");
            }
        }
        if (tripped) showOverlay();
    }

    var timer = setInterval(tick, CHECK_MS);

    function blockedKey(e) {
        var k = String(e.key || "").toLowerCase();
        var ctrl = e.ctrlKey || e.metaKey;
        if (e.keyCode === 123 || k === "f12") return true;
        if (ctrl && e.shiftKey && (k === "i" || k === "j" || k === "c" || k === "k")) return true;
        if (ctrl && e.altKey && (k === "i" || k === "j" || k === "c" || k === "u")) return true;
        if (ctrl && !e.shiftKey && !e.altKey && (k === "u" || k === "s")) return true;
        return false;
    }

    window.addEventListener("keydown", function(e) {
        if (isStaff()) return;
        if (blockedKey(e)) {
            e.preventDefault();
            e.stopPropagation();
            return false;
        }
    }, true);

    window.addEventListener("contextmenu", function(e) {
        if (isStaff()) return;
        var t = e.target;
        if (t && t.closest && t.closest("input,textarea,[contenteditable='true'],[data-allow-menu]")) return;
        e.preventDefault();
    }, true);
})();