#!/usr/bin/env python3
"""
Drunken Merge Sort
==================

A novelty / educational sorting algorithm. The name is the joke; the algorithm
itself is a real (if terrible) randomized construction that is worth studying.

The idea
--------
Every element starts as its own *block*. A block is a contiguous logical group
holding an internally sorted list of values, plus its min and max. On each
iteration ("stumble") we randomly permute the *sequence of blocks* - blocks
move as units, like a drunk person stumbling into a new arrangement - and then
look for accidental order:

  * FUSION     - adjacent blocks A, B where max(A) <= min(B) fuse into one
                 block. Fusions are permanent: a fused block has "sobered up"
                 and never breaks apart again.
  * ABSORPTION - a lone unfused element whose value falls strictly between the
                 min and max of an adjacent block gets slotted into that block
                 at its correct internal position.

Repeat until a single block remains: that block is the sorted array.

Honesty notice
--------------
This is an exploratory/educational algorithm, not an efficient one. It is
*worse* than Bogosort as n grows and - unlike Bogosort - it is not even
guaranteed to finish. See `is_wedged()` and the README for why.

Every state change is recorded in a structured event list so the visualizer can
replay and animate the run.
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
from bisect import bisect_left
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Core data structure
# ---------------------------------------------------------------------------

@dataclass
class Block:
    """A group of values that has locked into sorted order.

    `elements` is always kept internally sorted, so the block's min and max are
    just its first and last entries.
    """

    id: int
    elements: list

    @property
    def lo(self):
        """Minimum value in the block."""
        return self.elements[0]

    @property
    def hi(self):
        """Maximum value in the block."""
        return self.elements[-1]

    @property
    def is_singleton(self) -> bool:
        """True while this element is still 'unfused' (a block of one)."""
        return len(self.elements) == 1

    def snapshot(self) -> dict:
        return {"id": self.id, "elements": list(self.elements)}


def snapshot_all(blocks) -> list:
    return [b.snapshot() for b in blocks]


# ---------------------------------------------------------------------------
# Event log (drives the animated visualizer)
# ---------------------------------------------------------------------------

class EventLog:
    """Structured, replayable record of everything that happened.

    Each event carries a full `blocks` snapshot of the arrangement *after* the
    event, which keeps the visualizer's replay logic trivial and robust.
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.events = []

    def emit(self, kind: str, **payload) -> None:
        if self.enabled:
            self.events.append(dict(type=kind, **payload))


# ---------------------------------------------------------------------------
# Step 2: the stumble (random permutation of blocks)
# ---------------------------------------------------------------------------

def shuffle_blocks(blocks, rng):
    """Randomly permute the sequence of blocks. Blocks move as whole units."""
    stumbled = list(blocks)
    rng.shuffle(stumbled)
    return stumbled


# ---------------------------------------------------------------------------
# Step 3: scan-and-fuse adjacent blocks
# ---------------------------------------------------------------------------

def find_fusible_pair(blocks):
    """Index i of the first adjacent pair with max(blocks[i]) <= min(blocks[i+1])."""
    for i in range(len(blocks) - 1):
        if blocks[i].hi <= blocks[i + 1].lo:
            return i
    return None


def scan_and_fuse(blocks, log, next_id) -> bool:
    """Fuse adjacent fusible pairs until none remain. Mutates `blocks` in place.

    Returns True if at least one fusion happened.
    """
    changed = False
    while True:
        i = find_fusible_pair(blocks)
        if i is None:
            return changed
        left, right = blocks[i], blocks[i + 1]
        # Plain concatenation is already sorted because max(left) <= min(right).
        merged = Block(next_id(), left.elements + right.elements)
        blocks[i:i + 2] = [merged]
        changed = True
        log.emit(
            "fuse",
            at=i,
            left=left.snapshot(),
            right=right.snapshot(),
            result=merged.snapshot(),
            blocks=snapshot_all(blocks),
        )


# ---------------------------------------------------------------------------
# Step 4: single-element absorption
# ---------------------------------------------------------------------------

def find_absorption(blocks):
    """Find (singleton_index, block_index) for a legal absorption.

    A lone unfused element is absorbed by an *adjacent* block when its value
    lies strictly inside that block's [min, max] range.
    """
    for i, blk in enumerate(blocks):
        if not blk.is_singleton:
            continue
        value = blk.lo
        for j in (i - 1, i + 1):
            if 0 <= j < len(blocks):
                neighbour = blocks[j]
                if neighbour.lo < value < neighbour.hi:
                    return i, j
    return None


