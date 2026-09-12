"""
End-to-end tests. The real contract file, executed.

tests/test_logic.py covers the pure rules. This file covers everything they
cannot reach: the deal's state machine in storage, the roles swapping on a
counter-offer, the mailbox rule, the budgets, the linked walks, the two-pass
block, the validator's gates against a leader that lies, the authority rules,
and every branch that only fires when the leader and a validator see different
things.

It runs on tests/glsim.py, a small GenVM stand-in, so it needs no Studio and no
network:

    pytest tests/test_e2e.py -v

The important property is that the leader and the validator get their own
independent mock answers. Every mocking framework feeds both nodes the same
data by default, which is exactly why a contract that quietly assumes both
nodes see identical bytes passes its suite and fails on a real network.
"""

import ast
import collections
import pathlib
import re

import pytest

import glsim as S

CONTRACT_PATH = "contracts/assent.py"
M = S.load_contract(CONTRACT_PATH)

LABEL = "Office chairs, 40 units"
TERMS = ["unit price", "delivery date", "warranty"]
ROWS = TERMS + [M.RESIDUAL]
CATALOGUE = "|".join(TERMS)
OFFER = ("We offer 40 ergonomic office chairs at 180 EUR each, delivered to your "
         "Rotterdam office by 15 October, with a two year warranty.")
CONDITIONAL = "We accept, provided delivery is brought forward to 1 October."
COUNTER = ("We offer 40 ergonomic office chairs at 180 EUR each, delivered to your "
           "Rotterdam office by 1 October, with a two year warranty.")
IN_FULL = "We accept your offer in full, as written."
SHIPPING = "We accept, and you also pay the shipping to Rotterdam."

SELLER = "0x" + "11" * 20
BUYER = "0x" + "22" * 20
STRANGER = "0x" + "99" * 20


def passes(forward, reverse, rows=ROWS, because="read from the texts"):
    """Mock both presentation orders of one judgment.

    The forward prompt opens its terms block with rows[0] as row [0]; the
    reversed prompt opens with the residual row. A mock keys on that opening
    row, and no key can match both prompts. `reverse` is given in the REVERSED
    order, exactly as a model would answer it, so a test has to think about the
    un-reversal the contract does.
    """
    keys = {
        "[0] " + rows[0]: {"terms": forward, "because": because},
        "[0] " + rows[-1]: {"terms": reverse, "because": because},
    }
    fwd = M.build_prompt(LABEL, rows, len(rows), "o", "a")
    rev = M.build_prompt(LABEL, list(reversed(rows)), len(rows), "o", "a")
    for key in keys:
        assert (key in fwd) != (key in rev), "a mock key matches both prompts: %r" % key
    return keys


def stable(vector, rows=ROWS):
    """The common case: both orders read every row the same way."""
    return passes(vector, "|".join(reversed(vector.split("|"))), rows)


def by_texts(table, label=LABEL, rows=ROWS):
    """Key every (offer, acceptance, order) on its FULL prompt, so one table
    answers several judgments differently and a judgment of the wrong texts
    finds the wrong answer. `table` maps (offer, acceptance) to the forward
    answer."""
    out = {}
    n = len(rows)
    for (offer, acceptance), forward in table.items():
        rev = "|".join(reversed(forward.split("|")))
        out[M.build_prompt(label, rows, n, offer, acceptance)] = {"terms": forward, "because": "x"}
        out[M.build_prompt(label, list(reversed(rows)), n, offer, acceptance)] = \
            {"terms": rev, "because": "x"}
    return out


def as_(who, c, method, *args):
    S.set_sender(who)
    try:
        return S.call(c, method, *args)
    finally:
        S.set_sender(SELLER)


