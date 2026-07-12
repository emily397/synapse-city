"""Parameterised, execution-verified task families for the held-out eval suite.

Every task is generated from (family, seed) and is verifiable without a judge:
  kind "code"   -> model must emit a python function `solve`; asserts run in a sandbox
  kind "answer" -> model must end with "ANSWER: <value>"; compared exactly (normalised)

SEED POLICY (do not violate): seeds >= 1_000_000 are RESERVED FOR EVAL.
Training-data generators (Proving Grounds etc.) must only use seeds < 1_000_000,
so no eval task can ever leak into training.
"""
from __future__ import annotations

import hashlib
import hmac
import random
import string

EVAL_SEED_BASE = 1_000_000


def _words(rng, n):
    return [
        "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(3, 8)))
        for _ in range(n)
    ]


# ----------------------------------------------------------------- CODE ---- #

def reverse_words(seed):
    rng = random.Random(seed)
    s = " ".join(_words(rng, rng.randint(4, 8)))
    expected = " ".join(reversed(s.split()))
    return {
        "kind": "code",
        "prompt": ("Write a Python function `solve(s)` that returns the words of the "
                   "string s in reverse order, joined by single spaces.\n"
                   f"Example input: {s!r}\n"
                   "Reply with a single ```python code block defining solve."),
        "check": f"assert solve({s!r}) == {expected!r}\n"
                 f"assert solve('a b') == 'b a'\nassert solve('x') == 'x'",
    }


def dedupe_keep_order(seed):
    rng = random.Random(seed)
    xs = [rng.randint(1, 9) for _ in range(rng.randint(8, 14))]
    out, seen = [], set()
    for x in xs:
        if x not in seen:
            seen.add(x); out.append(x)
    return {
        "kind": "code",
        "prompt": ("Write a Python function `solve(xs)` that removes duplicates from the "
                   "list xs while keeping the first occurrence order.\n"
                   f"Example input: {xs}\n"
                   "Reply with a single ```python code block defining solve."),
        "check": f"assert solve({xs!r}) == {out!r}\n"
                 "assert solve([]) == []\nassert solve([2,2,2]) == [2]",
    }


def chunk_list(seed):
    rng = random.Random(seed)
    xs = list(range(rng.randint(7, 15)))
    k = rng.randint(2, 4)
    out = [xs[i:i + k] for i in range(0, len(xs), k)]
    return {
        "kind": "code",
        "prompt": ("Write a Python function `solve(xs, k)` that splits list xs into "
                   "consecutive chunks of size k (last chunk may be shorter).\n"
                   f"Example: solve({xs}, {k})\n"
                   "Reply with a single ```python code block defining solve."),
        "check": f"assert solve({xs!r}, {k}) == {out!r}\n"
                 "assert solve([1], 3) == [[1]]",
    }


def invert_dict(seed):
    rng = random.Random(seed)
    keys = _words(rng, rng.randint(4, 6))
    d = {k: rng.randint(1, 3) for k in keys}
    inv = {}
    for k in d:
        inv.setdefault(d[k], []).append(k)
    inv = {v: sorted(ks) for v, ks in inv.items()}
    return {
        "kind": "code",
        "prompt": ("Write a Python function `solve(d)` that inverts dict d, mapping each "
                   "value to the SORTED list of keys that had it.\n"
                   f"Example input: {d}\n"
                   "Reply with a single ```python code block defining solve."),
        "check": f"assert solve({d!r}) == {inv!r}\n"
                 "assert solve({}) == {}",
    }


def rle_encode(seed):
    rng = random.Random(seed)
    s = "".join(c * rng.randint(1, 4) for c in
                rng.sample(string.ascii_lowercase, rng.randint(3, 6)))
    out, prev, n = [], s[0], 1
    for c in s[1:]:
        if c == prev:
            n += 1
        else:
            out.append((prev, n)); prev, n = c, 1
    out.append((prev, n))
    return {
        "kind": "code",
        "prompt": ("Write a Python function `solve(s)` that run-length encodes string s "
                   "as a list of (char, count) tuples.\n"
                   f"Example input: {s!r}\n"
                   "Reply with a single ```python code block defining solve."),
        "check": f"assert solve({s!r}) == {out!r}\n"
                 "assert solve('a') == [('a', 1)]",
    }


