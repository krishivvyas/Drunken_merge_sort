#!/usr/bin/env python3
"""
Benchmark: Drunken Merge Sort vs Bogosort vs Insertion Sort vs Timsort.

Runs every algorithm on the *same* random arrays of increasing size and reports
wall-clock time plus each algorithm's natural work counter:

    Drunken Merge Sort  stumbles (random block permutations)
    Bogosort            shuffles (random full-array permutations)
    Insertion Sort      comparisons
    Timsort             - (CPython builtin; no instrumentation)

Three Drunken Merge Sort variants are measured:

    pure    - the algorithm exactly as specified. It can wedge permanently,
              so its success rate is the interesting number, not its speed.
    coffee  - same, but when wedged it is allowed one interleave merge, which
              guarantees termination (see README).
    restart - same, but a wedge means "sober up and start the night over".
              This is the variant that is a fair race against Bogosort: both
              are then pure shuffle-until-lucky algorithms.

Usage:
    python benchmark.py                       # default sweep
    python benchmark.py --sizes 4 6 8 --chart # custom sizes + PNG chart
"""

from __future__ import annotations

import argparse
import random
import time
from statistics import mean

from drunken_merge_sort import drunken_merge_sort, drunken_merge_sort_restarting, random_array


# ---------------------------------------------------------------------------
# Reference algorithms
# ---------------------------------------------------------------------------

def is_sorted(seq) -> bool:
    return all(seq[i] <= seq[i + 1] for i in range(len(seq) - 1))


def bogosort(values, rng, max_shuffles):
    """Shuffle the whole array until it happens to be sorted.

    Returns (array, shuffles, finished).
    """
    arr = list(values)
    shuffles = 0
    while not is_sorted(arr):
        if shuffles >= max_shuffles:
            return arr, shuffles, False
        rng.shuffle(arr)
        shuffles += 1
    return arr, shuffles, True


def insertion_sort(values):
    """Textbook insertion sort, counting comparisons."""
    arr = list(values)
    comparisons = 0
    for i in range(1, len(arr)):
        key = arr[i]
        j = i - 1
        while j >= 0:
            comparisons += 1
            if arr[j] <= key:
                break
            arr[j + 1] = arr[j]
            j -= 1
        arr[j + 1] = key
    return arr, comparisons


def timsort(values):
    """CPython's built-in sort."""
    return sorted(values), None


# ---------------------------------------------------------------------------
# Measurement helpers
# ---------------------------------------------------------------------------

class Stat:
    """Accumulates timings, work counters and completion outcomes."""

    def __init__(self, label):
        self.label = label
        self.times_ms = []
        self.counts = []
        self.finished = 0
        self.trials = 0

    def add(self, ms, count, finished=True):
        self.trials += 1
        self.times_ms.append(ms)
        if count is not None:
            self.counts.append(count)
        if finished:
            self.finished += 1

    @property
    def mean_ms(self):
        return mean(self.times_ms) if self.times_ms else float("nan")

    @property
    def mean_count(self):
        return mean(self.counts) if self.counts else None

    @property
    def success_rate(self):
        return self.finished / self.trials if self.trials else 0.0

    def time_cell(self):
        return "%.3f" % self.mean_ms

    def count_cell(self):
        if self.mean_count is None:
            return "-"
        return "{:,.0f}".format(self.mean_count)


