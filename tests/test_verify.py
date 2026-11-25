import pytest

from regtrace.evidence import Finding, Quote, Report, Status
from regtrace.evidence.models import Match
from regtrace.tree import DocumentTree, Node, assign_ids
from regtrace.verify import clean_quote, locate, match_text, rate, verify_finding, verify_report

RIGHTS = (
    "Under the GDPR you have the right to:\n- access the personal data we hold about you;\n"
    "- ask us to correct inaccurate data;\n- ask us to erase your data in certain cases."
)


def make_policy():
    root = Node(
        title="Acme Privacy Policy",
        text="Last updated 1 May 2026.",
        children=[
            Node(
                title="1. Who we are",
                text="Acme Ltd, 1 High Street, London, is the controller.",
                children=[Node(title="1.1 DPO", text="Our DPO is reachable at dpo@acme.example.")],
            ),
            Node(title="2. How long we keep data", text="We keep order data for six years."),
            Node(title="3. Your rights", text=RIGHTS),
        ],
    )
    assign_ids(root)
    return DocumentTree(
        doc_id="acme", title=root.title, source="acme.html", source_type="html", root=root
    )


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("We keep order data for six years.", Match.exact),
        ("We keep order data\n  for six years.", Match.exact),
        ("“We keep order data for six years [...]”", Match.exact),
        ("we keep ORDER data - for six years", Match.normalized),
        ("Under the GDPR you have the right to: - access the personal data", Match.exact),
        ("you have the right to: ... ask us to correct inaccurate data", Match.spliced),
        ("Under the GDPR you have the right to access and correct inaccurate data", Match.fuzzy),
        ("We sell your data to advertisers.", Match.not_found),
        ("", Match.not_found),
    ],
)
def test_match_text_grades(quote, expected):
    text = "We keep order data for six years.\n\n" + RIGHTS

    assert match_text(quote, text).match == expected


def test_match_text_returns_the_source_span():
    found = match_text("we keep ORDER data", "Intro. We keep order data for six years.")

    assert found.text == "We keep order data"
    assert found.coverage == 1.0


def test_spliced_words_far_apart_are_not_stitched_together():
    text = "We keep data. " + "Filler words here. " * 60 + "For six years only."

    assert match_text("We keep data for six years only", text).match != Match.spliced


def test_clean_quote():
    assert clean_quote(' "Hello there…" ') == "Hello there"
    assert clean_quote("a [ ... ]") == "a"


def test_locate_prefers_the_cited_section():
    found = locate(make_policy(), "Our DPO is reachable at dpo@acme.example.", "1")

    assert (found.match, found.section_id) == (Match.exact, "1")


def test_locate_corrects_a_wrong_section_to_the_deepest_match():
    found = locate(make_policy(), "Our DPO is reachable", "section 3")

    assert (found.match, found.section_id) == (Match.exact, "1.1")


def test_locate_finds_root_text_and_reports_missing_quotes():
    assert locate(make_policy(), "Last updated 1 May 2026", "9").section_id == "0"
    missing = locate(make_policy(), "We never share data.", "2")
    assert (missing.match, missing.section_id) == (Match.not_found, None)


def finding(status=Status.compliant, quotes=(), read=("2",), **extra):
    return Finding(
        obligation_id="gdpr-13-2-a",
        ref="13(2)(a)",
        title="Retention",
        status=status,
        quotes=[Quote(section_id=s, text=t) for s, t in quotes],
        sections_read=list(read),
        **extra,
    )


def test_verified_quote_gives_high_confidence():
    f = verify_finding(finding(quotes=[("2", "We keep order data for six years.")]), make_policy())

    assert f.quotes[0].match == Match.exact
    assert f.quotes[0].source_text == "We keep order data for six years."
    assert f.flags == []
    assert f.confidence == "high"


def test_invented_quote_gives_low_confidence():
    f = verify_finding(finding(quotes=[("2", "We delete data after 30 days.")]), make_policy())

    assert f.flags == ["quote not found in the policy: 'We delete data after 30 days.'"]
    assert f.confidence == "low"


def test_wrong_section_is_corrected_and_flagged():
    f = verify_finding(
        finding(quotes=[("2", "Our DPO is reachable at dpo@acme.example.")], read=["1"]),
        make_policy(),
    )

    assert f.quotes[0].section_id == "1.1"
    assert f.flags == ["quote is in section 1.1, not 2"]
    assert f.confidence == "medium"


def test_quote_from_unread_section_is_flagged():
    f = verify_finding(finding(quotes=[("3", "ask us to correct inaccurate data")]), make_policy())

    assert f.flags == ["quote comes from section 3, which was not read"]
    assert f.confidence == "medium"


def test_fuzzy_quote_is_flagged():
    quote = "Under the GDPR you have the right to access and correct inaccurate data"
    f = verify_finding(finding(Status.partial, quotes=[("3", quote)], read=["3"]), make_policy())

    assert f.quotes[0].match == Match.fuzzy
    assert f.flags[0].startswith("quote only loosely matches the text")
    assert f.confidence == "low"


def test_verify_resets_flags():
    f = finding(quotes=[("2", "We keep order data for six years.")])
    f.flags = ["old"]

    assert verify_finding(f, make_policy()).flags == []


@pytest.mark.parametrize(
    ("f", "expected"),
    [
        (finding(status=None, error="bad"), "low"),
        (finding(Status.compliant), "low"),
        (finding(Status.gap), "high"),
        (finding(Status.not_addressed, warnings=["no suggested fix"]), "medium"),
        (finding(Status.depends, condition="A DPO exists."), "medium"),
        (finding(Status.compliant, assumed=True), "high"),
    ],
)
def test_rate(f, expected):
    assert rate(f) == expected


def test_verify_report_counts_verified_quotes():
    report = Report(
        policy_id="acme",
        policy_title="Acme",
        policy_source="acme.html",
        pack_id="gdpr",
        model="m",
        created="now",
        findings=[
            finding(quotes=[("2", "We keep order data for six years."), ("2", "Invented.")]),
            finding(Status.gap),
        ],
    )

    verify_report(report, make_policy())

    assert report.quote_counts() == (1, 2)
    assert [f.confidence for f in report.findings] == ["low", "high"]