def absorb_singletons(blocks, log) -> bool:
    """Absorb lone elements into adjacent blocks until none can be. In place.

    Returns True if at least one absorption happened.
    """
    changed = False
    while True:
        hit = find_absorption(blocks)
        if hit is None:
            return changed
        i, j = hit
        loner, target = blocks[i], blocks[j]
        value = loner.lo
        # Slot it into the block's correct internal sorted position.
        position = bisect_left(target.elements, value)
        target.elements.insert(position, value)
        del blocks[i]
        changed = True
        log.emit(
            "absorb",
            value=value,
            element_id=loner.id,
            into=target.id,
            index=position,
            result=target.snapshot(),
            blocks=snapshot_all(blocks),
        )


def settle(blocks, log, next_id) -> bool:
    """Run fuse and absorb passes to fixpoint after a stumble."""
    settled_anything = False
    while True:
        changed = scan_and_fuse(blocks, log, next_id)
        changed |= absorb_singletons(blocks, log)
        if not changed:
            return settled_anything
        settled_anything = True


# ---------------------------------------------------------------------------
# Deadlock ("wedged") detection
# ---------------------------------------------------------------------------

def is_wedged(blocks) -> bool:
    """True when no future shuffle could ever make progress.

    Blocks only ever grow, so if *no ordering at all* admits a fusion and no
    absorption is possible, the run is permanently stuck. Example: the values
    {1, 4, 6, 10} can reach blocks [1,10] and [4,6] - neither ordering fuses
    (their ranges nest) and neither is a lone element, so absorption cannot
    apply either. Detecting this lets us fail fast and honestly instead of
    burning the whole iteration cap on a hopeless run.
    """
    if len(blocks) <= 1:
        return False
    for a in blocks:
        for b in blocks:
            if a is not b and a.hi <= b.lo:
                return False  # some arrangement would fuse these
    for loner in blocks:
        if loner.is_singleton:
            value = loner.lo
            for other in blocks:
                if other is not loner and other.lo < value < other.hi:
                    return False  # some arrangement would absorb this
    return True


