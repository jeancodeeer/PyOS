var later = [];
// regular expressions
print("2024-01-15".match(/(\d{4})-(\d{2})-(\d{2})/).slice(1).join("|"));
print("a1b22c333".replace(/\d+/g, m => "<" + m.length + ">"), "aaa".replace(/a/y, "b"));
print(/^[\w.+-]+@[\w-]+\.[a-z]{2,}$/i.test("Foo.Bar@Example.COM"), /colou?r/.test("color"));
const re = /(?<y>\d{4})\/(?<m>\d\d)/; const mm = "on 2023/07".match(re); print(mm.groups.y, mm.groups.m, mm.index);
print("x  y\tz".split(/\s+/), "a,b;c".split(/[,;]/), "abc".split(""), "a1b2".split(/(\d)/));
print([..."a1b2c3".matchAll(/[a-z](\d)/g)].map(m => m[1]).join(), "aBc".replace(/b/i, "$&$&"));
print(/(a+)+b/.test("aaaaaaaaaaaaaaaaab"), /^(?!foo).*$/.test("bar"), /(?<=\$)\d+/.exec("cost $42")[0]);
print("The Quick fox".replace(/(\w+) (\w+)/, "$2 $1"), /\bfox\b/.test("a fox!"), "tést".match(/\w+/)[0]);
print(/(\w)\1/.test("hello"), "x".padEnd(3, "ab"), /[^\]]+/.exec("ab]c")[0], /a{2,3}/.exec("caaaab")[0]);
// JSON
const j = JSON.parse('{"b":2,"a":[1,{"c":null}],"s":"\\u00e9\\n","n":-1.5e3}');
print(JSON.stringify(j), JSON.stringify(j, null, 2).split("\n").length, JSON.stringify({d: new Date(0), u: undefined, f() {}}));
print(JSON.stringify(" <"), JSON.stringify([undefined, NaN]), JSON.parse("[1,2]", (k, v) => typeof v === "number" ? v * 10 : v));
try { JSON.parse("{bad}"); } catch (e) { print(e.name); }
// classes: private, static, accessors, inheritance from builtins
class Counter { #n = 0; static instances = 0; constructor() { Counter.instances++; } inc() { return ++this.#n; } get value() { return this.#n; } static create() { return new Counter(); } }
const cc = Counter.create(); cc.inc(); cc.inc(); print(cc.value, Counter.instances, Object.keys(cc).length);
class MyErr extends Error { constructor(m) { super(m); this.name = "MyErr"; } }
try { throw new MyErr("boom"); } catch (e) { print(e instanceof MyErr, e instanceof Error, e.message, String(e)); }
class List extends Array { sum() { return this.reduce((a, b) => a + b, 0); } }
const L = new List(); L.push(1, 2, 3); print(L.sum(), L.length, Array.isArray(L));
class P { static #secret = 7; static reveal() { return P.#secret; } } print(P.reveal());
// iterators and generators
const it = { from: 1, to: 4, [Symbol.iterator]() { let c = this.from, t = this.to; return { next: () => c <= t ? { value: c++, done: false } : { value: undefined, done: true } }; } };
print([...it], Math.max(...it));
function* g2() { try { const x = yield 1; print("got", x); yield x * 2; } finally { print("cleanup"); } }
const gi = g2(); print(gi.next().value, gi.next(21).value, JSON.stringify(gi.return(5)));
function* inner() { yield 'a'; yield 'b'; return 'r'; } function* outer() { const r = yield* inner(); yield r; }
print([...outer()].join());
for (const [k, v] of new Map([["x", 1], ["y", 2]])) print(k, v);
// closures, this, call/apply/bind
function mk() { let n = 0; return { add: d => (n += d), get: () => n }; } const m1 = mk(); m1.add(5); m1.add(2); print(m1.get());
const obj = { name: "o", hi(greet) { return greet + " " + this.name; } };
print(obj.hi.call({ name: "c" }, "hey"), obj.hi.apply({ name: "a" }, ["yo"]), obj.hi.bind({ name: "b" })("hi"));
function Old(x) { this.x = x; } Old.prototype.get = function () { return this.x; }; print(new Old(3).get(), typeof Old.prototype);
// getters/setters, defineProperty, freeze
const acc = { _v: 1, get v() { return this._v; }, set v(x) { this._v = x * 2; } }; acc.v = 5; print(acc.v);
const dp = {}; Object.defineProperty(dp, "k", { value: 1, enumerable: false }); dp.k = 2; print(dp.k, Object.keys(dp).length, JSON.stringify(Object.getOwnPropertyDescriptor(dp, "k")));
const fr = Object.freeze({ a: 1 }); fr.a = 2; print(fr.a, Object.isFrozen(fr));
// Proxy and Reflect
const px = new Proxy({}, { get: (t, k) => k === "magic" ? 42 : Reflect.get(t, k), has: () => true });
print(px.magic, px.other, "anything" in px, Reflect.ownKeys({ a: 1, [Symbol.iterator]: 0 }).length);
// async ordering
const order = [];
setTimeoutLike(() => order.push("t"));
Promise.resolve().then(() => order.push("p1")).then(() => order.push("p2"));
(async () => { order.push("a1"); await null; order.push("a2"); })();
order.push("sync");
function setTimeoutLike(f) { later.push(f); }
Promise.all([1, Promise.resolve(2), new Promise(r => r(3))]).then(v => print("all", v.join()));
Promise.allSettled([Promise.reject(new Error("x")), 1]).then(r => print(r.map(x => x.status).join()));
Promise.race([new Promise(() => {}), Promise.resolve("fast")]).then(v => print("race", v));
(async function () { try { await Promise.reject(new TypeError("no")); } catch (e) { print("caught", e.message); } })();
Promise.resolve().then(() => print("order", order.join()));
// misc
print(typeof Symbol(), [1, 2, 3].at(-1), Object.fromEntries([["a", 1]]).a, structuredCloneLike({ a: [1] }));
function structuredCloneLike(v) { return JSON.parse(JSON.stringify(v)).a.length; }
print([0, -0, NaN].map(x => Object.is(x, -0)), 1 / -0, (-0).toString(), [1, 10, 2].sort().join());
print(new Date(Date.UTC(2020, 1, 29, 12)).toISOString(), new Date("2021-03-04T05:06:07Z").getTime());
print(new Uint8Array([1, 2, 300]).join(), new Int16Array(new Uint8Array([255, 255]).buffer)[0], new Float32Array([0.5])[0]);
const tag = (s, ...v) => s.raw.join("|") + v.join(","); print(tag`a${1}b${2}c`);
print(String(null), String([1, [2, 3]]), String({}), `${[]}`, [] + {}, 1 + "2" - 1, "3" * "4", true + 1);
print(0.1 * 3, 1e-7, 123456789012345680000, (25).toString(36), Number.MAX_SAFE_INTEGER + 2, 2 ** 53 + 1);
print([1, 2, 3, 4].findLast(x => x % 2), Object.groupBy([1, 2, 3], x => x % 2 ? "odd" : "even").odd.join());
var hoisted = typeof laterFn; function laterFn() {} print(hoisted, typeof notDefinedAnywhere);
let s2 = 0; for (const k in { a: 1, b: 2, c: 3 }) s2 += k.length; print(s2);
outerLoop: while (true) { do { break outerLoop; } while (false); }
print("done");
