# Assent - specification

One standalone GenLayer Intelligent Contract.
[`contracts/assent.py`](contracts/assent.py), deployed exactly as written, no
build step.

Runner pinned in the header:
`py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`

---

## Purpose

Record a negotiation between two parties in free text, and let an agreement
form only when an acceptance matches the operative offer **term for term**. A
reply that changes any term is a counter-offer: it terminates the offer it
answered and stands as a new offer by its author. This is the mirror-image rule
of contract law, applied by a contract.

The failure it catches is the conditional acceptance read as an acceptance: "we
accept, provided delivery is brought forward", and two parties who each believe
a different contract exists.

## Consensus

`gl.vm.run_nondet_unsafe`. **Two prompts in one block**, the rows in their
frozen order and then reversed and renumbered.

The block receives the deal label, the numbered rows, the operative offer and
the pending acceptance, and returns:

| Field | Type on the wire | Meaning |
|---|---|---|
| `verdict` | string | `formed`, `countered` or `indeterminate` |
| `changed` | pipe joined bits, one per row | 1 on each row that countered, only when `countered` |
| `because` | short string | leader supplied, sanitised, **not** consensus |

Everything crossing the boundary is a plain string in a flat dict.

### The words

Each row gets one word:

| Word | Meaning |
|---|---|
| `same` | the acceptance agrees to the offer's position on this term, or does not mention it; restating it in other words is `same` |
| `changed` | the acceptance proposes a different position on this term, adds a condition to it, asks for more or for something different, or makes accepting depend on it |

The prompt also says that politeness, thanks and signatures are not terms, and
that a change to a named term belongs to that term's row, not to the residual
row.

### The fold

The reversed pass lists the rows last to first, so its row `[0]` is the frozen
row `n-1`. The contract reads the answer back into the frozen order and folds
the two passes per row: the same word in both orders stands, different words
become `unclear`. `unclear` is the contract's word and no prompt may return it;
a model that does has given an unusable answer. A pass that is unusable as a
whole (the wrong length, a word outside the two, not a JSON object) leaves every
row `unclear`.

Every deal has at least two rows, because the contract appends the residual row
to at least one named term, so the two presentation orders are always different
prompts and the second call is always a position check.

### Canonical resolution

```python
def resolve(folded):
    mask = [1 if t == CHANGED else 0 for t in folded]
    if popcount(mask) > 0:
        return COUNTERED, mask
    for t in folded:
        if t != SAME:
            return INDETERMINATE, [0] * len(folded)
    return FORMED, [0] * len(folded)
```

| Folded rows | Verdict | Mask |
|---|---|---|
| any row `changed` | `countered` | 1 on each `changed` row, 0 elsewhere |
| no row `changed`, some row `unclear` | `indeterminate` | all 0 |
| every row `same` | `formed` | all 0 |

`resolve()` is pure and total, and it keeps exactly what decides something. An
`unclear` row beside a change decides nothing and is 0 in the mask, so it cannot
split two nodes. An `unclear` row with no change decides whether a contract
exists, so it makes the outcome indeterminate. Nothing records that the orders
disagreed.

### The validator

1. **Structural honesty, free.** A verdict from the closed set, one bit per
   row, and `countered` exactly when a bit is set. Runs before any prompt is
   spent.
2. **Exact equality on the canonical outcome.** The validator runs both orders
   itself, resolves, and compares the verdict and the mask. No tolerance on any
   row.

`assent_agrees(a, b) == assent_agrees(b, a)`, by construction: both sides pass
the same structural check and the comparison is an equality. The pair compared
is the pair stored. A test sweeps every folded vector against every other, for
two, three and four rows, and asserts that agreement always means the same
stored outcome.

## The state machine

| Status | Meaning |
|---|---|
| `open` | an operative offer awaits its offeree |
| `pending` | an acceptance is posted and awaits judgment |
| `agreed` | terminal |
| `withdrawn` | terminal |
| `rejected` | terminal |

