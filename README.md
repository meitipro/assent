<p align="left"><img src="brand/lockup.svg" alt="assent" height="64"></p>

# Assent - an agreement forms only when the acceptance matches the offer

A reusable GenLayer primitive for two parties negotiating in free text. It
enforces the **mirror-image rule** of contract law: a reply that changes any
term of an offer is not an acceptance. It is a counter-offer, it terminates the
offer it answered, and the side that made the offer is now the one deciding.
Nobody decides "we have a deal". The contract compares.

- **Contract:** [`contracts/assent.py`](contracts/assent.py)
- **Tests:** `pip install pytest && pytest tests/ -q` - nothing else to install
- **Deployed:** [`0x926a4819dFd01F39959b2FCfbd02eBA8FbB3045C`](https://explorer-studio.genlayer.com/address/0x926a4819dFd01F39959b2FCfbd02eBA8FbB3045C) on studionet
- **Deploying it yourself:** [DEPLOY.md](DEPLOY.md) - the contract, the demo, and the check to run before submitting
- **Verify a deployment:** `python scripts/verify_deployment.py 0x...` - compares the
  on-chain source with this file and lints it
- **Specification:** [CONTRACTS.md](CONTRACTS.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **License:** MIT. Copy the agreement rule; that is what it is for.

---

## It is live, and every outcome is on chain

Two parties, one deal on a frozen catalogue of three named terms and the
residual row. Every value below was read back from the chain with view calls,
not copied from a local run.

**The conditional acceptance** - "We accept, provided delivery is brought
forward to 1 October."

```
same | changed | same | same  ->  countered, changed 0|1|0|0
```

Read casually it is a yes. The contract refused to call it one: offer 0 was
terminated, and the reply now stands as offer 1, kind `conditional`, by the
buyer to the seller. The roles swapped. The leader's reason, stored and outside
consensus: "Only delivery date is altered from 15 October to 1 October; price,
warranty, and other terms are unchanged."

**The mailbox rule, in public.** While that acceptance was still waiting to be
judged, the seller tried to counter and the buyer tried to accept again. Both
were refused - "the mailbox rule: an acceptance is posted, so the offer cannot
be countered until it is judged" and "an acceptance is already posted and awaits
judgment" - and nothing was written.

**The agreement** - the seller countered with the whole offer restated at 1
October (offer 2, answering offer 1), and the buyer replied "We accept your offer
in full, as written."

```
same | same | same | same  ->  formed, changed 0|0|0|0
```

`agreement(0)`:

```json
{"agreed": true,
 "offer_text": "We offer 40 ergonomic office chairs at 180 EUR each, delivered to your Rotterdam office by 1 October, with a two year warranty.",
 "acceptance_text": "We accept your offer in full, as written.",
 "offeror": "0x3e1D268c8B1Ba7d042968ab713467C5631831513",
 "acceptor": "0x86277F71efeaF7AbA8c51FF3A5BF15D76D95F213"}
```

A second deal, desk lamps, was withdrawn by its offeror before anybody accepted
it: `status(1)` is `withdrawn`.

Eleven transactions, every one `FINALIZED`: the nine the demo needs and the two
refusals above.

---

## The problem

> We accept, provided delivery is brought forward to 1 October.

Read casually, that is an acceptance. Under the mirror-image rule it is a
counter-offer: the original offer is dead, and the seller is now the one
deciding whether to take the new date. People and agents negotiating in prose
lose track of exactly this, and a model asked "did they agree?" will usually say
yes.

What that costs is not a wrong answer on a test. It is two parties who each
believe a different contract exists.

## How consensus is used

Assent never asks whether there is an agreement. `open()` freezes a catalogue of
named terms - `unit price|delivery date|warranty` - and the contract appends one
row it owns, the residual row. The block sees the numbered rows, the operative
offer and the acceptance, and answers **one word per row**: `same` or
`changed`.

> The judgment is hard. Read a reply and decide, term by term, whether it agrees
> to the offer's position or quietly moves it.
>
> **The thing that crosses consensus is a verdict and a bit mask, derived
> deterministically from one word per row.**

### The residual row

```
any other term or condition, not named in this list
```

Without it, "we accept, and you also pay the shipping" agrees with every named
term and would form a contract with a cost nobody offered. The residual row is
where a new term lands. The prompt says a change to a named term belongs to that
term's row, so the residual row catches only what the catalogue never named. A
party cannot name it or edit it; the contract writes it.

### The leader resolves its own uncertainty first

The block asks **twice** - rows in frozen order, then reversed and renumbered -
and reads the reversed answer back into the frozen order. A row both orders
answered the same way keeps that word. A row they answered differently becomes
`unclear`, a word no prompt may return. A pass that is unusable as a whole
leaves every row `unclear`.

### Canonical resolution: compare only what decides something

`resolve()` reduces the folded rows to the only thing that decides anything:

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

An `unclear` row is 0 in a counter, because once another row has countered it
decides nothing: two nodes that fold `[changed, unclear]` and `[changed, same]`
**agree**. With no change, one `unclear` row makes the outcome indeterminate,
because that difference is whether a contract exists: two nodes that fold
`[same, unclear]` and `[same, same]` **disagree**, and the network must settle
it or not settle at all.

Nothing a node measured about its own uncertainty is compared or stored, and the
tuple compared is the tuple stored. **Uncertainty belongs in the value, never in
the comparison.**

### The validator, in two layers

```python
# LAYER 1 -- structural honesty. Costs nothing, runs before any prompt.
#   A verdict from the closed set, one bit per row, and countered exactly when
#   a bit is set. A proposal that says formed while naming a changed row
#   contradicts itself, and dies before any inference is spent on it.

# LAYER 2 -- exact equality on the canonical outcome.
#   The validator runs both orders itself, resolves, and compares the verdict
#   and the mask. No tolerance: two nodes that both countered but named
#   different rows would store a counter-offer one of them did not read.
```

## The deal

| Status | Meaning |
|---|---|
| `open` | an operative offer awaits its offeree |
| `pending` | an acceptance is posted and awaits judgment |
| `agreed` | an acceptance matched the operative offer. Terminal |
| `withdrawn` | the offeror took the operative offer back. Terminal |
| `rejected` | the offeree refused the operative offer. Terminal |

What each verdict does to it:

| Verdict | Effect |
|---|---|
| `formed` | the deal is `agreed`, and records which offer and which acceptance formed it |
| `countered` | the answered offer is terminated, and the acceptance stands as a new `conditional` offer by its author to the other party: the roles swap |
| `indeterminate` | nothing is terminated, the same offer stands, and its offeree may try again with a clearer acceptance |

A party may also answer an offer with an explicit `counter()`, which terminates
it and makes a new one with the roles swapped. No model is asked, because the
party is saying in terms that it is a new offer.

### The mailbox rule

Once an acceptance is posted, the offeror can no longer withdraw, and nobody can
counter or reject, until it is judged. Posting and judging are two transactions
on purpose: an acceptance on the record is one the offeror cannot outrun.

## Why this is not a thin LLM wrapper

The model never decides whether there is a contract. **It answers, per frozen
row, whether one reply moved one term, twice.** Which terms exist, which offer is
operative, who may speak, what a changed row does to the offer, whether an
agreement exists and what it says - all deterministic, all computed from storage
the block never sees.

Swap in a worse model and the mechanism still works. It reads fewer rows
consistently, so more judgments come back indeterminate, which forms nothing and
terminates nothing: the offer stands, and the offeree can say it more plainly.

## Who may write to a deal

| Call | Who |
|---|---|
| `open` | anyone. The caller becomes party A and makes the opening offer to the counterparty it names |
| `accept` | the offeree of the operative offer, while the deal is `open`, within the budgets below |
| `counter` | the offeree of the operative offer, while the deal is `open` |
| `reject` | the offeree of the operative offer, while the deal is `open` |
| `withdraw` | the offeror of the operative offer, while the deal is `open` |
| `judge` | anyone, deliberately |

`judge()` is open on purpose. It adds no text, it can reach only the outcome the
two frozen texts imply, and both parties want the acceptance judged: the one who
posted it and the one waiting on it.

### Budgets, so nobody can post for ever

| Budget | Value |
|---|---|
| offers per party per deal, the opening offer included | 6 |
| acceptances per party per deal | 6 |
| offer rows per deal | 12 |
| acceptance rows per deal | 12 |

An indeterminate judgment leaves the offer standing, so without a budget one
party could post acceptances for ever. A countered acceptance becomes an offer
by its author, so posting one needs an offer slot as well as an acceptance, and
both are checked when it is posted: `judge()` can never fail on a budget, and a
posted acceptance can always be judged. Every budget is a party's own; nothing
one party does spends the other's.

## The API

```python
open(label, terms, text, counterparty)   # anyone. terms pipe joined, frozen here
accept(deal_id, text)                    # the offeree of the operative offer
counter(deal_id, text)                   # the offeree of the operative offer
reject(deal_id)                          # the offeree of the operative offer
withdraw(deal_id)                        # the offeror of the operative offer
judge(deal_id)                           # anyone. judges the pending acceptance

status(deal_id)           -> str    # open | pending | agreed | withdrawn | rejected
deal(deal_id)             -> dict   # parties, the operative offer, counts, the frozen rows
agreement(deal_id)        -> dict   # what was agreed, in the parties' own words
offer(offer_id)           -> dict   # one offer, and whether it is operative or accepted
attempt(attempt_id)       -> dict   # one acceptance, its verdict and its changed rows
history(deal_id)          -> dict   # every offer and every acceptance, oldest first
terms_of(deal_id)         -> dict   # the frozen catalogue, the residual row last
may_accept(deal_id, who)  -> bool   # would accept() take that address right now
count() / offer_count() / attempt_count()
```

`may_accept()` asks the question `accept()` asks, through the same helper: the
deal's status, the offeree, and both budgets. It cannot see the text, which is
the one thing `accept()` checks that a view could not.

## Using it from another contract

```python
@gl.contract_interface
class Assent:
    class View:
        def status(self, deal_id: int) -> str: ...
        def agreement(self, deal_id: int) -> dict: ...

a = Assent(ASSENT_ADDR).view()

# act only on an agreement the texts actually formed, and bind to the parties,
# never to the label. On chain every address a view returns is the EIP-55
# checksummed string, so compare case-insensitively.
if a.status(did) == "agreed":
    terms = a.agreement(did)
    if terms["acceptor"].lower() == str(expected_buyer).lower():
        self._release_the_order(terms["offer_text"])
```

`deal()` returns `agreed_offer` and `agreed_attempt` as `0` unless `agreed` is
true, and offer `0` is a real offer, so read `agreed` first.

---

## Running the tests

```bash
pip install pytest
pytest tests/ -q
```

Nothing else is needed. `tests/glsim.py` is a small GenVM stand-in, so the unit,
end-to-end and runbook suites run with no Studio and no network.
`tests/test_runbook.py` replays [DEPLOY.md](DEPLOY.md) step by step and asserts
every value it tells you to expect, so the walkthrough is tested like the code.

The integration suite is **opt in**, and deliberately so. It skips when
`genlayer-test` is absent, and it also skips when `genlayer-test` is present
without a Studio to talk to - otherwise anybody who reviews GenLayer contracts,
and therefore has the plugin installed, would see a wall of connection errors on
a repository that promises an offline run. To run it against a live Studio:

```bash
pip install genlayer-test
GENLAYER_STUDIO=1 gltest --network studionet tests/test_integration.py
```

<!-- measured:tests -->
`pytest tests/ -q` reports **218 passed, 1 skipped**, and every one of the **157** mutations below is caught.
<!-- /measured:tests -->

### The tests have teeth

A passing count is a claim. The table below is evidence: every row is a real edit
to the contract that removes a defence, and the test named beside it is the one
that failed. It is generated by `scripts/mutate.py`, which regenerates the
lifted library from each mutant before the suite runs, so no parity check can
stand in for a behavioural test, and which refuses to emit a table if anything
escapes.

<!-- measured:mutations -->
| Mutation | Caught by |
|---|---|
| a disagreement between the orders keeps the forward answer | `test_a_row_the_two_orders_answer_differently_leaves_the_offer_standing` |
| a disagreement between the orders folds to same | `test_a_row_the_two_orders_answer_differently_leaves_the_offer_standing` |
| a disagreement between the orders folds to changed | `test_a_row_the_two_orders_answer_differently_leaves_the_offer_standing` |
| the reversed pass is ignored, so nothing is mirrored | `test_a_row_the_two_orders_answer_differently_leaves_the_offer_standing` |
| the reversed answer is not read back into the frozen order | `test_a_reply_that_changes_a_term_is_a_counter_offer_and_the_roles_swap` |
| the second pass asked in the same order as the first | `test_a_reply_that_changes_a_term_is_a_counter_offer_and_the_roles_swap` |
| an unusable pass forms the agreement | `test_an_unusable_pass_is_indeterminate_and_the_offer_stands` |
| an unusable pass counters the offer | `test_an_unusable_pass_is_indeterminate_and_the_offer_stands` |
| a fold of the wrong length accepted | `test_an_unusable_pass_leaves_every_row_unclear` |
| a prompt answer that is not an object crashes the block | `test_a_prompt_answer_that_is_not_an_object_is_unusable_not_fatal` |
| a partly unusable answer read slot by slot | `test_an_unusable_pass_is_indeterminate_and_the_offer_stands` |
| an answer of the wrong length parsed anyway | `test_parse_vector_is_all_or_nothing` |
| any word accepted from a prompt | `test_only_same_or_changed_survives` |
| a model allowed to answer with the contract's own word, unclear | `test_only_same_or_changed_survives` |
| an unclear row named in the countered mask | `test_a_row_the_two_orders_answer_differently_leaves_the_offer_standing` |
| an unclear row forms the agreement | `test_a_row_the_two_orders_answer_differently_leaves_the_offer_standing` |
| a change ignored, so a counter-offer is never recorded | `test_a_reply_that_changes_a_term_is_a_counter_offer_and_the_roles_swap` |
| a counter-offer names every row | `test_a_reply_that_changes_a_term_is_a_counter_offer_and_the_roles_swap` |
| the bit count stops at one | `test_popcount` |
| the mask rendered as all zeros | `test_a_reply_that_changes_a_term_is_a_counter_offer_and_the_roles_swap` |
| one row forgiven, the Winnow defect | `test_one_differing_row_is_a_disagreement` |
| agreement on the verdict alone, whatever rows were named | `test_nodes_that_name_different_rows_do_not_agree` |
| agreement on the mask alone, whatever the verdict | `test_an_unclear_row_against_a_clean_read_does_split_the_vote` |
| the agreement rule stops checking the shape of either side | `test_a_malformed_side_never_agrees` |
| the free structural layer removed | `test_a_malformed_proposal_is_refused_with_zero_validator_prompts` |
| the validator trusts a sound proposal without reading the texts | `test_nodes_that_name_different_rows_do_not_agree` |
| a leader that rolled back is not refused | `test_a_leader_that_rolled_back_is_refused_and_nothing_is_stored` |
| a leader payload that is not a mapping is not refused | `test_a_leader_payload_that_is_not_a_mapping_is_refused_for_free` |
| a verdict outside the closed set accepted | `test_a_malformed_proposal_is_refused_with_zero_validator_prompts` |
| a mask of the wrong length accepted | `test_unsound_outcomes_are_refused` |
| an empty mask accepted as sound | `test_unsound_outcomes_are_refused` |
| a value that is not a bit accepted in a mask | `test_unsound_outcomes_are_refused` |
| formed allowed to name a changed row | `test_a_malformed_proposal_is_refused_with_zero_validator_prompts` |
| countered allowed to name no row | `test_a_malformed_proposal_is_refused_with_zero_validator_prompts` |
| a mask of the wrong length parsed anyway | `test_parse_mask_is_all_or_nothing` |
| a mask value other than one or zero parsed as zero | `test_parse_mask_is_all_or_nothing` |
| a formed verdict does not agree the deal | `test_an_acceptance_that_matches_the_offer_forms_the_agreement` |
| the offer that formed the agreement not recorded | `test_the_original_offeror_may_accept_the_conditional_offer` |
| the acceptance that formed the agreement not recorded | `test_the_original_offeror_may_accept_the_conditional_offer` |
| a countered offer is not terminated | `test_a_reply_that_changes_a_term_is_a_counter_offer_and_the_roles_swap` |
| a countered acceptance does not become an offer | `test_a_reply_that_changes_a_term_is_a_counter_offer_and_the_roles_swap` |
| the roles do not swap on a countered acceptance | `test_a_reply_that_changes_a_term_is_a_counter_offer_and_the_roles_swap` |
| a countered deal left pending | `test_a_reply_that_changes_a_term_is_a_counter_offer_and_the_roles_swap` |
| an indeterminate deal left pending | `test_a_row_the_two_orders_answer_differently_leaves_the_offer_standing` |
| an indeterminate judgment terminates the offer | `test_a_row_the_two_orders_answer_differently_leaves_the_offer_standing` |
| a judged acceptance not marked judged | `test_an_acceptance_that_matches_the_offer_forms_the_agreement` |
| the verdict not recorded on the acceptance | `test_an_acceptance_that_matches_the_offer_forms_the_agreement` |
| the changed rows not recorded on the acceptance | `test_an_acceptance_that_matches_the_offer_forms_the_agreement` |
| the leader's reason stored unsanitised | `test_the_leader_s_explanation_is_stored_sanitised` |
| judge reads the first acceptance instead of the pending one | `test_the_original_offeror_may_accept_the_conditional_offer` |
| a counter-offer does not terminate the offer it answers | `test_counter_terminates_the_offer_and_swaps_the_roles` |
| a counter-offer does not swap the roles | `test_counter_terminates_the_offer_and_swaps_the_roles` |
| a counter-offer does not become the operative offer | `test_counter_terminates_the_offer_and_swaps_the_roles` |
| a withdrawal does not end the deal | `test_withdraw_ends_the_deal_and_terminates_the_offer` |
| a withdrawn offer not terminated | `test_withdraw_ends_the_deal_and_terminates_the_offer` |
| a rejection does not end the deal | `test_reject_ends_the_deal_and_terminates_the_offer` |
| a rejected offer not terminated | `test_reject_ends_the_deal_and_terminates_the_offer` |
| a posted acceptance does not make the deal pending | `test_an_acceptance_lands_before_it_is_judged` |
| the pending acceptance not recorded | `test_the_original_offeror_may_accept_the_conditional_offer` |
| an acceptance not bound to the offer it answered | `test_the_original_offeror_may_accept_the_conditional_offer` |
| an acceptance recorded as party B's whoever posted it | `test_the_original_offeror_may_accept_the_conditional_offer` |
| the mailbox rule dropped from withdraw() | `test_the_mailbox_rule_holds_while_an_acceptance_is_pending` |
| the mailbox rule dropped from counter() | `test_the_mailbox_rule_holds_while_an_acceptance_is_pending` |
| the mailbox rule dropped from reject() | `test_the_mailbox_rule_holds_while_an_acceptance_is_pending` |
| a second acceptance posted over a pending one | `test_the_mailbox_rule_holds_while_an_acceptance_is_pending` |
| accept() on a deal that is over | `test_a_deal_that_is_over_refuses_everything` |
| counter() on a deal that is over | `test_a_deal_that_is_over_refuses_everything` |
| withdraw() on a deal that is over | `test_a_deal_that_is_over_refuses_everything` |
| reject() on a deal that is over | `test_a_deal_that_is_over_refuses_everything` |
| judge() runs on a deal that is over | `test_judge_refuses_when_nothing_is_pending` |
| judge() runs with nothing pending | `test_judge_refuses_when_nothing_is_pending` |
| accept() left open to anyone | `test_the_original_offeror_may_accept_the_conditional_offer` |
| the offeror allowed to accept its own offer | `test_the_original_offeror_may_accept_the_conditional_offer` |
| accept() ignores the refusal it was handed | `test_the_mailbox_rule_holds_while_an_acceptance_is_pending` |
| counter() left open to anyone | `test_only_the_offeree_may_counter` |
| withdraw() left open to anyone | `test_only_the_offeror_may_withdraw` |
| the offeree allowed to withdraw the offer it was made | `test_only_the_offeror_may_withdraw` |
| reject() left open to anyone | `test_only_the_offeree_may_reject` |
| the per-party acceptance budget removed | `test_each_party_may_post_at_most_6_acceptances` |
| acceptances counted against party A's tally for everybody | `test_each_party_may_post_at_most_6_acceptances` |
| the per-party offer budget removed | `test_each_party_may_make_at_most_6_offers` |
| offers counted against party A's tally for everybody | `test_each_party_may_make_at_most_6_offers` |
| counter() ignores the offer budget | `test_each_party_may_make_at_most_6_offers` |
| the accept-time offer-slot check removed, so judge() could overrun a budget | `test_an_acceptance_is_refused_when_its_counter_could_not_be_recorded` |
| an offer not counted against its author | `test_a_reply_that_changes_a_term_is_a_counter_offer_and_the_roles_swap` |
| an acceptance not counted against its author | `test_an_acceptance_lands_before_it_is_judged` |
| the opening offer not counted against party A | `test_a_deal_opens_with_its_catalogue_frozen_and_the_residual_row_last` |
| the previous last offer not linked to the new one | `test_history_keeps_every_offer_and_every_attempt_oldest_first` |
| the deal's last offer not moved on | `test_history_keeps_every_offer_and_every_attempt_oldest_first` |
| the deal's offer count not kept | `test_a_reply_that_changes_a_term_is_a_counter_offer_and_the_roles_swap` |
| the previous last acceptance not linked to the new one | `test_history_keeps_every_offer_and_every_attempt_oldest_first` |
| a deal's first acceptance not recorded as its head | `test_two_deals_never_see_each_other_s_rows` |
| the deal's acceptance count not kept | `test_history_keeps_every_offer_and_every_attempt_oldest_first` |
| the offer walk replaced by a scan of every deal's rows | `test_two_deals_never_see_each_other_s_rows` |
| the terms read from the start of the array, not the deal's range | `test_two_deals_never_see_each_other_s_rows` |
| the residual row not appended | `test_a_deal_opens_with_its_catalogue_frozen_and_the_residual_row_last` |
| the residual row left out of the catalogue's count | `test_a_deal_opens_with_its_catalogue_frozen_and_the_residual_row_last` |
| a one-character label accepted | `test_the_label_bounds` |
| the label cap removed | `test_the_label_bounds` |
| a deal with no named term accepted | `test_the_catalogue_bounds` |
| the catalogue cap removed, so an unbounded prompt is built | `test_the_catalogue_bounds` |
| an over-long term accepted | `test_a_term_is_capped_and_never_truncated` |
| a party may name the residual row itself | `test_the_catalogue_bounds` |
| duplicate terms accepted | `test_the_catalogue_bounds` |
| terms that differ only in case accepted as two | `test_the_catalogue_bounds` |
| a fragment accepted as an offer | `test_the_offer_length_bounds` |
| an over-long offer accepted | `test_the_offer_length_bounds` |
| a fragment accepted as a counter-offer | `test_the_counter_offer_length_bounds` |
| an over-long counter-offer accepted | `test_the_counter_offer_length_bounds` |
| a one-character acceptance accepted | `test_the_acceptance_length_bounds` |
| an over-long acceptance accepted | `test_the_acceptance_length_bounds` |
| a malformed counterparty passed to Address() | `test_the_counterparty_must_be_another_address` |
| a deal with oneself accepted | `test_the_counterparty_must_be_another_address` |
| control characters kept in caller text | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| the label stored uncleaned | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| the terms split without the cleaner | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| the offer text stored uncleaned | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| the counter-offer text stored uncleaned | `test_a_counter_offer_is_cleaned_into_storage_too` |
| the acceptance text stored uncleaned | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| the reason sanitiser disabled | `test_the_leader_s_explanation_is_stored_sanitised` |
| control characters left in reasons | `test_the_leader_s_explanation_is_stored_sanitised` |
| the reason not capped | `test_it_is_capped` |
| the prompt fence removed, so a party can forge a block | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| the fence deletes instead of replacing | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| square brackets not fenced, so a text can forge a numbered row | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| only the opening angle bracket fenced | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| the offer reaches the model unfenced | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| the acceptance reaches the model unfenced | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| the deal label reaches the model unfenced | `test_the_label_is_fenced_too` |
| the term names reach the model unfenced | `test_rows_holds_nothing_but_the_numbering_and_fenced_names` |
| the whole block fenced after numbering, which fences away the contract's own rows | `test_an_acceptance_that_matches_the_offer_forms_the_agreement` |
| the count in the prompt derived from caller text | `test_the_count_line_comes_from_n` |
| a concrete example that is itself a valid answer | `test_the_answer_shape_is_a_placeholder_never_a_valid_answer` |
| the residual rule dropped from the prompt | `test_the_residual_rule_is_stated` |
| restating the offer no longer counted as the same | `test_restating_the_offer_is_same` |
| politeness left to be read as a term | `test_politeness_is_not_a_term` |
| the DATA framing dropped from the prompt | `test_the_prompt_says_the_tagged_text_is_data` |
| the deal bounds check removed | `test_may_accept_mirrors_accept_in_every_state` |
| negative deal ids allowed through to list indexing | `test_may_accept_mirrors_accept_in_every_state` |
| the offer bounds check removed | `test_a_read_or_a_write_with_a_bad_id_is_a_user_error` |
| negative offer ids allowed through to list indexing | `test_a_read_or_a_write_with_a_bad_id_is_a_user_error` |
| the acceptance bounds check removed | `test_a_read_or_a_write_with_a_bad_id_is_a_user_error` |
| negative acceptance ids allowed through to list indexing | `test_a_read_or_a_write_with_a_bad_id_is_a_user_error` |
| may_accept() checks the address before the deal exists | `test_may_accept_mirrors_accept_in_every_state` |
| may_accept() hands a malformed address to Address() | `test_may_accept_mirrors_accept_in_every_state` |
| may_accept() answers only who the offeree is | `test_a_deal_that_is_over_refuses_everything` |
| may_accept() says yes to any well formed address | `test_the_original_offeror_may_accept_the_conditional_offer` |
| an offer reported operative after the deal ended | `test_an_acceptance_that_matches_the_offer_forms_the_agreement` |
| every offer on an agreed deal reported accepted | `test_history_keeps_every_offer_and_every_attempt_oldest_first` |
| agreement() reports a deal that never agreed | `test_a_reply_that_changes_a_term_is_a_counter_offer_and_the_roles_swap` |
| a nested mapping returned from the block | `test_an_acceptance_that_matches_the_offer_forms_the_agreement` |
| a bool returned from the block, the noise flag this design refuses | `test_an_acceptance_that_matches_the_offer_forms_the_agreement` |
| the block reads storage | `test_two_deals_never_see_each_other_s_rows` |
| a collection nested back into a storage dataclass | `TypeError at import` |
| an int storage field | `TypeError at import` |
| a storage field declared twice | `test_no_storage_field_or_method_is_declared_twice` |
| a prompt moved outside the block, which genvm-lint refuses | `test_an_acceptance_that_matches_the_offer_forms_the_agreement` |
<!-- /measured:mutations -->

The simulator can also model **a leader that lies**: `set_leader_payload()` puts
a value on the wire that `leader_fn` would never return, which is the only way to
exercise the checks a validator runs against a peer it does not trust. Without
it, every one of those checks is unreachable in testing and a defence that cannot
be exercised looks identical to one that is not there.

## Design rules

- **The block returns words, never an outcome.** One per frozen row, from two.
- **Consensus compares the canonical outcome.** A verdict and the rows that
  countered, and nothing a node measured about its own uncertainty.
- **Uncertainty enters the stored value, and only the value.** A row the two
  orders answered differently is `unclear`, and `unclear` decides something only
  where it decides whether a contract exists.
- **The catalogue is frozen, and the contract owns its last row.**
- **A counter-offer terminates the offer it answers**, whether a party says so
  in terms or a reply turns out to be one.
- **The mailbox rule.** A posted acceptance is judged before anybody can outrun
  it.
- **Every budget is a party's own**, and an acceptance is only posted if its
  counter-offer could be recorded.
- **Every write is bound to an address**, and a structural test asserts it for
  the methods nobody has written yet.
- **Untrusted text is fenced at the prompt boundary.** `fence()` neutralises `<`
  `>`, which close a tag, and `[` `]`, which number a row, so an offer or an
  acceptance can forge neither. Replace, never delete, and at the boundary only.
- **No global scans.** Every per-deal walk follows links the rows carry, or a
  range frozen at open.
- **Refusing is designed.** `countered` and `indeterminate` are the outputs this
  contract exists to produce.
- **No web access.** Every input is text the parties supply, which removes an
  entire class of deployment failure.

## Further reading in this repository

- [CONTRACTS.md](CONTRACTS.md) - the full specification: purpose, consensus,
  the deal's state machine, state model, API, reuse
- [DECISIONS.md](DECISIONS.md) - engineering decisions, what they cost, and
  what was built in from a sibling's audit
- [lib/assent_consensus.py](lib/assent_consensus.py) - the agreement rules on
  their own, to be copied. Generated by `scripts/lift.py` and checked for drift
  by the suite
- [brand/](brand/) - the mark, the lockup, the palette, and the social card

## Related work

Separate primitives, built to the same standard and submitted independently:
[Accrue](https://github.com/meitipro/accrue) - a credential that can only be
earned.
[Quorum](https://github.com/meitipro/quorum) - one question, several
independent sources, one answer or none.
[Covenant](https://github.com/meitipro/covenant) - a breach is cured within the
window or it becomes a default.
[Ratchet](https://github.com/meitipro/ratchet) - a published commitment that can
only ever be tightened.
[Keystone](https://github.com/meitipro/keystone) - an ordering built one pair at
a time that cannot contradict itself.
[Recant](https://github.com/meitipro/recant) - self-consistency across a record
of statements.

They share an author and a discipline, not a codebase. Each deploys, tests and is
used entirely on its own.

---

Published by [InferNode](https://x.com/Infer_node).
