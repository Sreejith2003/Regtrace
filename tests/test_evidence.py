import pytest

from regtrace.evidence import (
    JudgeReply,
    Report,
    SectionChoice,
    Status,
    build_prompt,
    check_obligation,
    check_policy,
    navigation_outline,
    read_sections,
)
from regtrace.evidence.navigator import titles_outline, valid_ids
from regtrace.llm import LLMConnectionError, LLMResponseError
from regtrace.regulations import Definition, LinkedObligation, LinkResult, Obligation
from regtrace.tree import DocumentTree, Node, assign_ids


def make_policy():
    root = Node(
        title="Acme Privacy Policy",
        children=[
            Node(
                title="1. Who we are",
                text="Acme Ltd, 1 High Street, London, is the controller. Email: hi@acme.example.",
                summary="Controller identity and contact details.",
                children=[Node(title="1.1 DPO", text="Our DPO is reachable at dpo@acme.example.")],
            ),
            Node(title="2. How long we keep data", text="We keep order data for six years."),
            Node(title="3. Your rights", text="You can ask for access or erasure at any time."),
        ],
    )
    assign_ids(root)
    return DocumentTree(
        doc_id="acme", title=root.title, source="acme.html", source_type="html", root=root
    )


def make_regulation():
    root = Node(
        title="GDPR",
        children=[
            Node(
                title="Article 6 Lawfulness of processing",
                children=[
                    Node(
                        title="Article 6(1)",
                        text="(a) the data subject has given consent;\n\n(f) processing is "
                        "necessary for the purposes of the legitimate interests pursued;",
                    )
                ],
            )
        ],
    )
    assign_ids(root)
    return DocumentTree(doc_id="gdpr", title="GDPR", source="g.pdf", source_type="pdf", root=root)


def linked(obligation_id="gdpr-13-2-a", ref="13(2)(a)", cross_refs=None, condition=None):
    return LinkedObligation(
        obligation=Obligation(
            id=obligation_id,
            ref=ref,
            title="Retention period",
            who="controller",
            what="State how long personal data are stored.",
            when="At collection.",
            condition=condition,
            evidence="Concrete periods.",
        ),
        node_id="3.2.1.2",
        source_text="the period for which the personal data will be stored;",
        definitions=[Definition(term="personal data", ref="4(1)", text="‘personal data’ means x")],
        cross_refs=cross_refs or [],
    )


class ScriptedClient:
    model = "fake-model"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def generate_structured(self, prompt, schema, *, system=None):
        self.prompts.append((schema, prompt))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        assert isinstance(reply, schema), f"expected {schema.__name__}, got {type(reply).__name__}"
        return reply


def verdict(status, quotes=(), fix="Add the retention period.", more=()):
    return JudgeReply(
        quotes=[{"section_id": s, "text": t} for s, t in quotes],
        explanation="Because.",
        status=status,
        fix=fix,
        more_sections=list(more),
    )


# --- navigation ---


def test_navigation_outline_uses_summaries_or_snippets():
    outline = navigation_outline(make_policy()).splitlines()

    assert outline[0] == "1  Who we are: Controller identity and contact details."
    assert outline[1] == "  1.1  DPO: Our DPO is reachable at dpo@acme.example...."
    assert outline[2].startswith("2  How long we keep data: We keep order data")


def test_navigation_outline_drops_deep_levels_when_too_long():
    outline = navigation_outline(make_policy(), max_chars=150)

    assert "1.1" not in outline
    assert outline.startswith("1  Who we are")


def test_titles_outline():
    assert titles_outline(make_policy()).splitlines() == [
        "1  Who we are",
        "  1.1  DPO",
        "2  How long we keep data",
        "3  Your rights",
    ]


def test_valid_ids_drops_unknown_and_duplicates():
    assert valid_ids(make_policy(), ["2", "9", "section 1.1", "2", "3"], limit=2) == ["2", "1.1"]


def test_read_sections_labels_and_budget():
    text = read_sections(make_policy(), ["1", "2"])

    assert text.startswith("[section 1] 1. Who we are\nAcme Ltd")
    assert "1.1 DPO" in text  # subsections come with their parent
    assert "[section 2] 2. How long we keep data\nWe keep order data for six years." in text
    assert read_sections(make_policy(), ["1", "2"], budget=100) == ""


# --- judge prompt ---


