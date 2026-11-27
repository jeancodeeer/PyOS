// The DOM for SnakeyOS's browser: what page scripts see as `window` and
// `document`. It runs inside QuickJS (the kernel's _js module).
//
// The browser (browser/script.py) hands over the page's tree as JSON,
// runs the page's scripts, and when the scripts change the tree it takes
// it back (__dump) and lays the page out again. Things only the browser
// can do (the network, cookies, sizes on screen, saving localStorage) go
// through __py(name, json) -> json.
//
// Tree as JSON: an element is [id, tag, {attributes}, children...]; a text
// is a string. New nodes made by scripts get new ids.
(function () {
"use strict";
const G = globalThis;
// The engine's own promises, kept before any page script can replace Promise
// (polyfills do): the DOM's microtasks must not go through a page's version,
// whose then() may call queueMicrotask() again, endlessly.
const NativePromise = Promise;
const nativeThen = Promise.prototype.then;
const microtask = fn => { nativeThen.call(NativePromise.resolve(), fn); };
const call = (name, arg) => {
    const r = __py(name, arg === undefined ? "null" : JSON.stringify(arg));
    return r === undefined || r === "" ? undefined : JSON.parse(r);
};
let nextId = 1;
const byId = new Map();          // id -> node (elements only)
let dirty = false;               // the tree changed since the last __dump
const touch = () => { dirty = true; };

// ---------------------------------------------------------------- events

class Event {
    constructor(type, init) {
        init = init || {};
        this.type = String(type);
        this.bubbles = !!init.bubbles;
        this.cancelable = !!init.cancelable;
        this.composed = !!init.composed;
        this.defaultPrevented = false;
        this.target = this.currentTarget = null;
        this.eventPhase = 0;
        this.timeStamp = Date.now();
        this.isTrusted = false;
        this._stop = this._stopNow = false;
    }
    preventDefault() { if (this.cancelable) this.defaultPrevented = true; }
    stopPropagation() { this._stop = true; }
    stopImmediatePropagation() { this._stop = this._stopNow = true; }
    composedPath() { const p = []; for (let n = this.target; n; n = n.parentNode) p.push(n); p.push(G); return p; }
    get returnValue() { return !this.defaultPrevented; }
    set returnValue(v) { if (!v) this.preventDefault(); }
    get srcElement() { return this.target; }
}
Event.NONE = 0; Event.CAPTURING_PHASE = 1; Event.AT_TARGET = 2; Event.BUBBLING_PHASE = 3;
class CustomEvent extends Event {
    constructor(type, init) { super(type, init); this.detail = init && init.detail !== undefined ? init.detail : null; }
}
class UIEvent extends Event { constructor(t, i) { super(t, i); this.view = G; this.detail = (i && i.detail) || 0; } }
class MouseEvent extends UIEvent {
    constructor(t, i) {
        super(t, i); i = i || {};
        for (const k of ["clientX", "clientY", "screenX", "screenY", "pageX", "pageY", "button", "buttons"]) this[k] = i[k] || 0;
        for (const k of ["ctrlKey", "shiftKey", "altKey", "metaKey"]) this[k] = !!i[k];
        this.relatedTarget = i.relatedTarget || null;
    }
}
class PointerEvent extends MouseEvent { constructor(t, i) { super(t, i); this.pointerId = 1; this.pointerType = "mouse"; } }
class KeyboardEvent extends UIEvent {
    constructor(t, i) {
        super(t, i); i = i || {};
        this.key = i.key || ""; this.code = i.code || ""; this.keyCode = this.which = i.keyCode || 0;
        for (const k of ["ctrlKey", "shiftKey", "altKey", "metaKey", "repeat"]) this[k] = !!i[k];
    }
}
class FocusEvent extends UIEvent {}
class InputEvent extends UIEvent { constructor(t, i) { super(t, i); this.data = (i && i.data) || null; this.inputType = (i && i.inputType) || ""; } }
class SubmitEvent extends Event { constructor(t, i) { super(t, i); this.submitter = (i && i.submitter) || null; } }
class ErrorEvent extends Event { constructor(t, i) { super(t, i); this.message = (i && i.message) || ""; this.error = (i && i.error) || null; } }
class MessageEvent extends Event { constructor(t, i) { super(t, i); this.data = i ? i.data : undefined; this.origin = ""; } }
class ProgressEvent extends Event { constructor(t, i) { super(t, i); this.loaded = (i && i.loaded) || 0; this.total = (i && i.total) || 0; this.lengthComputable = false; } }
class PopStateEvent extends Event { constructor(t, i) { super(t, i); this.state = i ? i.state : null; } }

class EventTarget {
    constructor() { this._listeners = null; }
    addEventListener(type, fn, opts) {
        if (!fn) return;
        const capture = typeof opts === "boolean" ? opts : !!(opts && opts.capture);
        const once = !!(opts && typeof opts === "object" && opts.once);
        if (opts && typeof opts === "object" && opts.signal) opts.signal.addEventListener("abort", () => this.removeEventListener(type, fn, capture));
        const L = this._listeners || (this._listeners = {});
        const list = L[type] || (L[type] = []);
        if (!list.some(l => l.fn === fn && l.capture === capture)) list.push({ fn, capture, once });
    }
    removeEventListener(type, fn, opts) {
        const capture = typeof opts === "boolean" ? opts : !!(opts && opts.capture);
        const list = this._listeners && this._listeners[type];
        if (list) this._listeners[type] = list.filter(l => !(l.fn === fn && l.capture === capture));
    }
    _fire(ev, capturePhase) {
        const list = this._listeners && this._listeners[ev.type];
        const prop = this["on" + ev.type];
        ev.currentTarget = this;
        if (list) {
            for (const l of list.slice()) {
                if (ev.eventPhase !== 2 && l.capture !== capturePhase) continue;
                if (l.once) this.removeEventListener(ev.type, l.fn, l.capture);
                try {
                    if (typeof l.fn === "function") l.fn.call(this, ev); else if (l.fn && l.fn.handleEvent) l.fn.handleEvent(ev);
                } catch (e) { reportError(e); }
                if (ev._stopNow) return;
            }
        }
        if (typeof prop === "function" && !capturePhase) {
            try { if (prop.call(this, ev) === false) ev.preventDefault(); } catch (e) { reportError(e); }
        }
    }
    dispatchEvent(ev) {
        ev.target = this;
        const path = [];
        for (let n = this.parentNode; n; n = n.parentNode) path.push(n);
        if (this.nodeType && this.isConnected) path.push(G);
        ev.eventPhase = 1;
        for (let i = path.length - 1; i >= 0 && !ev._stop; i--) path[i]._fire(ev, true);
        ev.eventPhase = 2;
        if (!ev._stop) this._fire(ev, false);
        ev.eventPhase = 3;
        if (ev.bubbles) for (let i = 0; i < path.length && !ev._stop; i++) path[i]._fire(ev, false);
        ev.eventPhase = 0;
        ev.currentTarget = null;
        return !ev.defaultPrevented;
    }
}

function reportError(e) {
    try { call("error", String(e && e.stack ? e + "\n" + e.stack : e)); } catch (x) {}
}

// ---------------------------------------------------------------- nodes

class Node extends EventTarget {
    constructor(type, name) {
        super();
        this.nodeType = type;
        this.nodeName = name;
        this.parentNode = null;
        this.childNodes = [];
    }
    get ownerDocument() { return this === document ? null : document; }
    get parentElement() { const p = this.parentNode; return p && p.nodeType === 1 ? p : null; }
    get firstChild() { return this.childNodes[0] || null; }
    get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
    get previousSibling() { const p = this.parentNode; if (!p) return null; const i = p.childNodes.indexOf(this); return p.childNodes[i - 1] || null; }
    get nextSibling() { const p = this.parentNode; if (!p) return null; const i = p.childNodes.indexOf(this); return p.childNodes[i + 1] || null; }
    get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n === document; }
    hasChildNodes() { return this.childNodes.length > 0; }
    getRootNode() { let n = this; while (n.parentNode) n = n.parentNode; return n; }
    contains(o) { for (let n = o; n; n = n.parentNode) if (n === this) return true; return false; }
    get textContent() {
        if (this.nodeType === 3 || this.nodeType === 8) return this.data;
        let s = "";
        for (const c of this.childNodes) if (c.nodeType !== 8) s += c.textContent;
        return s;
    }
    set textContent(v) {
        for (const c of this.childNodes) c.parentNode = null;
        this.childNodes = [];
        if (v !== null && v !== undefined && v !== "") this.appendChild(document.createTextNode(String(v)));
        touch();
    }
    get nodeValue() { return this.nodeType === 3 || this.nodeType === 8 ? this.data : null; }
    set nodeValue(v) { if (this.nodeType === 3 || this.nodeType === 8) { this.data = String(v); touch(); } }
    _adopt(node) {
        if (node.nodeType === 11) {                     // a fragment: its children move in
            const kids = node.childNodes.slice();
            node.childNodes = [];
            for (const k of kids) k.parentNode = null;
            return kids;
        }
        if (node.parentNode) node.parentNode.removeChild(node);
        return [node];
    }
    insertBefore(node, ref) {
        if (!node) throw new TypeError("insertBefore: no node");
        const kids = this._adopt(node);
        let i = ref ? this.childNodes.indexOf(ref) : this.childNodes.length;
        if (i < 0) i = this.childNodes.length;
        for (const k of kids) {
            k.parentNode = this;
            this.childNodes.splice(i++, 0, k);
            if (k.isConnected) connected(k);
        }
        touch();
        queueMutation(this, "childList", kids, []);
        return node;
    }
    appendChild(node) { return this.insertBefore(node, null); }
    removeChild(node) {
        const i = this.childNodes.indexOf(node);
        if (i < 0) throw new Error("removeChild: not a child");
        this.childNodes.splice(i, 1);
        node.parentNode = null;
        touch();
        queueMutation(this, "childList", [], [node]);
        return node;
    }
    replaceChild(node, old) { this.insertBefore(node, old); return this.removeChild(old); }
    remove() { if (this.parentNode) this.parentNode.removeChild(this); }
    _nodes(args) { return args.map(a => typeof a === "string" ? document.createTextNode(a) : a); }
    before(...a) { const p = this.parentNode; if (p) for (const n of this._nodes(a)) p.insertBefore(n, this); }
    after(...a) { const p = this.parentNode; if (!p) return; let ref = this.nextSibling; for (const n of this._nodes(a)) p.insertBefore(n, ref); }
    replaceWith(...a) { const p = this.parentNode; if (!p) return; this.before(...a); this.remove(); }
    append(...a) { for (const n of this._nodes(a)) this.appendChild(n); }
    prepend(...a) { const first = this.firstChild; for (const n of this._nodes(a)) this.insertBefore(n, first); }
    replaceChildren(...a) { this.textContent = ""; this.append(...a); }
    cloneNode(deep) {
        let c;
        if (this.nodeType === 3) c = document.createTextNode(this.data);
        else if (this.nodeType === 8) c = document.createComment(this.data);
        else if (this.nodeType === 11) c = document.createDocumentFragment();
        else {
            c = document.createElementNS(this.namespaceURI, this.tagName.toLowerCase());
            c._attrs = Object.assign({}, this._attrs);
            if (this._value !== undefined) c._value = this._value;
        }
        if (deep) for (const k of this.childNodes) c.appendChild(k.cloneNode(true));
        return c;
    }
    isEqualNode(o) { return !!o && o.nodeType === this.nodeType && serialize(this) === serialize(o); }
    isSameNode(o) { return o === this; }
    compareDocumentPosition(o) {
        if (o === this) return 0;
        if (this.contains(o)) return 20;
        if (o.contains(this)) return 10;
        const all = allNodes(document);
        return all.indexOf(o) > all.indexOf(this) ? 4 : 2;
    }
    normalize() {}
    // children and searching (elements, documents, fragments)
    get children() { return this.childNodes.filter(c => c.nodeType === 1); }
    get childElementCount() { return this.children.length; }
    get firstElementChild() { return this.children[0] || null; }
    get lastElementChild() { const c = this.children; return c[c.length - 1] || null; }
    querySelector(sel) { return qsa(this, sel, true)[0] || null; }
    querySelectorAll(sel) { return toNodeList(qsa(this, sel, false)); }
    getElementsByTagName(t) {
        t = t.toLowerCase();
        return toNodeList(descendants(this).filter(e => t === "*" || e.localName === t));
    }
    getElementsByClassName(names) {
        const want = String(names).split(/\s+/).filter(Boolean);
        return toNodeList(descendants(this).filter(e => want.every(c => e.classList.contains(c))));
    }
    getElementById(id) { return descendants(this).find(e => e._attrs.id === id) || null; }
}
Node.ELEMENT_NODE = 1; Node.TEXT_NODE = 3; Node.COMMENT_NODE = 8; Node.DOCUMENT_NODE = 9; Node.DOCUMENT_FRAGMENT_NODE = 11;
Node.DOCUMENT_POSITION_PRECEDING = 2; Node.DOCUMENT_POSITION_FOLLOWING = 4; Node.DOCUMENT_POSITION_CONTAINS = 8; Node.DOCUMENT_POSITION_CONTAINED_BY = 16;

function toNodeList(arr) {
    arr.item = i => arr[i] || null;
    return arr;
}
function descendants(root) {
    const out = [];
    const walk = n => { for (const c of n.childNodes) if (c.nodeType === 1) { out.push(c); walk(c); } };
    walk(root);
    if (root._shadow) walk(root._shadow);
    return out;
}
function allNodes(root) {
    const out = [];
    const walk = n => { out.push(n); for (const c of n.childNodes) walk(c); };
    walk(root);
    return out;
}

class CharacterData extends Node {
    constructor(type, name, data) { super(type, name); this._data = String(data); }
    get data() { return this._data; }
    set data(v) { this._data = String(v); touch(); queueMutation(this, "characterData", [], []); }
    get length() { return this._data.length; }
    appendData(s) { this.data += s; }
    get wholeText() { return this._data; }
}
class Text extends CharacterData { constructor(d) { super(3, "#text", d === undefined ? "" : d); } splitText(o) { const t = new Text(this._data.slice(o)); this.data = this._data.slice(0, o); this.after(t); return t; } }
class Comment extends CharacterData { constructor(d) { super(8, "#comment", d === undefined ? "" : d); } }
class DocumentFragment extends Node { constructor() { super(11, "#document-fragment"); } get innerHTML() { return this.childNodes.map(serialize).join(""); } }
class ShadowRoot extends DocumentFragment { constructor(host) { super(); this.host = host; this.mode = "open"; } get innerHTML() { return super.innerHTML; } set innerHTML(v) { setHTML(this, v); } }

// ---- class names, data-*, inline style ----

class DOMTokenList {
    constructor(el, attr) { this._el = el; this._attr = attr; }
    _get() { return (this._el._attrs[this._attr] || "").split(/\s+/).filter(Boolean); }
    _set(list) { this._el.setAttribute(this._attr, list.join(" ")); }
    get length() { return this._get().length; }
    get value() { return this._el._attrs[this._attr] || ""; }
    item(i) { return this._get()[i] || null; }
    contains(c) { return this._get().includes(c); }
    add(...cs) { const l = this._get(); let ch = false; for (const c of cs) if (!l.includes(c)) { l.push(c); ch = true; } if (ch || !(this._attr in this._el._attrs)) this._set(l); }
    remove(...cs) { const l = this._get(); const k = l.filter(c => !cs.includes(c)); if (k.length !== l.length) this._set(k); }
    toggle(c, force) {
        const has = this.contains(c);
        if (force === true || (force === undefined && !has)) { if (!has) this.add(c); return true; }
        if (has) this.remove(c);
        return false;
    }
    replace(a, b) { const l = this._get(); const i = l.indexOf(a); if (i < 0) return false; l[i] = b; this._set(l); return true; }
    supports() { return true; }
    forEach(fn, t) { this._get().forEach(fn, t); }
    [Symbol.iterator]() { return this._get()[Symbol.iterator](); }
    toString() { return this.value; }
}

const camel = s => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
const kebab = s => s.replace(/[A-Z]/g, c => "-" + c.toLowerCase());
function parseStyle(text) {
    const out = {};
    for (const part of String(text || "").split(";")) {
        const i = part.indexOf(":");
        if (i > 0) out[part.slice(0, i).trim().toLowerCase()] = part.slice(i + 1).trim();
    }
    return out;
}
function styleObject(el) {
    const read = () => parseStyle(el._attrs.style);
    const write = map => el.setAttribute("style", Object.keys(map).map(k => k + ": " + map[k]).join("; "));
    const api = {
        getPropertyValue: n => read()[n] || "",
        setProperty: (n, v, prio) => { const m = read(); if (v === null || v === "") delete m[n]; else m[n] = String(v) + (prio ? " !important" : ""); write(m); },
        removeProperty: n => { const m = read(); const v = m[n] || ""; delete m[n]; write(m); return v; },
        getPropertyPriority: () => "",
        item: i => Object.keys(read())[i] || "",
    };
    return new Proxy(api, {
        get(t, k) {
            if (k in t) return t[k];
            if (k === "cssText") return el._attrs.style || "";
            if (k === "length") return Object.keys(read()).length;
            if (typeof k !== "string") return undefined;
            const name = k.startsWith("--") ? k : kebab(k);
            return read()[name] || "";
        },
        set(t, k, v) {
            if (k === "cssText") { el.setAttribute("style", String(v)); return true; }
            const name = String(k).startsWith("--") ? k : kebab(String(k));
            api.setProperty(name, v === null || v === undefined ? "" : String(v));
            return true;
        },
    });
}

// ---- elements ----

const VOID = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);
const SVG_NS = "http://www.w3.org/2000/svg", HTML_NS = "http://www.w3.org/1999/xhtml";

