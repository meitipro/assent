"""The runbook, executed, and the documents held to the code.

This file drives tests/glsim.py through DEPLOY.md's exact sequence: the same
methods, the argument strings copied character for character from the
document, the same two accounts, in the same order, with mocks returning the
answers DEPLOY.md says to expect. It then asserts every value DEPLOY.md's
checkpoints and reads table claim, and every result in SUBMISSION.md's
expected table.

It mirrors DEPLOY.md and must be updated with it. Every argument string used
here is also asserted to appear verbatim in DEPLOY.md, so the two cannot drift
apart in silence.

The second half holds the other documents to the code: every contract function
they quote must be the source as it stands, every constant they quote must be
the constant the contract runs, and the portal Notes must fit the portal box.

    pytest tests/test_runbook.py -v
"""

import pathlib
import re

import pytest

import glsim as S

CONTRACT_PATH = "contracts/assent.py"
M = S.load_contract(CONTRACT_PATH)
SOURCE = pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8")
DEPLOY = pathlib.Path("DEPLOY.md").read_text(encoding="utf-8")
SUBMISSION = pathlib.Path("SUBMISSION.md").read_text(encoding="utf-8")
README = pathlib.Path("README.md").read_text(encoding="utf-8")
CONTRACTS = pathlib.Path("CONTRACTS.md").read_text(encoding="utf-8")

A = "0x" + "a1" * 20          # the seller
B = "0x" + "b2" * 20          # the buyer

# -- the arguments, character for character as DEPLOY.md gives them ----------

LABEL0 = "Office chairs, 40 units"
TERMS0 = "unit price|delivery date|warranty"
OFFER0 = ("We offer 40 ergonomic office chairs at 180 EUR each, delivered to your "
          "Rotterdam office by 15 October, with a two year warranty.")
ACCEPT0 = "We accept, provided delivery is brought forward to 1 October."
COUNTER0 = ("We offer 40 ergonomic office chairs at 180 EUR each, delivered to your "
            "Rotterdam office by 1 October, with a two year warranty.")
ACCEPT1 = "We accept your offer in full, as written."
LABEL1 = "Desk lamps, 20 units"
TERMS1 = "unit price|delivery date"
OFFER1 = ("We offer 20 brass desk lamps at 35 EUR each, delivered to your "
          "Rotterdam office by 30 October.")

ROWS0 = TERMS0.split("|") + [M.RESIDUAL]
# what DEPLOY.md expects the model to answer, rows in frozen order
READ0 = "same|changed|same|same"
READ1 = "same|same|same|same"


def in_doc(value, doc):
    """A value as the document writes it: in backticks, pipes escaped inside a
    table and bare outside one."""
    v = str(value)
    return ("`%s`" % v) in doc or ("`%s`" % v.replace("|", "\\|")) in doc


def mocks():
    out = {}
    for offer, acceptance, forward in ((OFFER0, ACCEPT0, READ0), (COUNTER0, ACCEPT1, READ1)):
        reverse = "|".join(reversed(forward.split("|")))
        out[M.build_prompt(LABEL0, ROWS0, 4, offer, acceptance)] = \
            {"terms": forward, "because": "demo"}
        out[M.build_prompt(LABEL0, list(reversed(ROWS0)), 4, offer, acceptance)] = \
            {"terms": reverse, "because": "demo"}
    return out


def as_(who, c, method, *args):
    S.set_sender(who)
    try:
        return S.call(c, method, *args)
    finally:
        S.set_sender(A)


@pytest.fixture(scope="module")
def run():
    """DEPLOY.md, steps 1 to 8, with a snapshot at every point it checks."""
    S.set_mocks(leader_prompts=mocks())
    c = S.deploy(CONTRACT_PATH)
    seen = {}
    as_(A, c, "open", LABEL0, TERMS0, OFFER0, B)             # 1
    seen["deal0", 1] = c.deal(0)
    as_(B, c, "accept", 0, ACCEPT0)                          # 2
    as_(A, c, "judge", 0)                                    # 3
    seen["attempt0"] = c.attempt(0)
    seen["deal0", 3] = c.deal(0)
    seen["offer0", 3] = c.offer(0)
    seen["offer1", 3] = c.offer(1)
    as_(A, c, "counter", 0, COUNTER0)                        # 4
    seen["offer1", 4] = c.offer(1)
    seen["offer2", 4] = c.offer(2)
    as_(B, c, "accept", 0, ACCEPT1)                          # 5
    as_(B, c, "judge", 0)                                    # 6
    seen["attempt1"] = c.attempt(1)
    seen["deal0", 6] = c.deal(0)
    as_(A, c, "open", LABEL1, TERMS1, OFFER1, B)             # 7
    as_(A, c, "withdraw", 1)                                 # 8
    return c, seen


