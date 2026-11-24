from pathlib import Path

import pytest
from pydantic import ValidationError

from regtrace.regulations import (
    ArticleRef,
    Obligation,
    Pack,
    cross_refs,
    extract_definitions,
    find_article,
    link_pack,
    load_pack,
    point_text,
    terms_in,
)
from regtrace.tree import DocumentTree, Node, assign_ids

GDPR_PACK = Path(__file__).parents[1] / "packs" / "gdpr"

ART_4 = (
    "For the purposes of this Regulation:\n\n"
    "(1) ‘personal data’ means any information relating to an identified or identifiable natural "
    "person (‘data subject’);\n\n"
    "(2) ‘processing’ means any operation which is performed on personal data;\n\n"
    "(7) ‘controller’ means the natural or legal person which determines the purposes and means "
    "of the\n\nprocessing of personal data;\n\n"
    "(11) ‘consent’ of the data subject means any freely given indication of the data subject's "
    "wishes;\n\n"
    "(12) ‘personal data breach’ means a breach of security leading to the loss of personal data;"
)
ART_13_1 = (
    "Where personal data relating to a data subject are collected from the data subject, the "
    "controller shall provide the following information:\n\n"
    "(a) the identity and the contact details of the controller;\n\n"
    "(b) the contact details of the data protection officer, where applicable;\n\n"
    "(d) where the processing is based on point (f) of Article 6(1), the legitimate interests "
    "pursued by the controller or by a\n\nthird party;"
)


def obligation(**overrides):
    data = {
        "id": "gdpr-13-1-a",
        "ref": "13(1)(a)",
        "title": "Controller identity",
        "who": "controller",
        "what": "State the identity and contact details of the controller.",
        "when": "At the time when personal data are obtained.",
    }
    return Obligation(**(data | overrides))


def pack(*obligations):
    return Pack(
        id="gdpr",
        name="Test pack",
        regulation="GDPR",
        index="gdpr.json",
        definitions_article="4",
        obligations=list(obligations),
    )


@pytest.fixture
def regulation():
    root = Node(
        title="GDPR",
        children=[
            Node(
                title="CHAPTER I General provisions",
                children=[Node(title="Article 4 Definitions", text=ART_4)],
            ),
            Node(
                title="CHAPTER III Rights of the data subject",
                children=[
                    Node(
                        title="Article 13 Information to be provided",
                        children=[
                            Node(title="Article 13(1)", text=ART_13_1),
                            Node(title="Article 13(2)", text="In addition, ..."),
                        ],
                    ),
                    Node(title="Article 14 Information not obtained", text="..."),
                ],
            ),
        ],
    )
    assign_ids(root)
    return DocumentTree(
        doc_id="gdpr", title="GDPR", source="gdpr.pdf", source_type="pdf", root=root
    )


# --- models ---


@pytest.mark.parametrize(
    ("text", "parts"),
    [("13", ("13", None, None)), ("13(1)", ("13", "1", None)), ("13(1)(a)", ("13", "1", "a"))],
)
def test_article_ref_parse_and_str(text, parts):
    ref = ArticleRef.parse(text)

    assert (ref.article, ref.paragraph, ref.point) == parts
    assert str(ref) == text


@pytest.mark.parametrize("bad", ["Art. 13", "13a", "(1)", ""])
def test_bad_article_ref_is_rejected(bad):
    with pytest.raises(ValueError):
        ArticleRef.parse(bad)


def test_obligation_validates_refs():
    assert obligation(ref=" 13(1)(a) ").ref == "13(1)(a)"
    with pytest.raises(ValidationError):
        obligation(ref="Article 13")
    with pytest.raises(ValidationError):
        obligation(related=["14.1"])


def test_obligation_is_conditional_only_with_condition():
    assert not obligation().conditional
    assert obligation(condition="A DPO is appointed.").conditional


def test_pack_rejects_duplicate_ids():
    with pytest.raises(ValidationError, match="Duplicate"):
        pack(obligation(), obligation())


def test_pack_get():
    p = pack(obligation())

    assert p.get("gdpr-13-1-a").ref == "13(1)(a)"
    with pytest.raises(KeyError):
        p.get("missing")


# --- loading ---


