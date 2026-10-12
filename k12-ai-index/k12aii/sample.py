"""Matched stratified sample: equal wiki / non-wiki counts in every sector x locale x level cell."""
import numpy as np
import pandas as pd

from .common import resolve

CELLS = ["sector", "locale3", "level_group"]


def _match_pairs(g, k, seed, caliper):
    """k (wiki, non-wiki) pairs in one cell: random wiki order, each takes the nearest unused non-wiki by log enrollment."""
    w = g[g.from_wikipedia == 1].sample(frac=1, random_state=seed)
    pool = g[g.from_wikipedia == 0].reset_index(drop=True)
    used = np.zeros(len(pool), bool)
    le = pool.log_enroll.values
    pairs = []
    for _, row in w.iterrows():
        if len(pairs) == k:
            break
        dist = np.where(used, np.inf, np.abs(le - row.log_enroll))
        j = int(dist.argmin())
        if dist[j] <= caliper:
            used[j] = True
            pairs.append((row, pool.iloc[j], float(dist[j])))
    return pairs


def draw(cfg, n_per_group=None, seed=None, out=None):
    n = n_per_group or cfg["sampling"]["n_per_group"]
    seed = seed or cfg["sampling"]["seed"]
    df = pd.read_parquet(resolve(cfg["paths"]["frame"]))
    df = df[df.eligible]
    avail = {}
    for cell, g in df.groupby(CELLS):
        avail[cell] = min((g.from_wikipedia == 0).sum(), (g.from_wikipedia == 1).sum())
    take = {c: 0 for c in avail}
    total = 0
    while total < n and any(take[c] < avail[c] for c in take):  # round-robin => near-equal allocation
        for c in take:
            if take[c] < avail[c] and total < n:
                take[c] += 1
                total += 1
    parts, short = [], 0
    pid = 0
    for cell, k in take.items():
        if k == 0:
            continue
        g = df[(df[CELLS] == pd.Series(cell, index=CELLS)).all(axis=1)]
        if cfg["sampling"].get("match_enrollment"):
            pairs = _match_pairs(g, k, seed, cfg["sampling"].get("caliper_log", 0.35))
            short += k - len(pairs)
            for w_row, n_row, gap in pairs:
                parts += [pd.DataFrame([{**r.to_dict(), "pair_id": pid, "match_gap_log": gap}]) for r in (w_row, n_row)]
                pid += 1
        else:
            for w in (0, 1):
                parts.append(g[g.from_wikipedia == w].sample(k, random_state=seed))
    if short:
        print(f"note: {short} pair(s) could not be matched within the caliper and were dropped")
    s = pd.concat(parts).sort_values("nces_id").reset_index(drop=True)
    s["sample_id"] = range(len(s))
    out = resolve(out or f"runs/sample_n{n}_seed{seed}.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    s.to_parquet(out)
    print(f"sampled {len(s)} schools ({total} per group) -> {out}")
    print(s.groupby(["from_wikipedia", "sector", "locale3", "level_group"]).size().unstack(0, fill_value=0))
    return out