def balanced_brackets(seed):
    rng = random.Random(seed)
    pairs = {"(": ")", "[": "]", "{": "}"}
    s, stack = [], []
    for _ in range(rng.randint(6, 12)):
        if stack and rng.random() < 0.45:
            s.append(pairs[stack.pop()])
        else:
            b = rng.choice("([{"); s.append(b); stack.append(b)
    while stack:
        s.append(pairs[stack.pop()])
    good = "".join(s)
    bad_l = list(good)
    bad_l[rng.randrange(len(bad_l))] = rng.choice("([{)]}")
    bad = "".join(bad_l)
    exp_bad = _is_balanced(bad)
    return {
        "kind": "code",
        "prompt": ("Write a Python function `solve(s)` returning True if the bracket "
                   "string s (only ()[]{} chars) is balanced, else False.\n"
                   "Reply with a single ```python code block defining solve."),
        "check": f"assert solve({good!r}) is True\n"
                 f"assert solve({bad!r}) is {exp_bad}\n"
                 "assert solve('') is True\nassert solve('(]') is False",
    }


def _is_balanced(s):
    pairs = {")": "(", "]": "[", "}": "{"}
    st = []
    for c in s:
        if c in "([{":
            st.append(c)
        elif not st or st.pop() != pairs[c]:
            return False
    return not st


def two_sum(seed):
    rng = random.Random(seed)
    xs = rng.sample(range(1, 60), rng.randint(6, 10))
    i, j = sorted(rng.sample(range(len(xs)), 2))
    target = xs[i] + xs[j]
    # regenerate until the pair is unique
    n_pairs = sum(1 for a in range(len(xs)) for b in range(a + 1, len(xs))
                  if xs[a] + xs[b] == target)
    if n_pairs != 1:
        return two_sum(seed + 7919)
    return {
        "kind": "code",
        "prompt": ("Write a Python function `solve(xs, target)` returning the tuple "
                   "(i, j) with i<j of the unique pair of indices whose values sum to "
                   f"target.\nExample: solve({xs}, {target})\n"
                   "Reply with a single ```python code block defining solve."),
        "check": f"assert tuple(solve({xs!r}, {target})) == {(i, j)!r}",
    }


def transpose(seed):
    rng = random.Random(seed)
    r, c = rng.randint(2, 4), rng.randint(2, 4)
    m = [[rng.randint(0, 9) for _ in range(c)] for _ in range(r)]
    t = [list(row) for row in zip(*m)]
    return {
        "kind": "code",
        "prompt": ("Write a Python function `solve(m)` returning the transpose of the "
                   f"matrix m (list of lists).\nExample input: {m}\n"
                   "Reply with a single ```python code block defining solve."),
        "check": f"assert solve({m!r}) == {t!r}",
    }


def caesar(seed):
    rng = random.Random(seed)
    s = " ".join(_words(rng, 3))
    k = rng.randint(1, 25)
    enc = "".join(chr((ord(c) - 97 + k) % 26 + 97) if c != " " else " " for c in s)
    return {
        "kind": "code",
        "prompt": ("Write a Python function `solve(s, k)` that Caesar-shifts every "
                   "lowercase letter of s forward by k (wrapping z->a), leaving spaces "
                   f"unchanged.\nExample: solve({s!r}, {k})\n"
                   "Reply with a single ```python code block defining solve."),
        "check": f"assert solve({s!r}, {k}) == {enc!r}\n"
                 "assert solve('z', 1) == 'a'",
    }


# ----------------------------------------------------------------- MATH ---- #

