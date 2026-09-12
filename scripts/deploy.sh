#!/usr/bin/env bash
#
# deploy.sh - deploy Assent from the command line and make the opening offer.
#
#   ./scripts/deploy.sh studionet 0xBuyerAddress
#
# A deal has two parties, and the CLI signs with one key. This script does the
# seller's first move - lint, deploy, open the deal with the opening offer - and
# then prints exactly what each party does next. The recommended route is
# DEPLOY.md: the Studio web interface at studio.genlayer.com, where the account
# selector signs as either party in turn, and the on-chain table in
# SUBMISSION.md describes THAT run. Never put a private key into a file or hand
# one to a tool.
#
# Two things the CLI does that a script has to allow for:
#   - `genlayer write` exits 0 for a transaction that was rolled back, timed
#     out or never decided, so `set -e` does NOT stop on a refused call. Read
#     every receipt; the reads below exist for that.
#   - `genlayer deploy` prints the 64 character transaction hash before the
#     contract address, so a bare `0x[0-9a-fA-F]{40}` grep captures the first
#     40 characters of the hash. The address is taken from the line that names
#     it, bounded on both sides.
#
# Requires: npm i -g genlayer

set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

NETWORK="${1:-studionet}"
BUYER="${2:-}"
if [ -z "$BUYER" ]; then
  echo "usage: ./scripts/deploy.sh <network> <buyer address>" >&2
  exit 1
fi
gold() { printf '\033[33m%s\033[0m\n' "$*"; }
dim()  { printf '\033[2m%s\033[0m\n' "$*"; }

gold "Assent -> $NETWORK"
# `network` is a command group, not a value: `genlayer network studionet`
# answers "unknown command" and exits 1.
genlayer network set "$NETWORK"

dim "linting"
# genvm-lint needs its subcommand, and utf-8 stdout: the linter prints a tick
# on success and dies encoding it under the cp1252 stdout Windows hands a child
# process, reporting a PASSING contract as failed.
PYTHONIOENCODING=utf-8 genvm-lint lint contracts/assent.py

OUT=$(genlayer deploy --contract contracts/assent.py)
printf '%s\n' "$OUT"
ADDR=$(printf '%s\n' "$OUT" | grep -i 'address' | grep -oE '\b0x[0-9a-fA-F]{40}\b' | head -1 || true)
if [ -z "$ADDR" ]; then
  echo "could not read a contract address from the deploy output above" >&2
  exit 1
fi
gold "deployed at $ADDR"

LABEL="Office chairs, 40 units"
TERMS="unit price|delivery date|warranty"
OFFER="We offer 40 ergonomic office chairs at 180 EUR each, delivered to your Rotterdam office by 15 October, with a two year warranty."

# --args is variadic. A JSON array is ONE argument, not the argument list, so
# every value below is a separate token.
dim "open()      the catalogue frozen, the residual row appended, offer 0 made"
genlayer write "$ADDR" open --args "$LABEL" "$TERMS" "$OFFER" "$BUYER"
genlayer call "$ADDR" deal --args 0
genlayer call "$ADDR" terms_of --args 0

cat <<TXT

  Contract:  $ADDR
  Explorer:  https://explorer-studio.genlayer.com/address/$ADDR

The opening offer is on chain. The rest alternates between the two parties
and is written out step by step in DEPLOY.md (steps 2 to 8):

  buyer           accept(0, "We accept, provided delivery is brought forward to 1 October.")
  any account     judge(0)          -> countered, changed 0|1|0|0, the roles swap
  seller          counter(0, the offer restated with delivery by 1 October)
  buyer           accept(0, "We accept your offer in full, as written.")
  any account     judge(0)          -> formed, deal 0 agreed
  seller          open("Desk lamps, 20 units", ...), then withdraw(1)

Before submitting, prove the address is evidence for THIS repository:

  python scripts/verify_deployment.py $ADDR

TXT