class Element extends Node {
    constructor(tag, ns) {
        super(1, "");
        this.localName = String(tag).toLowerCase();
        this.namespaceURI = ns || HTML_NS;
        this.nodeName = this.tagName = this.namespaceURI === HTML_NS ? this.localName.toUpperCase() : String(tag);
        this._attrs = {};
        this._id = nextId++;
        byId.set(this._id, this);
    }
    get attributes() {
        const list = Object.keys(this._attrs).map(k => ({ name: k, localName: k, value: this._attrs[k], nodeName: k, nodeValue: this._attrs[k] }));
        list.getNamedItem = n => list.find(a => a.name === n) || null;
        list.item = i => list[i] || null;
        return list;
    }
    getAttribute(n) { n = String(n).toLowerCase(); return n in this._attrs ? this._attrs[n] : null; }
    getAttributeNS(ns, n) { return this.getAttribute(n); }
    setAttribute(n, v) {
        n = String(n).toLowerCase();
        const old = this.getAttribute(n);
        this._attrs[n] = String(v);
        touch();
        queueMutation(this, "attributes", [], [], n, old);
        if (n === "value" && this._value === undefined) {}
    }
    setAttributeNS(ns, n, v) { this.setAttribute(n.replace(/^.*:/, ""), v); }
    removeAttribute(n) {
        n = String(n).toLowerCase();
        if (n in this._attrs) { const old = this._attrs[n]; delete this._attrs[n]; touch(); queueMutation(this, "attributes", [], [], n, old); }
    }
    removeAttributeNS(ns, n) { this.removeAttribute(n); }
    hasAttribute(n) { return String(n).toLowerCase() in this._attrs; }
    hasAttributes() { return Object.keys(this._attrs).length > 0; }
    getAttributeNames() { return Object.keys(this._attrs); }
    toggleAttribute(n, force) {
        const has = this.hasAttribute(n);
        if (force === true || (force === undefined && !has)) { this.setAttribute(n, ""); return true; }
        this.removeAttribute(n); return false;
    }
    get id() { return this._attrs.id || ""; }
    set id(v) { this.setAttribute("id", v); }
    get className() { return this._attrs["class"] || ""; }
    set className(v) { this.setAttribute("class", v); }
    get classList() { return this._cl || (this._cl = new DOMTokenList(this, "class")); }
    get style() { return this._st || (this._st = styleObject(this)); }
    set style(v) { this.setAttribute("style", v); }
    get dataset() {
        const el = this;
        return new Proxy({}, {
            get(t, k) { return typeof k === "string" ? el.getAttribute("data-" + kebab(k)) ?? undefined : undefined; },
            set(t, k, v) { el.setAttribute("data-" + kebab(String(k)), v); return true; },
            deleteProperty(t, k) { el.removeAttribute("data-" + kebab(String(k))); return true; },
            has(t, k) { return el.hasAttribute("data-" + kebab(String(k))); },
            ownKeys() { return Object.keys(el._attrs).filter(a => a.startsWith("data-")).map(a => camel(a.slice(5))); },
            getOwnPropertyDescriptor(t, k) { return { enumerable: true, configurable: true, value: el.getAttribute("data-" + kebab(String(k))) }; },
        });
    }
    get innerHTML() { return this.childNodes.map(serialize).join(""); }
    set innerHTML(v) { setHTML(this, v); }
    get outerHTML() { return serialize(this); }
    set outerHTML(v) {
        const f = document.createElement("template");
        f.innerHTML = v;
        this.replaceWith(...f.content.childNodes.slice());
    }
    get innerText() { return this.textContent; }
    set innerText(v) { this.textContent = v; }
    get outerText() { return this.textContent; }
    insertAdjacentHTML(where, html) {
        const t = document.createElement("template");
        t.innerHTML = html;
        this._insertAt(where, t.content);
    }
    insertAdjacentElement(where, el) { this._insertAt(where, el); return el; }
    insertAdjacentText(where, text) { this._insertAt(where, document.createTextNode(text)); }
    _insertAt(where, node) {
        where = String(where).toLowerCase();
        if (where === "beforebegin") this.parentNode && this.parentNode.insertBefore(node, this);
        else if (where === "afterbegin") this.insertBefore(node, this.firstChild);
        else if (where === "beforeend") this.appendChild(node);
        else if (where === "afterend") this.parentNode && this.parentNode.insertBefore(node, this.nextSibling);
    }
    matches(sel) { return matchesSelector(this, sel); }
    webkitMatchesSelector(sel) { return this.matches(sel); }
    closest(sel) { for (let n = this; n && n.nodeType === 1; n = n.parentNode) if (n.matches(sel)) return n; return null; }
    get previousElementSibling() { for (let n = this.previousSibling; n; n = n.previousSibling) if (n.nodeType === 1) return n; return null; }
    get nextElementSibling() { for (let n = this.nextSibling; n; n = n.nextSibling) if (n.nodeType === 1) return n; return null; }
    // sizes come from the browser's layout
    getBoundingClientRect() {
        const r = call("rect", this._id) || [0, 0, 0, 0];
        const [x, y, w, h] = r;
        return { x, y, width: w, height: h, left: x, top: y, right: x + w, bottom: y + h, toJSON() { return this; } };
    }
    getClientRects() { const r = this.getBoundingClientRect(); return r.width || r.height ? [r] : []; }
    get offsetWidth() { return this.getBoundingClientRect().width; }
    get offsetHeight() { return this.getBoundingClientRect().height; }
    get offsetTop() { return this.getBoundingClientRect().top; }
    get offsetLeft() { return this.getBoundingClientRect().left; }
    get offsetParent() { return this.parentElement; }
    get clientWidth() { return this.offsetWidth; }
    get clientHeight() { return this.offsetHeight; }
    get scrollWidth() { return this.offsetWidth; }
    get scrollHeight() { return this.offsetHeight; }
    get clientTop() { return 0; }
    get clientLeft() { return 0; }
    scrollTop = 0;
    scrollLeft = 0;
    scrollIntoView() { call("scroll_to", this._id); }
    scrollTo() {}
    scrollBy() {}
    scroll() {}
    focus() { document.activeElement = this; this.dispatchEvent(new FocusEvent("focus")); this.dispatchEvent(new FocusEvent("focusin", { bubbles: true })); }
    blur() { if (document.activeElement === this) document.activeElement = document.body; this.dispatchEvent(new FocusEvent("blur")); }
    click() { this.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })); }
    attachShadow(init) { this._shadow = new ShadowRoot(this); this._shadow.mode = (init && init.mode) || "open"; this._shadow.parentNode = null; return this._shadow; }
    get shadowRoot() { return this._shadow && this._shadow.mode === "open" ? this._shadow : null; }
    animate() { return { finished: Promise.resolve(), cancel() {}, play() {}, pause() {}, onfinish: null, addEventListener() {} }; }
    getAnimations() { return []; }
    requestFullscreen() { return Promise.resolve(); }
    setPointerCapture() {}
    releasePointerCapture() {}
    hasPointerCapture() { return false; }
}

