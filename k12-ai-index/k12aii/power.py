"""Minimum detectable accuracy gap for a given sample size (two-sided, school-clustered design effect)."""
import numpy as np
from scipy import stats


def mde(n_schools_per_group, base_acc=0.5, items_per_school=2.5, icc=0.3, alpha=0.05, power=0.8):
    m = items_per_school
    deff = 1 + (m - 1) * icc
    n_eff = n_schools_per_group * m / deff
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    # solve for delta: z = delta / sqrt(2 * p(1-p) / n_eff) with p evaluated at base + delta/2
    d = 0.0
    for _ in range(50):
        p = min(max(base_acc + d / 2, 0.01), 0.99)
        d = z * np.sqrt(2 * p * (1 - p) / n_eff)
    return d


def report(ns=(25, 50, 100, 200, 400), base_accs=(0.3, 0.5, 0.7)):
    print("Minimum detectable accuracy gap (wiki vs no-wiki), 80% power, alpha .05, per model.")
    print("Assumes ~2.5 scored items/school and intra-school correlation 0.3 (adjust in power.py after the pilot).\n")
    print("n/group | " + " | ".join(f"base acc {b:.0%}" for b in base_accs))
    for n in ns:
        print(f"{n:7d} | " + " | ".join(f"{mde(n, b):>11.1%}" for b in base_accs))