class TestRunbook:
    def test_every_argument_is_the_one_deploy_md_gives(self):
        for value in (LABEL0, TERMS0, OFFER0, ACCEPT0, COUNTER0, ACCEPT1,
                      LABEL1, TERMS1, OFFER1):
            assert in_doc(value, DEPLOY), value

    def test_the_methods_run_are_the_methods_deploy_md_names(self):
        for method in ("open", "accept", "judge", "counter", "withdraw"):
            assert "| `%s` |" % method in DEPLOY
        assert "Eight writes" in DEPLOY

    def test_step_1_the_catalogue_and_the_residual_row(self, run):
        _, seen = run
        d = seen["deal0", 1]
        assert d["terms"] == ROWS0 and (d["offeror"], d["offeree"]) == (A, B)
        assert in_doc(M.RESIDUAL, DEPLOY)

    def test_checkpoint_1_the_conditional_acceptance_is_a_counter_offer(self, run):
        _, seen = run
        a = seen["attempt0"]
        assert (a["verdict"], a["changed"], a["offer"]) == ("countered", "0|1|0|0", 0)
        assert in_doc(a["verdict"], DEPLOY) and in_doc(a["changed"], DEPLOY)
        d = seen["deal0", 3]
        assert (d["status"], d["current"], d["offeror"], d["offeree"]) == ("open", 1, B, A)
        assert seen["offer0", 3]["terminated"] is True
        o = seen["offer1", 3]
        assert (o["kind"], o["by"], o["to"], o["text"], o["responds_to"]) == \
            ("conditional", B, A, ACCEPT0, 0)

    def test_step_4_the_counter_offer_answers_the_conditional_one(self, run):
        _, seen = run
        assert seen["offer1", 4]["terminated"] is True
        o = seen["offer2", 4]
        assert (o["kind"], o["by"], o["to"], o["responds_to"], o["text"]) == \
            ("counter", A, B, 1, COUNTER0)

    def test_checkpoint_2_the_agreement_forms(self, run):
        c, seen = run
        a = seen["attempt1"]
        assert (a["verdict"], a["changed"], a["offer"]) == ("formed", "0|0|0|0", 2)
        assert in_doc(a["changed"], DEPLOY)
        d = seen["deal0", 6]
        assert (d["status"], d["agreed_offer"], d["agreed_attempt"]) == ("agreed", 2, 1)
        assert c.agreement(0) == {"agreed": True, "offer_text": COUNTER0,
                                  "acceptance_text": ACCEPT1, "offeror": A, "acceptor": B}

    def test_the_reads_table(self, run):
        c, _ = run
        assert (c.count(), c.offer_count(), c.attempt_count()) == (2, 4, 2)
        assert c.status(0) == "agreed" and c.status(1) == "withdrawn"
        d = c.deal(0)
        assert (d["status"], d["current"], d["offers"], d["attempts"], d["agreed"],
                d["agreed_offer"], d["agreed_attempt"], d["a_offers"], d["b_offers"],
                d["a_attempts"], d["b_attempts"]) == \
            ("agreed", 2, 3, 2, True, 2, 1, 2, 1, 0, 2)
        rows = c.terms_of(0)["terms"]
        assert len(rows) == 4 and rows[-1]["name"] == M.RESIDUAL and rows[-1]["residual"] is True
        h = c.history(0)
        assert [o["kind"] for o in h["offers"]] == ["offer", "conditional", "counter"]
        assert [o["terminated"] for o in h["offers"]] == [True, True, False]
        assert [a["verdict"] for a in h["attempts"]] == ["countered", "formed"]
        o1, o2 = c.offer(1), c.offer(2)
        assert (o1["kind"], o1["responds_to"], o1["terminated"]) == ("conditional", 0, True)
        assert (o2["kind"], o2["responds_to"], o2["accepted"]) == ("counter", 1, True)
        a0 = c.attempt(0)
        assert (a0["verdict"], a0["changed"], a0["reason_is_leader_supplied"]) == \
            ("countered", "0|1|0|0", True)
        d1 = c.deal(1)
        assert (d1["status"], d1["offers"], d1["attempts"], d1["agreed"]) == \
            ("withdrawn", 1, 0, False)
        assert c.offer(3)["terminated"] is True and c.offer(3)["kind"] == "offer"
        assert c.may_accept(0, B) is False and c.may_accept(1, B) is False
        for phrase in ("`status agreed`", "`current 2`", "`offers 3`", "`attempts 2`",
                       "`agreed true`", "`agreed_offer 2`", "`agreed_attempt 1`",
                       "`a_offers 2`", "`b_offers 1`", "`a_attempts 0`", "`b_attempts 2`",
                       "`residual true`", "`kind conditional`", "`responds_to 0`",
                       "`terminated true`", "`kind counter`", "`responds_to 1`",
                       "`accepted true`", "`verdict countered`", "`changed 0\\|1\\|0\\|0`",
                       "`reason_is_leader_supplied true`", "`status withdrawn`",
                       "`offers 1`", "`attempts 0`", "`agreed false`", "`2`", "`4`"):
            assert phrase in DEPLOY, phrase

    def test_submission_md_claims_what_the_run_produces(self, run):
        c, seen = run
        assert seen["attempt0"]["verdict"] == "countered"
        assert seen["attempt1"]["verdict"] == "formed"
        for phrase in ("**`countered`**", "`changed 0\\|1\\|0\\|0`", "`conditional`",
                       "**`formed`**", "`changed 0\\|0\\|0\\|0`", "**`agreed`**",
                       "**`withdrawn`**", "`pending`", "kind `counter`"):
            assert phrase in SUBMISSION, phrase
        for claim in ('accept(0, "%s")' % ACCEPT0, 'accept(0, "%s")' % ACCEPT1,
                      'open("%s"' % LABEL0, 'open("%s"' % LABEL1):
            assert claim in SUBMISSION, claim
        assert "deal 0 **`agreed`** on offer 2" in SUBMISSION
        assert c.deal(0)["agreed_offer"] == 2 and c.offer(3)["terminated"] is True


