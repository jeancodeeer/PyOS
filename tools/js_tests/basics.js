print(1 + 2, "a" + 1, 7 / 2, 2 ** 10, -7 % 3, 0.1 + 0.2, 1e21, 1 / 3, [1, 2, 3].map(x => x * 2).join());
let o = { a: 1, b: [1, 2, { c: 3 }], get d() { return this.a + 1; } };
print(JSON.stringify(o), o.d, Object.keys(o));
class A { constructor(x) { this.x = x; } get dbl() { return this.x * 2; } static make() { return new this(5); } toString() { return "A" + this.x; } }
class B extends A { constructor() { super(10); this.y = 1; } get dbl() { return super.dbl + 1; } }
print(new B().dbl, A.make().dbl, String(new A(3)), new B() instanceof A);
function* gen() { let i = 0; while (i < 3) yield i++; return 9; }
print([...gen()], Array.from(gen(), x => x * 10));
const fs = []; for (let i = 0; i < 3; i++) fs.push(() => i); print(fs.map(f => f()));
let { a, b: [, second, { c }], ...rest } = o; print(a, second, c, JSON.stringify(rest));
print("x-y-z".split("-"), "Hello World".replace(/o/g, "0"), /(\d+)-(\d+)/.exec("tel 12-34")[2], "abc".padStart(5, "*"));
print([3, 1, 2].sort(), [10, 9, 1].sort((a, b) => a - b), typeof null, typeof undefined, typeof (() => 1));
label: for (let i = 0; i < 3; i++) { for (let j = 0; j < 3; j++) { if (j == 1) continue label; if (i == 2) break label; print("ij", i, j); } }
switch (3) { case 1: print("one"); case 3: print("three"); case 4: print("four"); break; default: print("d"); }
try { null.x; } catch (e) { print(e instanceof TypeError, e.message); }
(async () => { const v = await new Promise(r => r(5)); print("async", v); })().catch(e => print("err", e.message));
Promise.resolve(1).then(v => print("then", v));
print(new Map([[1, "a"], ["1", "b"]]).size, [...new Set([1, 1, 2, NaN, NaN])].length);
print(parseInt("0x1f"), parseFloat("3.5e2px"), (255).toString(16), (3.14159).toFixed(2), Number("12px"));
print(`t ${1 + 1} x`, String.raw`a\nb`, [1, [2, [3]]].flat(Infinity).length);
var x = 10; { let x = 20; print(x); } print(x);
print(new Date(0).toISOString(), Math.max(1, 5, 3), Math.round(2.5), Math.round(-2.5));
print(Object.entries({x: 1, y: 2}).map(([k, v]) => k + v).join(), "abc".at(-1), [1,2,3].includes(2));
const sym = Symbol("s"); const so = {[sym]: 1, n: 2}; print(so[sym], Object.keys(so).length, sym.toString());
print([..."héllo"].length, "ABC".toLowerCase(), "a,b,,c".split(","), encodeURIComponent("a b&c"));
let n = 0; do { n++; if (n == 2) continue; } while (n < 5); print(n);
print(((a, b = 2, ...r) => a + b + r.length)(1, undefined, 3, 4));
print(Array.isArray([]), [1,2,3].indexOf(2), [1,2,3].reduce((a, b) => a + b), "x".repeat(3));
print(0 || "d", null ?? "n", 1 && 2, undefined?.x, ({a:{b:1}}).a?.b);