def arith_eval(seed):
    rng = random.Random(seed)
    a, b, c, d = (rng.randint(2, 20) for _ in range(4))
    expr = f"({a} + {b}) * {c} - {d}"
    if rng.random() < 0.5:
        e = rng.randint(2, 9)
        expr = f"{expr} + {a} * {e}"
    val = eval(expr)  # generator-side ground truth (safe: constructed literals)
    return {
        "kind": "answer",
        "prompt": (f"Compute exactly: {expr}\n"
                   "End your reply with the final line 'ANSWER: <integer>'."),
        "expected": str(val),
    }


def gcd_lcm(seed):
    rng = random.Random(seed)
    import math
    a, b = rng.randint(6, 96), rng.randint(6, 96)
    g = math.gcd(a, b)
    l = a * b // g
    return {
        "kind": "answer",
        "prompt": (f"For a={a} and b={b}, find gcd(a,b) and lcm(a,b).\n"
                   "End your reply with the final line 'ANSWER: <gcd>,<lcm>'."),
        "expected": f"{g},{l}",
    }


def base_convert(seed):
    rng = random.Random(seed)
    n, b = rng.randint(20, 400), rng.randint(2, 9)
    digs, m = [], n
    while m:
        digs.append(str(m % b)); m //= b
    exp = "".join(reversed(digs))
    return {
        "kind": "answer",
        "prompt": (f"Convert the decimal number {n} to base {b}.\n"
                   "End your reply with the final line 'ANSWER: <digits>'."),
        "expected": exp,
    }


def digit_root(seed):
    rng = random.Random(seed)
    n = rng.randint(100, 99999)
    steps, m = 0, n
    while m >= 10:
        m = sum(int(c) for c in str(m)); steps += 1
    return {
        "kind": "answer",
        "prompt": (f"Repeatedly replace {n} by the sum of its digits until one digit "
                   "remains. How many replacement steps were needed, and what is the "
                   "final digit?\n"
                   "End your reply with the final line 'ANSWER: <steps>,<digit>'."),
        "expected": f"{steps},{m}",
    }


# ---------------------------------------------------------------- LOGIC ---- #

def truth_table(seed):
    rng = random.Random(seed)
    A, B, C = (rng.choice([True, False]) for _ in range(3))
    forms = [
        ("(A and B) or (not C)", (A and B) or (not C)),
        ("(A or B) and (B or not C)", (A or B) and (B or not C)),
        ("not (A and (B or C))", not (A and (B or C))),
        ("(A != B) or (B and C)", (A != B) or (B and C)),
    ]
    f, val = forms[rng.randrange(len(forms))]
    return {
        "kind": "answer",
        "prompt": (f"Given A={A}, B={B}, C={C}, evaluate: {f}\n"
                   "End your reply with the final line 'ANSWER: True' or 'ANSWER: False'."),
        "expected": str(val),
    }


def order_deduction(seed):
    rng = random.Random(seed)
    names = rng.sample(["Aria", "Ben", "Cleo", "Dev", "Esme"], 4)
    order = names[:]
    rng.shuffle(order)   # order[0] is 1st (front) .. order[3] is 4th (back)
    pos = {n: i for i, n in enumerate(order)}
    clues = [f"{order[0]} is first in line.",
             f"{order[2]} is directly behind {order[1]}."]
    a, b = rng.sample(names, 2)
    if pos[a] > pos[b]:
        a, b = b, a
    clues.append(f"{a} is somewhere ahead of {b}.")
    rng.shuffle(clues)
    k = rng.randint(2, 4)
    return {
        "kind": "answer",
        "prompt": ("Four people stand in a single line (position 1 = front, 4 = back): "
                   f"{', '.join(sorted(names))}.\n- " + "\n- ".join(clues) +
                   f"\nThe full order is {', '.join(order)} (positions 1 to 4). "
                   f"Who is in position {k}?\n"
                   "End your reply with the final line 'ANSWER: <name>'."),
        "expected": order[k - 1],
    }