// attributes that are also properties (el.href, el.src, el.disabled...)
function reflect(cls, names, bool) {
    for (const n of names) {
        const attr = n.toLowerCase();
        Object.defineProperty(cls.prototype, n, bool ? {
            get() { return this.hasAttribute(attr); },
            set(v) { this.toggleAttribute(attr, !!v); },
            configurable: true,
        } : {
            get() { return this.getAttribute(attr) ?? ""; },
            set(v) { this.setAttribute(attr, v); },
            configurable: true,
        });
    }
}
class HTMLElement extends Element {}
reflect(HTMLElement, ["title", "lang", "dir", "accessKey", "role"]);
reflect(HTMLElement, ["hidden", "inert", "draggable"], true);
Object.defineProperty(HTMLElement.prototype, "tabIndex", { get() { return +(this.getAttribute("tabindex") || -1); }, set(v) { this.setAttribute("tabindex", v); } });
Object.defineProperty(HTMLElement.prototype, "contentEditable", { get() { return this.getAttribute("contenteditable") || "inherit"; }, set(v) { this.setAttribute("contenteditable", v); } });
Object.defineProperty(HTMLElement.prototype, "isContentEditable", { get() { return this.getAttribute("contenteditable") === "true"; } });

const urlProp = (cls, names) => {
    for (const n of names) Object.defineProperty(cls.prototype, n, {
        get() { const v = this.getAttribute(n.toLowerCase()); return v === null ? "" : resolveURL(v); },
        set(v) { this.setAttribute(n.toLowerCase(), v); },
        configurable: true,
    });
};
class HTMLAnchorElement extends HTMLElement {
    get pathname() { return new URL(this.href || location.href).pathname; }
    get hostname() { return new URL(this.href || location.href).hostname; }
    get host() { return new URL(this.href || location.href).host; }
    get protocol() { return new URL(this.href || location.href).protocol; }
    get search() { return new URL(this.href || location.href).search; }
    get hash() { return new URL(this.href || location.href).hash; }
    get origin() { return new URL(this.href || location.href).origin; }
    toString() { return this.href; }
}
urlProp(HTMLAnchorElement, ["href"]);
reflect(HTMLAnchorElement, ["target", "rel", "download", "type", "hreflang"]);
class HTMLAreaElement extends HTMLAnchorElement {}
class HTMLImageElement extends HTMLElement {
    get complete() { return true; }
    get naturalWidth() { return +(this.getAttribute("width") || 0); }
    get naturalHeight() { return +(this.getAttribute("height") || 0); }
    get width() { return +(this.getAttribute("width") || 0); }
    set width(v) { this.setAttribute("width", v); }
    get height() { return +(this.getAttribute("height") || 0); }
    set height(v) { this.setAttribute("height", v); }
    get currentSrc() { return this.src; }
    decode() { return Promise.resolve(); }
}
urlProp(HTMLImageElement, ["src"]);
reflect(HTMLImageElement, ["alt", "srcset", "sizes", "loading", "decoding", "crossOrigin"]);
class HTMLScriptElement extends HTMLElement {
    get text() { return this.textContent; }
    set text(v) { this.textContent = v; }
}
urlProp(HTMLScriptElement, ["src"]);
reflect(HTMLScriptElement, ["type", "charset", "crossOrigin", "integrity", "nonce"]);
reflect(HTMLScriptElement, ["async", "defer", "noModule"], true);
class HTMLLinkElement extends HTMLElement { get sheet() { return null; } }
urlProp(HTMLLinkElement, ["href"]);
reflect(HTMLLinkElement, ["rel", "type", "media", "as", "crossOrigin"]);
class HTMLStyleElement extends HTMLElement { get sheet() { return { cssRules: [], insertRule() { return 0; }, deleteRule() {} }; } }
class HTMLIFrameElement extends HTMLElement { get contentWindow() { return null; } get contentDocument() { return null; } }
urlProp(HTMLIFrameElement, ["src"]);
class HTMLTemplateElement extends HTMLElement {
    get content() {
        if (!this._content) { this._content = new DocumentFragment(); }
        return this._content;
    }
    get innerHTML() { return this.content.innerHTML; }
    set innerHTML(v) { const f = this.content; f.childNodes = []; setHTML(f, v); }
}
class HTMLFormElement extends HTMLElement {
    get elements() { return toNodeList(descendants(this).filter(e => ["input", "select", "textarea", "button"].includes(e.localName))); }
    get length() { return this.elements.length; }
    submit() { call("submit", this._id); }
    requestSubmit(btn) { const ev = new SubmitEvent("submit", { bubbles: true, cancelable: true, submitter: btn }); if (this.dispatchEvent(ev)) this.submit(); }
    reset() { for (const e of this.elements) if (e._value !== undefined) { e._value = undefined; touch(); } }
    checkValidity() { return true; }
    reportValidity() { return true; }
}
urlProp(HTMLFormElement, ["action"]);
reflect(HTMLFormElement, ["method", "target", "enctype", "name"]);
reflect(HTMLFormElement, ["noValidate"], true);
class HTMLInputElement extends HTMLElement {
    get value() { return this._value !== undefined ? this._value : (this.getAttribute("value") ?? (this.type === "checkbox" || this.type === "radio" ? "on" : "")); }
    set value(v) { this._value = String(v); touch(); }
    get defaultValue() { return this.getAttribute("value") ?? ""; }
    set defaultValue(v) { this.setAttribute("value", v); }
    get checked() { return this._checked !== undefined ? this._checked : this.hasAttribute("checked"); }
    set checked(v) { this._checked = !!v; touch(); }
    get type() { return (this.getAttribute("type") || "text").toLowerCase(); }
    set type(v) { this.setAttribute("type", v); }
    get form() { return this.closest("form"); }
    get valueAsNumber() { return parseFloat(this.value); }
    get files() { return []; }
    select() {}
    setSelectionRange() {}
    checkValidity() { return true; }
    reportValidity() { return true; }
    setCustomValidity() {}
    get validity() { return { valid: true }; }
    get labels() { return []; }
}
reflect(HTMLInputElement, ["name", "placeholder", "autocomplete", "min", "max", "step", "pattern", "accept", "inputMode"]);
reflect(HTMLInputElement, ["disabled", "readOnly", "required", "multiple", "autofocus"], true);
class HTMLTextAreaElement extends HTMLInputElement {
    get value() { return this._value !== undefined ? this._value : this.textContent; }
    set value(v) { this._value = String(v); touch(); }
    get type() { return "textarea"; }
}
class HTMLButtonElement extends HTMLElement {
    get type() { return (this.getAttribute("type") || "submit").toLowerCase(); }
    set type(v) { this.setAttribute("type", v); }
    get form() { return this.closest("form"); }
    get value() { return this.getAttribute("value") ?? ""; }
    set value(v) { this.setAttribute("value", v); }
}
reflect(HTMLButtonElement, ["name"]);
reflect(HTMLButtonElement, ["disabled"], true);
class HTMLSelectElement extends HTMLElement {
    get options() { return toNodeList(descendants(this).filter(e => e.localName === "option")); }
    get selectedIndex() { const o = this.options; const i = o.findIndex(x => x.selected); return i < 0 ? (o.length ? 0 : -1) : i; }
    set selectedIndex(i) { this.options.forEach((o, k) => o.selected = k === i); }
    get value() { const o = this.options[this.selectedIndex]; return o ? o.value : ""; }
    set value(v) { this.options.forEach(o => o.selected = o.value === String(v)); }
    get type() { return this.multiple ? "select-multiple" : "select-one"; }
    get length() { return this.options.length; }
    get form() { return this.closest("form"); }
    add(o, before) { this.insertBefore(o, before || null); }
}
reflect(HTMLSelectElement, ["name"]);
reflect(HTMLSelectElement, ["disabled", "multiple", "required"], true);
class HTMLOptionElement extends HTMLElement {
    get value() { return this.getAttribute("value") ?? this.textContent; }
    set value(v) { this.setAttribute("value", v); }
    get text() { return this.textContent; }
    set text(v) { this.textContent = v; }
    get selected() { return this._sel !== undefined ? this._sel : this.hasAttribute("selected"); }
    set selected(v) { this._sel = !!v; if (v) this.setAttribute("selected", ""); else this.removeAttribute("selected"); }
}
reflect(HTMLOptionElement, ["label"]);
reflect(HTMLOptionElement, ["disabled"], true);
class HTMLLabelElement extends HTMLElement { get htmlFor() { return this.getAttribute("for") || ""; } set htmlFor(v) { this.setAttribute("for", v); } get control() { return document.getElementById(this.htmlFor); } }
class HTMLDetailsElement extends HTMLElement {}
reflect(HTMLDetailsElement, ["open"], true);
class HTMLDialogElement extends HTMLElement {
    show() { this.setAttribute("open", ""); }
    showModal() { this.setAttribute("open", ""); }
    close(v) { this.removeAttribute("open"); this.returnValue = v || ""; this.dispatchEvent(new Event("close")); }
}
reflect(HTMLDialogElement, ["open"], true);
class HTMLMediaElement extends HTMLElement {
    play() { return Promise.resolve(); }
    pause() {}
    load() {}
    canPlayType() { return ""; }
    get paused() { return true; }
}
urlProp(HTMLMediaElement, ["src"]);
reflect(HTMLMediaElement, ["autoplay", "controls", "loop", "muted", "playsInline"], true);
class HTMLVideoElement extends HTMLMediaElement {}
class HTMLAudioElement extends HTMLMediaElement {}
class HTMLCanvasElement extends HTMLElement {
    getContext() { return null; }                 // no canvas drawing (yet)
    toDataURL() { return "data:,"; }
    get width() { return +(this.getAttribute("width") || 300); }
    set width(v) { this.setAttribute("width", v); }
    get height() { return +(this.getAttribute("height") || 150); }
    set height(v) { this.setAttribute("height", v); }
}
class HTMLMetaElement extends HTMLElement {}
reflect(HTMLMetaElement, ["name", "content", "httpEquiv", "charset"]);
class HTMLTableElement extends HTMLElement { get rows() { return toNodeList(descendants(this).filter(e => e.localName === "tr")); } get tBodies() { return toNodeList(this.children.filter(e => e.localName === "tbody")); } }
class HTMLTableRowElement extends HTMLElement { get cells() { return toNodeList(this.children.filter(e => e.localName === "td" || e.localName === "th")); } }
class SVGElement extends Element { get ownerSVGElement() { return this.closest("svg"); } get style() { return super.style; } }

