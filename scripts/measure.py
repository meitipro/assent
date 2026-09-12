"""Measure the test count and the mutation table, and write them into the docs.

Never type a test count into a README. A README claiming a number nobody checked
is the first thing a reviewer catches, and a stale one is worse than none.

    python scripts/measure.py            # report the measured numbers
    python scripts/measure.py --write    # substitute them into README.md
    python scripts/measure.py --style    # the house style check alone

The README carries paired markers and everything between them is generated:

    <!-- measured:tests -->    ... <!-- /measured:tests -->
    <!-- measured:mutations --> ... <!-- /measured:mutations -->
"""

import argparse
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"


def measure_tests():
    """Run the suite and return (passed, skipped) as measured, not as claimed."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    )
    out = proc.stdout + proc.stderr
    m = re.search(r"(\d+) passed(?:, (\d+) skipped)?", out)
    if not m:
        raise SystemExit("could not read a result line from pytest:\n" + out[-2000:])
    if proc.returncode != 0:
        raise SystemExit("the suite is not green; refusing to write a number")
    return int(m.group(1)), int(m.group(2) or 0)


def measure_mutations():
    """Run the mutation pass and return its markdown table plus the counts."""
    proc = subprocess.run(
        [sys.executable, "scripts/mutate.py", "--md"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            "a mutation escaped; the table would be a lie:\n" + proc.stderr[-2000:]
        )
    table = proc.stdout.strip()
    # Drop the header and the separator, then count what is left. Counting by
    # prefix is what got this wrong once: the separator line "|---|---|" has no
    # space after the pipe, so it slipped past the filter and the slice ate a
    # real row instead.
    lines = [ln for ln in table.split("\n") if ln.strip()]
    return table, max(0, len(lines) - 2)


# House style: the spaced hyphen is the only connector, and three full stops
# are the only ellipsis. Nine characters are refused. They are built from their
# code points rather than written out, or this file would contain every
# character it bans and report itself on every clean run.
BANNED = {
    chr(0x2014): "em dash",
    chr(0x2013): "en dash",
    chr(0x00B7): "middle dot",
    chr(0x2022): "bullet",
    chr(0x2026): "ellipsis",
    chr(0x2010): "hyphen",
    chr(0x2012): "figure dash",
    chr(0x2015): "horizontal bar",
    chr(0x2212): "minus sign",
}
TEXT_SUFFIXES = {".md", ".py", ".sh", ".svg", ".yaml", ".txt", ".ini"}
TEXT_NAMES = {".gitignore", ".gitattributes", ".env.example", "LICENSE"}
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", "artifacts"}


def check_style(root=ROOT):
    """Refuse to go on while any of the nine characters is in any text file.

    Enforced here rather than remembered, because remembering has failed on
    every project in this line that relied on it. Returns the number of files
    scanned so a caller can print it; raises SystemExit naming every hit.
    """
    hits = []
    scanned = 0
    for p in sorted(pathlib.Path(root).rglob("*")):
        if not p.is_file() or SKIP_DIRS & set(p.parts):
            continue
        if p.suffix not in TEXT_SUFFIXES and p.name not in TEXT_NAMES:
            continue
        scanned += 1
        text = p.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(text.split("\n"), 1):
            for ch, name in BANNED.items():
                if ch in line:
                    hits.append("%s:%d  %s (U+%04X)"
                                % (p.relative_to(root), i, name, ord(ch)))
    if hits:
        raise SystemExit(
            "house style: %d banned character(s); the spaced hyphen is the only "
            "connector and ... the only ellipsis:\n  " % len(hits)
            + "\n  ".join(hits)
        )
    return scanned


def substitute(text, name, body):
    open_tag = "<!-- measured:%s -->" % name
    close_tag = "<!-- /measured:%s -->" % name
    if open_tag not in text or close_tag not in text:
        raise SystemExit("README is missing the %s markers" % name)
    head = text.split(open_tag, 1)[0]
    tail = text.split(close_tag, 1)[1]
    return head + open_tag + "\n" + body + "\n" + close_tag + tail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--style", action="store_true", help="run the style check alone")
    args = ap.parse_args()

    scanned = check_style()
    print("  style      : clean, %d characters checked in %d files"
          % (len(BANNED), scanned))
    if args.style:
        return 0

    passed, skipped = measure_tests()
    table, n_mutations = measure_mutations()

    print("  tests      : %d passed, %d skipped" % (passed, skipped))
    print("  mutations  : %d, all caught" % n_mutations)

    if not args.write:
        return 0

    text = README.read_text(encoding="utf-8")
    line = ("`pytest tests/ -q` reports **%d passed, %d skipped**, and every one "
            "of the **%d** mutations below is caught." % (passed, skipped, n_mutations))
    text = substitute(text, "tests", line)
    text = substitute(text, "mutations", table)
    README.write_text(text, encoding="utf-8", newline="\n")
    print("  README.md updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