def set_relation(seed):
    rng = random.Random(seed)
    A = set(rng.sample(range(1, 30), rng.randint(4, 8)))
    B = set(rng.sample(range(1, 30), rng.randint(4, 8)))
    return {
        "kind": "answer",
        "prompt": (f"Let A = {sorted(A)} and B = {sorted(B)}.\n"
                   "How many elements are in the intersection of A and B, and how many in the union?\n"
                   "End your reply with the final line 'ANSWER: <intersection>,<union>'."),
        "expected": f"{len(A & B)},{len(A | B)}",
    }


# =========================================================== INTEGRATION == #

def json_pluck(seed):
    rng = random.Random(seed)
    k = _words(rng, 3)
    d = {k[0]: {k[1]: {k[2]: rng.randint(1, 99)}}}
    path = ".".join(k)
    val = d[k[0]][k[1]][k[2]]
    return {"kind": "code",
            "prompt": ("Write `solve(d, path)` returning the value in nested dict d "
                       "at the dot-separated key path (like 'a.b.c').\n"
                       f"Example: solve({d!r}, {path!r})\n"
                       "Reply with one ```python code block."),
            "check": f"assert solve({d!r}, {path!r}) == {val!r}\n"
                     "assert solve({'x': {'y': 5}}, 'x.y') == 5"}


def schema_map(seed):
    rng = random.Random(seed)
    src, dst = _words(rng, 3), _words(rng, 3)
    d = {s: rng.randint(1, 9) for s in src}
    mapping = dict(zip(src, dst))
    out = {dst[i]: d[src[i]] for i in range(3)}
    return {"kind": "code",
            "prompt": ("Write `solve(d, mapping)` returning a new dict with each key of "
                       "d renamed per mapping (old->new); keys absent from mapping are "
                       "dropped. This adapts one API's fields onto another's.\n"
                       f"Example: solve({d!r}, {mapping!r})\n"
                       "Reply with one ```python code block."),
            "check": f"assert solve({d!r}, {mapping!r}) == {out!r}\n"
                     "assert solve({'a': 1}, {'a': 'b'}) == {'b': 1}"}


def flatten_dict(seed):
    rng = random.Random(seed)
    k = _words(rng, 3)
    d = {k[0]: {k[1]: rng.randint(1, 9)}, k[2]: rng.randint(1, 9)}
    flat = {f"{k[0]}.{k[1]}": d[k[0]][k[1]], k[2]: d[k[2]]}
    return {"kind": "code",
            "prompt": ("Write `solve(d)` that flattens a nested dict (depth up to 2, int "
                       "values) into one level with dot-joined keys.\n"
                       f"Example input: {d!r}\n"
                       "Reply with one ```python code block."),
            "check": f"assert solve({d!r}) == {flat!r}\n"
                     "assert solve({'a': {'b': 1}}) == {'a.b': 1}"}


def paginate_merge(seed):
    rng = random.Random(seed)
    ids = rng.sample(range(1, 30), rng.randint(5, 7))
    dup = rng.choice(ids)
    recs = [{"id": i, "v": i * 2} for i in ids] + [{"id": dup, "v": dup * 2}]
    pages = [recs[:3], recs[3:6], recs[6:]]
    seen = {}
    for p in pages:
        for r in p:
            seen.setdefault(r["id"], r)
    out = sorted(seen.values(), key=lambda r: r["id"])
    return {"kind": "code",
            "prompt": ("Write `solve(pages)` that merges a list of pages (each a list of "
                       "dicts having an 'id') into one list, keeping the FIRST occurrence "
                       "of each id, sorted by id ascending.\n"
                       "Reply with one ```python code block."),
            "check": f"assert solve({pages!r}) == {out!r}"}