const CLASSES = {
    a: HTMLAnchorElement, area: HTMLAreaElement, img: HTMLImageElement, script: HTMLScriptElement, link: HTMLLinkElement,
    style: HTMLStyleElement, iframe: HTMLIFrameElement, template: HTMLTemplateElement, form: HTMLFormElement,
    input: HTMLInputElement, textarea: HTMLTextAreaElement, button: HTMLButtonElement, select: HTMLSelectElement,
    option: HTMLOptionElement, label: HTMLLabelElement, details: HTMLDetailsElement, dialog: HTMLDialogElement,
    video: HTMLVideoElement, audio: HTMLAudioElement, canvas: HTMLCanvasElement, meta: HTMLMetaElement,
    table: HTMLTableElement, tr: HTMLTableRowElement,
};
const SIMPLE = {};
for (const [tag, name] of [["div", "Div"], ["span", "Span"], ["p", "Paragraph"], ["ul", "UList"], ["ol", "OList"], ["li", "LI"],
                           ["h1", "Heading"], ["body", "Body"], ["head", "Head"], ["html", "Html"], ["br", "BR"], ["hr", "HR"],
                           ["pre", "Pre"], ["title", "Title"], ["td", "TableCell"], ["th", "TableCell"], ["tbody", "TableSection"],
                           ["source", "Source"], ["picture", "Picture"], ["slot", "Slot"]]) {
    const cls = SIMPLE[name] || (SIMPLE[name] = ({ [name]: class extends HTMLElement {} })[name]);
    Object.defineProperty(cls, "name", { value: "HTML" + name + "Element" });
    G["HTML" + name + "Element"] = cls;
    CLASSES[tag] = cls;
}
for (const t of ["h2", "h3", "h4", "h5", "h6"]) CLASSES[t] = CLASSES.h1;

function makeElement(tag, ns) {
    tag = String(tag);
    const low = tag.toLowerCase();
    if (ns === SVG_NS || (!ns && (low === "svg" || low === "path"))) return new SVGElement(tag, SVG_NS);
    const custom = customElements._defs.get(low);
    if (custom) {
        try { const el = Reflect.construct(custom, [], custom); el.__init(low); return el; } catch (e) { reportError(e); }
    }
    const cls = CLASSES[low] || HTMLElement;
    return new cls(low, HTML_NS);
}
HTMLElement.prototype.__init = function (tag) {
    this.localName = tag; this.nodeName = this.tagName = tag.toUpperCase();
};

