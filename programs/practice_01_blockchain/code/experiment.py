"""Repeat PoW trials at four difficulties and create a log-scale chart."""
import csv
import random
import statistics
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from blockchain import Block

OUT = Path("../artifacts")
OUT.mkdir(exist_ok=True)
Path("../images").mkdir(exist_ok=True)
rows = []
for difficulty in (1, 2, 3, 4):
    times = []
    for _ in range(10):
        started = time.perf_counter()
        Block.mine(1, "0" * 64, [], difficulty)
        times.append(time.perf_counter() - started)
    avg = statistics.mean(times)
    spread = statistics.stdev(times)
    rows.append((difficulty, avg, spread, min(times), max(times)))
    print(f"difficulty={difficulty} mean={avg:.6f}s sd={spread:.6f}s min={min(times):.6f}s max={max(times):.6f}s")

with (OUT / "mining_results.csv").open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(("difficulty_hex_zeroes", "mean_seconds", "standard_deviation", "min_seconds", "max_seconds"))
    writer.writerows(rows)

plt.figure(figsize=(8, 4.8))
x = [r[0] for r in rows]
y = [r[1] for r in rows]
e = [r[2] for r in rows]
plt.errorbar(x, y, yerr=e, marker="o", capsize=5, linewidth=2)
plt.yscale("log")
plt.xticks(x)
plt.xlabel("Складність, кількість початкових нулів SHA-256")
plt.ylabel("Час майнінгу, с (логарифмічна шкала)")
plt.title("Залежність часу Proof of Work від складності")
plt.grid(True, which="both", linestyle=":", alpha=.6)
plt.tight_layout()
plt.savefig(OUT / "mining_experiment.png", dpi=180)
plt.savefig(Path("../images/mining_experiment.png"), dpi=180)