# ===========================================================================
# The documents, held to the code as it stands.
# ===========================================================================

def code_blocks(doc, lang="python"):
    return re.findall(r"```%s\n(.*?)```" % lang, doc, re.S)


def notes():
    return SUBMISSION.split("## Notes", 1)[1].split("```", 2)[1].strip("\n")


class TestDocuments:
    def test_every_function_the_docs_quote_is_the_source_as_it_stands(self):
        quoted = [b for doc in (README, CONTRACTS) for b in code_blocks(doc)
                  if b.lstrip().startswith("def ")]
        assert len(quoted) >= 2, "no quoted function found"
        for block in quoted:
            assert block.strip("\n") in SOURCE, "drifted from the contract:\n" + block

    def test_the_caps_table_matches_the_contract(self):
        rows = re.findall(r"^\| `((?:MAX|MIN)_\w+)` \| (\d+)", CONTRACTS, re.M)
        assert len(rows) == 13
        for name, value in rows:
            assert getattr(M, name) == int(value), name

    def test_the_residual_row_the_docs_quote_is_the_one_the_contract_writes(self):
        for doc in (README, CONTRACTS):
            assert "```\n%s\n```" % M.RESIDUAL in doc

    def test_the_resolution_table_matches_resolve(self):
        assert M.resolve(["same", "changed"]) == ("countered", [0, 1])
        assert M.resolve(["same", "unclear"]) == ("indeterminate", [0, 0])
        assert M.resolve(["same", "same"]) == ("formed", [0, 0])
        for doc in (README, CONTRACTS):
            assert "| any row `changed` | `countered` |" in doc
            assert "| no row `changed`, some row `unclear` | `indeterminate` | all 0 |" in doc
            assert "| every row `same` | `formed` | all 0 |" in doc

    def test_the_consuming_contract_snippet_compares_addresses_case_insensitively(self):
        block = [b for b in code_blocks(README) if "contract_interface" in b][0]
        assert ".lower()" in block and "agreement" in block and '"agreed"' in block

    def test_the_notes_fit_the_portal_box(self):
        n = len(notes())
        print("Notes: %d characters" % n)
        assert 0 < n <= 1000

    def test_the_notes_carry_no_address_and_lean_on_commas(self):
        text = notes()
        assert not re.search(r"0x[0-9a-fA-F]{6,}", text) and "{address}" not in text
        assert text.count(",") > 3 * text.count(".")

    def test_the_title(self):
        title = SUBMISSION.split("## Title", 1)[1].split("```", 2)[1].strip("\n")
        assert title == "Assent: an agreement forms only when the acceptance matches the offer"

    def test_the_readme_carries_the_measured_markers(self):
        for name in ("tests", "mutations"):
            assert "<!-- measured:%s -->" % name in README
            assert "<!-- /measured:%s -->" % name in README