// ---------------------------------------------------------------- HTML in and out

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
const RAW = new Set(["script", "style"]);
function serialize(n) {
    if (n.nodeType === 3) return n.parentNode && RAW.has(n.parentNode.localName) ? n.data : n.data.replace(/[&<>]/g, c => ESC[c]);
    if (n.nodeType === 8) return "<!--" + n.data + "-->";
    if (n.nodeType === 11) return n.childNodes.map(serialize).join("");
    let s = "<" + n.localName;
    for (const k in n._attrs) s += " " + k + '="' + String(n._attrs[k]).replace(/[&<>"]/g, c => ESC[c]) + '"';
    s += ">";
    if (VOID.has(n.localName)) return s;
    const kids = n.localName === "template" ? n.content.childNodes : n.childNodes;
    return s + kids.map(serialize).join("") + "</" + n.localName + ">";
}
// The browser parses (its HTML parser is in Python) and hands back JSON
function build(j) {
    if (typeof j === "string") return new Text(j);
    const [, tag, attrs, ...kids] = j;
    const el = makeElement(tag);
    el._attrs = attrs || {};
    const target = el.localName === "template" ? el.content : el;
    for (const k of kids) { const c = build(k); c.parentNode = target; target.childNodes.push(c); }
    return el;
}
function setHTML(el, html) {
    for (const c of el.childNodes) c.parentNode = null;
    el.childNodes = [];
    const parts = call("parse", String(html)) || [];
    for (const p of parts) el.appendChild(build(p));
    touch();
}

// ---------------------------------------------------------------- CSS selectors

const selCache = new Map();
function parseSelector(sel) {
    let r = selCache.get(sel);
    if (r) return r;
    r = [];
    for (const one of splitTop(sel, ",")) {
        const s = one.trim();
        if (!s) continue;
        const parts = [];                     // [compound, combinator to the left]
        let i = 0, comb = null;
        while (i < s.length) {
            while (i < s.length && /\s/.test(s[i])) { i++; if (comb === null && parts.length) comb = " "; }
            if (i >= s.length) break;
            if (">+~".includes(s[i])) { comb = s[i]; i++; continue; }
            let j = i, depth = 0, quote = null;
            while (j < s.length) {
                const c = s[j];
                if (quote) { if (c === quote) quote = null; }
                else if (c === '"' || c === "'") quote = c;
                else if (c === "(" || c === "[") depth++;
                else if (c === ")" || c === "]") depth--;
                else if (c === "\\") { j += 2; continue; }
                else if (depth === 0 && (/\s/.test(c) || ">+~".includes(c))) break;
                j++;
            }
            parts.push([compound(s.slice(i, j)), parts.length ? (comb || " ") : null]);
            comb = null;
            i = j;
        }
        r.push(parts);
    }
    selCache.set(sel, r);
    return r;
}
function splitTop(s, sep) {
    const out = []; let cur = "", depth = 0, quote = null;
    for (const c of s) {
        if (quote) { if (c === quote) quote = null; }
        else if (c === '"' || c === "'") quote = c;
        else if (c === "(" || c === "[") depth++;
        else if (c === ")" || c === "]") depth--;
        else if (c === sep && depth === 0) { out.push(cur); cur = ""; continue; }
        cur += c;
    }
    out.push(cur);
    return out;
}
function compound(s) {
    const c = { tag: null, id: null, classes: [], attrs: [], pseudos: [] };
    let i = 0;
    const name = () => { let n = ""; while (i < s.length && !".#[:".includes(s[i])) { if (s[i] === "\\") { n += s[i + 1]; i += 2; } else n += s[i++]; } return n; };
    if (i < s.length && !".#[:".includes(s[i])) { const t = name().toLowerCase(); c.tag = t === "*" ? null : t; }
    while (i < s.length) {
        const ch = s[i++];
        if (ch === ".") c.classes.push(name());
        else if (ch === "#") c.id = name();
        else if (ch === "[") {
            let j = i, quote = null;
            while (j < s.length && (quote || s[j] !== "]")) { if (quote) { if (s[j] === quote) quote = null; } else if (s[j] === '"' || s[j] === "'") quote = s[j]; j++; }
            const body = s.slice(i, j); i = j + 1;
            const m = body.match(/^\s*([^~|^$*=\s]+)\s*(?:([~|^$*]?=)\s*(?:"([^"]*)"|'([^']*)'|([^\s\]]*)))?\s*(i)?\s*$/);
            if (m) c.attrs.push([m[1].toLowerCase(), m[2] || null, m[3] ?? m[4] ?? m[5] ?? null, !!m[6]]);
        } else if (ch === ":") {
            if (s[i] === ":") i++;
            let n = ""; while (i < s.length && /[\w-]/.test(s[i])) n += s[i++];
            let arg = null;
            if (s[i] === "(") {
                let depth = 1, j = i + 1;
                while (j < s.length && depth) { if (s[j] === "(") depth++; else if (s[j] === ")") depth--; j++; }
                arg = s.slice(i + 1, j - 1); i = j;
            }
            c.pseudos.push([n.toLowerCase(), arg]);
        }
    }
    return c;
}
function nth(arg, k) {
    arg = arg.replace(/\s+/g, "").toLowerCase();
    if (arg === "odd") return k % 2 === 1;
    if (arg === "even") return k % 2 === 0;
    const m = arg.match(/^([+-]?\d*)n([+-]\d+)?$/);
    if (!m) return k === parseInt(arg, 10);
    const a = m[1] === "" || m[1] === "+" ? 1 : m[1] === "-" ? -1 : parseInt(m[1], 10);
    const b = m[2] ? parseInt(m[2], 10) : 0;
    return a === 0 ? k === b : (k - b) / a >= 0 && (k - b) % a === 0;
}
function matchCompound(el, c, scope) {
    if (el.nodeType !== 1) return false;
    if (c.tag && el.localName !== c.tag) return false;
    if (c.id !== null && el._attrs.id !== c.id) return false;
    if (c.classes.length) { const mine = (el._attrs["class"] || "").split(/\s+/); for (const k of c.classes) if (!mine.includes(k)) return false; }
    for (const [n, op, v0, ci] of c.attrs) {
        let have = el._attrs[n];
        if (have === undefined) return false;
        if (!op) continue;
        let v = v0;
        if (ci) { have = have.toLowerCase(); v = v.toLowerCase(); }
        if (op === "=" && have !== v) return false;
        if (op === "~=" && !have.split(/\s+/).includes(v)) return false;
        if (op === "^=" && !(v && have.startsWith(v))) return false;
        if (op === "$=" && !(v && have.endsWith(v))) return false;
        if (op === "*=" && !(v && have.includes(v))) return false;
        if (op === "|=" && !(have === v || have.startsWith(v + "-"))) return false;
    }
    for (const [p, arg] of c.pseudos) {
        const parent = el.parentNode;
        const sibs = parent ? parent.childNodes.filter(x => x.nodeType === 1) : [el];
        const same = sibs.filter(x => x.localName === el.localName);
        switch (p) {
            case "not": if (matchesSelector(el, arg, scope)) return false; break;
            case "is": case "where": case "matches": case "-webkit-any": if (!matchesSelector(el, arg, scope)) return false; break;
            case "has": if (!qsa(el, arg.trim().replace(/^>/, ":scope >"), true, el).length) return false; break;
            case "first-child": if (sibs[0] !== el) return false; break;
            case "last-child": if (sibs[sibs.length - 1] !== el) return false; break;
            case "only-child": if (sibs.length !== 1) return false; break;
            case "first-of-type": if (same[0] !== el) return false; break;
            case "last-of-type": if (same[same.length - 1] !== el) return false; break;
            case "only-of-type": if (same.length !== 1) return false; break;
            case "nth-child": if (!nth(arg.split(/\s+of\s+/)[0], sibs.indexOf(el) + 1)) return false; break;
            case "nth-last-child": if (!nth(arg, sibs.length - sibs.indexOf(el))) return false; break;
            case "nth-of-type": if (!nth(arg, same.indexOf(el) + 1)) return false; break;
            case "nth-last-of-type": if (!nth(arg, same.length - same.indexOf(el))) return false; break;
            case "empty": if (el.childNodes.some(x => x.nodeType === 1 || (x.nodeType === 3 && x.data))) return false; break;
            case "root": if (el !== document.documentElement) return false; break;
            case "scope": if (el !== (scope || document.documentElement)) return false; break;
            case "checked": if (!(el.checked || el.selected)) return false; break;
            case "disabled": if (!el.hasAttribute("disabled")) return false; break;
            case "enabled": if (el.hasAttribute("disabled")) return false; break;
            case "required": if (!el.hasAttribute("required")) return false; break;
            case "optional": if (el.hasAttribute("required")) return false; break;
            case "link": case "any-link": if (!(el.localName === "a" && el.hasAttribute("href"))) return false; break;
            case "defined": break;
            case "focus": case "focus-within": case "focus-visible": if (document.activeElement !== el) return false; break;
            case "hover": case "active": case "visited": case "target": case "placeholder-shown": case "invalid": return false;
            case "valid": break;
            case "before": case "after": case "first-line": case "first-letter": case "placeholder": case "selection": case "marker": return false;
            default: return false;
        }
    }
    return true;
}
function matchParts(el, parts, k, scope) {
    if (!matchCompound(el, parts[k][0], scope)) return false;
    if (k === 0) return true;
    const comb = parts[k][1];
    if (comb === ">") return !!el.parentNode && matchParts(el.parentNode, parts, k - 1, scope);
    if (comb === " ") { for (let a = el.parentNode; a && a.nodeType === 1; a = a.parentNode) if (matchParts(a, parts, k - 1, scope)) return true; return false; }
    const sibs = el.parentNode ? el.parentNode.childNodes.filter(x => x.nodeType === 1) : [];
    const i = sibs.indexOf(el);
    if (comb === "+") return i > 0 && matchParts(sibs[i - 1], parts, k - 1, scope);
    if (comb === "~") { for (let j = i - 1; j >= 0; j--) if (matchParts(sibs[j], parts, k - 1, scope)) return true; return false; }
    return false;
}
function matchesSelector(el, sel, scope) {
    let list;
    try { list = parseSelector(String(sel)); } catch (e) { throw new SyntaxError("bad selector: " + sel); }
    return list.some(parts => parts.length && matchParts(el, parts, parts.length - 1, scope));
}
function qsa(root, sel, first, scope) {
    const out = [];
    const list = parseSelector(String(sel));
    const sc = scope || (root.nodeType === 1 ? root : null);
    for (const el of descendants(root)) {
        if (list.some(parts => parts.length && matchParts(el, parts, parts.length - 1, sc))) {
            out.push(el);
            if (first) break;
        }
    }
    return out;
}

// ---------------------------------------------------------------- the document

class Document extends Node {
    constructor() {
        super(9, "#document");
        this.readyState = "loading";
        this.activeElement = null;
        this.currentScript = null;
        this.visibilityState = "visible";
        this.hidden = false;
        this.characterSet = "UTF-8";
        this.compatMode = "CSS1Compat";
        this.contentType = "text/html";
        this.designMode = "off";
        this.fonts = { ready: Promise.resolve(), load: () => Promise.resolve([]), check: () => true, add() {}, forEach() {} };
        this.implementation = { createHTMLDocument: t => { const d = new Document(); d.appendChild(build([0, "html", {}, [0, "head", {}], [0, "body", {}]])); return d; }, hasFeature: () => true };
    }
    get documentElement() { return this.children[0] || null; }
    get head() { const h = this.documentElement; return h ? h.children.find(e => e.localName === "head") || null : null; }
    get body() { const h = this.documentElement; return h ? h.children.find(e => e.localName === "body") || null : null; }
    get title() { const t = this.querySelector("title"); return t ? t.textContent.trim() : ""; }
    set title(v) { let t = this.querySelector("title"); if (!t) { t = this.createElement("title"); this.head && this.head.appendChild(t); } t.textContent = v; }
    get cookie() { return call("cookie_get") || ""; }
    set cookie(v) { call("cookie_set", String(v)); }
    get URL() { return location.href; }
    get documentURI() { return location.href; }
    get baseURI() { const b = this.querySelector("base[href]"); return b ? resolveURL(b.getAttribute("href")) : location.href; }
    get referrer() { return ""; }
    get domain() { return location.hostname; }
    get defaultView() { return G; }
    get location() { return G.location; }
    set location(v) { G.location.href = v; }
    get forms() { return this.getElementsByTagName("form"); }
    get images() { return this.getElementsByTagName("img"); }
    get links() { return toNodeList(descendants(this).filter(e => (e.localName === "a" || e.localName === "area") && e.hasAttribute("href"))); }
    get scripts() { return this.getElementsByTagName("script"); }
    get scrollingElement() { return this.documentElement; }
    createElement(t) { return makeElement(t); }
    createElementNS(ns, t) { return makeElement(t, ns); }
    createTextNode(d) { return new Text(d); }
    createComment(d) { return new Comment(d); }
    createDocumentFragment() { return new DocumentFragment(); }
    createEvent(kind) { const e = new Event(""); e.initEvent = (t, b, c) => { e.type = t; e.bubbles = !!b; e.cancelable = !!c; }; e.initCustomEvent = (t, b, c, d) => { e.initEvent(t, b, c); e.detail = d; }; return e; }
    createRange() { return { setStart() {}, setEnd() {}, selectNodeContents() {}, collapse() {}, getBoundingClientRect: () => ({ x: 0, y: 0, width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0 }), createContextualFragment: h => { const t = this.createElement("template"); t.innerHTML = h; return t.content; } }; }
    createTreeWalker(root, what, filter) {
        const all = allNodes(root).slice(1).filter(n => (!what || what === 0xFFFFFFFF) || ((what & 1) && n.nodeType === 1) || ((what & 4) && n.nodeType === 3));
        let i = -1;
        return { root, currentNode: root, nextNode() { i++; this.currentNode = all[i] || null; return this.currentNode; } };
    }
    createNodeIterator(root, what) { return this.createTreeWalker(root, what); }
    importNode(n, deep) { return n.cloneNode(deep); }
    adoptNode(n) { if (n.parentNode) n.remove(); return n; }
    hasFocus() { return true; }
    getSelection() { return G.getSelection(); }
    execCommand() { return false; }
    elementFromPoint() { return this.body; }
    elementsFromPoint() { return [this.body]; }
    open() {}
    close() {}
    write(...s) { call("document_write", s.join("")); }
    writeln(...s) { this.write(...s, "\n"); }
    get styleSheets() { return []; }
    get adoptedStyleSheets() { return []; }
    set adoptedStyleSheets(v) {}
    startViewTransition(fn) { if (fn) fn(); return { finished: Promise.resolve(), ready: Promise.resolve(), updateCallbackDone: Promise.resolve() }; }
}
const document = new Document();

// scripts that are put into the page run, as in a browser
function connected(node) {
    if (node.nodeType !== 1) return;
    const list = node.localName === "script" ? [node] : node.getElementsByTagName("script");
    for (const s of list) {
        if (s._ran) continue;
        s._ran = true;
        const type = (s.getAttribute("type") || "").toLowerCase();
        if (type && !/^(text|application)\/(java|ecma)script$|^module$/.test(type)) continue;
        if (s.hasAttribute("nomodule")) continue;            // old browsers only
        if (s.hasAttribute("src")) {
            const src = s.src;
            setTimeout(() => {
                const code = call("load_script", src);
                if (typeof code === "string") runScript(code, src, s);
                s.dispatchEvent(new Event(typeof code === "string" ? "load" : "error"));
            }, 0);
        } else {
            runScript(s.textContent, "inline", s);
        }
    }
}
function runScript(code, name, el) {
    const before = document.currentScript;
    document.currentScript = el || null;
    try { (0, eval)(code); } catch (e) { reportError(e); }
    document.currentScript = before;
}

// ---------------------------------------------------------------- mutation observers

const observers = [];
let pendingRecords = false;
function queueMutation(target, type, added, removed, attributeName, oldValue) {
    if (!observers.length) return;
    for (const o of observers) {
        for (const [node, opts] of o._targets) {
            const inside = node === target || (opts.subtree && node.contains(target));
            if (!inside) continue;
            if (type === "childList" && !opts.childList) continue;
            if (type === "attributes" && !(opts.attributes || opts.attributeFilter) ) continue;
            if (type === "attributes" && opts.attributeFilter && !opts.attributeFilter.includes(attributeName)) continue;
            if (type === "characterData" && !opts.characterData) continue;
            o._records.push({ type, target, addedNodes: added, removedNodes: removed, attributeName: attributeName || null,
                              oldValue: opts.attributeOldValue || opts.characterDataOldValue ? oldValue : null,
                              previousSibling: null, nextSibling: null });
            break;
        }
    }
    if (!pendingRecords) {
        pendingRecords = true;
        microtask(() => {
            pendingRecords = false;
            for (const o of observers) if (o._records.length) { const r = o._records; o._records = []; try { o._fn(r, o); } catch (e) { reportError(e); } }
        });
    }
}
class MutationObserver {
    constructor(fn) { this._fn = fn; this._targets = []; this._records = []; }
    observe(node, opts) { this._targets.push([node, opts || {}]); if (!observers.includes(this)) observers.push(this); }
    disconnect() { this._targets = []; const i = observers.indexOf(this); if (i >= 0) observers.splice(i, 1); }
    takeRecords() { const r = this._records; this._records = []; return r; }
}
// Everything is "in view": lazy loaders show their content straight away.
class IntersectionObserver {
    constructor(fn, opts) { this._fn = fn; this.root = (opts && opts.root) || null; this.rootMargin = "0px"; this.thresholds = [0]; }
    observe(el) {
        setTimeout(() => {
            const r = el.getBoundingClientRect();
            try { this._fn([{ target: el, isIntersecting: true, intersectionRatio: 1, boundingClientRect: r, intersectionRect: r, rootBounds: null, time: performance.now() }], this); } catch (e) { reportError(e); }
        }, 0);
    }
    unobserve() {}
    disconnect() {}
    takeRecords() { return []; }
}
class ResizeObserver {
    constructor(fn) { this._fn = fn; }
    observe(el) {
        setTimeout(() => {
            const r = el.getBoundingClientRect();
            try { this._fn([{ target: el, contentRect: r, borderBoxSize: [{ inlineSize: r.width, blockSize: r.height }], contentBoxSize: [{ inlineSize: r.width, blockSize: r.height }] }], this); } catch (e) { reportError(e); }
        }, 0);
    }
    unobserve() {}
    disconnect() {}
}

// ---------------------------------------------------------------- timers

let timerId = 0;
const timers = new Map();
let rafs = [];
function setTimeout_(fn, ms, ...args) {
    const id = ++timerId;
    timers.set(id, { fn, at: performance.now() + Math.max(0, +ms || 0), args, every: 0 });
    return id;
}
function setInterval_(fn, ms, ...args) {
    const id = ++timerId;
    const every = Math.max(10, +ms || 0);
    timers.set(id, { fn, at: performance.now() + every, args, every });
    return id;
}
const clearTimer = id => { timers.delete(id); };
// The browser calls this several times a second: due timers and animation frames run.
function tick(limit) {
    const now = performance.now();
    let ran = 0;
    const due = [...timers.entries()].filter(([, t]) => t.at <= now).sort((a, b) => a[1].at - b[1].at);
    for (const [id, t] of due) {
        if (!timers.has(id)) continue;
        if (t.every) t.at = now + t.every; else timers.delete(id);
        try { if (typeof t.fn === "function") t.fn(...t.args); else (0, eval)(String(t.fn)); } catch (e) { reportError(e); }
        if (++ran >= (limit || 200)) break;
    }
    if (rafs.length) {
        const list = rafs; rafs = [];
        for (const [, fn] of list) { try { fn(now); } catch (e) { reportError(e); } }
    }
    return ran;
}

// ---------------------------------------------------------------- network

class Headers {
    constructor(init) {
        this._h = {};
        if (init instanceof Headers) init = init._h;
        if (Array.isArray(init)) for (const [k, v] of init) this.append(k, v);
        else if (init) for (const k in init) this.append(k, init[k]);
    }
    append(k, v) { k = k.toLowerCase(); this._h[k] = k in this._h ? this._h[k] + ", " + v : String(v); }
    set(k, v) { this._h[k.toLowerCase()] = String(v); }
    get(k) { k = k.toLowerCase(); return k in this._h ? this._h[k] : null; }
    has(k) { return k.toLowerCase() in this._h; }
    delete(k) { delete this._h[k.toLowerCase()]; }
    forEach(fn) { for (const k in this._h) fn(this._h[k], k, this); }
    entries() { return Object.entries(this._h)[Symbol.iterator](); }
    keys() { return Object.keys(this._h)[Symbol.iterator](); }
    values() { return Object.values(this._h)[Symbol.iterator](); }
    [Symbol.iterator]() { return this.entries(); }
}
class Response {
    constructor(body, init) {
        init = init || {};
        this._body = body === undefined || body === null ? "" : String(body);
        this.status = init.status === undefined ? 200 : init.status;
        this.statusText = init.statusText || "";
        this.headers = new Headers(init.headers);
        this.url = init.url || "";
        this.redirected = false;
        this.type = "basic";
        this.bodyUsed = false;
    }
    get ok() { return this.status >= 200 && this.status < 300; }
    text() { this.bodyUsed = true; return Promise.resolve(this._body); }
    json() { this.bodyUsed = true; return new Promise((ok, no) => { try { ok(JSON.parse(this._body)); } catch (e) { no(e); } }); }
    arrayBuffer() { return Promise.resolve(new TextEncoder().encode(this._body).buffer); }
    blob() { return Promise.resolve(new Blob([this._body], { type: this.headers.get("content-type") || "" })); }
    clone() { return new Response(this._body, this); }
    static json(data, init) { return new Response(JSON.stringify(data), init); }
}
class Request {
    constructor(url, init) {
        init = init || {};
        if (url instanceof Request) { init = Object.assign({}, url, init); url = url.url; }
        this.url = resolveURL(String(url));
        this.method = (init.method || "GET").toUpperCase();
        this.headers = new Headers(init.headers);
        this.body = init.body === undefined ? null : init.body;
        this.signal = init.signal || null;
    }
}
function bodyText(b) {
    if (b === null || b === undefined) return null;
    if (typeof b === "string") return b;
    if (b instanceof URLSearchParams) return b.toString();
    if (b instanceof FormData) return b._entries.map(([k, v]) => encodeURIComponent(k) + "=" + encodeURIComponent(v)).join("&");
    if (b instanceof Blob) return b._text;
    if (ArrayBuffer.isView(b) || b instanceof ArrayBuffer) return new TextDecoder().decode(b);
    return String(b);
}
function fetch_(input, init) {
    const req = new Request(input, init);
    return new Promise((ok, no) => {
        if (req.signal && req.signal.aborted) return no(new DOMException("aborted", "AbortError"));
        setTimeout_(() => {
            const r = call("fetch", { url: req.url, method: req.method, headers: req.headers._h, body: bodyText(req.body) });
            if (!r || r.error) return no(new TypeError("Failed to fetch: " + (r ? r.error : req.url)));
            ok(new Response(r.body, { status: r.status, headers: r.headers, url: r.url }));
        }, 0);
    });
}
class XMLHttpRequest extends EventTarget {
    constructor() { super(); this.readyState = 0; this.status = 0; this.responseText = ""; this.response = ""; this.responseType = ""; this._h = {}; this.timeout = 0; this.withCredentials = false; this.upload = new EventTarget(); }
    open(method, url, async) { this._m = String(method).toUpperCase(); this._u = resolveURL(String(url)); this.readyState = 1; }
    setRequestHeader(k, v) { this._h[k.toLowerCase()] = v; }
    getResponseHeader(k) { return this._rh ? this._rh[k.toLowerCase()] ?? null : null; }
    getAllResponseHeaders() { return this._rh ? Object.entries(this._rh).map(([k, v]) => k + ": " + v).join("\r\n") : ""; }
    overrideMimeType() {}
    abort() { this._aborted = true; }
    send(body) {
        setTimeout_(() => {
            if (this._aborted) return;
            const r = call("fetch", { url: this._u, method: this._m, headers: this._h, body: bodyText(body) });
            if (!r || r.error) { this.readyState = 4; this.dispatchEvent(new ProgressEvent("error")); this.dispatchEvent(new ProgressEvent("loadend")); return; }
            this.status = r.status; this.statusText = ""; this._rh = r.headers || {}; this.responseURL = r.url;
            this.responseText = r.body;
            this.response = this.responseType === "json" ? (() => { try { return JSON.parse(r.body); } catch (e) { return null; } })() : r.body;
            this.readyState = 4;
            this.dispatchEvent(new Event("readystatechange"));
            this.dispatchEvent(new ProgressEvent("load"));
            this.dispatchEvent(new ProgressEvent("loadend"));
        }, 0);
    }
}
XMLHttpRequest.UNSENT = 0; XMLHttpRequest.OPENED = 1; XMLHttpRequest.HEADERS_RECEIVED = 2; XMLHttpRequest.LOADING = 3; XMLHttpRequest.DONE = 4;

class AbortSignal extends EventTarget {
    constructor() { super(); this.aborted = false; this.reason = undefined; }
    throwIfAborted() { if (this.aborted) throw this.reason; }
    static timeout(ms) { const c = new AbortController(); setTimeout_(() => c.abort(), ms); return c.signal; }
    static abort(r) { const c = new AbortController(); c.abort(r); return c.signal; }
    static any(list) { const c = new AbortController(); for (const s of list) s.addEventListener("abort", () => c.abort()); return c.signal; }
}
class AbortController {
    constructor() { this.signal = new AbortSignal(); }
    abort(reason) { if (this.signal.aborted) return; this.signal.aborted = true; this.signal.reason = reason || new DOMException("aborted", "AbortError"); this.signal.dispatchEvent(new Event("abort")); }
}
class DOMException extends Error { constructor(msg, name) { super(msg); this.name = name || "Error"; } }

// WebSocket / EventSource: not available, but they fail politely
class WebSocket extends EventTarget {
    constructor(url) { super(); this.url = url; this.readyState = 3; setTimeout_(() => { this.dispatchEvent(new Event("error")); this.dispatchEvent(new Event("close")); }, 0); }
    send() {}
    close() {}
}
class EventSource extends WebSocket {}

// ---------------------------------------------------------------- URL

function resolveURL(u) { return call("resolve", String(u)) || String(u); }
class URLSearchParams {
    constructor(init) {
        this._p = [];
        if (typeof init === "string") {
            for (const part of init.replace(/^\?/, "").split("&")) if (part) {
                const i = part.indexOf("=");
                const dec = s => decodeURIComponent(s.replace(/\+/g, " "));
                this._p.push(i < 0 ? [dec(part), ""] : [dec(part.slice(0, i)), dec(part.slice(i + 1))]);
            }
        } else if (Array.isArray(init)) this._p = init.map(([k, v]) => [String(k), String(v)]);
        else if (init && typeof init === "object") for (const k in init) this._p.push([k, String(init[k])]);
    }
    append(k, v) { this._p.push([String(k), String(v)]); this._changed && this._changed(); }
    set(k, v) { const i = this._p.findIndex(p => p[0] === k); if (i < 0) this._p.push([k, String(v)]); else { this._p[i][1] = String(v); this._p = this._p.filter((p, j) => p[0] !== k || j === i); } this._changed && this._changed(); }
    get(k) { const p = this._p.find(p => p[0] === k); return p ? p[1] : null; }
    getAll(k) { return this._p.filter(p => p[0] === k).map(p => p[1]); }
    has(k) { return this._p.some(p => p[0] === k); }
    delete(k) { this._p = this._p.filter(p => p[0] !== k); this._changed && this._changed(); }
    sort() { this._p.sort((a, b) => a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0); }
    forEach(fn) { for (const [k, v] of this._p) fn(v, k, this); }
    entries() { return this._p.map(p => [p[0], p[1]])[Symbol.iterator](); }
    keys() { return this._p.map(p => p[0])[Symbol.iterator](); }
    values() { return this._p.map(p => p[1])[Symbol.iterator](); }
    get size() { return this._p.length; }
    [Symbol.iterator]() { return this.entries(); }
    toString() { return this._p.map(([k, v]) => encodeURIComponent(k).replace(/%20/g, "+") + "=" + encodeURIComponent(v).replace(/%20/g, "+")).join("&"); }
}
class URL {
    constructor(url, base) {
        const parts = call("url_parse", { url: String(url), base: base === undefined ? null : String(base) });
        if (!parts) throw new TypeError("Invalid URL: " + url);
        Object.assign(this, parts);
        this._sp = null;
    }
    get searchParams() {
        if (!this._sp) { this._sp = new URLSearchParams(this.search); this._sp._changed = () => { const s = this._sp.toString(); this.search = s ? "?" + s : ""; }; }
        return this._sp;
    }
    get host() { return this.hostname + (this.port ? ":" + this.port : ""); }
    get origin() { return this.protocol + "//" + this.host; }
    get href() { return this.protocol + "//" + (this.username ? this.username + "@" : "") + this.host + this.pathname + this.search + this.hash; }
    set href(v) { Object.assign(this, new URL(v)); }
    toString() { return this.href; }
    toJSON() { return this.href; }
    static canParse(u, b) { try { new URL(u, b); return true; } catch (e) { return false; } }
    static createObjectURL() { return "blob:pyos/" + Math.random().toString(36).slice(2); }
    static revokeObjectURL() {}
}

// ---------------------------------------------------------------- text, data, random

class TextEncoder {
    get encoding() { return "utf-8"; }
    encode(s) {
        s = String(s === undefined ? "" : s);
        const out = [];
        for (let i = 0; i < s.length; i++) {
            let c = s.codePointAt(i);
            if (c > 0xffff) i++;
            if (c < 0x80) out.push(c);
            else if (c < 0x800) out.push(0xc0 | c >> 6, 0x80 | c & 63);
            else if (c < 0x10000) out.push(0xe0 | c >> 12, 0x80 | c >> 6 & 63, 0x80 | c & 63);
            else out.push(0xf0 | c >> 18, 0x80 | c >> 12 & 63, 0x80 | c >> 6 & 63, 0x80 | c & 63);
        }
        return new Uint8Array(out);
    }
}
class TextDecoder {
    constructor(enc) { this.encoding = enc || "utf-8"; }
    decode(b) {
        if (!b) return "";
        const a = b instanceof ArrayBuffer ? new Uint8Array(b) : new Uint8Array(b.buffer || b, b.byteOffset || 0, b.byteLength);
        let s = "";
        for (let i = 0; i < a.length;) {
            const c = a[i];
            let cp, n;
            if (c < 0x80) { cp = c; n = 1; }
            else if (c >> 5 === 6) { cp = (c & 31) << 6 | a[i + 1] & 63; n = 2; }
            else if (c >> 4 === 14) { cp = (c & 15) << 12 | (a[i + 1] & 63) << 6 | a[i + 2] & 63; n = 3; }
            else { cp = (c & 7) << 18 | (a[i + 1] & 63) << 12 | (a[i + 2] & 63) << 6 | a[i + 3] & 63; n = 4; }
            s += String.fromCodePoint(cp);
            i += n;
        }
        return s;
    }
}
const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
function btoa(s) {
    s = String(s); let out = "";
    for (let i = 0; i < s.length; i += 3) {
        const a = s.charCodeAt(i), b = s.charCodeAt(i + 1), c = s.charCodeAt(i + 2);
        if (a > 255 || b > 255 || c > 255) throw new DOMException("not Latin-1", "InvalidCharacterError");
        out += B64[a >> 2] + B64[(a & 3) << 4 | (b || 0) >> 4] + (isNaN(b) ? "=" : B64[(b & 15) << 2 | (c || 0) >> 6]) + (isNaN(c) ? "=" : B64[c & 63]);
    }
    return out;
}
function atob(s) {
    s = String(s).replace(/[\s=]/g, ""); let out = "", bits = 0, n = 0;
    for (const ch of s) { const v = B64.indexOf(ch); if (v < 0) throw new DOMException("bad base64", "InvalidCharacterError"); bits = bits << 6 | v; n += 6; if (n >= 8) { n -= 8; out += String.fromCharCode(bits >> n & 255); } }
    return out;
}
class Blob {
    constructor(parts, opts) { this._text = (parts || []).map(p => p instanceof Blob ? p._text : typeof p === "string" ? p : new TextDecoder().decode(p)).join(""); this.type = (opts && opts.type) || ""; }
    get size() { return this._text.length; }
    text() { return Promise.resolve(this._text); }
    arrayBuffer() { return Promise.resolve(new TextEncoder().encode(this._text).buffer); }
    slice(a, b) { return new Blob([this._text.slice(a, b)], { type: this.type }); }
}
class File extends Blob { constructor(parts, name, opts) { super(parts, opts); this.name = name; this.lastModified = Date.now(); } }
class FormData {
    constructor(form) {
        this._entries = [];
        if (form && form.elements) for (const e of form.elements) {
            if (!e.name || e.disabled) continue;
            if ((e.type === "checkbox" || e.type === "radio") && !e.checked) continue;
            if (e.localName === "button") continue;
            this._entries.push([e.name, e.value]);
        }
    }
    append(k, v) { this._entries.push([String(k), v instanceof Blob ? v : String(v)]); }
    set(k, v) { this.delete(k); this.append(k, v); }
    get(k) { const e = this._entries.find(e => e[0] === k); return e ? e[1] : null; }
    getAll(k) { return this._entries.filter(e => e[0] === k).map(e => e[1]); }
    has(k) { return this._entries.some(e => e[0] === k); }
    delete(k) { this._entries = this._entries.filter(e => e[0] !== k); }
    forEach(fn) { for (const [k, v] of this._entries) fn(v, k, this); }
    entries() { return this._entries[Symbol.iterator](); }
    [Symbol.iterator]() { return this.entries(); }
}
const cryptoObj = {
    getRandomValues(a) { for (let i = 0; i < a.length; i++) a[i] = Math.floor(Math.random() * 4294967296); return a; },
    randomUUID() { const h = [...Array(32)].map(() => (Math.random() * 16 | 0).toString(16)).join(""); return h.slice(0, 8) + "-" + h.slice(8, 12) + "-4" + h.slice(13, 16) + "-" + (8 + (Math.random() * 4 | 0)).toString(16) + h.slice(17, 20) + "-" + h.slice(20); },
    subtle: {},
};

// ---------------------------------------------------------------- storage

class Storage {
    constructor(kind) { this._kind = kind; this._d = kind === "local" ? (call("storage_load") || {}) : {}; }
    _save() { if (this._kind === "local") call("storage_save", this._d); }
    get length() { return Object.keys(this._d).length; }
    key(i) { return Object.keys(this._d)[i] ?? null; }
    getItem(k) { k = String(k); return Object.prototype.hasOwnProperty.call(this._d, k) ? this._d[k] : null; }
    setItem(k, v) { this._d[String(k)] = String(v); this._save(); }
    removeItem(k) { delete this._d[String(k)]; this._save(); }
    clear() { this._d = {}; this._save(); }
}
function storageProxy(s) {
    return new Proxy(s, {
        get(t, k) { if (k in t) return typeof t[k] === "function" ? t[k].bind(t) : t[k]; return typeof k === "string" ? t.getItem(k) ?? undefined : undefined; },
        set(t, k, v) { t.setItem(k, v); return true; },
        deleteProperty(t, k) { t.removeItem(k); return true; },
    });
}

// ---------------------------------------------------------------- window

const location = {
    _set(u) { Object.assign(this, call("url_parse", { url: u, base: null }) || {}); },
    get href() { return this.protocol + "//" + this.hostname + (this.port ? ":" + this.port : "") + this.pathname + this.search + this.hash; },
    set href(u) { call("navigate", resolveURL(String(u))); },
    get host() { return this.hostname + (this.port ? ":" + this.port : ""); },
    get origin() { return this.protocol + "//" + this.host; },
    assign(u) { this.href = u; },
    replace(u) { this.href = u; },
    reload() { call("navigate", this.href); },
    toString() { return this.href; },
    ancestorOrigins: [],
};
const history = {
    _stack: [], state: null,
    get length() { return this._stack.length + 1; },
    pushState(state, title, url) { this.state = state; if (url !== undefined && url !== null) { location._set(resolveURL(String(url))); call("url_changed", location.href); } },
    replaceState(state, title, url) { this.pushState(state, title, url); },
    back() {}, forward() {}, go() {},
    scrollRestoration: "auto",
};

const performance = {
    _t0: Date.now(),
    now() { return Date.now() - this._t0; },
    get timeOrigin() { return this._t0; },
    mark() {}, measure() {}, clearMarks() {}, clearMeasures() {},
    getEntriesByType() { return []; }, getEntriesByName() { return []; }, getEntries() { return []; },
    timing: {}, navigation: { type: 0 },
};

const consoleObj = {};
for (const level of ["log", "info", "warn", "error", "debug", "trace", "dir", "table"]) {
    consoleObj[level] = (...a) => { try { call("log", { level, text: a.map(x => typeof x === "string" ? x : (() => { try { return JSON.stringify(x); } catch (e) { return String(x); } })()).join(" ") }); } catch (e) {} };
}
for (const n of ["group", "groupCollapsed", "groupEnd", "time", "timeEnd", "timeLog", "count", "countReset", "assert", "clear", "profile", "profileEnd"]) consoleObj[n] = () => {};

class CSSStyleDeclarationRO {}
function getComputedStyle(el) {
    const st = el && el._id ? (call("style", el._id) || {}) : {};
    const inline = el && el._attrs ? parseStyle(el._attrs.style) : {};
    const all = Object.assign({}, st, inline);
    return new Proxy({ getPropertyValue: n => all[n] ?? "" }, {
        get(t, k) { if (k in t) return t[k]; if (k === "length") return Object.keys(all).length; return typeof k === "string" ? (all[k.startsWith("--") ? k : kebab(k)] ?? "") : undefined; },
    });
}
function matchMedia(q) {
    const m = { media: q, matches: !!call("media", String(q)), onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; } };
    return m;
}

const customElements = {
    _defs: new Map(), _waits: new Map(),
    define(name, cls) {
        this._defs.set(name, cls);
        const w = this._waits.get(name); if (w) { w(cls); this._waits.delete(name); }
        // elements already in the page: upgrade them in place
        for (const el of document.getElementsByTagName(name)) {
            try { Object.setPrototypeOf(el, cls.prototype); if (el.connectedCallback) el.connectedCallback(); } catch (e) { reportError(e); }
        }
    },
    get(name) { return this._defs.get(name); },
    getName(cls) { for (const [k, v] of this._defs) if (v === cls) return k; return null; },
    whenDefined(name) { return this._defs.has(name) ? Promise.resolve(this._defs.get(name)) : new Promise(ok => this._waits.set(name, ok)); },
    upgrade() {},
};
// a custom element made with `new` (class X extends HTMLElement; new X())
const NativeHTMLElement = HTMLElement;

Object.assign(G, {
    window: G, self: G, globalThis: G, top: G, parent: G, frames: G, opener: null, frameElement: null, length: 0,
    document, location, history, performance, console: consoleObj, navigator: {
        userAgent: call("user_agent") || "Mozilla/5.0 (SnakeyOS) PyKernel", appName: "Netscape", appVersion: "5.0", platform: "SnakeyOS",
        language: "es-ES", languages: ["es-ES", "es", "en"], onLine: true, cookieEnabled: true, vendor: "", product: "Gecko",
        hardwareConcurrency: 1, maxTouchPoints: 0, deviceMemory: 2, webdriver: false, doNotTrack: "1", pdfViewerEnabled: false,
        clipboard: { writeText: t => { call("clipboard", String(t)); return Promise.resolve(); }, readText: () => Promise.resolve(call("clipboard_read") || "") },
        sendBeacon: () => true, vibrate: () => false, share: () => Promise.reject(new DOMException("no", "NotAllowedError")),
        serviceWorker: { register: () => Promise.reject(new Error("no service workers")), getRegistrations: () => Promise.resolve([]), ready: new Promise(() => {}), controller: null, addEventListener() {} },
        permissions: { query: () => Promise.resolve({ state: "denied", addEventListener() {} }) },
        mediaDevices: { getUserMedia: () => Promise.reject(new DOMException("no", "NotAllowedError")), enumerateDevices: () => Promise.resolve([]) },
        geolocation: { getCurrentPosition(ok, no) { no && no({ code: 1, message: "denied" }); }, watchPosition() { return 0; }, clearWatch() {} },
        storage: { estimate: () => Promise.resolve({ quota: 0, usage: 0 }), persist: () => Promise.resolve(false) },
        userAgentData: { brands: [], mobile: false, platform: "SnakeyOS", getHighEntropyValues: () => Promise.resolve({}) },
        connection: { effectiveType: "4g", saveData: false, addEventListener() {} },
    },
    screen: { width: 1024, height: 768, availWidth: 1024, availHeight: 700, colorDepth: 24, pixelDepth: 24, orientation: { type: "landscape-primary", angle: 0, addEventListener() {} } },
    innerWidth: 1000, innerHeight: 640, outerWidth: 1024, outerHeight: 768, devicePixelRatio: 1,
    scrollX: 0, scrollY: 0, pageXOffset: 0, pageYOffset: 0, screenX: 0, screenY: 0, isSecureContext: true, origin: "",
    name: "", closed: false, status: "", visualViewport: { width: 1000, height: 640, scale: 1, offsetTop: 0, offsetLeft: 0, addEventListener() {}, removeEventListener() {} },
    scrollTo() {}, scrollBy() {}, scroll() {}, focus() {}, blur() {}, print() {}, stop() {}, close() {}, moveTo() {}, resizeTo() {},
    open: u => { if (u) call("open", resolveURL(String(u))); return null; },
    alert: m => { call("alert", String(m)); },
    confirm: m => !!call("confirm", String(m)),
    prompt: (m, d) => d === undefined ? null : String(d),
    postMessage: (data) => { setTimeout_(() => G.dispatchEvent(new MessageEvent("message", { data })), 0); },
    getSelection: () => ({ toString: () => "", rangeCount: 0, removeAllRanges() {}, addRange() {}, getRangeAt() { return document.createRange(); }, collapse() {} }),
    getComputedStyle, matchMedia,
    setTimeout: setTimeout_, setInterval: setInterval_, clearTimeout: clearTimer, clearInterval: clearTimer,
    requestAnimationFrame: fn => { const id = ++timerId; rafs.push([id, fn]); return id; },
    cancelAnimationFrame: id => { rafs = rafs.filter(r => r[0] !== id); },
    requestIdleCallback: fn => setTimeout_(() => fn({ didTimeout: false, timeRemaining: () => 10 }), 1),
    cancelIdleCallback: clearTimer,
    queueMicrotask: fn => { microtask(fn); },
    structuredClone: v => v === undefined ? undefined : JSON.parse(JSON.stringify(v)),
    reportError,
    fetch: fetch_, Headers, Request, Response, XMLHttpRequest, AbortController, AbortSignal, DOMException, WebSocket, EventSource,
    URL, URLSearchParams, TextEncoder, TextDecoder, Blob, File, FormData, btoa, atob, crypto: cryptoObj,
    localStorage: storageProxy(new Storage("local")), sessionStorage: storageProxy(new Storage("session")),
    Event, CustomEvent, UIEvent, MouseEvent, PointerEvent, KeyboardEvent, FocusEvent, InputEvent, SubmitEvent, ErrorEvent,
    MessageEvent, ProgressEvent, PopStateEvent, EventTarget, Node, Text, Comment, CharacterData, DocumentFragment, ShadowRoot,
    Element, HTMLElement, SVGElement, Document, HTMLDocument: Document, DOMTokenList, MutationObserver, IntersectionObserver,
    ResizeObserver, HTMLAnchorElement, HTMLImageElement, HTMLScriptElement, HTMLLinkElement, HTMLStyleElement, HTMLIFrameElement,
    HTMLTemplateElement, HTMLFormElement, HTMLInputElement, HTMLTextAreaElement, HTMLButtonElement, HTMLSelectElement,
    HTMLOptionElement, HTMLLabelElement, HTMLDetailsElement, HTMLDialogElement, HTMLMediaElement, HTMLVideoElement,
    HTMLAudioElement, HTMLCanvasElement, HTMLMetaElement, HTMLTableElement, HTMLTableRowElement, HTMLAreaElement,
    CSSStyleDeclaration: CSSStyleDeclarationRO, customElements,
    Image: function (w, h) { const i = document.createElement("img"); if (w) i.width = w; if (h) i.height = h; return i; },
    Option: function (text, value, d, sel) { const o = document.createElement("option"); if (text !== undefined) o.text = text; if (value !== undefined) o.value = value; if (sel) o.selected = true; return o; },
    CSS: { supports: () => false, escape: s => String(s).replace(/([^\w-])/g, "\\$1") },
    DOMParser: class { parseFromString(s, type) { const d = new Document(); const parts = call("parse_document", String(s)); if (parts) d.appendChild(build(parts)); return d; } },
    XMLSerializer: class { serializeToString(n) { return serialize(n); } },
    NodeFilter: { SHOW_ALL: 0xFFFFFFFF, SHOW_ELEMENT: 1, SHOW_TEXT: 4, FILTER_ACCEPT: 1, FILTER_REJECT: 2, FILTER_SKIP: 3 },
    Worker: class { constructor() { throw new Error("Web Workers are not supported"); } },
    BroadcastChannel: class extends EventTarget { postMessage() {} close() {} },
    Notification: Object.assign(class { constructor() {} }, { permission: "denied", requestPermission: () => Promise.resolve("denied") }),
    indexedDB: { open() { const r = new EventTarget(); setTimeout_(() => r.dispatchEvent(new Event("error")), 0); return r; } },
    caches: { open: () => Promise.reject(new Error("no Cache API")), match: () => Promise.resolve(undefined), keys: () => Promise.resolve([]) },
    onload: null, onerror: null, onresize: null, onpopstate: null,
});
G.HTMLElement = NativeHTMLElement;
Object.setPrototypeOf(G, EventTarget.prototype);     // window.addEventListener and friends
G._listeners = null;

// ---------------------------------------------------------------- what the browser calls

// The page's tree arrives (as JSON) and becomes `document`.
G.__dom_load = function (url) {
    location._set(url);
    const tree = call("tree");                  // straight from the browser, parsed once
    document.childNodes = [];
    const root = build(tree);
    root.parentNode = document;
    document.childNodes.push(root);
    reindex(root, tree);
    document.activeElement = document.body;
    dirty = false;
};
function reindex(el, j) {                    // the browser's ids for the elements it sent
    if (typeof j === "string" || el.nodeType !== 1) return;
    byId.delete(el._id);
    el._id = j[0];
    byId.set(el._id, el);
    if (j[0] >= nextId) nextId = j[0] + 1;
    const kids = el.localName === "template" ? el.content.childNodes : el.childNodes;
    for (let i = 0; i < kids.length; i++) reindex(kids[i], j[i + 3]);
}
// elements with an id are also global variables (window.menu, or just menu), as in browsers
const IDENT = /^[A-Za-z_$][\w$]*$/;
function exposeIds() {
    for (const el of descendants(document)) {
        const id = el._attrs.id;
        if (!id || !IDENT.test(id) || Object.prototype.hasOwnProperty.call(G, id)) continue;
        Object.defineProperty(G, id, { get() { return document.getElementById(id); }, set(v) {
            Object.defineProperty(G, id, { value: v, writable: true, configurable: true, enumerable: true }); },
            configurable: true, enumerable: false });
    }
}
// run one of the page's scripts
G.__run = function (code, name, id) { exposeIds(); runScript(code, name, byId.get(id) || null); };
// the browser runs a page script by itself, between these two (no copy of the code through JSON)
G.__before = function (id) { exposeIds(); document.currentScript = byId.get(id) || null; };
G.__after = function () { document.currentScript = null; };
G.__ready = function () {
    for (const s of document.getElementsByTagName("script")) s._ran = true;     // the browser ran those already
    document.readyState = "interactive";
    document.dispatchEvent(new Event("readystatechange"));
    document.dispatchEvent(new Event("DOMContentLoaded", { bubbles: true }));
    document.readyState = "complete";
    document.dispatchEvent(new Event("readystatechange"));
    G.dispatchEvent(new Event("load"));
    G.dispatchEvent(new Event("pageshow"));
};
G.__tick = tick;
// for finding leaks: what the DOM holds
G.__stats = () => JSON.stringify({ elements: byId.size, timers: timers.size, frames: rafs.length, observers: observers.length,
    records: observers.reduce((n, o) => n + o._records.length, 0), selectors: selCache.size });
G.__timers = () => timers.size + rafs.length;
G.__dirty = () => dirty;
// the tree back to the browser: [id, tag, attrs, children...] (inputs carry their value)
G.__dump = function () {
    dirty = false;
    const out = n => {
        if (n.nodeType === 3) return n.data;
        if (n.nodeType !== 1) return null;
        const a = Object.assign({}, n._attrs);
        if (n._value !== undefined) a.value = n._value;
        if (n._checked !== undefined) { if (n._checked) a.checked = ""; else delete a.checked; }
        const r = [n._id, n.localName, a];
        const kids = n._shadow ? n._shadow.childNodes.concat(n.childNodes) : n.childNodes;
        for (const c of kids) { const x = out(c); if (x !== null) r.push(x); }
        return r;
    };
    return JSON.stringify(out(document.documentElement));
};
// the user did something: events for it; returns whether the page let the default happen
G.__event = function (id, type, extra) {
    const el = byId.get(id);
    if (!el) return true;
    extra = extra || {};
    let ev;
    if (type === "click" || type === "mousedown" || type === "mouseup" || type === "dblclick")
        ev = new MouseEvent(type, Object.assign({ bubbles: true, cancelable: true, button: 0 }, extra));
    else if (type === "keydown" || type === "keyup" || type === "keypress")
        ev = new KeyboardEvent(type, Object.assign({ bubbles: true, cancelable: true }, extra));
    else if (type === "input" || type === "change")
        ev = new InputEvent(type, { bubbles: true });
    else if (type === "submit")
        ev = new SubmitEvent(type, { bubbles: true, cancelable: true });
    else ev = new Event(type, { bubbles: true, cancelable: true });
    ev.isTrusted = true;
    if (type === "click") { for (let n = el; n; n = n.parentNode) if (n.focus && n.matches && n.matches("a,button,input,select,textarea,[tabindex]")) { document.activeElement = n; break; } }
    const ok = el.dispatchEvent(ev);
    // a click on a <label> clicks its control; on a checkbox, ticks it
    if (ok && type === "click") {
        if (el.localName === "input" && (el.type === "checkbox" || el.type === "radio")) { el.checked = el.type === "radio" ? true : !el.checked; el.dispatchEvent(new InputEvent("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); }
        const label = el.closest && el.closest("label");
        if (label && label.control && label.control !== el) label.control.click();
    }
    return ok;
};
G.__set_value = function (id, value) {
    const el = byId.get(id);
    if (!el) return;
    el._value = String(value);
    el.dispatchEvent(new InputEvent("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
};
G.__resize = function (w, h) { G.innerWidth = w; G.innerHeight = h; G.dispatchEvent(new Event("resize")); };
})();