def trials_for(n, base):
    """Fewer trials as n grows, so the sweep stays interruptible."""
    if n <= 8:
        return base
    if n <= 10:
        return max(3, base // 8)
    return max(1, base // 20)


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------

def run_sweep(sizes, trials, bogo_cap, drunk_cap, drunk_trials, seed):
    """Run every algorithm on shared inputs. Returns {n: {name: Stat}}."""
    results = {}

    for n in sizes:
        t_generic = trials_for(n, trials)
        stats = {
            "drunk_pure": Stat("Drunken Merge Sort (pure)"),
            "drunk_coffee": Stat("Drunken Merge Sort (coffee)"),
            "drunk_restart": Stat("Drunken Merge Sort (restart)"),
            "bogo": Stat("Bogosort"),
            "insertion": Stat("Insertion Sort"),
            "timsort": Stat("Timsort"),
        }

        # -- Drunken Merge Sort gets its own (larger) trial count: it is cheap, and its
        #    success rate needs a decent sample to mean anything.
        restart_trials = max(10, drunk_trials // (4 if n >= 12 else 1))
        for t in range(drunk_trials):
            arr = random_array(n, seed=seed + 7919 * n + t)

            start = time.perf_counter()
            res = drunken_merge_sort(arr, seed=seed + t, max_stumbles=drunk_cap,
                             record_events=False)
            elapsed = (time.perf_counter() - start) * 1000
            stats["drunk_pure"].add(elapsed, res.stumbles, res.ok)

            start = time.perf_counter()
            res_c = drunken_merge_sort(arr, seed=seed + t, max_stumbles=drunk_cap,
                               record_events=False, coffee=True)
            elapsed = (time.perf_counter() - start) * 1000
            stats["drunk_coffee"].add(elapsed, res_c.stumbles, res_c.ok)
            assert res_c.array == sorted(arr), "coffee mode must always sort"

            if t >= restart_trials:
                continue
            start = time.perf_counter()
            res_r, total_stumbles, _ = drunken_merge_sort_restarting(
                arr, seed=seed + t, max_stumbles=drunk_cap)
            elapsed = (time.perf_counter() - start) * 1000
            stats["drunk_restart"].add(elapsed, total_stumbles, res_r.ok)

        # -- The classical algorithms on shared inputs.
        rng = random.Random(seed)
        for t in range(t_generic):
            arr = random_array(n, seed=seed + 7919 * n + t)

            start = time.perf_counter()
            out, shuffles, done = bogosort(arr, rng, bogo_cap)
            elapsed = (time.perf_counter() - start) * 1000
            stats["bogo"].add(elapsed, shuffles, done)

            start = time.perf_counter()
            out, comparisons = insertion_sort(arr)
            elapsed = (time.perf_counter() - start) * 1000
            stats["insertion"].add(elapsed, comparisons)
            assert out == sorted(arr)

            start = time.perf_counter()
            out, _ = timsort(arr)
            elapsed = (time.perf_counter() - start) * 1000
            stats["timsort"].add(elapsed, None)

        results[n] = stats
        print("  n=%-3d done  (drunk pure success %.0f%%, bogo success %.0f%%)"
              % (n, 100 * stats["drunk_pure"].success_rate,
                 100 * stats["bogo"].success_rate))

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

ORDER = ["drunk_pure", "drunk_coffee", "drunk_restart", "bogo",
         "insertion", "timsort"]


def markdown_tables(results, sizes, bogo_cap, drunk_cap, drunk_trials):
    lines = []
    add = lines.append

    add("### Wall-clock time (mean ms per run)\n")
    add("| n | " + " | ".join(results[sizes[0]][k].label for k in ORDER) + " |")
    add("|---" * (len(ORDER) + 1) + "|")
    for n in sizes:
        row = ["%d" % n] + [results[n][k].time_cell() for k in ORDER]
        add("| " + " | ".join(row) + " |")

    add("\n### Work done (mean iterations / comparisons per run)\n")
    add("| n | Drunken Merge stumbles (pure) | Drunken Merge stumbles (coffee) | "
        "Drunken Merge stumbles (restart) | Bogo shuffles | Insertion comparisons |")
    add("|---|---|---|---|---|---|")
    for n in sizes:
        s = results[n]
        add("| %d | %s | %s | %s | %s | %s |"
            % (n, s["drunk_pure"].count_cell(), s["drunk_coffee"].count_cell(),
               s["drunk_restart"].count_cell(), s["bogo"].count_cell(),
               s["insertion"].count_cell()))

    add("\n### Did it actually finish?\n")
    add("| n | Drunken Merge (pure) sorted | Drunken Merge (coffee) sorted | "
        "Drunken Merge (restart) sorted | Bogosort finished within cap |")
    add("|---|---|---|---|---|")
    for n in sizes:
        s = results[n]
        add("| %d | %.0f%% | %.0f%% | %.0f%% | %.0f%% |"
            % (n, 100 * s["drunk_pure"].success_rate,
               100 * s["drunk_coffee"].success_rate,
               100 * s["drunk_restart"].success_rate,
               100 * s["bogo"].success_rate))

    add("")
    add("_Caps: Bogosort %s shuffles, Drunken Merge Sort %s stumbles. "
        "Drunken Merge Sort trials per size: %d._"
        % ("{:,}".format(bogo_cap), "{:,}".format(drunk_cap), drunk_trials))
    add("")
    add("A pure Drunken Merge Sort run that does not sort ended **wedged**, not timed "
        "out: no two surviving blocks can fuse in any arrangement, so no "
        "amount of extra shuffling would have helped.")
    return "\n".join(lines)


def draw_chart(results, sizes, path):
    """Optional matplotlib chart. Returns True if it was written."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    fig, (ax_t, ax_c) = plt.subplots(1, 2, figsize=(12, 4.5))
    palette = {
        "drunk_pure": "#e0679a",
        "drunk_coffee": "#f2b134",
        "drunk_restart": "#5aa9e6",
        "bogo": "#8b7ff0",
        "insertion": "#4bb3a8",
        "timsort": "#7f8ea3",
    }

    for key in ORDER:
        ax_t.plot(sizes, [results[n][key].mean_ms for n in sizes],
                  marker="o", label=results[sizes[0]][key].label,
                  color=palette[key])
    ax_t.set_yscale("log")
    ax_t.set_xlabel("n")
    ax_t.set_ylabel("mean time (ms, log scale)")
    ax_t.set_title("Wall-clock time")
    ax_t.grid(alpha=0.25)
    ax_t.legend(fontsize=8)

    for key in ("drunk_pure", "drunk_coffee", "drunk_restart",
                "bogo", "insertion"):
        values = [results[n][key].mean_count for n in sizes]
        if any(v is None for v in values):
            continue
        ax_c.plot(sizes, values, marker="o",
                  label=results[sizes[0]][key].label, color=palette[key])
    ax_c.set_yscale("log")
    ax_c.set_xlabel("n")
    ax_c.set_ylabel("mean iterations (log scale)")
    ax_c.set_title("Work done")
    ax_c.grid(alpha=0.25)
    ax_c.legend(fontsize=8)

    fig.suptitle("Drunken Merge Sort benchmark", fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    return True


def main():
    parser = argparse.ArgumentParser(description="Benchmark Drunken Merge Sort.")
    parser.add_argument("--sizes", type=int, nargs="+",
                        default=[4, 6, 8, 10, 12])
    parser.add_argument("--trials", type=int, default=20,
                        help="trials per size for the classical algorithms")
    parser.add_argument("--drunk-trials", type=int, default=200,
                        help="trials per size for Drunken Merge Sort (it is cheap)")
    parser.add_argument("--bogo-cap", type=int, default=2_000_000,
                        help="max Bogosort shuffles before giving up")
    parser.add_argument("--drunk-cap", type=int, default=10_000,
                        help="max Drunken Merge Sort stumbles before passing out")
    parser.add_argument("--seed", type=int, default=20260830)
    parser.add_argument("--out", type=str, default="benchmark_results.md")
    parser.add_argument("--chart", action="store_true",
                        help="also render benchmark_chart.png (needs matplotlib)")
    args = parser.parse_args()

    sizes = sorted(args.sizes)
    print("Benchmarking sizes %s ..." % sizes)
    started = time.perf_counter()
    results = run_sweep(sizes, args.trials, args.bogo_cap, args.drunk_cap,
                        args.drunk_trials, args.seed)
    total = time.perf_counter() - started

    tables = markdown_tables(results, sizes, args.bogo_cap, args.drunk_cap,
                             args.drunk_trials)
    print()
    print(tables)

    chart_note = ""
    if args.chart:
        if draw_chart(results, sizes, "benchmark_chart.png"):
            chart_note = "\n![Benchmark chart](benchmark_chart.png)\n"
            print("\nchart written to benchmark_chart.png")
        else:
            print("\nmatplotlib not installed - skipping chart")

    header = (
        "# Drunken Merge Sort - benchmark results\n\n"
        "Generated by `benchmark.py` (seed %d, sweep took %.1fs).\n"
        % (args.seed, total)
    )
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(header + "\n" + tables + "\n" + chart_note)
    print("\nresults written to %s" % args.out)


if __name__ == "__main__":
    main()
