#!/usr/bin/env python3
"""
Generate `demo.svg` - the animated demo embedded in the README.

The animation is not hand-drawn: it replays a *real* run of the algorithm by
walking the same structured event list the HTML visualizer consumes, so the
picture in the README can never drift from what the code actually does.

Output is a single self-contained SVG animated with CSS keyframes (no script,
no external assets), which is what GitHub renders inline in a README.

    python make_demo_svg.py                                  # regenerate demo.svg
    python make_demo_svg.py --seed 1 --out demo_wedged.svg   # the failure mode
"""

from __future__ import annotations

import argparse

from drunken_merge_sort import drunken_merge_sort

# --- canvas -----------------------------------------------------------------
W, H = 760, 400
BASELINE = 300
BAR_W = 64
INNER_GAP = 6          # gap between bars inside one block
BLOCK_GAP = 26         # gap between separate blocks
PAD = 8                # capsule padding around the bars it wraps
CAPSULE_Y, CAPSULE_H = 56, 278

# --- palette ----------------------------------------------------------------
BG, CARD_EDGE = "#0f1420", "#232b3b"
TITLE, SUBTLE = "#e6edf3", "#8b98ac"
LONE, FUSED, DONE, STUCK = "#4a5670", "#f0b429", "#3ddc97", "#f4696b"

# --- timing: seconds a frame stays on screen, by event kind -----------------
DUR = {"init": 1.8, "shuffle": 1.7, "fuse": 1.25, "absorb": 1.5, "coffee": 1.6,
       "sorted": 3.0, "passed_out": 3.0}


def fmt(elements):
    return "[" + ", ".join(str(v) for v in elements) + "]"


def escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def frames_from_run(values, seed, coffee):
    """Turn one run's event list into (blocks, caption, kind) animation frames."""
    result = drunken_merge_sort(values, seed=seed, coffee=coffee)
    events = result.events
    frames = []

    for i, event in enumerate(events):
        kind = event["type"]
        nxt = events[i + 1]["type"] if i + 1 < len(events) else None
        if kind == "init":
            text = "every element starts as its own block"
        elif kind == "shuffle":
            text = "stumble %d - the blocks stagger into a random new order" % event["stumble"]
            if nxt in ("shuffle", "sorted", "passed_out"):
                text += "   (nothing lines up)"
        elif kind == "fuse":
            text = "fuse %s + %s - max %d <= min %d, so they lock together" % (
                fmt(event["left"]["elements"]), fmt(event["right"]["elements"]),
                event["left"]["elements"][-1], event["right"]["elements"][0])
        elif kind == "absorb":
            text = "absorb: lone %d falls strictly inside its neighbour -> %s" % (
                event["value"], fmt(event["result"]["elements"]))
        elif kind == "coffee":
            text = "coffee: one interleave merge un-sticks the run -> %s" % fmt(
                event["result"]["elements"])
        elif kind == "sorted":
            text = "sorted in %d stumbles: %s" % (event["stumbles"], fmt(event["array"]))
        else:
            text = "passed out - no two blocks left can ever fuse"
        blocks = ([list(b["elements"]) for b in event["blocks"]]
                  if "blocks" in event else frames[-1][0])
        frames.append((blocks, text, kind))
    return frames, result


def layout(blocks):
    """Per-frame geometry: an x per value, plus one capsule per fused block."""
    widths = [len(b) * BAR_W + (len(b) - 1) * INNER_GAP for b in blocks]
    total = sum(widths) + BLOCK_GAP * (len(blocks) - 1)
    cursor = (W - total) / 2
    bar_x, capsules = {}, []
    for block, width in zip(blocks, widths):
        for k, value in enumerate(block):
            bar_x[value] = cursor + k * (BAR_W + INNER_GAP)
        if len(block) > 1:                     # lone elements get no capsule
            capsules.append((cursor - PAD, width + 2 * PAD))
        cursor += width + BLOCK_GAP
    return bar_x, capsules


def keyframes(name, stops):
    """`stops` is [(percent, declarations)], emitted as one @keyframes rule."""
    body = " ".join("%.4f%%{%s}" % (percent, decls) for percent, decls in stops)
    return "@keyframes %s{%s}" % (name, body)