def test_judge_prompt_includes_definitions_cross_refs_and_condition():
    item = linked(cross_refs=["6(1)(f)", "99"], condition="Legitimate interests are used.")

    prompt = build_prompt(item, "[section 2] text", regulation=make_regulation(), outline="2  X")

    assert "Regulation text:\nthe period for which the personal data will be stored;" in prompt
    assert "- ‘personal data’ means x" in prompt
    assert "- Art. 6(1)(f): processing is necessary for the purposes" in prompt
    assert "Art. 99" not in prompt
    assert "Condition: Legitimate interests are used." in prompt
    assert "more_sections" in prompt


def test_judge_prompt_without_outline_does_not_offer_more_sections():
    prompt = build_prompt(linked(), "excerpt", allow_more=False, outline="2  X")

    assert "more_sections" not in prompt
    assert "Condition: none, it always applies." in prompt


# --- checking one obligation ---


def test_check_obligation_navigates_then_judges():
    client = ScriptedClient(
        SectionChoice(section_ids=["2", "7"], reason="retention"),
        verdict(Status.compliant, quotes=[("2", "We keep order data for six years.")]),
    )

    finding = check_obligation(make_policy(), linked(), client)

    assert finding.status == Status.compliant
    assert finding.sections_read == ["2"]
    assert finding.quotes[0].text == "We keep order data for six years."
    assert finding.fix == ""
    assert finding.warnings == []
    assert finding.llm_calls == 2
    assert "[section 2]" in client.prompts[1][1]


def test_check_obligation_reads_more_sections_when_asked():
    client = ScriptedClient(
        SectionChoice(section_ids=["1"]),
        verdict(Status.not_addressed, more=["2", "1"]),
        verdict(Status.partial, quotes=[("2", "We keep order data for six years.")]),
    )

    finding = check_obligation(make_policy(), linked(), client)

    assert finding.status == Status.partial
    assert finding.sections_read == ["1", "2"]
    assert finding.llm_calls == 3
    assert "more_sections" not in client.prompts[2][1]


def test_check_obligation_flags_bad_quotes_and_missing_fix():
    client = ScriptedClient(
        SectionChoice(section_ids=["2"]),
        verdict(Status.partial, quotes=[("3", "You can ask for access.")], fix=""),
    )

    finding = check_obligation(make_policy(), linked(), client)

    assert finding.quotes == []
    assert finding.warnings == [
        "quote from a section that was not read: '3'",
        "status partial without a supporting quote",
        "no suggested fix",
    ]


def test_check_obligation_on_policy_without_sections_reads_whole_document():
    root = Node(title="Short notice", text="We keep data for one year.")
    assign_ids(root)
    policy = DocumentTree(doc_id="s", title="Short", source="s", source_type="html", root=root)
    client = ScriptedClient(verdict(Status.compliant, quotes=[("0", "We keep data for one year.")]))

    finding = check_obligation(policy, linked(), client)

    assert finding.sections_read == ["0"]
    assert finding.llm_calls == 1
    assert finding.status == Status.compliant


def test_llm_error_is_recorded_and_connection_error_raised():
    finding = check_obligation(make_policy(), linked(), ScriptedClient(LLMResponseError("bad")))

    assert finding.status is None
    assert finding.error == "bad"

    with pytest.raises(LLMConnectionError):
        check_obligation(make_policy(), linked(), ScriptedClient(LLMConnectionError("down")))


# --- whole policy ---


def test_check_policy_builds_report(tmp_path):
    links = LinkResult(
        pack_id="gdpr",
        definitions=[],
        linked=[linked(), linked(obligation_id="gdpr-13-2-d", ref="13(2)(d)")],
        errors=[],
    )
    client = ScriptedClient(
        SectionChoice(section_ids=["2"]),
        verdict(Status.compliant, quotes=[("2", "We keep order data for six years.")]),
        SectionChoice(section_ids=["3"]),
        verdict(Status.not_addressed, more=[]),
    )
    progress = []

    report = check_policy(
        make_policy(), links, client, on_progress=lambda d, t, i: progress.append((d, t))
    )

    assert progress == [(1, 2), (2, 2)]
    assert [f.status for f in report.findings] == [Status.compliant, Status.not_addressed]
    assert report.counts() == {"compliant": 1, "not_addressed": 1}
    assert report.model == "fake-model"
    path = tmp_path / "r.json"
    report.save(path)
    assert Report.load(path) == report


def test_check_policy_only():
    links = LinkResult(
        pack_id="gdpr",
        definitions=[],
        linked=[linked(), linked(obligation_id="gdpr-13-2-d", ref="13(2)(d)")],
        errors=[],
    )
    client = ScriptedClient(SectionChoice(section_ids=["3"]), verdict(Status.gap))

    report = check_policy(make_policy(), links, client, only=["gdpr-13-2-d"])

    assert [f.obligation_id for f in report.findings] == ["gdpr-13-2-d"]