class TestAssent:

    def deploy(self):
        c = S.deploy(CONTRACT_PATH)
        S.set_sender(SELLER)
        S.call(c, "open", LABEL, CATALOGUE, OFFER, BUYER)
        return c

    def mocks(self, prompts, v_prompts=None):
        S.set_mocks(leader_pages={}, leader_prompts=prompts, validator_pages={},
                    validator_prompts=v_prompts if v_prompts is not None else prompts)

    def judged(self, c, vector, text=CONDITIONAL, who=BUYER, deal=0):
        """Post one acceptance and judge it, both orders reading `vector`."""
        as_(who, c, "accept", deal, text)
        self.mocks(stable(vector))
        S.call(c, "judge", deal)
        return c.attempt(c.attempt_count() - 1)

    def alternate(self, c, rounds):
        """Counter back and forth. The offeree of the operative offer makes the
        next one, so the offers alternate between the parties."""
        for k in range(rounds):
            who = BUYER if k % 2 == 0 else SELLER
            as_(who, c, "counter", 0, "Counter-offer number %d, on the same terms otherwise." % k)

    # -- the deal -------------------------------------------------------------

    def test_a_deal_opens_with_its_catalogue_frozen_and_the_residual_row_last(self):
        c = self.deploy()
        d = c.deal(0)
        assert d["status"] == "open" and d["terms"] == ROWS
        assert d["party_a"] == SELLER and d["party_b"] == BUYER
        assert d["offeror"] == SELLER and d["offeree"] == BUYER and d["current"] == 0
        assert (d["offers"], d["attempts"], d["a_offers"], d["b_offers"]) == (1, 0, 1, 0)
        rows = c.terms_of(0)["terms"]
        assert [r["name"] for r in rows] == ROWS
        assert [r["residual"] for r in rows] == [False, False, False, True]
        assert all(r["deal"] == 0 for r in rows)
        o = c.offer(0)
        assert (o["kind"], o["by"], o["to"], o["text"], o["responds_to"]) == \
            ("offer", SELLER, BUYER, OFFER, 0)
        assert o["operative"] is True and o["terminated"] is False and o["accepted"] is False

    def test_an_acceptance_lands_before_it_is_judged(self):
        c = self.deploy()
        as_(BUYER, c, "accept", 0, IN_FULL)
        assert c.status(0) == "pending"
        a = c.attempt(0)
        assert (a["deal"], a["offer"], a["by"], a["text"]) == (0, 0, BUYER, IN_FULL)
        assert a["judged"] is False and a["verdict"] == "" and a["changed"] == ""
        assert c.deal(0)["b_attempts"] == 1 and c.offer(0)["operative"] is True

    # -- the three outcomes ---------------------------------------------------

    def test_an_acceptance_that_matches_the_offer_forms_the_agreement(self):
        c = self.deploy()
        a = self.judged(c, "same|same|same|same", IN_FULL)
        assert (a["verdict"], a["changed"], a["judged"]) == ("formed", "0|0|0|0", True)
        d = c.deal(0)
        assert d["status"] == "agreed" and d["agreed"] is True
        assert (d["agreed_offer"], d["agreed_attempt"]) == (0, 0)
        assert c.agreement(0) == {"agreed": True, "offer_text": OFFER, "acceptance_text": IN_FULL,
                                  "offeror": SELLER, "acceptor": BUYER}
        o = c.offer(0)
        assert o["accepted"] is True and o["operative"] is False and o["terminated"] is False

    def test_a_reply_that_changes_a_term_is_a_counter_offer_and_the_roles_swap(self):
        """The mirror-image rule. The answered offer is dead, and the reply
        stands as a new offer by its author."""
        c = self.deploy()
        a = self.judged(c, "same|changed|same|same", CONDITIONAL)
        assert (a["verdict"], a["changed"]) == ("countered", "0|1|0|0")
        assert c.offer(0)["terminated"] is True and c.offer(0)["operative"] is False
        d = c.deal(0)
        assert d["status"] == "open" and d["current"] == 1
        assert d["offeror"] == BUYER and d["offeree"] == SELLER
        assert (d["offers"], d["a_offers"], d["b_offers"]) == (2, 1, 1)
        o = c.offer(1)
        assert (o["kind"], o["by"], o["to"], o["text"], o["responds_to"]) == \
            ("conditional", BUYER, SELLER, CONDITIONAL, 0)
        assert o["operative"] is True and o["terminated"] is False
        assert c.agreement(0)["agreed"] is False

    def test_the_original_offeror_may_accept_the_conditional_offer(self):
        c = self.deploy()
        self.judged(c, "same|changed|same|same", CONDITIONAL)
        assert c.may_accept(0, SELLER) is True and c.may_accept(0, BUYER) is False
        reply = "Agreed, delivery by 1 October it is."
        as_(SELLER, c, "accept", 0, reply)
        self.mocks(by_texts({(CONDITIONAL, reply): "same|same|same|same"}))
        S.call(c, "judge", 0)
        assert c.status(0) == "agreed"
        assert c.agreement(0) == {"agreed": True, "offer_text": CONDITIONAL,
                                  "acceptance_text": reply, "offeror": BUYER, "acceptor": SELLER}
        d = c.deal(0)
        assert (d["a_attempts"], d["agreed_offer"], d["agreed_attempt"]) == (1, 1, 1)

    def test_the_residual_row_catches_a_term_the_catalogue_never_named(self):
        c = self.deploy()
        a = self.judged(c, "same|same|same|changed", SHIPPING)
        assert (a["verdict"], a["changed"]) == ("countered", "0|0|0|1")
        assert c.offer(1)["kind"] == "conditional" and c.offer(1)["text"] == SHIPPING

    def test_a_row_the_two_orders_answer_differently_leaves_the_offer_standing(self):
        """Forward reads the delivery date as changed; the reversed order reads
        it as the same. The row is unclear and nothing else changed, so the
        outcome is indeterminate: no contract forms and no offer dies."""
        c = self.deploy()
        as_(BUYER, c, "accept", 0, CONDITIONAL)
        self.mocks(passes("same|changed|same|same", "same|same|same|same"))
        S.call(c, "judge", 0)
        a = c.attempt(0)
        assert (a["verdict"], a["changed"]) == ("indeterminate", "0|0|0|0")
        d = c.deal(0)
        assert d["status"] == "open" and d["current"] == 0 and d["offers"] == 1
        assert c.offer(0)["terminated"] is False and c.offer(0)["operative"] is True
        # the recourse: the offeree tries again, with a clearer acceptance
        assert c.may_accept(0, BUYER) is True
        a = self.judged(c, "same|same|same|same", IN_FULL)
        assert a["verdict"] == "formed" and c.status(0) == "agreed"
        assert c.deal(0)["b_attempts"] == 2

    def test_an_unclear_row_is_never_named_in_a_counter(self):
        """Forward: the delivery date and the warranty changed. Reversed, read
        back: the delivery date changed, the warranty the same. The warranty is
        unclear, and once the delivery date has countered it decides nothing."""
        c = self.deploy()
        as_(BUYER, c, "accept", 0, CONDITIONAL)
        self.mocks(passes("same|changed|changed|same", "same|same|changed|same"))
        S.call(c, "judge", 0)
        a = c.attempt(0)
        assert (a["verdict"], a["changed"]) == ("countered", "0|1|0|0")

    def test_the_reversed_answer_is_read_back_into_the_frozen_order(self):
        """A consistent model: the delivery date changed in both orders, which
        is row [1] forward and row [2] reversed. Un-reversed, the orders agree."""
        c = self.deploy()
        as_(BUYER, c, "accept", 0, CONDITIONAL)
        self.mocks(passes("same|changed|same|same", "same|same|changed|same"))
        S.call(c, "judge", 0)
        assert c.attempt(0)["changed"] == "0|1|0|0"

    def test_the_same_position_marked_in_both_orders_is_position_bias(self):
        """The model marks row [1] in both prompts: the delivery date forward,
        the warranty reversed. That is a lean on position, and the fold catches
        it. A contract that forgot the un-reversal would read agreement and
        counter on the delivery date, over a reply that moved nothing."""
        c = self.deploy()
        as_(BUYER, c, "accept", 0, IN_FULL)
        self.mocks(passes("same|changed|same|same", "same|changed|same|same"))
        S.call(c, "judge", 0)
        a = c.attempt(0)
        assert (a["verdict"], a["changed"]) == ("indeterminate", "0|0|0|0")
        assert c.offer(0)["terminated"] is False

    @pytest.mark.parametrize("reverse", ["banana", "same|same", "same|unclear|same|same", ""])
    def test_an_unusable_pass_is_indeterminate_and_the_offer_stands(self, reverse):
        c = self.deploy()
        as_(BUYER, c, "accept", 0, IN_FULL)
        self.mocks(passes("same|same|same|same", reverse))
        S.call(c, "judge", 0)
        assert c.attempt(0)["verdict"] == "indeterminate"
        assert c.status(0) == "open" and c.offer(0)["terminated"] is False

    def test_a_prompt_answer_that_is_not_an_object_is_unusable_not_fatal(self):
        """json mode does not guarantee an object. A list or a bare string is
        an unusable answer and is recorded as one, rather than crashing the
        block and failing the transaction."""
        c = self.deploy()
        as_(BUYER, c, "accept", 0, IN_FULL)
        self.mocks({"[0] " + ROWS[0]: ["same"] * 4, "[0] " + M.RESIDUAL: "same|same|same|same"})
        S.call(c, "judge", 0)
        assert c.attempt(0)["verdict"] == "indeterminate" and c.status(0) == "open"

    # -- the moves that need no model ------------------------------------------

    def test_counter_terminates_the_offer_and_swaps_the_roles(self):
        c = self.deploy()
        as_(BUYER, c, "counter", 0, COUNTER)
        assert c.offer(0)["terminated"] is True
        o = c.offer(1)
        assert (o["kind"], o["by"], o["to"], o["responds_to"], o["text"]) == \
            ("counter", BUYER, SELLER, 0, COUNTER)
        d = c.deal(0)
        assert (d["status"], d["current"], d["offeror"], d["offeree"]) == ("open", 1, BUYER, SELLER)
        assert d["attempts"] == 0 and (d["a_offers"], d["b_offers"]) == (1, 1)
        assert c.may_accept(0, SELLER) is True and c.may_accept(0, BUYER) is False

    def test_withdraw_ends_the_deal_and_terminates_the_offer(self):
        c = self.deploy()
        S.call(c, "withdraw", 0)
        assert c.status(0) == "withdrawn"
        assert c.offer(0)["terminated"] is True and c.offer(0)["operative"] is False

    def test_reject_ends_the_deal_and_terminates_the_offer(self):
        c = self.deploy()
        as_(BUYER, c, "reject", 0)
        assert c.status(0) == "rejected" and c.offer(0)["terminated"] is True

    def test_history_keeps_every_offer_and_every_attempt_oldest_first(self):
        c = self.deploy()
        self.judged(c, "same|changed|same|same", CONDITIONAL)
        as_(SELLER, c, "counter", 0, COUNTER)
        self.judged(c, "same|same|same|same", IN_FULL)
        h = c.history(0)
        assert h["status"] == "agreed" and h["label"] == LABEL
        assert [(o["id"], o["kind"], o["by"], o["to"], o["responds_to"], o["terminated"])
                for o in h["offers"]] == [
            (0, "offer", SELLER, BUYER, 0, True),
            (1, "conditional", BUYER, SELLER, 0, True),
            (2, "counter", SELLER, BUYER, 1, False)]
        assert [(a["id"], a["offer"], a["by"], a["judged"], a["verdict"], a["changed"])
                for a in h["attempts"]] == [
            (0, 0, BUYER, True, "countered", "0|1|0|0"), (1, 2, BUYER, True, "formed", "0|0|0|0")]
        assert c.offer(2)["accepted"] is True and c.offer(1)["accepted"] is False

    # -- the mailbox rule, and a deal that is over ------------------------------

    def test_the_mailbox_rule_holds_while_an_acceptance_is_pending(self):
        """Once an acceptance is posted, the offeror cannot outrun it."""
        c = self.deploy()
        as_(BUYER, c, "accept", 0, IN_FULL)
        with pytest.raises(S.UserError, match="mailbox rule: an acceptance is posted, "
                                              "so the offer cannot be withdrawn"):
            S.call(c, "withdraw", 0)
        with pytest.raises(S.UserError, match="mailbox rule: an acceptance is posted, "
                                              "so the offer cannot be countered"):
            as_(BUYER, c, "counter", 0, COUNTER)
        with pytest.raises(S.UserError, match="mailbox rule: an acceptance is posted, "
                                              "so the offer cannot be rejected"):
            as_(BUYER, c, "reject", 0)
        with pytest.raises(S.UserError, match="already posted and awaits judgment"):
            as_(BUYER, c, "accept", 0, IN_FULL)
        assert c.status(0) == "pending" and c.offer(0)["terminated"] is False
        assert c.offer_count() == 1 and c.attempt_count() == 1
        self.mocks(stable("same|same|same|same"))
        S.call(c, "judge", 0)
        assert c.status(0) == "agreed"

    def test_judge_refuses_when_nothing_is_pending(self):
        c = self.deploy()
        with pytest.raises(S.UserError, match="nothing to judge: no acceptance is pending"):
            S.call(c, "judge", 0)
        self.judged(c, "same|same|same|same", IN_FULL)
        with pytest.raises(S.UserError, match="this deal is over"):
            S.call(c, "judge", 0)

    @pytest.mark.parametrize("end", ["agreed", "withdrawn", "rejected"])
    def test_a_deal_that_is_over_refuses_everything(self, end):
        c = self.deploy()
        if end == "agreed":
            self.judged(c, "same|same|same|same", IN_FULL)
        elif end == "withdrawn":
            S.call(c, "withdraw", 0)
        else:
            as_(BUYER, c, "reject", 0)
        assert c.status(0) == end
        for who, call in ((BUYER, ("accept", 0, IN_FULL)), (BUYER, ("counter", 0, COUNTER)),
                          (BUYER, ("reject", 0)), (SELLER, ("withdraw", 0)),
                          (STRANGER, ("judge", 0))):
            with pytest.raises(S.UserError, match="this deal is over"):
                as_(who, c, *call)
        assert c.may_accept(0, BUYER) is False and c.may_accept(0, SELLER) is False

    # -- authority --------------------------------------------------------------

    @pytest.mark.parametrize("who", [SELLER, STRANGER])
    def test_only_the_offeree_may_accept(self, who):
        c = self.deploy()
        with pytest.raises(S.UserError, match="only the offeree of the operative offer may accept it"):
            as_(who, c, "accept", 0, IN_FULL)
        assert c.status(0) == "open" and c.attempt_count() == 0

    @pytest.mark.parametrize("who", [SELLER, STRANGER])
    def test_only_the_offeree_may_counter(self, who):
        c = self.deploy()
        with pytest.raises(S.UserError, match="only the offeree of the operative offer may counter it"):
            as_(who, c, "counter", 0, COUNTER)
        assert c.offer_count() == 1 and c.offer(0)["terminated"] is False

    @pytest.mark.parametrize("who", [SELLER, STRANGER])
    def test_only_the_offeree_may_reject(self, who):
        c = self.deploy()
        with pytest.raises(S.UserError, match="only the offeree of the operative offer may reject it"):
            as_(who, c, "reject", 0)
        assert c.status(0) == "open"

    @pytest.mark.parametrize("who", [BUYER, STRANGER])
    def test_only_the_offeror_may_withdraw(self, who):
        c = self.deploy()
        with pytest.raises(S.UserError, match="only the offeror of the operative offer may withdraw it"):
            as_(who, c, "withdraw", 0)
        assert c.status(0) == "open"

    def test_after_a_counter_the_gates_follow_the_roles(self):
        c = self.deploy()
        as_(BUYER, c, "counter", 0, COUNTER)
        with pytest.raises(S.UserError, match="only the offeree"):
            as_(BUYER, c, "accept", 0, IN_FULL)
        with pytest.raises(S.UserError, match="only the offeror"):
            as_(SELLER, c, "withdraw", 0)
        as_(BUYER, c, "withdraw", 0)
        assert c.status(0) == "withdrawn"

    def test_anyone_may_judge_and_that_is_deliberate(self):
        """judge() adds no text and can reach only the outcome the two frozen
        texts imply. Both parties want an acceptance judged, so there is nobody
        to protect the record from here."""
        c = self.deploy()
        as_(BUYER, c, "accept", 0, CONDITIONAL)
        self.mocks(stable("same|changed|same|same"))
        as_(STRANGER, c, "judge", 0)
        assert c.attempt(0)["verdict"] == "countered"

    def test_an_address_is_matched_by_value_not_by_spelling(self):
        c = S.deploy(CONTRACT_PATH)
        S.set_sender(SELLER)
        S.call(c, "open", LABEL, CATALOGUE, OFFER, "0x" + "AB" * 20)
        assert c.may_accept(0, "0x" + "Ab" * 20) is True
        as_("0x" + "ab" * 20, c, "accept", 0, IN_FULL)
        assert c.status(0) == "pending"

    # -- budgets ----------------------------------------------------------------

    def test_each_party_may_post_at_most_6_acceptances(self):
        """An indeterminate judgment leaves the offer standing, so without a
        budget one party could post acceptances for ever."""
        c = self.deploy()
        for k in range(6):
            as_(BUYER, c, "accept", 0, "We accept, attempt %d." % k)
            self.mocks(passes("same|same|same|same", "banana"))
            S.call(c, "judge", 0)
        assert c.deal(0)["b_attempts"] == 6 and c.status(0) == "open"
        assert c.may_accept(0, BUYER) is False
        with pytest.raises(S.UserError, match="each party may make at most 6 acceptance attempts on a deal"):
            as_(BUYER, c, "accept", 0, IN_FULL)
        # the offeree may still reject, so the deal can always end
        as_(BUYER, c, "reject", 0)
        assert c.status(0) == "rejected"

    def test_each_party_may_make_at_most_6_offers(self):
        c = self.deploy()
        self.alternate(c, 11)
        d = c.deal(0)
        assert (d["offers"], d["a_offers"], d["b_offers"]) == (12, 6, 6)
        assert d["offeror"] == BUYER and d["offeree"] == SELLER
        with pytest.raises(S.UserError, match="each party may make at most 6 offers on a deal"):
            as_(SELLER, c, "counter", 0, COUNTER)
        assert c.offer_count() == 12 and len(c.history(0)["offers"]) == 12

    def test_an_acceptance_is_refused_when_its_counter_could_not_be_recorded(self):
        """A countered acceptance becomes an offer by its author, so posting
        one needs an offer slot as well as an attempt. It is checked at
        accept(), so judge() can never fail on a budget."""
        c = self.deploy()
        self.alternate(c, 11)
        assert c.may_accept(0, SELLER) is False
        with pytest.raises(S.UserError, match="each party may make at most 6 offers on a deal, "
                                              "and a countered acceptance would be one more"):
            as_(SELLER, c, "accept", 0, IN_FULL)
        assert c.attempt_count() == 0
        # the deal can still end: the offeror withdraws
        as_(BUYER, c, "withdraw", 0)
        assert c.status(0) == "withdrawn"

    def test_the_last_offer_slot_is_spent_by_a_countered_acceptance(self):
        c = self.deploy()
        self.alternate(c, 10)
        d = c.deal(0)
        assert (d["offers"], d["a_offers"], d["b_offers"], d["offeree"]) == (11, 6, 5, BUYER)
        assert c.may_accept(0, BUYER) is True
        a = self.judged(c, "same|changed|same|same", CONDITIONAL)
        assert a["verdict"] == "countered"
        d = c.deal(0)
        assert (d["offers"], d["b_offers"], d["offeree"]) == (12, 6, SELLER)
        assert c.may_accept(0, SELLER) is False

    # -- may_accept mirrors accept() ---------------------------------------------

    def test_may_accept_mirrors_accept_in_every_state(self):
        c = self.deploy()
        for bad in ((9, BUYER), (9, "not-an-address"), (-1, BUYER)):
            with pytest.raises(S.UserError, match="no such deal"):
                c.may_accept(*bad)
        assert c.may_accept(0, "not-an-address") is False
        assert c.may_accept(0, BUYER) is True
        assert c.may_accept(0, SELLER) is False and c.may_accept(0, STRANGER) is False
        for who, ok in ((SELLER, False), (STRANGER, False)):
            with pytest.raises(S.UserError, match="only the offeree"):
                as_(who, c, "accept", 0, IN_FULL)
        as_(BUYER, c, "accept", 0, IN_FULL)
        assert c.may_accept(0, BUYER) is False                        # pending
        self.mocks(stable("same|changed|same|same"))
        S.call(c, "judge", 0)
        assert c.may_accept(0, SELLER) is True                        # the roles swapped
        assert c.may_accept(0, BUYER) is False
        S.call(c, "reject", 0)
        assert c.may_accept(0, SELLER) is False                       # over

    # -- the linked walks ---------------------------------------------------------

    def test_two_deals_never_see_each_other_s_rows(self):
        c = self.deploy()
        lamps = ("We offer 20 brass desk lamps at 35 EUR each, delivered to your "
                 "Rotterdam office by 30 October.")
        lamp_label = "Desk lamps, 20 units"
        lamp_rows = ["unit price", "delivery date", M.RESIDUAL]
        counter1 = "We offer to buy 20 brass desk lamps at 30 EUR each, delivered by 30 October."
        S.call(c, "open", lamp_label, "unit price|delivery date", lamps, BUYER)
        as_(BUYER, c, "counter", 1, counter1)
        as_(BUYER, c, "accept", 0, CONDITIONAL)
        h0, h1 = c.history(0), c.history(1)
        assert [o["id"] for o in h0["offers"]] == [0] and [o["id"] for o in h1["offers"]] == [1, 2]
        assert [a["id"] for a in h0["attempts"]] == [0] and h1["attempts"] == []
        assert c.deal(1)["terms"] == lamp_rows
        assert [r["deal"] for r in c.terms_of(1)["terms"]] == [1, 1, 1]
        # deal 0 is judged against its own four rows and its own offer
        self.mocks(by_texts({(OFFER, CONDITIONAL): "same|changed|same|same"}))
        S.call(c, "judge", 0)
        assert c.attempt(0)["changed"] == "0|1|0|0"
        assert [o["id"] for o in c.history(0)["offers"]] == [0, 3]
        assert [o["id"] for o in c.history(1)["offers"]] == [1, 2]
        # deal 1 is judged against its own three rows and its own offer
        as_(SELLER, c, "accept", 1, "Agreed at 30 EUR each.")
        self.mocks(by_texts({(counter1, "Agreed at 30 EUR each."): "same|same|same"},
                            label=lamp_label, rows=lamp_rows))
        S.call(c, "judge", 1)
        assert c.status(1) == "agreed" and c.status(0) == "open"
        assert c.agreement(1)["offer_text"] == counter1
        assert [a["id"] for a in c.history(1)["attempts"]] == [1]

    # -- consensus --------------------------------------------------------------

    def test_nodes_that_name_different_rows_do_not_agree(self):
        c = self.deploy()
        as_(BUYER, c, "accept", 0, CONDITIONAL)
        self.mocks(stable("same|changed|same|same"), v_prompts=stable("same|same|changed|same"))
        with pytest.raises(S.UserError):
            S.call(c, "judge", 0)
        assert c.status(0) == "pending" and c.attempt(0)["judged"] is False
        assert c.offer(0)["terminated"] is False and c.offer_count() == 1

    def test_an_unclear_row_beside_a_change_does_not_split_the_vote(self):
        """The leader folds the warranty to unclear beside a changed delivery
        date; a validator reads the warranty as the same. Both counter on the
        delivery date alone, so they agree, and the network settles."""
        c = self.deploy()
        as_(BUYER, c, "accept", 0, CONDITIONAL)
        self.mocks(passes("same|changed|changed|same", "same|same|changed|same"),
                   v_prompts=stable("same|changed|same|same"))
        S.call(c, "judge", 0)
        assert c.attempt(0)["changed"] == "0|1|0|0"

    def test_an_unclear_row_against_a_clean_read_does_split_the_vote(self):
        """Indeterminate against formed. That difference is whether a contract
        exists, so the network must agree on it or not settle."""
        c = self.deploy()
        as_(BUYER, c, "accept", 0, IN_FULL)
        self.mocks(passes("same|changed|same|same", "same|same|same|same"),
                   v_prompts=stable("same|same|same|same"))
        with pytest.raises(S.UserError):
            S.call(c, "judge", 0)
        assert c.status(0) == "pending" and c.agreement(0)["agreed"] is False

    def test_the_leader_s_explanation_is_stored_sanitised(self):
        """`why` is the one stored field the leader chooses outright, so it is
        cleaned at the point it is stored, not only where it is produced."""
        c = self.deploy()
        as_(BUYER, c, "accept", 0, IN_FULL)
        self.mocks(stable("same|same|same|same"))
        S.set_leader_payload({"verdict": "formed", "changed": "0|0|0|0",
                              "because": "<b>{x}`y`" + chr(1) + "z"})
        try:
            S.call(c, "judge", 0)
        finally:
            S.set_leader_payload(None)
        assert c.attempt(0)["why"] == "bxy z"
        assert c.attempt(0)["reason_is_leader_supplied"] is True

    # -- the validator's gates, against a leader it does not trust --------------

    def test_a_leader_that_rolled_back_is_refused_and_nothing_is_stored(self):
        """Only the forward prompt is mocked, so the leader's block fails. The
        validator must refuse it cleanly rather than read a result that is not
        there."""
        c = self.deploy()
        as_(BUYER, c, "accept", 0, IN_FULL)
        self.mocks({"[0] " + ROWS[0]: {"terms": "same|same|same|same", "because": "x"}})
        with pytest.raises(S.UserError):
            S.call(c, "judge", 0)
        assert S.RT.last_validator_verdict is False
        assert c.status(0) == "pending" and c.attempt(0)["judged"] is False

    def test_a_leader_payload_that_is_not_a_mapping_is_refused_for_free(self):
        c = self.deploy()
        as_(BUYER, c, "accept", 0, IN_FULL)
        self.mocks(stable("same|same|same|same"))      # mocks first: set_mocks resets the payload
        S.set_leader_payload("not a mapping")
        try:
            with pytest.raises(S.UserError):
                S.call(c, "judge", 0)
        finally:
            S.set_leader_payload(None)
        assert S.validator_prompt_calls() == 0
        assert c.attempt(0)["judged"] is False

    @pytest.mark.parametrize("payload", [
        {"verdict": "formed", "changed": "0|0|0", "because": "x"},        # wrong length
        {"verdict": "formed", "changed": "0|1|0|0", "because": "x"},      # formed, naming a row
        {"verdict": "countered", "changed": "0|0|0|0", "because": "x"},   # countered, naming none
        {"verdict": "agreed", "changed": "0|0|0|0", "because": "x"},      # not a verdict
        {"verdict": "countered", "changed": "0|2|0|0", "because": "x"},   # not a bit
        {"because": "x"},                                                 # nothing at all
    ])
    def test_a_malformed_proposal_is_refused_with_zero_validator_prompts(self, payload):
        """The free layer is only worth having if it is free, and the prompt
        count is the only observable difference."""
        c = self.deploy()
        as_(BUYER, c, "accept", 0, IN_FULL)
        self.mocks(stable("same|same|same|same"))
        S.set_leader_payload(payload)
        try:
            with pytest.raises(S.UserError):
                S.call(c, "judge", 0)
        finally:
            S.set_leader_payload(None)
        assert S.validator_prompt_calls() == 0
        assert c.attempt(0)["judged"] is False

    def test_a_lying_leader_cannot_form_an_agreement_the_texts_do_not_make(self):
        """A well formed lie passes layer 1 and dies at layer 2, after the
        validator has read the two texts itself."""
        c = self.deploy()
        as_(BUYER, c, "accept", 0, CONDITIONAL)
        self.mocks(stable("same|changed|same|same"))
        S.set_leader_payload({"verdict": "formed", "changed": "0|0|0|0", "because": "x"})
        try:
            with pytest.raises(S.UserError):
                S.call(c, "judge", 0)
        finally:
            S.set_leader_payload(None)
        assert S.validator_prompt_calls() == 2
        assert c.status(0) == "pending" and c.agreement(0)["agreed"] is False

    # -- validation, at both edges ------------------------------------------------

    @pytest.mark.parametrize("label,ok", [("a", False), ("ab", True),
                                          ("x" * 120, True), ("x" * 121, False)])
    def test_the_label_bounds(self, label, ok):
        c = S.deploy(CONTRACT_PATH)
        S.set_sender(SELLER)
        if ok:
            S.call(c, "open", label, CATALOGUE, OFFER, BUYER)
            assert c.deal(0)["label"] == label
        else:
            with pytest.raises(S.UserError, match="a label of at least 2 characters|"
                                                  "a label is capped at 120 characters"):
                S.call(c, "open", label, CATALOGUE, OFFER, BUYER)
            assert c.count() == 0

    def test_the_catalogue_bounds(self):
        c = S.deploy(CONTRACT_PATH)
        S.set_sender(SELLER)
        eight = "|".join("term %d" % k for k in range(8))
        S.call(c, "open", LABEL, eight, OFFER, BUYER)
        assert len(c.deal(0)["terms"]) == 9
        with pytest.raises(S.UserError, match="capped at 8 named terms"):
            S.call(c, "open", LABEL, eight + "|term 8", OFFER, BUYER)
        for empty in ("", "|||", "  |  "):
            with pytest.raises(S.UserError, match="at least one named term"):
                S.call(c, "open", LABEL, empty, OFFER, BUYER)
        for dupes in ("price|delivery|price", "Unit price|unit price"):
            with pytest.raises(S.UserError, match="same wording"):
                S.call(c, "open", LABEL, dupes, OFFER, BUYER)
        with pytest.raises(S.UserError, match="residual row is added by the contract"):
            S.call(c, "open", LABEL, "price|" + M.RESIDUAL.upper(), OFFER, BUYER)
        assert c.count() == 1

    def test_a_term_is_capped_and_never_truncated(self):
        c = S.deploy(CONTRACT_PATH)
        S.set_sender(SELLER)
        with pytest.raises(S.UserError, match="a term name is capped at 60 characters"):
            S.call(c, "open", LABEL, "x" * 61 + "|b", OFFER, BUYER)
        S.call(c, "open", LABEL, "x" * 60 + "|b", OFFER, BUYER)
        assert c.deal(0)["terms"][0] == "x" * 60

    @pytest.mark.parametrize("n,ok", [(19, False), (20, True), (700, True), (701, False)])
    def test_the_offer_length_bounds(self, n, ok):
        c = S.deploy(CONTRACT_PATH)
        S.set_sender(SELLER)
        if ok:
            S.call(c, "open", LABEL, CATALOGUE, "o" * n, BUYER)
            assert len(c.offer(0)["text"]) == n
        else:
            with pytest.raises(S.UserError, match="an offer needs at least 20 characters|"
                                                  "an offer is capped at 700 characters"):
                S.call(c, "open", LABEL, CATALOGUE, "o" * n, BUYER)
            assert c.count() == 0

    @pytest.mark.parametrize("n,ok", [(19, False), (20, True), (700, True), (701, False)])
    def test_the_counter_offer_length_bounds(self, n, ok):
        c = self.deploy()
        if ok:
            as_(BUYER, c, "counter", 0, "c" * n)
            assert len(c.offer(1)["text"]) == n
        else:
            with pytest.raises(S.UserError, match="a counter-offer needs at least 20 characters|"
                                                  "a counter-offer is capped at 700 characters"):
                as_(BUYER, c, "counter", 0, "c" * n)
            assert c.offer_count() == 1 and c.offer(0)["terminated"] is False

    @pytest.mark.parametrize("n,ok", [(1, False), (2, True), (400, True), (401, False)])
    def test_the_acceptance_length_bounds(self, n, ok):
        c = self.deploy()
        if ok:
            as_(BUYER, c, "accept", 0, "a" * n)
            assert len(c.attempt(0)["text"]) == n
        else:
            with pytest.raises(S.UserError, match="an acceptance needs at least 2 characters|"
                                                  "an acceptance is capped at 400 characters"):
                as_(BUYER, c, "accept", 0, "a" * n)
            assert c.attempt_count() == 0 and c.status(0) == "open"

    def test_the_counterparty_must_be_another_address(self):
        c = S.deploy(CONTRACT_PATH)
        S.set_sender(SELLER)
        for bad in ("not-an-address", "0x1234", "", "0x" + "zz" * 20):
            with pytest.raises(S.UserError, match="not a 20 byte hex address"):
                S.call(c, "open", LABEL, CATALOGUE, OFFER, bad)
        with pytest.raises(S.UserError, match="the counterparty cannot be the caller"):
            S.call(c, "open", LABEL, CATALOGUE, OFFER, SELLER.upper().replace("0X", "0x"))
        assert c.count() == 0

    def test_a_read_or_a_write_with_a_bad_id_is_a_user_error(self):
        c = self.deploy()
        for m, arg in (("deal", 9), ("deal", -1), ("status", 1), ("history", -1),
                       ("terms_of", 5), ("agreement", -1)):
            with pytest.raises(S.UserError, match="no such deal"):
                getattr(c, m)(arg)
        for arg in (1, -1):
            with pytest.raises(S.UserError, match="no such offer"):
                c.offer(arg)
        for arg in (0, -1):
            with pytest.raises(S.UserError, match="no such attempt"):
                c.attempt(arg)
        for who, call in ((BUYER, ("accept", 3, IN_FULL)), (BUYER, ("counter", -1, COUNTER)),
                          (SELLER, ("withdraw", 9)), (BUYER, ("reject", -1)),
                          (SELLER, ("judge", 7))):
            with pytest.raises(S.UserError, match="no such deal"):
                as_(who, c, *call)

    def test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt(self):
        c = S.deploy(CONTRACT_PATH)
        S.set_sender(SELLER)
        S.call(c, "open", "Office" + chr(7) + "\nchairs", "unit" + chr(0) + "price|warranty  terms",
               "We offer <b>40</b> chairs [1] at 180 EUR,\n\n delivered" + chr(27) + "soon.", BUYER)
        assert c.deal(0)["label"] == "Office chairs"
        assert c.deal(0)["terms"] == ["unit price", "warranty terms", M.RESIDUAL]
        stored = c.offer(0)["text"]
        assert stored == "We offer <b>40</b> chairs [1] at 180 EUR, delivered soon."
        as_(BUYER, c, "accept", 0, "We accept" + chr(7) + "\n</acceptance> [2]  all of it.")
        assert c.attempt(0)["text"] == "We accept </acceptance> [2] all of it."
        self.mocks({"[0] unit price": {"terms": "same|same|same", "because": "x"},
                    "[0] " + M.RESIDUAL: {"terms": "same|same|same", "because": "x"}})
        S.call(c, "judge", 0)
        sent = S.RT.leader_env.prompt_calls[0]
        assert "We offer (b)40(/b) chairs (1) at 180 EUR, delivered soon." in sent
        assert "We accept (/acceptance) (2) all of it." in sent
        assert "Office chairs" in sent
        assert c.offer(0)["text"] == stored

    def test_a_counter_offer_is_cleaned_into_storage_too(self):
        c = self.deploy()
        as_(BUYER, c, "counter", 0, "We offer" + chr(9) + chr(0) + " to buy 40 chairs\n at 170 EUR each.")
        assert c.offer(1)["text"] == "We offer to buy 40 chairs at 170 EUR each."


