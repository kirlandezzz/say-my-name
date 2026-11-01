"""String similarity in plain Python (no C extensions needed)."""

from __future__ import annotations


def jaro(s1: str, s2: str) -> float:
    if s1 == s2:
        return 1.0
    l1, l2 = len(s1), len(s2)
    if not l1 or not l2:
        return 0.0
    window = max(max(l1, l2) // 2 - 1, 0)
    m1 = [False] * l1
    m2 = [False] * l2
    matches = 0
    for i, ch in enumerate(s1):
        for j in range(max(0, i - window), min(i + window + 1, l2)):
            if not m2[j] and s2[j] == ch:
                m1[i] = m2[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    transpositions = 0
    k = 0
    for i in range(l1):
        if m1[i]:
            while not m2[k]:
                k += 1
            if s1[i] != s2[k]:
                transpositions += 1
            k += 1
    t = transpositions / 2
    return (matches / l1 + matches / l2 + (matches - t) / matches) / 3


def jaro_winkler(s1: str, s2: str, prefix_scale: float = 0.1) -> float:
    j = jaro(s1, s2)
    prefix = 0
    for a, b in zip(s1[:4], s2[:4]):
        if a != b:
            break
        prefix += 1
    return j + prefix * prefix_scale * (1 - j)


def edit_distance(s1: str, s2: str) -> int:
    """Damerau-Levenshtein (optimal string alignment): a swap of neighbours costs 1."""
    prev2: list[int] = []
    prev = list(range(len(s2) + 1))
    for i in range(1, len(s1) + 1):
        cur = [i] + [0] * len(s2)
        for j in range(1, len(s2) + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and s1[i - 1] == s2[j - 2] and s1[i - 2] == s2[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def same_token(a: str, b: str, threshold: float = 0.9) -> bool:
    """Equal, one typo apart (words of 4+ letters), or Jaro-Winkler >= threshold."""
    if a == b:
        return True
    if min(len(a), len(b)) >= 4 and abs(len(a) - len(b)) <= 1 and edit_distance(a, b) <= 1:
        return True
    return jaro_winkler(a, b) >= threshold


def soft_dice(a: list[str], b: list[str]) -> float:
    """Dice overlap of two token lists, counting near-identical tokens as equal."""
    if not a or not b:
        return 0.0
    unused = list(b)
    matched = 0
    for tok in a:
        hit = tok if tok in unused else next((o for o in unused if same_token(tok, o)), None)
        if hit is not None:
            unused.remove(hit)
            matched += 1
    return 2 * matched / (len(a) + len(b))


def token_similarity(a: list[str], b: list[str]) -> float:
    """Average of Jaro-Winkler on sorted tokens and soft Dice on the token sets."""
    if not a or not b:
        return 0.0
    jw = jaro_winkler(" ".join(sorted(a)), " ".join(sorted(b)))
    return 0.5 * jw + 0.5 * soft_dice(a, b)
