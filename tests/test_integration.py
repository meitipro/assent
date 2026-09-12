"""Integration tests, run against GenLayer Studio with gltest.

    pip install genlayer-test
    GENLAYER_STUDIO=1 gltest --network studionet tests/test_integration.py

They are opt in: without GENLAYER_STUDIO set they skip, so that
`pytest tests/ -q` stays clean on a machine that has genlayer-test
installed but no Studio to talk to.

These are slower than the other suites and they prove something different:
that the contract deploys, that storage round-trips, that the linked walks hold
on a real runtime, and that the deterministic gates fire.

Everything here exercises the deterministic half, which needs no inference: a
deal opens with a frozen catalogue and the residual row, an acceptance lands
before it is judged, the mailbox rule holds, the authority rules fire, refusals
are clean. The judging path costs two prompts per node and belongs in a manual
Studio run; see DEPLOY.md.
"""

import os

import pytest

# gltest is only needed for this file. Skip cleanly when it is absent so that
# `pytest tests/` works out of the box on a machine with nothing installed but
# pytest, and still runs everything else.
gltest = pytest.importorskip(
    "gltest",
    reason="integration tests need genlayer-test and a running Studio: "
           "pip install genlayer-test, then GENLAYER_STUDIO=1 gltest",
)
from gltest import get_contract_factory, get_accounts        # noqa: E402
from gltest.assertions import tx_execution_succeeded         # noqa: E402


# The second half of the same guard, and it is the half that bites.
#
# importorskip above covers "genlayer-test is not installed". It does NOT cover
# "genlayer-test IS installed and there is no Studio to talk to", which is the
# common case for anybody who reviews GenLayer contracts: the plugin loads,
# collects this file, and every test in it fails on a connection error rather
# than skipping. So the gate is explicit. These tests need a live Studio, and
# you say so.
if not os.environ.get("GENLAYER_STUDIO"):
    pytest.skip(
        "integration tests run against a live GenLayer Studio and are opt in: "
        "set GENLAYER_STUDIO=1 to enable them. Everything else runs offline "
        "with pytest tests/ -q",
        allow_module_level=True,
    )


LABEL = "Office chairs, 40 units"
TERMS = "unit price|delivery date|warranty"
OFFER = ("We offer 40 ergonomic office chairs at 180 EUR each, delivered to your "
         "Rotterdam office by 15 October, with a two year warranty.")
IN_FULL = "We accept your offer in full, as written."
RESIDUAL = "any other term or condition, not named in this list"


def same(a, b):
    """Every address a view returns is the EIP-55 checksummed string on chain."""
    return str(a).lower() == str(b).lower()


class TestAssent:
    """The deterministic half on a real runtime. Two accounts, because a deal
    needs two parties."""

    @pytest.fixture
    def two(self):
        accounts = get_accounts()
        if len(accounts) < 2:
            pytest.skip("needs two configured accounts: a seller and a buyer")
        return accounts[0], accounts[1]

    @pytest.fixture
    def contract(self, two):
        seller, _ = two
        factory = get_contract_factory(contract_file_path="assent.py")
        return factory.deploy(args=[], account=seller)

    def test_a_deal_opens_with_its_catalogue_and_the_residual_row(self, contract, two):
        seller, buyer = two
        assert tx_execution_succeeded(contract.open(args=[LABEL, TERMS, OFFER, buyer.address]))
        d = contract.deal(args=[0])
        assert d["status"] == "open" and d["terms"][-1] == RESIDUAL and len(d["terms"]) == 4
        assert same(d["offeror"], seller.address) and same(d["offeree"], buyer.address)

    def test_an_acceptance_lands_before_it_is_judged(self, contract, two):
        _, buyer = two
        contract.open(args=[LABEL, TERMS, OFFER, buyer.address])
        assert tx_execution_succeeded(contract.connect(buyer).accept(args=[0, IN_FULL]))
        assert contract.status(args=[0]) == "pending"
        assert contract.attempt(args=[0])["judged"] is False

    def test_the_mailbox_rule_holds_on_chain(self, contract, two):
        _, buyer = two
        contract.open(args=[LABEL, TERMS, OFFER, buyer.address])
        contract.connect(buyer).accept(args=[0, IN_FULL])
        with pytest.raises(Exception):
            contract.withdraw(args=[0])
        assert contract.status(args=[0]) == "pending"

    def test_a_fragment_is_refused(self, contract, two):
        _, buyer = two
        with pytest.raises(Exception):
            contract.open(args=[LABEL, TERMS, "too short", buyer.address])

    def test_naming_the_residual_row_is_refused(self, contract, two):
        _, buyer = two
        with pytest.raises(Exception):
            contract.open(args=[LABEL, "price|" + RESIDUAL, OFFER, buyer.address])

    def test_a_deal_with_oneself_is_refused(self, contract, two):
        seller, _ = two
        with pytest.raises(Exception):
            contract.open(args=[LABEL, TERMS, OFFER, seller.address])

    def test_an_unknown_deal_is_refused(self, contract):
        with pytest.raises(Exception):
            contract.deal(args=[9])

    def test_a_negative_id_does_not_return_the_newest_row(self, contract, two):
        # Python accepts -1 and hands back the last row, correctly formatted,
        # with nothing failing anywhere.
        _, buyer = two
        contract.open(args=[LABEL, TERMS, OFFER, buyer.address])
        with pytest.raises(Exception):
            contract.deal(args=[-1])