def csv_column_sum(seed):
    rng = random.Random(seed)
    col = rng.choice(["amount", "qty", "price"])
    vals = [rng.randint(1, 50) for _ in range(rng.randint(3, 6))]
    csv_text = f"name,{col}\n" + "\n".join(f"item{i},{v}" for i, v in enumerate(vals))
    return {"kind": "code",
            "prompt": ("Write `solve(csv_text, col)` that parses CSV text (comma-separated, "
                       "first row is headers) and returns the integer sum of the named "
                       f"column.\nColumn: {col!r}\n"
                       "Reply with one ```python code block."),
            "check": f"assert solve({csv_text!r}, {col!r}) == {sum(vals)}"}


# ============================================================ ALGORITHMS == #

def fib_n(seed):
    rng = random.Random(seed)
    n = rng.randint(10, 30)
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return {"kind": "answer",
            "prompt": (f"Compute the {n}th Fibonacci number (F(0)=0, F(1)=1).\n"
                       "End with the final line 'ANSWER: <integer>'."),
            "expected": str(a)}


def binary_search(seed):
    rng = random.Random(seed)
    xs = sorted(rng.sample(range(1, 80), rng.randint(6, 12)))
    t = rng.choice(xs)
    return {"kind": "code",
            "prompt": ("Write `solve(xs, t)` returning the index of t in the sorted list "
                       "xs via binary search, or -1 if absent.\n"
                       f"Example: solve({xs!r}, {t})\n"
                       "Reply with one ```python code block."),
            "check": f"assert solve({xs!r}, {t}) == {xs.index(t)}\n"
                     f"assert solve({xs!r}, 999) == -1"}


def merge_intervals(seed):
    rng = random.Random(seed)
    ivs, start = [], rng.randint(0, 5)
    for _ in range(rng.randint(3, 5)):
        s = start + rng.randint(0, 4)
        e = s + rng.randint(1, 5)
        ivs.append([s, e])
        start = e + rng.randint(-1, 3)
    rng.shuffle(ivs)
    merged = [list(x) for x in sorted(ivs)]
    out = [merged[0]]
    for a, b in merged[1:]:
        if a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return {"kind": "code",
            "prompt": ("Write `solve(intervals)` that merges overlapping [start,end] "
                       "intervals and returns them sorted, as a list of [start,end] lists.\n"
                       f"Example input: {ivs!r}\n"
                       "Reply with one ```python code block."),
            "check": f"assert solve({ivs!r}) == {out!r}"}


def longest_common_prefix(seed):
    rng = random.Random(seed)
    base = "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(2, 4)))
    strs = [base + "".join(rng.choice(string.ascii_lowercase)
                           for _ in range(rng.randint(1, 4)))
            for _ in range(rng.randint(2, 4))]
    lcp = strs[0]
    for s in strs[1:]:
        while not s.startswith(lcp):
            lcp = lcp[:-1]
    return {"kind": "code",
            "prompt": ("Write `solve(strs)` returning the longest common prefix of a list "
                       "of strings ('' if none).\n"
                       f"Example input: {strs!r}\n"
                       "Reply with one ```python code block."),
            "check": f"assert solve({strs!r}) == {lcp!r}\n"
                     "assert solve(['ab', 'a']) == 'a'"}


# ============================================ DEFENSIVE AUTH / SECURITY == #

def hmac_verify(seed):
    rng = random.Random(seed)
    secret = "".join(rng.choice(string.ascii_letters) for _ in range(8))
    payload = "".join(rng.choice(string.ascii_letters) for _ in range(12))
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return {"kind": "code",
            "prompt": ("Write `solve(payload, secret, sig)` returning True iff sig is the "
                       "correct HMAC-SHA256 hex digest of payload keyed by secret. Use "
                       "hmac.compare_digest for the check. This verifies an INCOMING "
                       "webhook signature.\n"
                       "Reply with one ```python code block."),
            "check": f"assert solve({payload!r}, {secret!r}, {sig!r}) is True\n"
                     f"assert solve({payload!r}, {secret!r}, {'0' * 64!r}) is False"}