| Move | Who | Effect |
|---|---|---|
| `open` | anyone | freezes the catalogue, appends the residual row, makes offer `0` of the deal, kind `offer`, by the caller to the counterparty |
| `accept` | the offeree | posts an acceptance of the operative offer; the deal is `pending` |
| `judge` `formed` | anyone | the deal is `agreed`; `agreed_offer` and `agreed_attempt` recorded |
| `judge` `countered` | anyone | the answered offer is terminated; the acceptance becomes a new offer, kind `conditional`, by its author to the other party, answering the old one; the deal is `open` with the roles swapped |
| `judge` `indeterminate` | anyone | nothing is terminated; the same offer stands; the deal is `open` |
| `counter` | the offeree | the operative offer is terminated; a new offer, kind `counter`, by the offeree to the offeror; no model is asked |
| `withdraw` | the offeror | the operative offer is terminated; the deal is `withdrawn` |
| `reject` | the offeree | the operative offer is terminated; the deal is `rejected` |

**The mailbox rule.** While an acceptance is pending, `withdraw`, `counter`,
`reject` and a second `accept` are all refused. Once an acceptance is on the
record, the offeror cannot outrun it.

Anything on a deal that is `agreed`, `withdrawn` or `rejected` is refused with
"this deal is over".

## State

Every collection is a **top level contract field**. No storage dataclass
contains a collection, because GenVM cannot construct one. Children carry a
parent id; offers and acceptances also carry the index of the next row on the
same deal, so a deal's rows are walked by following links rather than by
scanning the array. Terms are appended in one call at `open()`, so they are
contiguous and a range from `first_term` suffices.

| Field | Type | Note |
|---|---|---|
| `deals` | `DynArray[Deal]` | append only |
| `terms` | `DynArray[Term]` | flat; a deal's terms are `first_term + k`, the residual row last |
| `offers` | `DynArray[Offer]` | flat; linked through `Offer.next` |
| `attempts` | `DynArray[Attempt]` | flat; linked through `Attempt.next` |
| `Deal.party_a` | `Address` | opened the deal and made the opening offer |
| `Deal.party_b` | `Address` | the counterparty named at `open()` |
| `Deal.status` | `str` | `open`, `pending`, `agreed`, `withdrawn` or `rejected` |
| `Deal.first_term / n_terms` | `u256` | the frozen catalogue's range, the residual row included |
| `Deal.current` | `u256` | the operative offer |
| `Deal.first_offer / last_offer / n_offers` | `u256` | the offer chain |
| `Deal.first_attempt / last_attempt / n_attempts` | `u256` | the acceptance chain |
| `Deal.pending` | `u256` | the acceptance awaiting judgment, while `pending` |
| `Deal.a_offers / b_offers / a_attempts / b_attempts` | `u256` | each party's own budgets, spent |
| `Deal.agreed_offer / agreed_attempt` | `u256` | valid only when `agreed` |
| `Offer.by / to` | `Address` | the offeror and the offeree |
| `Offer.kind` | `str` | `offer`, `counter` or `conditional` |
| `Offer.responds_to` | `u256` | the offer it answered; its own index for an opening offer |
| `Offer.terminated` | `bool` | set when countered, withdrawn or rejected; never cleared |
| `Attempt.offer_id` | `u256` | the offer it answered, operative when it was posted |
| `Attempt.judged` | `bool` | set once, by `judge()` |
| `Attempt.verdict` | `str` | `""` until judged |
| `Attempt.changed` | `str` | pipe joined bits, `""` until judged |
| `Attempt.why` | `str` | leader supplied, sanitised, **not** consensus |

## The frozen catalogue

`open()` freezes 1 to 8 named terms, pipe joined. Each is cleaned, at most 60
characters and refused rather than truncated, distinct from the others without
regard to case, and never the residual row's own wording. The contract then
appends the residual row:

```
any other term or condition, not named in this list
```

Nothing can edit the catalogue after `open()`. A list of terms that could change
after an acceptance was posted would let whoever wanted a particular answer add
the row the reply happens to move, or drop the one it does.

