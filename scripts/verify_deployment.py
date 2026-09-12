"""Prove the deployed contract is the contract in this repository.

    python scripts/verify_deployment.py 0xYourAddress

A submission is judged on the DEPLOYED source. The reviewer reads it back off
chain, diffs it against the repository, and runs the linter on those bytes, so
a repository that is correct proves nothing on its own if the address points at
an earlier draft. Two GenLayer submissions have been rejected for exactly that,
with the fix already sitting in the repo, unreachable.

This script does the same three things the reviewer does:

    1. reads the contract source out of the deploy transaction on chain
    2. compares it with contracts/assent.py
    3. runs `genvm-lint lint` on the bytes that came off the chain

The comparison is for identity UP TO LINE ENDINGS AND THE TRAILING NEWLINE.
Pasting a file into a web editor rewrites LF to CRLF and often drops the final
newline; neither changes a byte of what runs. So both sides are normalised
first, and the script reports the two kinds of difference separately: a
COSMETIC one (only line endings or the trailing newline differ, which it
prints and accepts) and a MATERIAL one (the code differs, which fails).

It exits non-zero if the source differs materially, if the lint fails, or if
genvm-lint is not installed at all: a gate that cannot run its check fails
closed rather than waving the address through.
"""

import argparse
import base64
import difflib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "contracts" / "assent.py"
RPC = "https://studio.genlayer.com/api"


def rpc(method, params, rpc_url):
    req = urllib.request.Request(
        rpc_url,
        data=json.dumps({"jsonrpc": "2.0", "method": method,
                         "params": params, "id": 1}).encode(),
        # Without a User-Agent the Studio endpoint answers 403, which reads
        # like a bad address rather than a missing header.
        headers={"Content-Type": "application/json",
                 "User-Agent": "assent-verify/1.0"},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        out = json.loads(r.read())
    if isinstance(out, dict) and "error" in out:
        raise SystemExit(f"RPC error from {method}: {out['error']}")
    return out.get("result", out) if isinstance(out, dict) else out


def deployed_source(address, rpc_url):
    """The source that was actually deployed, from the deploy transaction.

    Addresses are case sensitive to this endpoint: a lower cased address comes
    back as "contract not found". Pass the checksummed form the explorer shows.
    """
    txs = rpc("sim_getTransactionsForAddress", [address], rpc_url)
    if not isinstance(txs, list) or not txs:
        raise SystemExit(f"no transactions found for {address}. "
                         "Check the address casing: it is not normalised here.")
    for tx in txs:
        code = (tx.get("data") or {}).get("contract_code")
        if code:
            return base64.b64decode(code).decode("utf-8"), tx.get("hash", "")
    raise SystemExit("no deploy transaction found on that address")


def lint(text):
    """Run the linter on the bytes that came off the chain, not on the repo file.

    `lint` rather than `check`: `check` also runs validate, which cannot see a
    class named Contract and so reports a working contract as broken. Note that
    `check` prints a green validation line UNDERNEATH a lint failure, which is
    how an unlinted contract reaches a deployment in the first place.
    """
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "deployed.py"
        p.write_text(text, encoding="utf-8")
        try:
            proc = subprocess.run(
                ["genvm-lint", "lint", str(p)],
                capture_output=True, text=True,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        except FileNotFoundError:
            print("genvm-lint is not installed: pip install genvm-linter")
            sys.exit(2)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def canonical(text):
    """What runs: line endings normalised, the trailing newline ignored."""
    return text.replace("\r\n", "\n").rstrip("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("address", help="the deployed contract address, checksummed")
    ap.add_argument("--rpc", default=RPC)
    args = ap.parse_args()

    local = SOURCE.read_text(encoding="utf-8")
    remote, tx = deployed_source(args.address, args.rpc)

    print(f"  address      {args.address}")
    print(f"  deploy tx    {tx}")
    print(f"  repo file    {SOURCE.relative_to(ROOT)}  ({len(local)} chars)")
    print(f"  on chain     {len(remote)} chars")

    same = canonical(local) == canonical(remote)
    cosmetic = same and local != remote
    print(f"  identical    {'yes' if same else 'NO, the code differs'}")
    if cosmetic:
        print("               cosmetic only: line endings or the trailing newline "
              "differ, which nothing runs")

    ok_lint, out = lint(remote)
    print(f"  lint         {'passed' if ok_lint else 'FAILED'}")
    if not ok_lint:
        for line in out.splitlines():
            print(f"               {line}")

    if not same:
        print("\n  The deployed source is not this file. First differences:\n")
        diff = difflib.unified_diff(
            canonical(remote).splitlines(),
            canonical(local).splitlines(),
            fromfile="deployed", tofile="repository", lineterm="", n=1,
        )
        for i, line in enumerate(diff):
            if i > 40:
                print("               ... truncated")
                break
            print(f"               {line}")

    if same and ok_lint:
        print("\n  The address is evidence for this repository. Safe to submit.")
        return 0
    print("\n  Do NOT submit this address. Redeploy from the current file.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
