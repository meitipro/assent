# Submission

One submission, under **Builder -> Intelligent Contracts**. This repository is
one standalone primitive.

---

## Before you submit, in order

1. **Measure, do not estimate.**

   ```bash
   python scripts/measure.py --write
   ```

   Checks the house style, runs the suite, runs the full mutation pass, and
   writes the numbers into README.md. It refuses to write anything if the style
   check fails, the suite is red, or a mutation escapes, so a number in the
   README is always one that was checked.

2. **Deploy and exercise.** Through the Studio web interface at
   studio.genlayer.com, following [DEPLOY.md](DEPLOY.md) step by step, with the
   two accounts it asks for. Never put a private key into a file.

3. **Put the refusal on chain, not only a success.** The story the run tells is
   the submission: a conditional acceptance that the contract refuses to call an
   acceptance and records as a counter-offer, the roles swapping, a full offer
   answering it, and an acceptance in full that forms the agreement. Then a
   second deal withdrawn before anybody accepted it.

4. **Prove the address is evidence for this repository.**

   ```bash
   python scripts/verify_deployment.py 0xYourAddress
   ```

   Reads the source back out of the deploy transaction on chain, compares it
   with `contracts/assent.py` (identical up to line endings, which pasting into
   a web editor rewrites and nothing runs), and runs `genvm-lint lint` on those
   bytes. **A submission is judged on the deployed source**, so a correct
   repository proves nothing on its own if the address points at an earlier
   draft. Exits non-zero if either check fails, or if `genvm-lint` is missing.

5. **Open the explorer page and check it.** It must show a Deploy transaction
   **and** method calls with a Consensus Result beside them, and no failed or
   abandoned transaction.

6. **Paste the address** into README.md and into this file where `{address}`
   appears, then push.

7. **Upload `brand/social.png`** under Settings -> General -> Social preview.
   GitHub has no API for this.

---

## On chain

Deployed and exercised on studionet at
[`{address}`](https://explorer-studio.genlayer.com/address/{address}).

The values below are what the run in [DEPLOY.md](DEPLOY.md) is expected to
produce - `tests/test_runbook.py` replays that run and asserts each of them - and
every one is to be **read back from the chain with view calls afterwards** and
replaced with what the chain actually says before this file is submitted.

| # | Transaction | Result |
|---|---|---|
| 1 | deploy | finalized |
| 2 | `open("Office chairs, 40 units", "unit price\|delivery date\|warranty", the offer, B)` (A) | deal 0: three named terms and the residual row, offer 0 by A to B |
| 3 | `accept(0, "We accept, provided delivery is brought forward to 1 October.")` (B) | acceptance 0 posted, deal 0 `pending` |
| 4 | `judge(0)` | acceptance 0: **`countered`**, `changed 0\|1\|0\|0`; offer 0 terminated, offer 1 `conditional` by B to A |
| 5 | `counter(0, the offer restated with delivery by 1 October)` (A) | offer 2, kind `counter`, by A to B; offer 1 terminated |
| 6 | `accept(0, "We accept your offer in full, as written.")` (B) | acceptance 1 posted |
| 7 | `judge(0)` | acceptance 1: **`formed`**, `changed 0\|0\|0\|0`; deal 0 **`agreed`** on offer 2 |
| 8 | `open("Desk lamps, 20 units", "unit price\|delivery date", the offer, B)` (A) | deal 1, offer 3 by A to B |
| 9 | `withdraw(1)` (A) | deal 1 **`withdrawn`**, offer 3 terminated |

### Reproducing the check

```bash
python scripts/verify_deployment.py {address}
```

---

## Title

```
Assent: an agreement forms only when the acceptance matches the offer
```

## Notes (under 1000 characters, the box caps at 1000)

```
Assent enforces the mirror-image rule for two parties negotiating in free text, an acceptance forms an agreement only when it matches the offer term for term, and a reply that changes any term is a counter-offer that terminates the offer it answered. The terms are frozen at open with a residual row the contract owns, so a term nobody named is still caught, and the block answers one word per row, same or changed, asked twice, in the frozen order and reversed, with a row the orders answer differently marked unclear. What crosses consensus is the canonical outcome, formed, countered with the changed rows named, or indeterminate, so an unclear row beside a change cannot split a vote, and an unclear row alone leaves the offer standing. Agreement is exact on verdict and mask, the mailbox rule stops anyone outrunning a posted acceptance, and each party has its own budget.
```

## Links

```
GitHub:   https://github.com/meitipro/assent
Contract: https://github.com/meitipro/assent/blob/main/contracts/assent.py
Spec:     https://github.com/meitipro/assent/blob/main/CONTRACTS.md
Decisions https://github.com/meitipro/assent/blob/main/DECISIONS.md
Tests:    https://github.com/meitipro/assent/tree/main/tests
Explorer: https://explorer-studio.genlayer.com/address/{address}
```

---

## What clears the bar, line by line

The category rejects "thin LLM wrappers" and "generic AI decides X demos".

- **The model never decides.** It answers, per frozen row, whether one reply
  moved one term, twice. Which terms exist, which offer is operative, who may
  speak, what a changed row does to the offer, and whether an agreement exists
  are all deterministic.
- **Consensus compares only what decides something.** The rows are reduced to a
  verdict and the rows that countered before anything is compared, so a
  difference that changes nothing cannot split a vote, and a difference that
  decides whether a contract exists cannot be forgiven.
- **Uncertainty is in the value, not the comparison.** A row the two orders
  answered differently is unclear, and an unclear judgment forms nothing and
  terminates nothing. Nothing reports how unsure the model was, and there is no
  tolerance anywhere in the agreement rule.
- **The validator function is the contribution.** A free structural check before
  any prompt, then exact equality on the canonical outcome. Explained in
  [CONTRACTS.md](CONTRACTS.md) with the code.
- **The residual row.** The contract owns a row for every term nobody named, so
  an acceptance that slips in a new cost is a counter-offer, not a match.
- **The mailbox rule, and budgets that are a party's own.** A posted acceptance
  is judged before anybody can outrun it, and nothing one party does spends the
  other's budget.
- **Every write is bound to an address.** Only the offeree accepts, counters or
  rejects, only the offeror withdraws, and a static test asserts every gated
  write refuses a wrong sender.
- **No global scans.** Every per-deal walk follows links the rows carry or a
  range frozen at open. A static test asserts it.
- **The tests have teeth.** The mutation table in the README is generated by a
  script that refuses to emit a table if anything escapes, the agreement rule is
  swept exhaustively, and the simulator can model a leader that lies.
- **It runs with nothing installed.** `pip install pytest && pytest tests/ -q`.

## The one line worth putting first

**The judgment is hard and the thing crossing consensus is a verdict and the
rows that countered, derived from one word per row, so the network compares
exactly the differences that decide whether a contract exists.** Everything else
in the design follows from it.
