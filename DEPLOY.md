# Deploying Assent

Everything you need is on this page. Deploy through the Studio web interface at
**studio.genlayer.com** - paste the contract, deploy, and call the methods
through the form. Never put a private key into a file or hand one to a tool.

You need **two accounts** in Studio: the seller, called **A** below, and the
buyer, called **B**. The account selector in Studio's top bar lets you create a
second account and switch between them; studionet charges no gas, so nothing
needs funding. Write down both addresses before you start. Every step says which
account it is run from.

`tests/test_runbook.py` replays this page step by step, with these exact
strings, and asserts every value it tells you to expect. If the page and the
contract ever disagree, that test fails before you do.

Do not try the refusals on the live contract - withdrawing an offer while an
acceptance is pending, accepting your own offer, posting a second acceptance
before the first is judged. They are refused, and each is tested, but a failed
transaction on the explorer page costs more than it shows.

---

## 1 - Get the contract

Open the raw file and copy all of it:

**https://raw.githubusercontent.com/meitipro/assent/main/contracts/assent.py**

Take it from that link, not from a local copy. What gets deployed has to be the
file in this repository - the reviewer reads the deployed source back off the
chain and compares it, and a submission has been rejected for nothing but a
stale address with the fix already sitting in the repository.

Paste it into Studio and deploy from **A**. **The constructor takes no
arguments.**

---

## 2 - Run the demo

Eight writes, in this order. `judge` may be called from either account: it is
open to anyone on purpose.

### The opening offer - from A

| # | Account | Method | Field | Value |
|---|---|---|---|---|
| 1 | **A** | `open` | `label` | `Office chairs, 40 units` |
| | | | `terms` | `unit price\|delivery date\|warranty` |
| | | | `text` | `We offer 40 ergonomic office chairs at 180 EUR each, delivered to your Rotterdam office by 15 October, with a two year warranty.` |
| | | | `counterparty` | *B's address* |

`terms` is **one string with pipe separators** - three named terms. The
contract appends a fourth row itself, `any other term or condition, not named in
this list`, so an acceptance that slips in a term nobody named is still caught.
The catalogue is frozen here and can never be edited. This is `offer(0)`, by A
to B.

### A conditional acceptance - B posts it, anyone judges

| # | Account | Method | Field | Value |
|---|---|---|---|---|
| 2 | **B** | `accept` | `deal_id` | `0` |
| | | | `text` | `We accept, provided delivery is brought forward to 1 October.` |
| 3 | either | `judge` | `deal_id` | `0` |

> **Stop here and read `attempt(0)` and `deal(0)`.**
>
> - **`verdict` = `countered`, `changed` = `0|1|0|0`** - the reply moved the
>   delivery date and nothing else, so it is a counter-offer, not an
>   acceptance. `deal(0)` shows `status` = `open`, `current` = `1`, `offeror` =
>   B's address and `offeree` = A's address: the roles have swapped.
>   `offer(0).terminated` is `true`, and `offer(1)` is `conditional`, by B to
>   A, with B's sentence as its text. Carry on.
> - **`countered` with `changed` = `0|1|0|1`** - the model also read the proviso
>   as a new term on the residual row. It is still a counter-offer and the rest
>   of the demo works the same, so carry on, but tell me.
> - **`formed`** - the model read the conditional acceptance as an acceptance.
>   Stop and send me the whole `attempt(0)` JSON. That is the failure this
>   contract exists to prevent.
> - **`indeterminate`** - the two orders read a row differently, nothing was
>   terminated and the same offer still stands. Stop and send me the JSON
>   before posting again.

### A takes the condition into a full offer - from A

| # | Account | Method | Field | Value |
|---|---|---|---|---|
| 4 | **A** | `counter` | `deal_id` | `0` |
| | | | `text` | `We offer 40 ergonomic office chairs at 180 EUR each, delivered to your Rotterdam office by 1 October, with a two year warranty.` |

