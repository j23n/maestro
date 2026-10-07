#!/usr/bin/env python3
"""Check WCAG contrast for the colour pairs the UI actually uses (docs/07 § Layout rules).

Usage: python3 scripts/check-contrast.py [design/tokens.json]
Text pairs need 4.5:1; control boundaries 3:1. `divider` and `subtle` are decorative and exempt;
`warning` is a border colour only (warning text uses `warningText`). Add a pair here whenever a view
combines two tokens in a new way. Exits 1 on any failure.
"""
import json
import sys

TEXT = [  # (foreground, background)
    ("ink", "background"), ("ink", "surface"), ("ink", "subtle"), ("ink", "accentTint"), ("ink", "warningBackground"),
    ("secondary", "background"), ("secondary", "surface"), ("secondary", "subtle"),
    ("accent", "background"), ("accent", "surface"), ("accent", "accentTint"),
    ("onAccent", "accent"), ("onAccent", "accentPressed"),
    ("warningText", "warningBackground"), ("warningText", "warningInputBackground"),
    ("success", "background"), ("success", "surface"),
]
CONTROL = [  # boundaries that identify a control
    ("inputBorder", "background"), ("inputBorder", "surface"),
    ("switchOff", "background"), ("switchOff", "surface"),
    ("warning", "warningInputBackground"), ("warning", "background"),
    ("accent", "background"), ("ink", "background"),
]


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "design/tokens.json"
    colours = json.load(open(path))["color"]
    failures = 0
    for mode, palette in colours.items():
        for pairs, minimum, kind in ((TEXT, 4.5, "text"), (CONTROL, 3.0, "control")):
            for fg, bg in pairs:
                r = ratio(palette[fg], palette[bg])
                if r < minimum:
                    failures += 1
                    print(f"FAIL {mode:5} {kind:7} {fg} on {bg}: {r:.2f} < {minimum}")
    print("contrast OK" if not failures else f"{failures} contrast failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
