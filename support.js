(function() {
    if (window.SUP) return;
    var root = document.getElementById("supRoot");
    if (!root) return;

    var ICONS = {
        copy: '<svg viewBox="0 0 24 24" fill="none"><rect x="8.5" y="8.5" width="11" height="11" rx="3" stroke="currentColor" stroke-width="2"/><path d="M15.5 8.5V7a3 3 0 0 0-3-3H7a3 3 0 0 0-3 3v5.5a3 3 0 0 0 3 3h1.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
        edit: '<svg viewBox="0 0 24 24" fill="none"><path d="M4 20h4.2L19.4 8.8a2.4 2.4 0 0 0 0-3.4l-.8-.8a2.4 2.4 0 0 0-3.4 0L4 15.8V20Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="m13.5 6.5 4 4" stroke="currentColor" stroke-width="2"/></svg>',
        trash: '<svg viewBox="0 0 24 24" fill="none"><path d="M5 7h14M10 7V5.5A1.5 1.5 0 0 1 11.5 4h1A1.5 1.5 0 0 1 14 5.5V7M7 7l.8 11.2A2 2 0 0 0 9.8 20h4.4a2 2 0 0 0 2-1.8L17 7M10.3 11v5M13.7 11v5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        check: '<svg viewBox="0 0 24 24" fill="none"><path d="m5 12.5 4.6 4.6L19 7.5" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        back: '<svg viewBox="0 0 24 24" fill="none"><path d="M15 6l-6 6 6 6" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        chev: '<svg viewBox="0 0 24 24" fill="none"><path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        plus: '<svg viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>',
        cam: '<svg viewBox="0 0 24 24" fill="none"><path d="M4 8.5A2.5 2.5 0 0 1 6.5 6h1.2l1-1.6A1.5 1.5 0 0 1 10 3.7h4a1.5 1.5 0 0 1 1.3.7l1 1.6h1.2A2.5 2.5 0 0 1 20 8.5v8A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5v-8Z" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/><circle cx="12" cy="12.4" r="3.2" stroke="currentColor" stroke-width="1.9"/></svg>',
        send: '<svg viewBox="0 0 24 24" fill="none"><path d="M5 12h13M13 6l6 6-6 6" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        x: '<svg viewBox="0 0 24 24" fill="none"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>',
        search: '<svg viewBox="0 0 24 24" fill="none"><circle cx="11" cy="11" r="6.5" stroke="currentColor" stroke-width="2"/><path d="m16 16 4 4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
        lock: '<svg viewBox="0 0 24 24" fill="none"><rect x="5" y="10.5" width="14" height="9.5" rx="2.5" stroke="currentColor" stroke-width="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
        down: '<svg viewBox="0 0 24 24" fill="none"><path d="M12 5v13M6 13l6 6 6-6" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        dots: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5.5" r="1.9"/><circle cx="12" cy="12" r="1.9"/><circle cx="12" cy="18.5" r="1.9"/></svg>',
        verified: '<svg class="help-verified" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 1.8l2.4 1.7 2.9-.2 1.2 2.7 2.6 1.4-.4 2.9 1.4 2.6-1.7 2.4.1 2.9-2.8.9-1.5 2.5-2.9-.6L12 22.2l-2.4-1.8-2.9.6-1.5-2.5-2.8-.9.1-2.9-1.7-2.4 1.4-2.6-.4-2.9 2.6-1.4 1.2-2.7 2.9.2L12 1.8Z"/><path d="m8 12.2 2.6 2.6L16.2 9" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        arrow: '<svg viewBox="0 0 24 24" fill="none"><path d="M9 6l6 6-6 6" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    };
    // Image tags cannot carry Telegram's signed header. Fetch files through the authenticated wrapper.
    var supportBlobs = new Map();
    function loadSupportImages() {
        root.querySelectorAll("img[data-support-file]").forEach(function(img) {
            var token = img.getAttribute("data-support-file");
            img.removeAttribute("data-support-file");
            var existing = supportBlobs.get(token);
            if (existing) { img.src = existing; return; }
            fetch("/api/support/file?t=" + encodeURIComponent(token), {cache: "no-store"})
                .then(function(r) { if (!r.ok) throw new Error("Фото недоступно"); return r.blob(); })
                .then(function(blob) {
                    var url = URL.createObjectURL(blob);
                    if (supportBlobs.has(token)) URL.revokeObjectURL(supportBlobs.get(token));
                    supportBlobs.set(token, url);
                    img.src = url;
                    if (supportBlobs.size > 100) {
                        var first = supportBlobs.keys().next().value;
                        URL.revokeObjectURL(supportBlobs.get(first)); supportBlobs.delete(first);
                    }
                }).catch(function() { img.alt = "Фото недоступно"; });
        });
    }
    new MutationObserver(loadSupportImages).observe(root, {childList: true, subtree: true});
    window.addEventListener("mjrstar:realtime", function(event) {
        if (!event.detail || !event.detail.supportChanged) return;
        if (S.view === "ticket") poll();
        else if (S.view === "home") loadState(true).then(function(d) {
            if (d && S.view === "home") {
                var list = document.getElementById("supTickets");
                if (list) list.innerHTML = d.tickets.map(ticketCard).join("");
            }
        });
    });
    var RULES = [
        "Сразу к сути — без meta вопросов",
        "Чётко формулируйте проблему — что случилось, когда, что делали.",
        "Будьте вежливы и грамотны.",
        "Соблюдайте субординацию — уважайте специалиста.",
        "При необходимости — прикладывайте скриншоты/логи.",
        "Не спамьте и не дублируйте вопросы.",
        "Терпение — залог хорошего ответа."
    ];
    var STATUS_TEXT = {
        open: "Ждёт ответа",
        answered: "Есть ответ",
        closed: "Закрыт"
    };

    function statusLabel(t) {
        return t.status === "closed" && t.closeReason === "no_reply" ? "Закрыт без ответа" : (STATUS_TEXT[t.status] || t.status);
    }
    var AVATAR = "/images/legacy_icons/cryptogame_avatar.jpg";
    var S = {
        state: null,
        view: "home",
        ticket: null,
        lastId: 0,
        msgs: [],
        draft: {
            category: "general",
            subject: "",
            text: ""
        },
        photos: [],
        pending: [],
        faqQ: "",
        faqOpen: null,
        rulesOpen: false,
        schedOpen: false,
        pollTimer: null,
        stateTimer: null,
        busy: false,
        typingAt: 0,
        lastTyping: false,
        atBottom: true,
        newCount: 0,
        loading: false
    };

    function esc(v) {
        return escapeHtml(v);
    }

    function haptic(kind) {
        try {
            if (typeof window.haptic === "function") window.haptic(kind || "selection");
        } catch (e) {}
    }

    function toast(msg, type) {
        try {
            showToast(msg, type || "error");
        } catch (e) {}
    }

    function api(method, path, body) {
        var opt = {
            method: method,
            credentials: "same-origin"
        };
        if (body !== undefined) {
            opt.headers = {
                "Content-Type": "application/json"
            };
            opt.body = JSON.stringify(body);
        }
        return fetch(path, opt).then(function(r) {
            return r.json().catch(function() {
                return {
                    ok: false,
                    error: "Ошибка сервера. Попробуйте ещё раз."
                };
            }).then(function(d) {
                d.status = r.status;
                return d;
            });
        }).catch(function() {
            return {
                ok: false,
                error: "Нет связи с сервером",
                offline: true
            };
        });
    }

    function clock(ts) {
        var d = new Date(ts * 1000);
        return ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2);
    }

    function dayKey(ts) {
        var d = new Date(ts * 1000);
        return d.getFullYear() + "-" + d.getMonth() + "-" + d.getDate();
    }

    function dayLabel(ts) {
        var d = new Date(ts * 1000);
        var now = new Date();
        if (dayKey(ts) === dayKey(now.getTime() / 1000)) return "Сегодня";
        if (dayKey(ts) === dayKey(now.getTime() / 1000 - 86400)) return "Вчера";
        return d.getDate() + " " + ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"][d.getMonth()] + (d.getFullYear() !== now.getFullYear() ? " " + d.getFullYear() : "");
    }

    function ago(ts) {
        var s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
        if (s < 60) return "только что";
        if (s < 3600) return Math.floor(s / 60) + " мин назад";
        if (s < 86400) return Math.floor(s / 3600) + " ч назад";
        if (s < 86400 * 7) return Math.floor(s / 86400) + " дн назад";
        return dayLabel(ts);
    }

    function lottieIcon(path, pngPath, cls) {
        if (typeof lazyImgTag !== "function") return "";
        var lite = document.documentElement.classList.contains("lite-ui");
        if (lite && !pngPath) return "";
        return '<span class="skel-box"></span>' + lazyImgTag(lite ? pngPath : path, "", cls || "");
    }

    function mountLotties() {
        try {
            if (typeof mountLottieCanvas === "function") root.querySelectorAll("canvas[data-lottie-src]").forEach(mountLottieCanvas);
        } catch (e) {}
    }

    function setNavVisible(on) {
        var nav = document.querySelector(".bottom-nav");
        if (nav) nav.style.display = on ? "" : "none";
        var app = document.querySelector(".app");
        if (app) app.classList.toggle("no-nav", !on);
        root.classList.toggle("sup-chat-on", !on);
        document.body.classList.toggle("sup-chat-open", !on);
        if (!on) fitChat();
        else window.scrollTo(0, 0);
    }

    function fitChat() {
        var chat = document.getElementById("supChat");
        if (!chat || S.view !== "ticket") return;
        var vh = (window.visualViewport && window.visualViewport.height) || window.innerHeight;
        var pad = parseFloat(getComputedStyle(root).paddingBottom) || 0;
        var top = chat.getBoundingClientRect().top + (window.pageYOffset || 0);
        chat.style.height = Math.max(320, Math.floor(vh - top - pad)) + "px";
    }

    function stopTimers() {
        clearInterval(S.pollTimer);
        S.pollTimer = null;
    }

    function loadState(silent) {
        return api("GET", "/api/support/state").then(function(d) {
            if (!d.ok) {
                if (!silent) toast(d.error);
                return null;
            }
            S.state = d;
            S.ban = d.ban || null;
            setBadge(d.unread);
            return d;
        });
    }

    function setBadge(n) {
        window.__supportUnread = n || 0;
        if (typeof window.supportBadgeSet === "function") window.supportBadgeSet(n || 0);
    }

    function skeleton() {
        root.innerHTML = topHTML("") + '<div class="sup-sk" style="height:84px;margin:0 0 14px"></div><div class="sup-sk" style="height:46px;margin:0 0 14px"></div><div class="sup-sk" style="height:56px;margin:0 0 18px"></div><div class="sup-sk" style="height:96px;margin:0 0 10px"></div><div class="sup-sk" style="height:96px"></div>';
    }

    function topHTML(title, extra, back) {
        if (!back && !title && !extra) return "";
        return '<div class="sup-top">' + (back ? '<button class="back-pill" type="button" data-act="' + back + '">' + ICONS.back + 'Обратно</button>' : '<span style="width:40px"></span>') + '<div class="sup-top-title">' + (title ? esc(title) : "") + '</div>' + (extra || '<span style="width:40px"></span>') + '</div>';
    }

    function statusPill(s) {
        return '<div class="sup-pills"><div class="sup-pill ' + (s.online ? "on" : "") + '"><i></i>' + (s.online ? "Онлайн" : "Не в сети" + (s.nextOpen ? " · " + esc(s.nextOpen) : "")) + '</div>' +
            '<div class="sup-pill">Ответ ~' + esc(s.replyEta) + '</div>' +
            '<button class="sup-pill btn ' + (S.schedOpen ? "open" : "") + '" type="button" data-act="sched">График работы' + ICONS.chev + '</button></div>';
    }

    function schedHTML(s) {
        var names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
        var rows = s.schedule.map(function(d, i) {
            return '<div class="sup-sched-row ' + (i === s.today ? "today" : "") + (d.on ? "" : " off") + '"><span>' + names[i] + (i === s.today ? " · сегодня" : "") + '</span><span>' + (d.on ? esc(d.from) + " – " + esc(d.to) : "выходной") + '</span></div>';
        }).join("");
        return '<div class="sup-card sup-sched ' + (S.schedOpen ? "open" : "") + '" id="supSched" style="padding:10px">' + rows + '<div class="sup-sched-note">Время указано по Москве (МСК). ' + (s.mode === "online" ? "Сейчас поддержка отвечает вне графика." : "Вне графика ответим в ближайшее рабочее время.") + '</div></div>';
    }

    function banWhen(ban) {
        if (!ban || !ban.at) return "";
        var day = dayLabel(ban.at);
        return (day === "Сегодня" || day === "Вчера" ? day.toLowerCase() : day) + " в " + clock(ban.at);
    }

    function banCardHTML(ban) {
        return '<div class="sup-ban"><div class="sup-ban-ic">' + ICONS.lock + '</div><div class="sup-ban-t"><b>Обращения в поддержку заблокированы</b>' +
            (ban.reason ? '<p><span>Причина</span>' + esc(ban.reason) + '</p>' : "") +
            '<small>' + (banWhen(ban) ? "Заблокировано " + esc(banWhen(ban)) + " · " : "") + 'Создавать тикеты и писать в поддержку сейчас нельзя. Если считаете это ошибкой — свяжитесь с администрацией проекта.</small></div></div>';
    }

    function onBanned(d) {
        S.ban = d.ban || {
            reason: "",
            at: 0
        };
        if (S.state) S.state.ban = S.ban;
        if (S.view === "ticket" && S.ticket) {
            applyTicketMeta(S.ticket);
            renderMessages();
        } else if (S.view === "create") {
            S.state = null;
            renderHome();
        }
    }

    function ticketCard(t) {
        return '<button class="sup-tk ' + (t.unread ? "unread" : "") + '" type="button" data-act="open" data-id="' + t.id + '">' +
            '<div class="sup-tk-top"><span class="sup-tk-num">№' + esc(t.num) + '</span><span class="sup-st ' + esc(t.status) + '">' + esc(statusLabel(t)) + '</span></div>' +
            '<p class="sup-tk-subj">' + esc(t.subject) + '</p><p class="sup-tk-prev">' + esc(t.preview || "") + '</p>' +
            '<div class="sup-tk-foot"><span>' + esc(t.categoryLabel) + " · " + ago(t.updatedAt) + '</span>' + (t.unread ? '<span class="sup-badge">' + t.unread + '</span>' : '') + '</div></button>';
    }

    function faqHTML(s) {
        var q = S.faqQ.trim().toLowerCase();
        var items = s.faq.filter(function(f) {
            return !q || f.q.toLowerCase().indexOf(q) !== -1 || f.a.toLowerCase().indexOf(q) !== -1;
        });
        if (!s.faq.length) return "";
        var list = items.length ? items.map(function(f) {
            return '<div class="sup-q ' + (S.faqOpen === f.id ? "open" : "") + '"><button class="sup-q-btn" type="button" data-act="faq" data-id="' + f.id + '"><span>' + esc(f.q) + '</span>' + ICONS.chev + '</button><div class="sup-q-a">' + esc(f.a) + '</div></div>';
        }).join("") : '<div class="sup-empty">' + '<div class="sup-empty-ic">' + lottieIcon("/lottie/images/ПоискИгрНеНайдено.lottie", "/lottie/images/ПоискИгрНеНайдено.png") + '</div>Ничего не нашли — создайте тикет, и мы поможем</div>';
        return '<div class="sup-sec"><h3>Частые вопросы</h3><span>' + s.faq.length + '</span></div>' +
            '<div class="sup-faq-search">' + ICONS.search + '<input id="supFaqQ" type="text" maxlength="60" placeholder="Поиск по вопросам" autocomplete="off" value="' + esc(S.faqQ) + '"></div><div class="sup-faq" id="supFaqList">' + list + '</div>';
    }

    function homeHTML() {
        var s = S.state;
        var open = s.openCount;
        var tickets = s.tickets.length ? s.tickets.map(ticketCard).join("") : '<div class="sup-empty"><div class="sup-empty-ic">' + lottieIcon("/lottie/images/ПоискИгрНеНайдено.lottie", "/lottie/images/ПоискИгрНеНайдено.png") + '</div>Обращений пока нет.<br>Если что-то пошло не так — мы на связи.</div>';
        return topHTML("") +
            '<div class="sup-hero"><div class="sup-ava"><img src="' + AVATAR + '" alt=""><span class="sup-ava-dot ' + (s.online ? "on" : "") + '"></span></div><div class="sup-hero-main"><h2 class="sup-title">Поддержка проекта' + ICONS.verified + '</h2><p class="sup-sub">Официальная поддержка · ответим прямо в этом чате</p></div></div>' +
            statusPill(s) + schedHTML(s) +
            (S.ban ? banCardHTML(S.ban) : '<div class="sup-cta"><button class="sup-btn gold" type="button" data-act="new">' + ICONS.plus + 'Создать тикет</button></div>') +
            '<button class="sup-link" type="button" data-act="rules-modal"><span class="sup-card-ic">' + lottieIcon("/lottie/NavBar/StarsTerms.lottie", "/lottie/NavBar/StarsTerms.png") + '</span><span class="sup-link-main"><b>Условия проекта</b><small>Правила, ответственность и безопасность</small></span>' + ICONS.arrow + '</button>' +
            '<div class="sup-sec"><h3>' + (s.isAdmin ? 'Все обращения · администратор' : 'Мои обращения') + '</h3><span>' + (open ? "открыто: " + open : "") + '</span></div><div class="sup-tickets" id="supTickets">' + tickets + '</div>' +
            faqHTML(s) +
            '<div class="sup-sec"></div><div class="sup-card sup-rules ' + (S.rulesOpen ? "open" : "") + '"><div class="sup-card-head" data-act="rules"><div class="sup-card-ic">' + lottieIcon("/lottie/images/ПравилоОбращения.lottie", "/lottie/images/ПравилоОбращения.png") + '</div><div><h3 class="sup-card-title">Правила обращения</h3><p class="sup-card-sub">Соблюдайте — и ответ придёт быстрее</p></div><span class="sup-chev">' + ICONS.chev + '</span></div><div class="sup-rules-body"><ol>' + RULES.map(function(r) {
                return "<li>" + esc(r) + "</li>";
            }).join("") + '</ol></div></div>' +
            (s.contactUrl ? '<a class="sup-contact" href="' + esc(s.contactUrl) + '" target="_blank" rel="noopener"><img src="/lottie/images/TelegramLogo.png" alt=""><span><b>Связаться в Telegram</b><small>' + esc(s.contactLabel || "") + '</small></span>' + ICONS.arrow + '</a>' : "");
    }

    function renderHome() {
        S.view = "home";
        stopTimers();
        setNavVisible(true);
        if (!S.state) {
            skeleton();
            return loadState().then(function(d) {
                if (d && S.view === "home") renderHome();
            });
        }
        root.innerHTML = homeHTML();
        mountLotties();
        clearInterval(S.stateTimer);
        S.stateTimer = setInterval(function() {
            if (document.hidden || S.view !== "home") return;
            loadState(true).then(function(d) {
                if (d && S.view === "home") {
                    var el = document.getElementById("supTickets");
                    if (el) el.innerHTML = d.tickets.length ? d.tickets.map(ticketCard).join("") : el.innerHTML;
                }
            });
        }, 20000);
    }

    function photoTile(p) {
        return '<div class="sup-ph ' + (p.busy ? "busy" : "") + '" data-key="' + p.key + '"><img src="' + esc(p.url) + '" alt="">' + '<button class="sup-ph-x" type="button" data-act="rmphoto" data-key="' + p.key + '">' + ICONS.x + '</button></div>';
    }

    function createHTML() {
        var s = S.state;
        var chips = s.categories.map(function(c) {
            return '<button class="sup-chip ' + (S.draft.category === c.key ? "on" : "") + '" type="button" data-act="cat" data-key="' + esc(c.key) + '">' + esc(c.label) + '</button>';
        }).join("");
        var tiles = S.photos.map(photoTile).join("") + (S.photos.length < s.limits.maxImages ? '<button class="sup-ph sup-ph-add" type="button" data-act="addphoto">' + ICONS.cam + '<span>Фото</span></button>' : "");
        return topHTML("Новый тикет", null, "home") +
            '<div class="sup-card"><div class="sup-field"><label>Категория</label><div class="sup-chips">' + chips + '</div></div>' +
            '<div class="sup-field"><label>Тема <em id="supSubjN">' + S.draft.subject.length + '/' + s.limits.subjectMax + '</em></label><input class="sup-input" id="supSubj" type="text" maxlength="' + s.limits.subjectMax + '" placeholder="Коротко о проблеме" value="' + esc(S.draft.subject) + '" autocomplete="off"></div>' +
            '<div class="sup-field"><label>Сообщение <em id="supTextN">' + S.draft.text.length + '/' + s.limits.textMax + '</em></label><textarea class="sup-text" id="supText" maxlength="' + s.limits.textMax + '" placeholder="Что случилось, когда и что вы делали? Если это про платёж — укажите сумму и время.">' + esc(S.draft.text) + '</textarea></div>' +
            '<div class="sup-field" style="margin-bottom:0"><label>Фото <em>до ' + s.limits.maxImages + '</em></label><div class="sup-photos" id="supPhotos">' + tiles + '</div><p class="sup-hint">Скриншоты ускоряют ответ. Подойдут JPG, PNG, WebP.</p></div></div>' +
            '<button class="sup-btn gold wide" type="button" id="supSubmit" data-act="submit">Отправить тикет</button>' +
            '<p class="sup-hint" style="text-align:center;margin-top:12px">' + (s.online ? "Поддержка в сети — ответим как можно скорее." : "Сейчас поддержка не в сети — ответим " + esc(s.nextOpen || "в рабочее время") + ".") + '</p>' +
            '<input type="file" id="supFile" accept="image/jpeg,image/png,image/webp" multiple hidden>';
    }

    function renderCreate() {
        S.view = "create";
        stopTimers();
        clearInterval(S.stateTimer);
        setNavVisible(true);
        root.innerHTML = createHTML();
        updateSubmit();
    }

    function updateSubmit() {
        var b = document.getElementById("supSubmit");
        if (!b) return;
        var ok = S.draft.subject.trim().length >= S.state.limits.subjectMin && (S.draft.text.trim().length >= 5 || S.photos.length) && !S.photos.some(function(p) {
            return p.busy;
        });
        b.disabled = !ok || S.busy;
    }

    function compress(file) {
        return new Promise(function(resolve, reject) {
            if (file.size <= 900 * 1024 && /^image\/(jpeg|png|webp)$/.test(file.type)) return resolve(file);
            var url = URL.createObjectURL(file);
            var img = new Image();
            img.onload = function() {
                var max = 1600;
                var k = Math.min(1, max / Math.max(img.width, img.height));
                var c = document.createElement("canvas");
                c.width = Math.max(1, Math.round(img.width * k));
                c.height = Math.max(1, Math.round(img.height * k));
                var ctx = c.getContext("2d");
                ctx.fillStyle = "#fff";
                ctx.fillRect(0, 0, c.width, c.height);
                ctx.drawImage(img, 0, 0, c.width, c.height);
                URL.revokeObjectURL(url);
                c.toBlob(function(b) {
                    b ? resolve(b) : reject(new Error("compress"));
                }, "image/jpeg", 0.82);
            };
            img.onerror = function() {
                URL.revokeObjectURL(url);
                reject(new Error("image"));
            };
            img.src = url;
        });
    }

    function addFiles(fileList, target) {
        var limit = S.state.limits.maxImages;
        var list = Array.prototype.slice.call(fileList || []);
        list.forEach(function(file) {
            var bag = target === "reply" ? S.pending : S.photos;
            if (bag.length >= limit) {
                toast("Можно приложить не больше " + limit + " фото");
                return;
            }
            if (!/^image\//.test(file.type)) {
                toast("Подходят только фото");
                return;
            }
            var item = {
                key: "k" + Date.now() + Math.random().toString(36).slice(2, 7),
                url: URL.createObjectURL(file),
                busy: true,
                id: null
            };
            bag.push(item);
            refreshPhotos(target);
            compress(file).then(function(blob) {
                return fetch("/api/support/upload", {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "Content-Type": blob.type || "image/jpeg"
                    },
                    body: blob
                });
            }).then(function(r) {
                return r.json();
            }).then(function(d) {
                if (!d.ok) throw new Error(d.error || "Не удалось загрузить фото");
                item.id = d.file.id;
                item.busy = false;
                refreshPhotos(target);
            }).catch(function(e) {
                var i = bag.indexOf(item);
                if (i >= 0) bag.splice(i, 1);
                toast(e && e.message ? e.message : "Не удалось загрузить фото");
                refreshPhotos(target);
            });
        });
    }

    function refreshPhotos(target) {
        if (target === "reply") {
            var prev = document.getElementById("supPrev");
            if (prev) prev.innerHTML = S.pending.map(photoTile).join("");
            if (prev) prev.style.display = S.pending.length ? "flex" : "none";
            updateSend();
            return;
        }
        var box = document.getElementById("supPhotos");
        if (!box) return;
        box.innerHTML = S.photos.map(photoTile).join("") + (S.photos.length < S.state.limits.maxImages ? '<button class="sup-ph sup-ph-add" type="button" data-act="addphoto">' + ICONS.cam + '<span>Фото</span></button>' : "");
        updateSubmit();
    }

    function removePhoto(key, target) {
        var bag = target === "reply" ? S.pending : S.photos;
        var i = bag.findIndex(function(p) {
            return p.key === key;
        });
        if (i < 0) return;
        var p = bag[i];
        bag.splice(i, 1);
        if (p.id) api("POST", "/api/support/file/delete", {
            id: p.id
        });
        refreshPhotos(target);
    }

    function submitTicket() {
        if (S.busy) return;
        var b = document.getElementById("supSubmit");
        S.busy = true;
        if (b) {
            b.disabled = true;
            b.textContent = "Отправляем…";
        }
        api("POST", "/api/support/ticket/create", {
            subject: S.draft.subject,
            category: S.draft.category,
            text: S.draft.text,
            files: S.photos.map(function(p) {
                return p.id;
            })
        }).then(function(d) {
            S.busy = false;
            if (!d.ok) {
                toast(d.error);
                if (d.banned) {
                    onBanned(d);
                    return;
                }
                if (b) {
                    b.disabled = false;
                    b.textContent = "Отправить тикет";
                }
                updateSubmit();
                return;
            }
            haptic("notification");
            S.draft = {
                category: "general",
                subject: "",
                text: ""
            };
            S.photos = [];
            S.state = null;
            showCreated(d.ticket);
        });
    }

    function showCreated(t) {
        S.view = "created";
        root.innerHTML = topHTML("") + '<div class="sup-card sup-success"><div class="sup-check"><svg viewBox="0 0 72 72" aria-hidden="true"><circle class="sup-check-ring" cx="36" cy="36" r="30"/><path class="sup-check-tick" d="M22 37.5l9.5 9.5L51 26"/></svg></div><h3>Тикет №' + esc(t.num) + ' создан</h3><p>Мы получили ваше обращение. Ответ придёт сюда и в личные сообщения бота.</p><button class="sup-btn gold wide" type="button" data-act="open" data-id="' + t.id + '">Открыть тикет</button><button class="sup-btn ghost wide" type="button" data-act="home" style="margin-top:10px">К списку обращений</button></div>';
        mountLotties();
        loadState(true);
    }

    function findMsg(id) {
        id = parseInt(id, 10);
        for (var i = 0; i < S.msgs.length; i++)
            if (S.msgs[i].id === id) return S.msgs[i];
        return null;
    }

    function ownMessage(m) {
        return typeof CURRENT_UID !== "undefined" && String(m.userId) === String(CURRENT_UID);
    }

    function canEditMsg(m) {
        var t = S.ticket;
        var win = (S.state && S.state.limits && S.state.limits.editWindow) || 172800;
        return ownMessage(m) && !!t && !S.ban && t.status !== "closed" && Date.now() / 1000 - m.createdAt <= win;
    }

    function copyText(text) {
        return new Promise(function(resolve, reject) {
            var fallback = function() {
                try {
                    var ta = document.createElement("textarea");
                    ta.value = text;
                    ta.setAttribute("readonly", "");
                    ta.style.cssText = "position:fixed;top:0;left:0;opacity:0";
                    document.body.appendChild(ta);
                    ta.select();
                    ta.setSelectionRange(0, text.length);
                    var ok = document.execCommand("copy");
                    document.body.removeChild(ta);
                    if (ok) resolve();
                    else reject(new Error("copy"));
                } catch (e) {
                    reject(e);
                }
            };
            if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(resolve).catch(fallback);
            else fallback();
        });
    }

    function msgHTML(m, prevMsg) {
        var out = "";
        if (!prevMsg || dayKey(prevMsg.createdAt) !== dayKey(m.createdAt)) out += '<div class="sup-day">' + esc(dayLabel(m.createdAt)) + '</div>';
        if (m.author === "system") return out + '<div class="sup-sys" data-mid="' + m.id + '">' + esc(m.text) + '</div>';
        var me = ownMessage(m);
        var bot = m.author === "bot";
        var imgs = (m.files || []).map(function(f) {
            return '<button class="sup-im" type="button" data-act="zoom" data-t="' + esc(f.t) + '"><img loading="lazy" data-support-file="' + encodeURIComponent(f.t) + '" alt=""></button>';
        }).join("");
        var cls = m.files && m.files.length === 1 ? "one" : (m.files && m.files.length >= 3 ? "three" : "");
        var who = me ? "" : '<div class="sup-who">' + esc(m.name || (S.ticketTeam || "Поддержка")) + (bot ? "<em>АВТООТВЕТ</em>" : "") + '</div>';
        var cp = m.text ? '<button class="sup-cp" type="button" data-act="copy" data-mid="' + m.id + '" aria-label="Скопировать сообщение">' + ICONS.copy + '</button>' : "";
        var tools = "";
        if (me) {
            if (canEditMsg(m)) tools += '<button class="sup-tool" type="button" data-act="edit" data-mid="' + m.id + '" aria-label="Изменить сообщение">' + ICONS.edit + '</button>';
            tools += '<button class="sup-tool danger" type="button" data-act="del" data-mid="' + m.id + '" aria-label="Удалить сообщение">' + ICONS.trash + '</button>';
        }
        var foot = '<div class="sup-foot">' + (tools ? '<span class="sup-tools">' + tools + '</span>' : "") + '<span class="sup-time">' + (m.edited ? '<span class="sup-ed">изменено</span>' : "") + clock(m.createdAt) + '</span></div>';
        var bub = '<div class="sup-bub">' + who + (imgs ? '<div class="sup-imgs ' + cls + '">' + imgs + '</div>' : "") + (m.text ? '<div class="sup-txt">' + esc(m.text) + '</div>' : "") + foot + '</div>';
        var editing = S.editing && S.editing.id === m.id ? " editing" : "";
        return out + '<div class="sup-row ' + (me ? "me" : (bot ? "them bot" : "them")) + editing + '" data-mid="' + m.id + '">' + (me ? cp + bub : '<div class="sup-ava"><img src="' + AVATAR + '" alt=""></div>' + bub + cp) + '</div>';
    }

    function renderMessages() {
        var el = listEl();
        if (!el) return;
        var top = el.scrollTop;
        var stick = nearBottom(el);
        var typing = document.getElementById("supTyping");
        var html = "";
        var prev = null;
        S.msgs.forEach(function(m) {
            html += msgHTML(m, prev);
            prev = m;
        });
        el.classList.add("norise");
        Array.prototype.slice.call(el.children).forEach(function(n) {
            if (n !== typing) n.remove();
        });
        var tmp = document.createElement("div");
        tmp.innerHTML = html;
        while (tmp.firstChild) el.insertBefore(tmp.firstChild, typing || null);
        el.scrollTop = stick ? el.scrollHeight : top;
        showToEnd();
        setTimeout(function() {
            el.classList.remove("norise");
        }, 80);
    }

    function applyChanges(list) {
        var dirty = false;
        (list || []).forEach(function(c) {
            var i = -1;
            for (var k = 0; k < S.msgs.length; k++)
                if (S.msgs[k].id === c.id) {
                    i = k;
                    break;
                }
            if (i < 0) return;
            if (c.deleted) {
                S.msgs.splice(i, 1);
                dirty = true;
                if (S.editing && S.editing.id === c.id) endEdit();
            } else if (JSON.stringify(S.msgs[i]) !== JSON.stringify(c)) {
                S.msgs[i] = c;
                dirty = true;
            }
        });
        if (dirty) renderMessages();
    }

    function copyMessage(btn) {
        var m = findMsg(btn.dataset.mid);
        if (!m || !m.text) return;
        copyText(m.text).then(function() {
            haptic("selection");
            toast("Сообщение скопировано", "success");
            btn.classList.add("done");
            btn.innerHTML = ICONS.check;
            setTimeout(function() {
                btn.classList.remove("done");
                btn.innerHTML = ICONS.copy;
            }, 1400);
        }).catch(function() {
            toast("Не удалось скопировать — выделите текст вручную", "warning");
        });
    }

    function paintEdit() {
        var on = !!S.editing;
        var comp = document.getElementById("supComp");
        var bar = document.getElementById("supEditing");
        var send = document.getElementById("supSend");
        if (comp) comp.classList.toggle("edit", on);
        if (bar) {
            bar.hidden = !on;
            bar.innerHTML = on ? '<span class="sup-editing-ic">' + ICONS.edit + '</span><div class="sup-editing-t"><b>Изменение сообщения</b><small>' + esc(String(S.editing.text || "").replace(/\s+/g, " ").slice(0, 90)) + '</small></div><button class="sup-editing-x" type="button" data-act="cancel-edit" aria-label="Отменить изменение">' + ICONS.x + '</button>' : "";
        }
        if (send) {
            send.innerHTML = on ? ICONS.check : ICONS.send;
            send.setAttribute("aria-label", on ? "Сохранить изменения" : "Отправить");
        }
        root.querySelectorAll(".sup-row").forEach(function(r) {
            r.classList.toggle("editing", on && String(S.editing.id) === r.getAttribute("data-mid"));
        });
    }

    function autosize(ta) {
        ta.style.height = "auto";
        ta.style.height = Math.min(132, ta.scrollHeight) + "px";
    }

    function startEdit(mid) {
        var m = findMsg(mid);
        var ta = document.getElementById("supMsg");
        if (!m || !ta || !canEditMsg(m) || S.busy) return;
        if (!S.editing) S.stash = ta.value;
        S.editing = {
            id: m.id,
            text: m.text
        };
        ta.value = m.text;
        autosize(ta);
        paintEdit();
        updateSend();
        haptic("selection");
        try {
            ta.focus();
            ta.setSelectionRange(ta.value.length, ta.value.length);
        } catch (e) {}
        var row = root.querySelector('.sup-row[data-mid="' + m.id + '"]');
        if (row && row.scrollIntoView) row.scrollIntoView({
            block: "nearest",
            behavior: "smooth"
        });
    }

    function endEdit() {
        if (!S.editing) return;
        S.editing = null;
        var ta = document.getElementById("supMsg");
        if (ta) {
            ta.value = S.stash || "";
            autosize(ta);
            if (!ta.value) ta.style.height = "";
        }
        S.stash = "";
        paintEdit();
        updateSend();
    }

    function saveEdit() {
        var ta = document.getElementById("supMsg");
        if (!ta || S.busy || !S.editing || !S.ticket) return;
        var m = findMsg(S.editing.id);
        var text = ta.value.trim();
        if (!text && !(m && m.files && m.files.length)) return;
        if (text === String(S.editing.text || "").trim()) {
            endEdit();
            return;
        }
        S.busy = true;
        updateSend();
        api("POST", "/api/support/message/edit", {
            id: S.ticket.id,
            mid: S.editing.id,
            text: text
        }).then(function(d) {
            S.busy = false;
            if (!d.ok) {
                toast(d.error);
                if (d.banned) {
                    onBanned(d);
                    return;
                }
                if (/закрыт|удалено|не найден/.test(d.error || "")) poll();
                updateSend();
                return;
            }
            haptic("notification");
            applyChanges([d.message]);
            endEdit();
            if (d.ticket) applyTicketMeta(d.ticket);
            if (d.changed) toast("Сообщение изменено", "success");
        });
    }

    function deleteMsg(mid) {
        var m = findMsg(mid);
        if (!m || !ownMessage(m)) return;
        askConfirm({
            icon: ICONS.trash,
            title: "Удалить сообщение?",
            text: "Оно исчезнет из вашей переписки. Поддержка сохранит копию и увидит, что вы его удалили.",
            ok: "Удалить",
            cancel: "Отмена",
            danger: true,
            onOk: function() {
                api("POST", "/api/support/message/delete", {
                    id: S.ticket.id,
                    mid: m.id
                }).then(function(d) {
                    if (!d.ok) {
                        toast(d.error);
                        return;
                    }
                    haptic("notification");
                    var row = root.querySelector('.sup-row[data-mid="' + m.id + '"]');
                    if (row) row.classList.add("out");
                    setTimeout(function() {
                        applyChanges([{
                            id: m.id,
                            deleted: true
                        }]);
                        if (d.ticket) applyTicketMeta(d.ticket);
                        toast("Сообщение удалено", "success");
                    }, 230);
                });
            }
        });
    }

    function ticketShell(t) {
        var st = S.state;
        return '<div class="sup-chat" id="supChat"><div class="sup-top" style="margin-bottom:8px"><button class="back-pill" type="button" data-act="home">' + ICONS.back + 'Назад</button><div class="sup-top-title" id="supCTitle">№' + esc(t.num) + '</div>' +
            '<button class="sup-top-act" type="button" data-act="menu" aria-label="Меню">' + ICONS.dots + '</button></div>' +
            '<div class="sup-chat-head"><div class="sup-ava"><img src="' + AVATAR + '" alt=""><span class="sup-ava-dot ' + (st && st.online ? "on" : "") + '" id="supDot"></span></div><div class="sup-chat-meta"><b>' + esc(t.subject) + '</b><small><span class="sup-st ' + esc(t.status) + '" id="supStat">' + esc(statusLabel(t)) + '</span><span id="supOnline">' + (st && st.online ? "поддержка в сети" : "поддержка не в сети") + '</span></small></div></div>' +
            '<div class="sup-list" id="supList"></div><button class="sup-toend" id="supToEnd" type="button" data-act="toend">' + ICONS.down + '<b class="sup-badge" id="supNew" style="display:none"></b></button>' +
            '<div class="sup-comp" id="supComp"></div></div>';
    }

    function compState(t) {
        if (S.ban) return "b";
        return t.status !== "closed" ? "0" : (t.canReply ? "r" : "1");
    }

    function compHTML(t) {
        if (S.ban) {
            return '<div class="sup-closed sup-banned"><div class="sup-lock">' + ICONS.lock + '</div><b>Обращения заблокированы</b><span>' + (S.ban.reason ? "Причина: " + esc(S.ban.reason) + ". " : "") +
                'Писать в поддержку сейчас нельзя. Если считаете это ошибкой — свяжитесь с администрацией проекта.</span></div>';
        }
        if (t.status === "closed" && !t.canReply) {
            var hard = t.closeReason === "no_reply";
            return '<div class="sup-closed"><div class="sup-lock">' + ICONS.lock + '</div><b>' + (hard ? "Закрыт без ответа" : "Тикет закрыт") + '</b><span>' +
                (hard ? "Поддержка закрыла обращение без ответа. Писать в этот тикет больше нельзя — если вопрос актуален, создайте новый." : "Прошло слишком много времени, чтобы вернуться в этот тикет. Если вопрос остался — создайте новый.") +
                '</span><button class="sup-btn gold wide" type="button" data-act="new">' + ICONS.plus + 'Создать новый тикет</button></div>';
        }
        var hint = t.status === "closed" ? '<div class="sup-reopen">' + ICONS.lock + '<span>Тикет закрыт. Напишите сообщение — и переписка возобновится.</span></div>' : "";
        return hint + '<div class="sup-editing" id="supEditing" hidden></div><div class="sup-comp-prev" id="supPrev" style="display:' + (S.pending.length ? "flex" : "none") + '">' + S.pending.map(photoTile).join("") + '</div><div class="sup-comp-row"><button class="sup-comp-btn" type="button" data-act="addreply" aria-label="Прикрепить фото">' + ICONS.cam + '</button><textarea id="supMsg" rows="1" maxlength="' + S.state.limits.textMax + '" placeholder="Напишите сообщение…"></textarea><button class="sup-comp-btn send" type="button" id="supSend" data-act="send" disabled aria-label="Отправить">' + ICONS.send + '</button></div><input type="file" id="supFileR" accept="image/jpeg,image/png,image/webp" multiple hidden>';
    }

    function updateSend() {
        var b = document.getElementById("supSend");
        var ta = document.getElementById("supMsg");
        if (!b || !ta) return;
        if (S.editing) {
            var em = findMsg(S.editing.id);
            var typed = ta.value.trim();
            b.disabled = S.busy || !(typed || (em && em.files && em.files.length)) || typed === String(S.editing.text || "").trim();
            return;
        }
        b.disabled = S.busy || !((ta.value.trim().length) || S.pending.length) || S.pending.some(function(p) {
            return p.busy;
        });
    }

    function listEl() {
        return document.getElementById("supList");
    }

    function nearBottom(el) {
        return el.scrollHeight - el.scrollTop - el.clientHeight < 90;
    }

    function appendMessages(msgs, fromPoll) {
        var el = listEl();
        if (!el || !msgs.length) return;
        var stick = nearBottom(el);
        var typing = document.getElementById("supTyping");
        var html = "";
        msgs.forEach(function(m) {
            S.lastId = Math.max(S.lastId, m.id);
            if (m.deleted) return;
            if (el.querySelector('[data-mid="' + m.id + '"]')) return;
            html += msgHTML(m, S.msgs[S.msgs.length - 1]);
            S.msgs.push(m);
            S.lastId = Math.max(S.lastId, m.id);
        });
        if (!html) return;
        var tmp = document.createElement("div");
        tmp.innerHTML = html;
        while (tmp.firstChild) el.insertBefore(tmp.firstChild, typing || null);
        var incoming = msgs.some(function(m) {
            return !ownMessage(m) && !m.deleted;
        });
        if (stick || !fromPoll) {
            scrollEnd(true);
            S.newCount = 0;
        } else if (incoming) {
            S.newCount += msgs.filter(function(m) {
                return !ownMessage(m) && !m.deleted;
            }).length;
            showToEnd();
        }
        if (fromPoll && incoming) haptic("notification");
    }

    function scrollEnd(smooth) {
        var el = listEl();
        if (!el) return;
        el.scrollTo ? el.scrollTo({
            top: el.scrollHeight,
            behavior: smooth ? "smooth" : "auto"
        }) : (el.scrollTop = el.scrollHeight);
        showToEnd();
    }

    function showToEnd() {
        var el = listEl();
        var b = document.getElementById("supToEnd");
        var n = document.getElementById("supNew");
        if (!el || !b) return;
        var far = !nearBottom(el);
        b.classList.toggle("on", far);
        if (n) {
            n.style.display = S.newCount ? "" : "none";
            n.textContent = S.newCount;
        }
        if (!far) S.newCount = 0;
    }

    function setTyping(on) {
        var el = listEl();
        if (!el) return;
        var t = document.getElementById("supTyping");
        if (on && !t) {
            t = document.createElement("div");
            t.id = "supTyping";
            t.className = "sup-typing on";
            t.innerHTML = '<div class="sup-ava"><img src="' + AVATAR + '" alt=""></div><div><small>Поддержка печатает…</small><div class="sup-dots"><i></i><i></i><i></i></div></div>';
            var stick = nearBottom(el);
            el.appendChild(t);
            if (stick) scrollEnd(true);
        } else if (!on && t) {
            t.remove();
        }
    }

    function applyTicketMeta(t, online) {
        var flip = !!S.ticket && (S.ticket.status === "closed") !== (t.status === "closed");
        if (S.editing && (t.status === "closed" || S.ban)) {
            var ta0 = document.getElementById("supMsg");
            if (ta0) ta0.value = S.stash || "";
            S.editing = null;
            S.stash = "";
        }
        S.ticket = t;
        var st = document.getElementById("supStat");
        if (st) {
            st.className = "sup-st " + t.status;
            st.textContent = statusLabel(t);
        }
        var on = document.getElementById("supOnline");
        if (on && online !== undefined) on.textContent = online ? "поддержка в сети" : "поддержка не в сети";
        var dot = document.getElementById("supDot");
        if (dot && online !== undefined) dot.classList.toggle("on", !!online);
        var comp = document.getElementById("supComp");
        if (comp && comp.getAttribute("data-closed") !== compState(t)) {
            var keep = document.getElementById("supMsg");
            var typed = keep ? keep.value : "";
            var list = listEl();
            var stick = !list || nearBottom(list);
            comp.setAttribute("data-closed", compState(t));
            comp.innerHTML = compHTML(t);
            var again = document.getElementById("supMsg");
            if (again && typed) {
                again.value = typed;
                again.dispatchEvent(new Event("input", {
                    bubbles: true
                }));
            }
            paintEdit();
            fitChat();
            if (stick) scrollEnd(false);
        }
        if (flip && S.msgs.length) renderMessages();
    }

    function poll() {
        if (document.hidden || S.view !== "ticket" || !S.ticket) return;
        var id = S.ticket.id;
        api("GET", "/api/support/ticket?id=" + encodeURIComponent(id) + "&after=" + S.lastId + "&rev=" + S.rev).then(function(d) {
            if (!d.ok || S.view !== "ticket" || !S.ticket || S.ticket.id !== id) return;
            S.ticketTeam = d.teamName;
            var banKey = JSON.stringify(S.ban || null);
            S.ban = d.ban || null;
            applyTicketMeta(d.ticket, d.online);
            if (banKey !== JSON.stringify(S.ban) && S.msgs.length) renderMessages();
            appendMessages(d.messages, true);
            applyChanges(d.changed);
            if (typeof d.rev === "number") S.rev = d.rev;
            setTyping(!!d.typing && d.ticket.status !== "closed");
        });
    }

    function openTicket(id) {
        S.view = "ticket";
        S.msgs = [];
        S.lastId = 0;
        S.rev = 0;
        S.editing = null;
        S.stash = "";
        S.newCount = 0;
        S.pending = [];
        clearInterval(S.stateTimer);
        stopTimers();
        setNavVisible(false);
        root.innerHTML = topHTML("") + '<div class="sup-sk" style="height:64px;margin:0 0 12px"></div><div class="sup-sk" style="height:300px"></div>';
        var go = function() {
            return api("GET", "/api/support/ticket?id=" + encodeURIComponent(id) + "&after=0").then(function(d) {
                if (!d.ok) {
                    toast(d.error);
                    renderHome();
                    return;
                }
                S.ticket = d.ticket;
                S.ticketTeam = d.teamName;
                S.ban = d.ban || null;
                root.innerHTML = ticketShell(d.ticket);
                var comp = document.getElementById("supComp");
                comp.setAttribute("data-closed", compState(d.ticket));
                comp.innerHTML = compHTML(d.ticket);
                fitChat();
                appendMessages(d.messages, false);
                S.rev = d.rev || 0;
                setTyping(!!d.typing);
                scrollEnd(false);
                var list = listEl();
                list.addEventListener("scroll", showToEnd, {
                    passive: true
                });
                S.pollTimer = setInterval(poll, 2500);
                loadState(true);
            });
        };
        return S.state ? go() : loadState(true).then(function() {
            if (!S.state) {
                toast("Нет связи с сервером");
                return renderHome();
            }
            return go();
        });
    }

    function sendReply() {
        var ta = document.getElementById("supMsg");
        if (S.editing) {
            saveEdit();
            return;
        }
        if (!ta || S.busy || !S.ticket) return;
        var text = ta.value.trim();
        if (!text && !S.pending.length) return;
        if (S.pending.some(function(p) {
                return p.busy;
            })) return;
        S.busy = true;
        updateSend();
        api("POST", "/api/support/ticket/reply", {
            id: S.ticket.id,
            text: text,
            files: S.pending.map(function(p) {
                return p.id;
            })
        }).then(function(d) {
            S.busy = false;
            if (!d.ok) {
                toast(d.error);
                if (d.banned) {
                    onBanned(d);
                    return;
                }
                if (/закрыт/.test(d.error || "")) poll();
                updateSend();
                return;
            }
            haptic("selection");
            ta.value = "";
            ta.style.height = "";
            S.pending = [];
            refreshPhotos("reply");
            applyTicketMeta(d.ticket);
            appendMessages(d.messages || [d.message], false);
            updateSend();
        });
    }

    function notifyTyping() {
        var now = Date.now();
        if (!S.ticket || S.ticket.status === "closed" || now - S.typingAt < 3000) return;
        S.typingAt = now;
        api("POST", "/api/support/typing", {
            id: S.ticket.id
        });
    }

    function lightbox(id) {
        var lb = document.createElement("div");
        lb.className = "sup-lb";
        lb.innerHTML = '<img alt="Фото"><button type="button" aria-label="Закрыть">' + ICONS.x + '</button>';
        var image = lb.querySelector('img');
        var blobUrl = supportBlobs.get(String(id));
        if (blobUrl) image.src = blobUrl;
        lb.addEventListener("click", function() {
            lb.remove();
        });
        document.body.appendChild(lb);
    }

    function ticketMenu() {
        var t = S.ticket;
        if (!t || t.status === "closed") return;
        var existing = document.getElementById("supMenu");
        if (existing) {
            existing.remove();
            return;
        }
        var m = document.createElement("div");
        m.id = "supMenu";
        m.style.cssText = "position:absolute;right:0;top:46px;z-index:5;min-width:210px;padding:8px;border-radius:18px;border:1px solid rgba(255,255,255,.1);background:rgba(16,16,22,.97);box-shadow:0 18px 50px rgba(0,0,0,.55)";
        m.innerHTML = '<button class="sup-btn danger wide" type="button" data-act="close" style="min-height:44px;font-size:13.5px">Закрыть тикет</button>';
        document.getElementById("supChat").appendChild(m);
    }

    function closeOwn() {
        var m = document.getElementById("supMenu");
        if (m) m.remove();
        if (!S.ticket) return;
        askConfirm({
            title: "Закрыть тикет?",
            text: "Если вопрос останется, вы сможете вернуться: достаточно написать в этот же тикет — переписка возобновится.",
            ok: "Закрыть тикет",
            cancel: "Отмена",
            danger: true,
            onOk: function() {
                api("POST", "/api/support/ticket/close", {
                    id: S.ticket.id
                }).then(function(d) {
                    if (!d.ok) {
                        toast(d.error);
                        return;
                    }
                    haptic("notification");
                    poll();
                });
            }
        });
    }

    function askConfirm(o) {
        var old = document.getElementById("supDlg");
        if (old) old.remove();
        var dlg = document.createElement("div");
        dlg.className = "sup-dlg";
        dlg.id = "supDlg";
        dlg.setAttribute("role", "dialog");
        dlg.setAttribute("aria-modal", "true");
        dlg.innerHTML = '<div class="sup-dlg-card"><div class="sup-dlg-ic ' + (o.danger ? "danger" : "") + '">' + (o.icon || ICONS.lock) + '</div><h3>' + esc(o.title) + '</h3><p>' + esc(o.text) + '</p><div class="sup-dlg-btns"><button class="sup-btn ' + (o.danger ? "danger" : "gold") + '" type="button" data-dlg="ok">' + esc(o.ok || "Да") + '</button><button class="sup-btn ghost" type="button" data-dlg="no">' + esc(o.cancel || "Отмена") + '</button></div></div>';
        var onKey = function(e) {
            if (e.key === "Escape") {
                e.preventDefault();
                done(false);
            }
        };
        var done = function(yes) {
            document.removeEventListener("keydown", onKey, true);
            dlg.remove();
            if (yes && o.onOk) o.onOk();
        };
        dlg.addEventListener("click", function(e) {
            var b = e.target.closest("[data-dlg]");
            if (b) done(b.getAttribute("data-dlg") === "ok");
            else if (e.target === dlg) done(false);
        });
        document.addEventListener("keydown", onKey, true);
        document.body.appendChild(dlg);
        haptic("selection");
    }

    root.addEventListener("click", function(e) {
        var el = e.target.closest("[data-act]");
        if (!el || !root.contains(el)) {
            var menu = document.getElementById("supMenu");
            if (menu && !e.target.closest("#supMenu")) menu.remove();
            return;
        }
        var act = el.dataset.act;
        if (act === "back") {
            stopTimers();
            clearInterval(S.stateTimer);
            if (typeof closeGame === "function") closeGame();
            return;
        }
        if (act === "home") {
            S.state = null;
            S.ticket = null;
            renderHome();
            return;
        }
        if (act === "new") {
            if (S.ban) {
                toast("Обращения в поддержку для вас заблокированы");
                return;
            }
            S.view = "create";
            if (!S.state) {
                loadState().then(function(d) {
                    if (d) renderCreate();
                });
            } else renderCreate();
            return;
        }
        if (act === "open") {
            openTicket(el.dataset.id);
            return;
        }
        if (act === "rules-modal") {
            haptic("selection");
            if (typeof openProjectRulesModal === "function") openProjectRulesModal();
            return;
        }
        if (act === "sched") {
            S.schedOpen = !S.schedOpen;
            el.classList.toggle("open", S.schedOpen);
            var sc = document.getElementById("supSched");
            if (sc) sc.classList.toggle("open", S.schedOpen);
            return;
        }
        if (act === "rules") {
            S.rulesOpen = !S.rulesOpen;
            el.closest(".sup-rules").classList.toggle("open", S.rulesOpen);
            return;
        }
        if (act === "faq") {
            var id = parseInt(el.dataset.id, 10);
            var q = el.closest(".sup-q");
            var willOpen = S.faqOpen !== id;
            root.querySelectorAll(".sup-q.open").forEach(function(n) {
                n.classList.remove("open");
            });
            S.faqOpen = willOpen ? id : null;
            if (willOpen) {
                q.classList.add("open");
                api("POST", "/api/support/faq/view", {
                    id: id
                });
            }
            haptic("selection");
            return;
        }
        if (act === "cat") {
            S.draft.category = el.dataset.key;
            root.querySelectorAll(".sup-chip").forEach(function(c) {
                c.classList.toggle("on", c === el);
            });
            haptic("selection");
            return;
        }
        if (act === "addphoto") {
            var f = document.getElementById("supFile");
            if (f) f.click();
            return;
        }
        if (act === "addreply") {
            var fr = document.getElementById("supFileR");
            if (fr) fr.click();
            return;
        }
        if (act === "rmphoto") {
            removePhoto(el.dataset.key, S.view === "ticket" ? "reply" : "create");
            return;
        }
        if (act === "submit") {
            submitTicket();
            return;
        }
        if (act === "send") {
            sendReply();
            return;
        }
        if (act === "zoom") {
            lightbox(el.dataset.t);
            return;
        }
        if (act === "toend") {
            S.newCount = 0;
            scrollEnd(true);
            return;
        }
        if (act === "menu") {
            ticketMenu();
            return;
        }
        if (act === "close") {
            closeOwn();
            return;
        }
        if (act === "copy") {
            copyMessage(el);
            return;
        }
        if (act === "edit") {
            startEdit(el.dataset.mid);
            return;
        }
        if (act === "del") {
            deleteMsg(el.dataset.mid);
            return;
        }
        if (act === "cancel-edit") {
            endEdit();
            return;
        }
    });

    root.addEventListener("input", function(e) {
        var t = e.target;
        if (t.id === "supSubj") {
            S.draft.subject = t.value;
            var n = document.getElementById("supSubjN");
            if (n) n.textContent = t.value.length + "/" + S.state.limits.subjectMax;
            updateSubmit();
        } else if (t.id === "supText") {
            S.draft.text = t.value;
            var n2 = document.getElementById("supTextN");
            if (n2) n2.textContent = t.value.length + "/" + S.state.limits.textMax;
            updateSubmit();
        } else if (t.id === "supFaqQ") {
            S.faqQ = t.value;
            var wrap = document.getElementById("supFaqList");
            if (wrap) {
                var tmp = document.createElement("div");
                tmp.innerHTML = faqHTML(S.state);
                var nl = tmp.querySelector("#supFaqList");
                wrap.innerHTML = nl ? nl.innerHTML : "";
                mountLotties();
            }
        } else if (t.id === "supMsg") {
            t.style.height = "auto";
            t.style.height = Math.min(132, t.scrollHeight) + "px";
            updateSend();
            if (t.value.trim() && !S.editing) notifyTyping();
        }
    });

    root.addEventListener("change", function(e) {
        var t = e.target;
        if (t.id === "supFile") {
            addFiles(t.files, "create");
            t.value = "";
        } else if (t.id === "supFileR") {
            addFiles(t.files, "reply");
            t.value = "";
        }
    });

    root.addEventListener("keydown", function(e) {
        if (e.target.id === "supMsg" && e.key === "Escape" && S.editing) {
            e.preventDefault();
            endEdit();
            return;
        }
        if (e.target.id === "supMsg" && e.key === "Enter" && !e.shiftKey && window.matchMedia && window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
            e.preventDefault();
            sendReply();
        }
    });

    document.addEventListener("visibilitychange", function() {
        if (!document.hidden && S.view === "ticket") poll();
    });
    window.addEventListener("resize", function() {
        if (S.view === "ticket") {
            fitChat();
            scrollEnd(false);
        }
    });
    if (window.visualViewport) window.visualViewport.addEventListener("resize", function() {
        if (S.view === "ticket") fitChat();
    });

    window.SUP = {
        open: function() {
            if (S.view === "ticket" && S.ticket) {
                setNavVisible(false);
                return;
            }
            S.state = null;
            renderHome();
        },
        openTicket: function(id) {
            S.state = null;
            return openTicket(String(id));
        },
        leave: function() {
            stopTimers();
            clearInterval(S.stateTimer);
            setNavVisible(true);
            S.view = "home";
            S.ticket = null;
        }
    };
})();