A is now the offeree of B's conditional offer, so A may accept it, counter it
or reject it. A counters with the whole offer restated and the delivery date
moved, so the agreement that forms is one complete text. This is `offer(2)`,
kind `counter`, by A to B, answering `offer(1)`, which is now terminated. No
model is asked: a counter-offer says in terms that it is a new offer.

### The acceptance - B posts it, anyone judges

| # | Account | Method | Field | Value |
|---|---|---|---|---|
| 5 | **B** | `accept` | `deal_id` | `0` |
| | | | `text` | `We accept your offer in full, as written.` |
| 6 | either | `judge` | `deal_id` | `0` |

> **Stop here and read `attempt(1)` and `agreement(0)`.**
>
> - **`verdict` = `formed`, `changed` = `0|0|0|0`**, and `agreement(0)` shows
>   `agreed` = `true`, the offer text of step 4, the acceptance text of step 5,
>   `offeror` = A's address and `acceptor` = B's address. `deal(0)` shows
>   `status` = `agreed`, `agreed_offer` = `2` and `agreed_attempt` = `1`. Carry
>   on.
> - **anything else** - stop and send me the whole `attempt(1)` JSON.

### A second deal, withdrawn - from A

| # | Account | Method | Field | Value |
|---|---|---|---|---|
| 7 | **A** | `open` | `label` | `Desk lamps, 20 units` |
| | | | `terms` | `unit price\|delivery date` |
| | | | `text` | `We offer 20 brass desk lamps at 35 EUR each, delivered to your Rotterdam office by 30 October.` |
| | | | `counterparty` | *B's address* |
| 8 | **A** | `withdraw` | `deal_id` | `1` |

The offeror takes its offer back before anybody accepted it. `status(1)` is
`withdrawn` and `offer(3).terminated` is `true`. Had B posted an acceptance
first, the withdrawal would have been refused until the acceptance was judged:
that is the mailbox rule.

---

## 3 - Reads - free, no transaction

| Call | Argument | Expect |
|---|---|---|
| `count` | | `2` |
| `offer_count` | | `4` |
| `attempt_count` | | `2` |
| `status` | `0` | `agreed` |
| `status` | `1` | `withdrawn` |
| `deal` | `0` | `status agreed`, `current 2`, `offers 3`, `attempts 2`, `agreed true`, `agreed_offer 2`, `agreed_attempt 1`, `a_offers 2`, `b_offers 1`, `a_attempts 0`, `b_attempts 2` |
| `terms_of` | `0` | four rows, the last one `any other term or condition, not named in this list` with `residual true` |
| `history` | `0` | offers `offer`, `conditional`, `counter`, the first two terminated; attempts `countered` then `formed` |
| `offer` | `1` | `kind conditional`, `responds_to 0`, `terminated true` |
| `offer` | `2` | `kind counter`, `responds_to 1`, `accepted true` |
| `attempt` | `0` | `verdict countered`, `changed 0\|1\|0\|0`, `reason_is_leader_supplied true` |
| `agreement` | `0` | `agreed true`, the texts of steps 4 and 5 |
| `deal` | `1` | `status withdrawn`, `offers 1`, `attempts 0`, `agreed false` |
| `may_accept` | `0`, *B's address* | `false` - the deal is agreed |
| `may_accept` | `1`, *B's address* | `false` - the offer was withdrawn |

Every address a view returns is the EIP-55 checksummed form, with mixed case.
Compare addresses case-insensitively.

---

## 4 - Before the portal

```bash
python scripts/verify_deployment.py 0xYourAddress
```

Reads the source back out of the deploy transaction, compares it with
`contracts/assent.py`, and runs `genvm-lint lint` on those bytes. It must print
**"The address is evidence for this repository. Safe to submit."**

If it prints anything else, do not submit that address. It needs `genvm-lint`
installed (`pip install genvm-linter`), and says so if it is missing.

---

## 5 - Done

Paste the address into README.md and SUBMISSION.md where `{address}` appears,
replace the expected values in SUBMISSION.md with the ones read back from the
chain, and push.

One step stays manual: uploading `brand/social.png` under
Settings -> General -> Social preview. GitHub has no API for it.