class TestAuthority:
    """The authorisation rules, against a real runtime.

    These matter more than the rest of this file. tests/glsim.py models
    gl.message.sender_address with a variable a test can set; a node derives it
    from a signature. A rule that holds in the simulator and not on chain would
    be invisible to every other test here.
    """

    @pytest.fixture
    def three(self):
        accounts = get_accounts()
        if len(accounts) < 3:
            pytest.skip("needs three configured accounts: seller, buyer, stranger")
        return accounts[0], accounts[1], accounts[2]

    @pytest.fixture
    def contract(self, three):
        seller, buyer, _ = three
        factory = get_contract_factory(contract_file_path="assent.py")
        c = factory.deploy(args=[], account=seller)
        c.open(args=[LABEL, TERMS, OFFER, buyer.address])
        return c

    def test_only_the_offeree_may_accept(self, contract, three):
        seller, buyer, stranger = three
        for who in (seller, stranger):
            with pytest.raises(Exception):
                contract.connect(who).accept(args=[0, IN_FULL])
        assert tx_execution_succeeded(contract.connect(buyer).accept(args=[0, IN_FULL]))
        assert same(contract.attempt(args=[0])["by"], buyer.address)

    def test_only_the_offeror_may_withdraw(self, contract, three):
        _, buyer, stranger = three
        for who in (buyer, stranger):
            with pytest.raises(Exception):
                contract.connect(who).withdraw(args=[0])
        assert tx_execution_succeeded(contract.withdraw(args=[0]))
        assert contract.status(args=[0]) == "withdrawn"

    def test_only_the_offeree_may_counter_and_the_roles_swap(self, contract, three):
        seller, buyer, stranger = three
        text = "We offer to buy 40 chairs at 170 EUR each, on the same terms otherwise."
        for who in (seller, stranger):
            with pytest.raises(Exception):
                contract.connect(who).counter(args=[0, text])
        assert tx_execution_succeeded(contract.connect(buyer).counter(args=[0, text]))
        d = contract.deal(args=[0])
        assert same(d["offeror"], buyer.address) and same(d["offeree"], seller.address)

    def test_may_accept_answers_what_accept_enforces(self, contract, three):
        seller, buyer, stranger = three
        assert contract.may_accept(args=[0, buyer.address]) is True
        assert contract.may_accept(args=[0, seller.address]) is False
        assert contract.may_accept(args=[0, stranger.address]) is False
        assert contract.may_accept(args=[0, "not-an-address"]) is False

    def test_an_address_is_matched_by_value_not_by_spelling(self, contract, three):
        """An Address is 20 raw bytes on chain, so case carries no meaning."""
        _, buyer, _ = three
        upper = "0x" + buyer.address[2:].upper()
        assert contract.may_accept(args=[0, upper]) is True
        assert contract.may_accept(args=[0, buyer.address.lower()]) is True