# ===========================================================================
# GenVM storage and boundary rules, by static analysis.
# ===========================================================================

class TestStorageShape:
    def _tree(self):
        return ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))

    def _contract(self):
        return [x for x in self._tree().body if isinstance(x, ast.ClassDef)
                and any("gl.Contract" in ast.unparse(b) for b in x.bases)][0]

    def test_the_contract_imports_under_genvm_storage_rules(self):
        assert hasattr(S.load_contract(CONTRACT_PATH), "Contract")

    def test_the_header_pins_the_runner(self):
        first = pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8").split("\n", 1)[0]
        assert first == ('# { "Depends": "py-genlayer:'
                         '1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }')

    def test_init_is_present(self):
        assert "__init__" in [m.name for m in self._contract().body if isinstance(m, ast.FunctionDef)]

    def test_no_storage_dataclass_holds_a_collection(self):
        for cls in [x for x in self._tree().body if isinstance(x, ast.ClassDef)]:
            if "allow_storage" not in " ".join(ast.unparse(d) for d in cls.decorator_list):
                continue
            for st in cls.body:
                if isinstance(st, ast.AnnAssign):
                    ann = ast.unparse(st.annotation)
                    assert "DynArray" not in ann and "TreeMap" not in ann, (cls.name, ann)

    def test_no_forbidden_storage_types(self):
        for cls in [x for x in self._tree().body if isinstance(x, ast.ClassDef)]:
            decs = " ".join(ast.unparse(d) for d in cls.decorator_list)
            is_contract = any("gl.Contract" in ast.unparse(b) for b in cls.bases)
            if "allow_storage" not in decs and not is_contract:
                continue
            for st in cls.body:
                if isinstance(st, ast.AnnAssign):
                    ann = ast.unparse(st.annotation)
                    assert ann not in ("int", "float", "list", "dict", "tuple"), (cls.name, ann)

    def test_no_storage_field_or_method_is_declared_twice(self):
        for cls in [x for x in self._tree().body if isinstance(x, ast.ClassDef)]:
            fields = [st.target.id for st in cls.body if isinstance(st, ast.AnnAssign)]
            meths = [m.name for m in cls.body if isinstance(m, ast.FunctionDef)]
            for names in (fields, meths):
                dupes = [n for n, k in collections.Counter(names).items() if k > 1]
                assert not dupes, f"{cls.name}: {dupes}"

    def test_every_persistent_field_is_declared_in_the_class_body(self):
        cls = self._contract()
        declared = {st.target.id for st in cls.body if isinstance(st, ast.AnnAssign)}
        for m in [x for x in cls.body if isinstance(x, ast.FunctionDef)]:
            for node in ast.walk(m):
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target] if isinstance(node, ast.AugAssign) else [])
                for tg in targets:
                    if isinstance(tg, ast.Attribute) and isinstance(tg.value, ast.Name) \
                            and tg.value.id == "self":
                        assert tg.attr in declared, f"self.{tg.attr} undeclared"

    def test_every_stored_field_is_read_somewhere(self):
        """A field nothing reads is a field whose comment nobody checks."""
        tree = self._tree()
        fields = set()
        for cls in [x for x in tree.body if isinstance(x, ast.ClassDef)]:
            if "allow_storage" in " ".join(ast.unparse(d) for d in cls.decorator_list):
                fields |= {st.target.id for st in cls.body if isinstance(st, ast.AnnAssign)}
        loaded = {n.attr for n in ast.walk(self._contract())
                  if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load)}
        assert fields - loaded == set(), f"written, never read: {sorted(fields - loaded)}"

    def test_the_block_boundary_carries_flat_strings_only(self):
        blocks = [x for x in ast.walk(self._tree()) if isinstance(x, ast.FunctionDef)
                  and x.name == "leader_fn"]
        assert blocks
        for blk in blocks:
            for r in [n for n in ast.walk(blk) if isinstance(n, ast.Return)]:
                assert isinstance(r.value, ast.Dict)
                for k, v in zip(r.value.keys, r.value.values):
                    assert isinstance(k, ast.Constant) and isinstance(k.value, str)
                    assert not isinstance(v, (ast.Dict, ast.List, ast.Set, ast.Tuple,
                                              ast.Compare, ast.BoolOp, ast.Constant))

    def test_the_block_never_touches_storage(self):
        for blk in [x for x in ast.walk(self._tree()) if isinstance(x, ast.FunctionDef)
                    and x.name in ("leader_fn", "validator_fn")]:
            for n in ast.walk(blk):
                if isinstance(n, ast.Name):
                    assert n.id != "self", f"{blk.name} reads storage"

    def test_prompts_are_only_ever_run_inside_the_block(self):
        cls = self._contract()
        for m in [x for x in cls.body if isinstance(x, ast.FunctionDef)]:
            inner = {id(n) for f in ast.walk(m) if isinstance(f, ast.FunctionDef)
                     and f.name in ("leader_fn", "validator_fn") for n in ast.walk(f)}
            for n in ast.walk(m):
                if isinstance(n, ast.Attribute) and ast.unparse(n).startswith("gl.nondet"):
                    assert id(n) in inner, f"{m.name} runs a prompt outside the block"

    def test_no_identity_comparison_on_storage(self):
        for n in ast.walk(self._tree()):
            if isinstance(n, ast.Compare) and any(isinstance(o, (ast.Is, ast.IsNot)) for o in n.ops):
                assert "self." not in ast.unparse(n)

    def test_every_gated_write_checks_the_sender(self):
        """Not a substring search. For every write except `open` (which makes
        the caller party A) and `judge` (deliberately open, see the behavioural
        test), there must be an `if` whose test reads the sender, directly or
        through a local derived from it, and whose body raises."""
        UNGATED = {"open", "judge"}
        writes = [m for m in self._contract().body if isinstance(m, ast.FunctionDef)
                  and any("gl.public.write" in ast.unparse(d) for d in m.decorator_list)]
        assert {m.name for m in writes} == {"open", "accept", "counter", "withdraw", "reject", "judge"}
        for m in writes:
            if m.name in UNGATED:
                continue
            aliases, grew = set(), True
            while grew:
                grew = False
                for node in ast.walk(m):
                    if not isinstance(node, ast.Assign):
                        continue
                    reads = ("sender_address" in ast.unparse(node.value)
                             or any(isinstance(x, ast.Name) and x.id in aliases
                                    for x in ast.walk(node.value)))
                    for t in node.targets:
                        if reads and isinstance(t, ast.Name) and t.id not in aliases:
                            aliases.add(t.id)
                            grew = True
            gated = False
            for node in ast.walk(m):
                if not isinstance(node, ast.If):
                    continue
                reads = ("sender_address" in ast.unparse(node.test)
                         or any(isinstance(x, ast.Name) and x.id in aliases for x in ast.walk(node.test)))
                raises = any(isinstance(x, ast.Raise) for st in node.body for x in ast.walk(st))
                gated = gated or (reads and raises)
            assert gated, f"{m.name} has no sender check that refuses"

    def test_no_global_scan_over_any_storage_array(self):
        """Every walk follows links or a frozen range. A loop, or a
        comprehension, over range(len(self.<array>)) is a scan of everybody
        else's rows."""
        scans = [ast.unparse(n.iter) for n in ast.walk(self._tree())
                 if isinstance(n, (ast.For, ast.comprehension))
                 and re.search(r"len\(self\.", ast.unparse(n.iter))]
        assert scans == [], scans