def pour_coffee(blocks, log, next_id) -> None:
    """Optional rescue: interleave-merge the first two blocks in the arrangement.

    Only ever used when the run is wedged and coffee mode is enabled. Merging
    two sorted blocks by interleaving is exactly natural merge sort's merge
    step - which is precisely the "sober" algorithm hiding underneath all of
    this. With coffee enabled, termination is guaranteed.
    """
    left, right = blocks[0], blocks[1]
    merged = Block(next_id(), sorted(left.elements + right.elements))
    blocks[0:2] = [merged]
    log.emit(
        "coffee",
        left=left.snapshot(),
        right=right.snapshot(),
        result=merged.snapshot(),
        blocks=snapshot_all(blocks),
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

@dataclass
class DrunkenMergeSortResult:
    """Outcome of a run."""

    array: list                 # flattened final arrangement
    original: list
    status: str                 # "sorted" | "wedged" | "passed_out"
    stumbles: int
    block_history: list         # number of blocks after each stumble
    events: list = field(default_factory=list)
    seed: int = None

    @property
    def ok(self) -> bool:
        return self.status == "sorted" and self.array == sorted(self.original)

    @property
    def message(self) -> str:
        return {
            "sorted":
                "Sorted in %d stumbles." % self.stumbles,
            "wedged":
                "Drunken Merge Sort got wedged after %d stumbles - no two remaining "
                "blocks can ever fuse, in any arrangement." % self.stumbles,
            "passed_out":
                "Drunken Merge Sort passed out before finishing (hit the %d-stumble "
                "cap)." % self.stumbles,
        }[self.status]


def drunken_merge_sort(values, seed=None, max_stumbles=10_000,
               record_events=True, coffee=False) -> DrunkenMergeSortResult:
    """Sort `values` by stumbling around until order accidentally emerges.

    Args:
        values:        iterable of distinct comparable values.
        seed:          RNG seed, for reproducible runs.
        max_stumbles:  safety cap; exceeding it means "passed out".
        record_events: build the replayable event list (turn off to benchmark).
        coffee:        when wedged, allow one interleave merge to un-stick the
                       run instead of giving up. Guarantees termination.
    """
    values = list(values)
    rng = random.Random(seed)
    log = EventLog(record_events)
    ids = itertools.count(len(values))
    next_id = lambda: next(ids)  # noqa: E731 - tiny id factory

    blocks = [Block(i, [v]) for i, v in enumerate(values)]
    log.emit("init", values=list(values), blocks=snapshot_all(blocks))

    history = [len(blocks)]
    stumbles = 0
    status = "sorted"

    while len(blocks) > 1:
        if is_wedged(blocks):
            if coffee:
                pour_coffee(blocks, log, next_id)
                settle(blocks, log, next_id)
                history.append(len(blocks))
                continue
            status = "wedged"
            break
        if stumbles >= max_stumbles:
            status = "passed_out"
            break

        stumbles += 1
        blocks = shuffle_blocks(blocks, rng)
        log.emit(
            "shuffle",
            stumble=stumbles,
            order=[b.id for b in blocks],
            blocks=snapshot_all(blocks),
        )
        settle(blocks, log, next_id)
        history.append(len(blocks))

    flattened = [v for b in blocks for v in b.elements]
    if status == "sorted":
        log.emit("sorted", stumbles=stumbles, array=list(flattened))
    else:
        log.emit("passed_out", stumbles=stumbles, reason=status,
                 blocks=snapshot_all(blocks))

    return DrunkenMergeSortResult(
        array=flattened,
        original=values,
        status=status,
        stumbles=stumbles,
        block_history=history,
        events=log.events,
        seed=seed,
    )


def drunken_merge_sort_restarting(values, seed=None, max_attempts=100_000,
                          max_stumbles=10_000):
    """Variant: on a wedge, sober up completely and start the night over.

    Pure Drunken Merge Sort usually wedges, so on its own it is not a sorting algorithm
    at all. Restarting from scratch makes it one again (with probability 1),
    and it is the fair variant to race against Bogosort - both then are
    "shuffle until you get lucky" algorithms.

    Returns (result_of_the_winning_run, total_stumbles, attempts).
    """
    values = list(values)
    total_stumbles = 0
    for attempt in range(1, max_attempts + 1):
        # A fresh seed per attempt, so restarts explore different nights out.
        attempt_seed = None if seed is None else seed * 100_003 + attempt
        result = drunken_merge_sort(values, seed=attempt_seed,
                            max_stumbles=max_stumbles, record_events=False)
        total_stumbles += result.stumbles
        if result.status == "sorted":
            return result, total_stumbles, attempt
    return result, total_stumbles, max_attempts


def random_array(n, seed=None, lo=1, hi=99):
    """n distinct random integers drawn from [lo, hi]."""
    rng = random.Random(seed)
    return rng.sample(range(lo, hi + 1), n)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Run Drunken Merge Sort.")
    parser.add_argument("-n", type=int, default=8, help="array size (default 8)")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed")
    parser.add_argument("--values", type=str, default=None,
                        help="comma-separated values to sort instead of random")
    parser.add_argument("--max-stumbles", type=int, default=10_000)
    parser.add_argument("--coffee", action="store_true",
                        help="allow an interleave merge when wedged")
    parser.add_argument("--events", type=str, default=None,
                        help="write the event list to this JSON file")
    parser.add_argument("--trace", action="store_true", help="print every event")
    args = parser.parse_args()

    if args.values:
        values = [int(v) for v in args.values.split(",")]
    else:
        values = random_array(args.n, seed=args.seed)

    print("input : %s" % values)
    result = drunken_merge_sort(values, seed=args.seed,
                        max_stumbles=args.max_stumbles, coffee=args.coffee)

    if args.trace:
        for event in result.events:
            kind = event["type"]
            if kind == "shuffle":
                print("  #%4d shuffle -> %s"
                      % (event["stumble"],
                         [b["elements"] for b in event["blocks"]]))
            elif kind == "fuse":
                print("        fuse   %s + %s = %s"
                      % (event["left"]["elements"], event["right"]["elements"],
                         event["result"]["elements"]))
            elif kind == "absorb":
                print("        absorb %s into %s"
                      % (event["value"], event["result"]["elements"]))
            elif kind == "coffee":
                print("        coffee %s + %s = %s"
                      % (event["left"]["elements"], event["right"]["elements"],
                         event["result"]["elements"]))

    print("output: %s" % result.array)
    print("status: %s" % result.message)
    print("blocks over time: %s" % result.block_history)
    print("correct: %s" % result.ok)

    if args.events:
        with open(args.events, "w", encoding="utf-8") as handle:
            json.dump({
                "input": values,
                "seed": args.seed,
                "status": result.status,
                "stumbles": result.stumbles,
                "events": result.events,
            }, handle, indent=2)
        print("events written to %s (%d events)"
              % (args.events, len(result.events)))


if __name__ == "__main__":
    main()
