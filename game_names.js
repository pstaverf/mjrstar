(function() {
    if (window.GameNames) return;
    var map = {};
    var exactMap = {};
    var exactOn = false;
    var re = null;
    var started = false;
    var lastSig = null;
    var origText = new WeakMap();
    var origAttr = new WeakMap();
    var ATTRS = ["title", "alt", "aria-label", "placeholder"];
    var SKIP_TAGS = {
        SCRIPT: 1,
        STYLE: 1,
        TEXTAREA: 1,
        NOSCRIPT: 1
    };
    var DECO;
    try {
        DECO = new RegExp("^([^\\p{L}\\p{N}_]*)([\\s\\S]*?)([^\\p{L}\\p{N}_]*)$", "u");
    } catch (e) {
        DECO = /^([^A-Za-z0-9_\u0400-\u04FF]*)([\s\S]*?)([^A-Za-z0-9_\u0400-\u04FF]*)$/;
    }

    function escapeRe(s) {
        return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    function build(names) {
        var m = {};
        var ex = {};
        Object.keys(names || {}).forEach(function(id) {
            var item = names[id];
            if (!item || !item.to) return;
            (item.from || []).forEach(function(src) {
                if (src && src !== item.to)(item.exact ? ex : m)[src] = item.to;
            });
        });
        exactMap = ex;
        exactOn = Object.keys(ex).length > 0;
        var keys = Object.keys(m).sort(function(a, b) {
            return b.length - a.length;
        });
        map = m;
        if (!keys.length) {
            re = null;
            return;
        }
        var body = keys.map(escapeRe).join("|");
        try {
            re = new RegExp("(^|[^\\p{L}\\p{N}_])(" + body + ")(?![\\p{L}\\p{N}_])", "gu");
        } catch (e) {
            re = new RegExp("(^|[^A-Za-z0-9_\\u0400-\\u04FF])(" + body + ")(?![A-Za-z0-9_\\u0400-\\u04FF])", "g");
        }
    }

    function transform(text) {
        if ((!re && !exactOn) || !text) return text;
        var src = String(text);
        var out = src;
        if (re) {
            out = src.replace(re, function(all, pre, name) {
                return pre + (Object.prototype.hasOwnProperty.call(map, name) ? map[name] : name);
            });
        }
        if (out === src && exactOn) {
            var parts = DECO.exec(src);
            if (parts && Object.prototype.hasOwnProperty.call(exactMap, parts[2])) out = parts[1] + exactMap[parts[2]] + parts[3];
        }
        return out;
    }

    function skipNode(node) {
        var p = node.nodeType === 3 ? node.parentNode : node;
        while (p && p.nodeType === 1) {
            if (SKIP_TAGS[p.tagName] || p.hasAttribute("data-no-gn")) return true;
            p = p.parentNode;
        }
        return false;
    }

    function processText(node) {
        var rec = origText.get(node);
        var cur = node.nodeValue;
        var orig = rec && rec.out === cur ? rec.orig : cur;
        var out = transform(orig);
        if (out !== cur) node.nodeValue = out;
        if (out !== orig) origText.set(node, {
            orig: orig,
            out: out
        });
        else if (rec) origText.delete(node);
    }

    function processAttrs(el) {
        var rec = origAttr.get(el) || {};
        ATTRS.forEach(function(name) {
            var saved = rec[name];
            if (!el.hasAttribute(name)) {
                if (saved) delete rec[name];
                return;
            }
            var cur = el.getAttribute(name);
            var orig = saved && saved.out === cur ? saved.orig : cur;
            var out = transform(orig);
            if (out !== cur) el.setAttribute(name, out);
            if (out !== orig) rec[name] = {
                orig: orig,
                out: out
            };
            else if (saved) delete rec[name];
        });
        origAttr.set(el, rec);
    }

    function walk(root) {
        if (!root) return;
        if (root.nodeType === 3) {
            if (!skipNode(root)) processText(root);
            return;
        }
        if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
        var base = root.nodeType === 9 ? root.documentElement : root;
        if (!base) return;
        if (base.nodeType === 1) {
            if (skipNode(base)) return;
            processAttrs(base);
        }
        var walker = document.createTreeWalker(base, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
            acceptNode: function(node) {
                if (node.nodeType === 1 && (SKIP_TAGS[node.tagName] || node.hasAttribute("data-no-gn"))) return NodeFilter.FILTER_REJECT;
                return NodeFilter.FILTER_ACCEPT;
            }
        });
        var node;
        while ((node = walker.nextNode())) {
            if (node.nodeType === 3) processText(node);
            else processAttrs(node);
        }
    }

    function onMutations(list) {
        if (!re && !exactOn) return;
        for (var i = 0; i < list.length; i++) {
            var m = list[i];
            if (m.type === "childList") {
                for (var j = 0; j < m.addedNodes.length; j++) walk(m.addedNodes[j]);
            } else if (m.type === "characterData") {
                if (m.target.nodeType === 3 && !skipNode(m.target)) processText(m.target);
            } else if (m.type === "attributes") {
                if (!skipNode(m.target)) processAttrs(m.target);
            }
        }
    }

    function start() {
        if (started) return;
        if (!document.body) {
            document.addEventListener("DOMContentLoaded", start, {
                once: true
            });
            return;
        }
        started = true;
        walk(document);
        new MutationObserver(onMutations).observe(document.documentElement, {
            childList: true,
            subtree: true,
            characterData: true,
            attributes: true,
            attributeFilter: ATTRS
        });
    }

    function set(names) {
        var sig = JSON.stringify(names || {});
        if (sig === lastSig) return;
        lastSig = sig;
        build(names);
        if (started) walk(document);
    }

    window.GameNames = {
        set: set,
        start: start,
        transform: transform
    };
    set(window.__GN0__ || {});
    start();
})();