## Caps and budgets

| Constant | Value | Note |
|---|---|---|
| `MAX_TERMS` | 8 | named terms per deal; the residual row is one more |
| `MAX_TERM` | 60 | characters per term name, refused rather than truncated |
| `MIN_LABEL` | 2 | characters |
| `MAX_LABEL` | 120 | characters |
| `MIN_OFFER` | 20 | characters, an offer or a counter-offer |
| `MAX_OFFER` | 700 | characters, an offer or a counter-offer |
| `MIN_ACCEPTANCE` | 2 | characters |
| `MAX_ACCEPTANCE` | 400 | characters |
| `MAX_OFFERS_EACH` | 6 | offers per party per deal, the opening offer included |
| `MAX_ATTEMPTS_EACH` | 6 | acceptances per party per deal |
| `MAX_OFFER_ROWS` | 12 | offer rows per deal, every row counted |
| `MAX_ATTEMPT_ROWS` | 12 | acceptance rows per deal, every row counted |
| `MAX_REASON` | 140 | characters of the leader's explanation |

`accept()` checks the offer budget as well as the acceptance budget, because a
countered acceptance becomes an offer by its author. So `judge()` never needs a
budget it might not have, and a posted acceptance can always be judged.

Every caller string goes through one cleaner on the way into storage: every
character below 32, and 127, becomes a space, then whitespace collapses. At the
prompt boundary only, `fence()` replaces `<` `>` `[` `]` with `(` `)` `(` `)`.

## Authority

| Call | Who | Why |
|---|---|---|
| `open` | anyone | the caller becomes party A and names party B, who must be a different account |
| `accept` | the offeree of the operative offer | an offer is accepted by the party it was made to |
| `counter` | the offeree of the operative offer | only the party an offer was made to can answer it |
| `reject` | the offeree of the operative offer | the same |
| `withdraw` | the offeror of the operative offer | an offer is withdrawn by the party that made it |
| `judge` | anyone | it adds no text and reaches only the outcome the two frozen texts imply; both parties want it judged |

`accept()` and `may_accept()` share one helper, `_accept_refusal()`, which
returns the reason `accept()` would refuse an address or an empty string, so the
view cannot drift from the rule the write enforces.

## API

```
open(label: str, terms: str, text: str, counterparty: str)   # terms pipe joined
accept(deal_id: u256, text: str)
counter(deal_id: u256, text: str)
reject(deal_id: u256)
withdraw(deal_id: u256)
judge(deal_id: u256)

status(deal_id)                 -> str
deal(deal_id)                   -> dict
agreement(deal_id)              -> dict
offer(offer_id)                 -> dict
attempt(attempt_id)             -> dict
history(deal_id)                -> dict
terms_of(deal_id)               -> dict
may_accept(deal_id, who: str)   -> bool
count() / offer_count() / attempt_count()   -> u256
```

`deal()` returns `agreed_offer` and `agreed_attempt` as `0` unless `agreed` is
true, and `0` is also a real index, so read `agreed` first. `agreement()`
returns empty strings for a deal that has not agreed rather than raising.

Every address a view returns is the **EIP-55 checksummed string** on chain,
with mixed case. Compare addresses case-insensitively.

Every read and every write with an out-of-range **or negative** id raises a
`UserError`: Python list indexing accepts `-1` and returns the newest row, which
would hand a caller a different record with nothing failing anywhere.
`may_accept()` looks the deal up before it looks at the address, so a bad id
raises there too.

## Reuse

[`lib/assent_consensus.py`](lib/assent_consensus.py) holds the pure rules with
no storage and no contract around them. It is **generated** by
`scripts/lift.py` from the contract, and `tests/test_logic.py` compares the two
parsed trees function by function, so a copied rule is always one a deployed
contract actually runs.

The idea worth lifting is `resolve()`: let the model answer in the vocabulary
natural to it, then reduce what it said to the outcome it decides before
anything is compared, so the network agrees on consequences rather than on
wording, and a difference that decides nothing cannot split a vote.
