import pytest

from regtrace.baseline import (
    Chunk,
    ChunkIndex,
    check_obligation_chunked,
    check_policy_chunked,
    chunk_evidence,
    chunk_tree,
    linearize,
    query_text,
    section_of,
)
from regtrace.evidence import JudgeReply, Status
from regtrace.llm import LLMConnectionError, LLMResponseError
from regtrace.regulations import LinkedObligation, LinkResult, Obligation
from regtrace.tree import DocumentTree, Node, assign_ids


def make_policy():
    root = Node(
        title="Acme Privacy Policy",
        children=[
            Node(
                title="1. Who we are",
                text="Acme Ltd is the controller.",
                children=[Node(title="1.1 DPO", text="Our DPO is reachable at dpo@acme.example.")],
            ),
            Node(title="2. Retention", text="We keep order data for six years."),
            Node(title="3. Complaints", text="You may complain to the Data Protection Commission."),
        ],
    )
    assign_ids(root)
    return DocumentTree(
        doc_id="acme", title=root.title, source="acme.html", source_type="html", root=root
    )


def linked(obligation_id="gdpr-13-2-a", condition=None):
    return LinkedObligation(
        obligation=Obligation(
            id=obligation_id,
            ref="13(2)(a)",
            title="Retention period",
            who="controller",
            what="State how long personal data are stored.",
            when="At collection.",
            condition=condition,
            evidence="Concrete periods.",
        ),
        node_id="3.2.1.2",
        source_text="the period for which the personal data will be stored;",
    )


KEYWORDS = ["retention keep years", "complain commission", "dpo controller acme"]


class FakeModel:
    """Embeds text as keyword counts and replays scripted judge replies."""

    model = "fake-model"

    def __init__(self, embed_model="fake-embed", replies=()):
        self.embed_model = embed_model
        self.replies = list(replies)
        self.embedded = []
        self.prompts = []

    def embed(self, texts):
        self.embedded += texts
        return [
            [sum(t.lower().count(w) for w in group.split()) for group in KEYWORDS] for t in texts
        ]

    def generate_structured(self, prompt, schema, *, system=None):
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def verdict(status, quotes=(), condition="yes"):
    return JudgeReply(
        quotes=[{"section_id": s, "text": t} for s, t in quotes],
        condition_met=condition,
        explanation="Because.",
        status=status,
        fix="Add it.",
    )


def test_linearize_keeps_node_spans():
    text, spans = linearize(make_policy())

    for start, end, node_id in spans:
        node = make_policy().get(node_id)
        assert text[start:end].startswith(node.title)
    assert [s[2] for s in spans] == ["0", "1", "1.1", "2", "3"]


def test_chunks_cover_the_text_with_overlap():
    chunks = chunk_tree(make_policy(), size=60, overlap=20)

    assert [c.id for c in chunks[:2]] == ["c1", "c2"]
    assert all(len(c.text) <= 60 for c in chunks)
    joined = " ".join(c.text for c in chunks)
    assert "six years" in joined and "Data Protection Commission" in joined
    assert chunks[0].text.split()[-1] in chunks[1].text
    assert chunks[0].section_ids[0] == "0"


def test_small_policy_is_one_chunk():
    chunks = chunk_tree(make_policy())

    assert len(chunks) == 1
    assert chunks[0].section_ids == ["0", "1", "1.1", "2", "3"]


def test_overlap_must_be_smaller_than_size():
    with pytest.raises(ValueError):
        chunk_tree(make_policy(), size=50, overlap=50)


def test_index_returns_the_most_similar_chunks():
    chunks = [
        Chunk(id="c1", text="We keep data for six years.", section_ids=["2"]),
        Chunk(id="c2", text="Complain to the commission.", section_ids=["3"]),
    ]
    model = FakeModel()

    index = ChunkIndex.build(chunks, model)
    hits = index.search("How many years do you keep data?", k=1)

    assert [c.id for c, _ in hits] == ["c1"]
    assert hits[0][1] == pytest.approx(1.0)


def test_nomic_models_get_task_prefixes():
    model = FakeModel(embed_model="nomic-embed-text")
    index = ChunkIndex.build([Chunk(id="c1", text="keep", section_ids=["2"])], model)
    index.search("retention", k=1)

    assert model.embedded == ["search_document: keep", "search_query: retention"]


def test_index_needs_one_vector_per_chunk():
    with pytest.raises(ValueError):
        ChunkIndex([Chunk(id="c1", text="x", section_ids=[])], [], FakeModel())


def test_query_and_evidence_text():
    assert query_text(linked()) == (
        "Retention period. State how long personal data are stored. Concrete periods."
    )
    chunk = Chunk(id="c2", text="Body.", section_ids=["2"])
    assert chunk_evidence([chunk]) == "[section c2]\nBody."


def test_section_of_finds_the_deepest_section_with_the_quote():
    policy = make_policy()
    chunk = Chunk(id="c1", text="", section_ids=["1", "1.1", "2"])

    assert section_of(policy, chunk, "Our DPO is reachable") == "1.1"
    assert section_of(policy, chunk, "not in any section") == "1"


def small_index(model):
    return ChunkIndex.build(chunk_tree(make_policy(), size=80, overlap=10), model)


def test_chunked_check_retrieves_judges_and_maps_quotes_to_sections():
    model = FakeModel()
    index = small_index(model)
    hit = next(c for c in index.chunks if "six years" in c.text)
    model.replies = [verdict(Status.compliant, [(hit.id, "keep order data for six years")])]

    finding = check_obligation_chunked(make_policy(), linked(), model, index=index, k=2)

    assert finding.status == Status.compliant
    assert finding.llm_calls == 1
    assert finding.quotes[0].section_id == "2"
    assert "2" in finding.sections_read
    assert f"[section {hit.id}]" in model.prompts[0]
    assert "more_sections" not in model.prompts[0]


def test_chunked_check_applies_conditions_and_assumptions():
    model = FakeModel(replies=[verdict(Status.not_addressed, condition="unknown")])
    index = small_index(model)

    depends = check_obligation_chunked(
        make_policy(), linked(condition="A DPO exists."), model, index=index
    )
    skipped = check_obligation_chunked(
        make_policy(), linked(condition="A DPO exists."), model, index=index, assume="no"
    )

    assert depends.status == Status.depends
    assert skipped.status == Status.compliant
    assert skipped.llm_calls == 0


def test_chunked_check_records_errors_and_raises_connection_errors():
    model = FakeModel(replies=[LLMResponseError("bad"), LLMConnectionError("down")])
    index = small_index(model)

    assert check_obligation_chunked(make_policy(), linked(), model, index=index).error == "bad"
    with pytest.raises(LLMConnectionError):
        check_obligation_chunked(make_policy(), linked(), model, index=index)


def test_check_policy_chunked_builds_a_chunked_report():
    links = LinkResult(
        pack_id="gdpr",
        definitions=[],
        linked=[linked(), linked(obligation_id="gdpr-13-2-d")],
        errors=[],
    )
    model = FakeModel(replies=[verdict(Status.compliant), verdict(Status.gap)])

    report = check_policy_chunked(make_policy(), links, model, small_index(model))

    assert report.method == "chunked"
    assert [f.status for f in report.findings] == [Status.compliant, Status.gap]