def jwt_claims_valid(seed):
    rng = random.Random(seed)
    now = rng.randint(1000, 2000)
    iss = rng.choice(["auth.example", "id.acme", "login.corp"])
    exp = now + rng.choice([-50, 50, 100])
    claims = {"iss": iss, "exp": exp, "sub": "u1"}
    return {"kind": "code",
            "prompt": ("Write `solve(claims, now, expected_iss)` returning True iff a "
                       "decoded token is valid: claims['exp'] is strictly greater than now "
                       "AND claims['iss'] equals expected_iss.\n"
                       "Reply with one ```python code block."),
            "check": f"assert solve({claims!r}, {now}, {iss!r}) is {exp > now}\n"
                     f"assert solve({claims!r}, {now}, 'wrong.iss') is False"}


def mask_secret(seed):
    rng = random.Random(seed)
    tok = "".join(rng.choice(string.ascii_letters + string.digits)
                  for _ in range(rng.randint(8, 16)))
    masked = "*" * (len(tok) - 4) + tok[-4:]
    return {"kind": "code",
            "prompt": ("Write `solve(s)` that redacts a secret for safe logging: replace "
                       "all but the last 4 characters with '*'. Strings of length <= 4 "
                       "become all '*'.\n"
                       f"Example: solve({tok!r})\n"
                       "Reply with one ```python code block."),
            "check": f"assert solve({tok!r}) == {masked!r}\n"
                     "assert solve('ab') == '**'"}


def rate_limiter(seed):
    rng = random.Random(seed)
    limit = rng.randint(2, 3)
    window = rng.choice([5, 10])
    times = sorted(rng.randint(0, 30) for _ in range(rng.randint(5, 8)))
    allowed, hist = [], []
    for t in times:
        hist = [x for x in hist if x > t - window]
        if len(hist) < limit:
            allowed.append(True)
            hist.append(t)
        else:
            allowed.append(False)
    return {"kind": "code",
            "prompt": ("Write `solve(times, limit, window)` for a sliding-window rate "
                       "limiter: given ascending request timestamps, return a list of "
                       "booleans marking each request allowed if fewer than `limit` "
                       "requests were ALLOWED in the interval (t-window, t]. Rejected "
                       "requests do not count.\n"
                       f"Params: limit={limit}, window={window}\n"
                       "Reply with one ```python code block."),
            "check": f"assert solve({times!r}, {limit}, {window}) == {allowed!r}"}


FAMILIES = {
    "json_pluck": json_pluck,
    "schema_map": schema_map,
    "flatten_dict": flatten_dict,
    "paginate_merge": paginate_merge,
    "csv_column_sum": csv_column_sum,
    "fib_n": fib_n,
    "binary_search": binary_search,
    "merge_intervals": merge_intervals,
    "longest_common_prefix": longest_common_prefix,
    "hmac_verify": hmac_verify,
    "jwt_claims_valid": jwt_claims_valid,
    "mask_secret": mask_secret,
    "rate_limiter": rate_limiter,
    "reverse_words": reverse_words,
    "dedupe_keep_order": dedupe_keep_order,
    "chunk_list": chunk_list,
    "invert_dict": invert_dict,
    "rle_encode": rle_encode,
    "balanced_brackets": balanced_brackets,
    "two_sum": two_sum,
    "transpose": transpose,
    "caesar": caesar,
    "arith_eval": arith_eval,
    "gcd_lcm": gcd_lcm,
    "base_convert": base_convert,
    "digit_root": digit_root,
    "truth_table": truth_table,
    "order_deduction": order_deduction,
    "set_relation": set_relation,
}


def make_task(family: str, seed: int) -> dict:
    t = FAMILIES[family](seed)
    t.update({"id": f"{family}:{seed}", "family": family, "seed": seed})
    return t