def build(values, seed, coffee):
    frames, result = frames_from_run(values, seed, coffee)
    geo = [layout(blocks) for blocks, _, _ in frames]
    durations = [DUR[kind] for _, _, kind in frames]
    total = sum(durations)

    starts, elapsed = [], 0.0
    for duration in durations:
        starts.append(elapsed)
        elapsed += duration
    # How much of each frame is spent moving into it; the rest is a hold.
    move = [min(0.55 * duration, 0.75) for duration in durations]

    def pct(seconds):
        return 100.0 * seconds / total

    max_value = max(values)
    fused = [{v for b in blocks if len(b) > 1 for v in b} for blocks, _, _ in frames]
    accent = [DONE if kind == "sorted" else STUCK if kind == "passed_out" else FUSED
              for _, _, kind in frames]
    finished = [kind in ("sorted", "passed_out") for _, _, kind in frames]
    max_capsules = max(len(capsules) for _, capsules in geo)

    css, body = [], []

    # --- bars: slide to their new slot, and change colour as they sober up --
    for value in sorted(values):
        height = 36 + 196 * value / max_value

        def bar_decls(i):
            colour = accent[i] if (finished[i] or value in fused[i]) else LONE
            return "transform:translateX(%.1fpx);fill:%s" % (geo[i][0][value], colour)

        stops = [(0.0, bar_decls(0))]
        for i in range(1, len(frames)):
            stops.append((pct(starts[i]), bar_decls(i - 1)))
            stops.append((pct(starts[i] + move[i]), bar_decls(i)))
        stops.append((100.0, stops[-1][1]))
        css.append(keyframes("bar%d" % value, stops))
        css.append(".b%d{animation-name:bar%d}" % (value, value))
        # The static attributes are the first frame: that is what a
        # reduced-motion renderer, which drops the animation, will show.
        body.append(
            '<g class="bar b%d" transform="translate(%.1f,0)" fill="%s">'
            '<rect y="%.1f" width="%d" height="%.1f" rx="9"/>'
            '<text class="lab" x="%d" y="%d">%d</text></g>'
            % (value, geo[0][0][value], LONE, BASELINE - height, BAR_W, height,
               BAR_W // 2, BASELINE + 26, value))

    # --- capsules: the visible "these are one block now" grouping -----------
    for k in range(max_capsules):
        def capsule_decls(i):
            capsules = geo[i][1]
            if k >= len(capsules):
                return "opacity:0"
            x, width = capsules[k]
            return ("x:%.1fpx;width:%.1fpx;opacity:.9;stroke:%s;fill:%s"
                    % (x, width, accent[i], accent[i]))

        stops = [(0.0, capsule_decls(0))]
        for i in range(1, len(frames)):
            stops.append((pct(starts[i]), capsule_decls(i - 1)))
            stops.append((pct(starts[i] + move[i]), capsule_decls(i)))
        stops.append((100.0, stops[-1][1]))
        css.append(keyframes("cap%d" % k, stops))
        css.append(".c%d{animation-name:cap%d}" % (k, k))
        body.append('<rect class="cap c%d" y="%d" height="%d" rx="14" opacity="0"/>'
                    % (k, CAPSULE_Y, CAPSULE_H))

    # --- caption + block counter: hard cuts, exactly one visible per frame --
    # `fill-opacity` rides along with `opacity` on purpose: an opacity-only
    # animation is composited, and some renderers then never advance it.
    on, off = "opacity:1;fill-opacity:1", "opacity:0;fill-opacity:0"
    for i, (blocks, text, _) in enumerate(frames):
        show, hide = pct(starts[i]), pct(starts[i] + durations[i])
        stops = [(0.0, off), (max(show - 0.01, 0.0), off),
                 (show, on), (max(hide - 0.01, show), on)]
        if hide < 100.0:
            stops.append((hide, off))
        stops.append((100.0, on if hide >= 100.0 else off))
        css.append(keyframes("cue%d" % i, stops))
        css.append(".u%d{animation-name:cue%d}" % (i, i))
        visible = 1 if i == 0 else 0   # static fallback = the first frame
        body.append('<text class="cue u%d caption" x="%d" y="356" opacity="%d">%s</text>'
                    % (i, W // 2, visible, escape(text)))
        body.append('<text class="cue u%d count" x="%d" y="34" opacity="%d">%d block%s</text>'
                    % (i, W - 32, visible, len(blocks), "" if len(blocks) == 1 else "s"))

    style = """
    .card{fill:%s;stroke:%s}
    .bar rect{filter:drop-shadow(0 2px 6px rgba(0,0,0,.45))}
    .lab{font:600 17px ui-monospace,SFMono-Regular,Menlo,monospace;text-anchor:middle;fill:#c9d4e6}
    .cap{fill-opacity:.12;stroke-width:1.5}
    .title{font:600 15px ui-monospace,SFMono-Regular,Menlo,monospace;fill:%s}
    .count{font:600 13px ui-monospace,SFMono-Regular,Menlo,monospace;fill:%s;text-anchor:end}
    .caption{font:400 15px ui-monospace,SFMono-Regular,Menlo,monospace;fill:%s;text-anchor:middle}
    .base{stroke:%s;stroke-width:1}
    .bar,.cap{animation-duration:%.2fs;animation-iteration-count:infinite;
              animation-timing-function:cubic-bezier(.34,.9,.3,1);animation-fill-mode:both}
    .cue{animation-duration:%.2fs;animation-iteration-count:infinite;
         animation-timing-function:linear;animation-fill-mode:both}
    @media (prefers-reduced-motion:reduce){.bar,.cap,.cue{animation:none}}
    """ % (BG, CARD_EDGE, TITLE, SUBTLE, TITLE, CARD_EDGE, total, total)

    header = ('<text class="title" x="32" y="34">drunken_merge_sort(%s, seed=%d)%s</text>'
              % (fmt(values), seed, ", coffee" if coffee else ""))
    baseline = ('<line class="base" x1="32" y1="%d" x2="%d" y2="%d"/>'
                % (BASELINE + 1, W - 32, BASELINE + 1))

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
        'role="img" aria-label="Animated replay of Drunken Merge Sort on %s">'
        '<style>%s %s</style>'
        '<rect class="card" x=".5" y=".5" width="%d" height="%d" rx="16"/>'
        '%s%s%s</svg>'
    ) % (W, H, W, H, fmt(values), " ".join(style.split()), "".join(css), W - 1, H - 1,
         header, baseline, "".join(body))
    return svg, result


def main():
    parser = argparse.ArgumentParser(description="Generate the animated README demo.")
    parser.add_argument("--values", default="5,3,8,1,9,6")
    parser.add_argument("--seed", type=int, default=59)
    parser.add_argument("--coffee", action="store_true")
    parser.add_argument("--out", default="demo.svg")
    args = parser.parse_args()

    values = [int(v) for v in args.values.split(",")]
    svg, result = build(values, args.seed, args.coffee)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(svg)
    print("%s written (%d events, status=%s, %d stumbles, %.1f KB)"
          % (args.out, len(result.events), result.status, result.stumbles,
             len(svg) / 1024))


if __name__ == "__main__":
    main()