def test_load_pack_from_folder(tmp_path):
    (tmp_path / "pack.yaml").write_text(
        "id: t\nname: Test\nregulation: GDPR\nindex: gdpr.json\ndefinitions_article: '4'\n",
        encoding="utf-8",
    )
    (tmp_path / "obligations.yaml").write_text(
        "obligations:\n"
        "  - id: t-13-1-a\n    ref: '13(1)(a)'\n    title: Identity\n    who: controller\n"
        "    what: State who you are.\n    when: At collection.\n",
        encoding="utf-8",
    )

    p = load_pack(tmp_path)

    assert p.id == "t"
    assert [o.id for o in p.obligations] == ["t-13-1-a"]


def test_load_pack_without_pack_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_pack(tmp_path)


def test_gdpr_pack_is_valid():
    p = load_pack(GDPR_PACK)

    assert 15 <= len(p.obligations) <= 20
    assert {o.article_ref.article for o in p.obligations} == {"12", "13", "14"}
    assert all(o.evidence for o in p.obligations)


# --- linking ---


def test_find_article_and_paragraph(regulation):
    assert find_article(regulation, ArticleRef.parse("4")).title == "Article 4 Definitions"
    assert find_article(regulation, ArticleRef.parse("13(2)")).title == "Article 13(2)"
    assert find_article(regulation, ArticleRef.parse("13(9)")) is None
    assert find_article(regulation, ArticleRef.parse("1")) is None


def test_point_text_spans_wrapped_lines():
    assert point_text(ART_13_1, "a") == "the identity and the contact details of the controller;"
    assert point_text(ART_13_1, "d").endswith("by the controller or by a third party;")
    assert point_text(ART_13_1, "z") == ""


def test_extract_definitions(regulation):
    definitions = extract_definitions(find_article(regulation, ArticleRef.parse("4")))

    assert [(d.ref, d.term) for d in definitions] == [
        ("4(1)", "personal data"),
        ("4(1)", "data subject"),
        ("4(2)", "processing"),
        ("4(7)", "controller"),
        ("4(11)", "consent"),
        ("4(12)", "personal data breach"),
    ]
    controller = definitions[3]
    assert controller.text.startswith("‘controller’ means the natural or legal person")
    assert "of the processing of personal data;" in controller.text
    assert definitions[4].text.startswith("‘consent’ of the data subject means")


def test_terms_in_prefers_longer_terms_and_plurals(regulation):
    definitions = extract_definitions(find_article(regulation, ArticleRef.parse("4")))

    found = terms_in("Controllers must report a personal data breach.", definitions)

    assert [d.term for d in found] == ["controller", "personal data breach"]


@pytest.mark.parametrize(
    ("text", "refs"),
    [
        ("based on point (f) of Article 6(1)", ["6(1)(f)"]),
        ("referred to in Article 46 or 47, or Article 49(1)", ["46", "47", "49(1)"]),
        ("referred to in Article 22(1) and (4)", ["22(1)", "22(4)"]),
        ("a request under Articles 15 to 17", ["15", "16", "17"]),
        ("point (b) of Article 1(1) of Directive (EU) 2015/1535", []),
        ("Article 2 of Regulation (EC) No 45/2001", []),
    ],
)
def test_cross_refs(text, refs):
    assert cross_refs(text) == refs


def test_link_pack(regulation):
    p = pack(
        obligation(),
        obligation(id="gdpr-13-1-d", ref="13(1)(d)", condition="Legitimate interests are used."),
    )

    result = link_pack(p, regulation)

    assert result.ok
    first, second = result.linked
    assert first.node_id == "2.1.1"
    assert first.source_text == "the identity and the contact details of the controller;"
    assert [d.term for d in first.definitions] == ["controller"]
    assert second.cross_refs == ["6(1)(f)"]
    assert [d.term for d in second.definitions] == ["processing", "controller"]


def test_link_pack_reports_missing_references(regulation):
    p = pack(
        obligation(id="a", ref="13(3)"),
        obligation(id="b", ref="13(1)(c)"),
        obligation(id="c", related=["14(5)"]),
    )

    result = link_pack(p, regulation)

    assert not result.ok
    assert result.errors == [
        "a: Article 13(3) not found in the regulation index",
        "b: point (c) not found in Article 13(1)(c)",
        "c: related Article 14(5) not found",
    ]
    assert [item.obligation.id for item in result.linked] == ["c"]


def test_link_pack_reports_missing_definitions(regulation):
    p = pack(obligation()).model_copy(update={"definitions_article": "99"})

    assert "No definitions found in Article 99" in link_pack(p, regulation).errors
