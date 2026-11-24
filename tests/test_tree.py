import pytest
from pydantic import ValidationError

from regtrace.tree import DocumentTree, Node, NodeNotFoundError, assign_ids


@pytest.fixture
def tree() -> DocumentTree:
    root = Node(
        title="Example Privacy Policy",
        children=[
            Node(
                title="Who we are",
                text="Example Ltd is the controller.",
                summary="Identifies the controller.",
            ),
            Node(
                title="Data we collect",
                text="We collect the following data.",
                children=[Node(title="Contact data", text="Name and email address.")],
            ),
        ],
    )
    assign_ids(root)
    return DocumentTree(
        doc_id="example",
        title="Example Privacy Policy",
        source="example.pdf",
        source_type="pdf",
        root=root,
    )


def test_assign_ids_numbers_nodes_path_style(tree):
    assert [node.id for node in tree.walk()] == ["0", "1", "2", "2.1"]


def test_assign_ids_sets_levels(tree):
    assert [node.level for node in tree.walk()] == [0, 1, 1, 2]


def test_walk_is_in_reading_order(tree):
    assert [node.title for node in tree.walk()] == [
        "Example Privacy Policy",
        "Who we are",
        "Data we collect",
        "Contact data",
    ]


def test_get_finds_nested_node(tree):
    assert tree.get("2.1").title == "Contact data"


def test_get_unknown_id_raises(tree):
    with pytest.raises(NodeNotFoundError, match="9.9"):
        tree.get("9.9")


def test_full_text_includes_descendants_in_order(tree):
    assert tree.full_text("2") == (
        "Data we collect\n\n"
        "We collect the following data.\n\n"
        "Contact data\n\n"
        "Name and email address."
    )


def test_outline_respects_max_depth_and_shows_summaries(tree):
    assert tree.outline(max_depth=1).splitlines() == [
        "1  Who we are: Identifies the controller.",
        "2  Data we collect",
    ]


def test_outline_without_summaries_shows_full_tree(tree):
    assert tree.outline(with_summaries=False).splitlines() == [
        "1  Who we are",
        "2  Data we collect",
        "  2.1  Contact data",
    ]


def test_outline_does_not_repeat_number_already_in_title():
    root = Node(
        title="Policy",
        children=[Node(title="1. Who we are", children=[Node(title="1.1 Contact us")])],
    )
    assign_ids(root)
    tree = DocumentTree(doc_id="p", title="Policy", source="p.pdf", source_type="pdf", root=root)

    assert tree.outline().splitlines() == ["1  Who we are", "  1.1  Contact us"]
    assert tree.get("1").title == "1. Who we are"


def test_save_and_load_round_trip(tree, tmp_path):
    path = tmp_path / "index" / "example.json"

    tree.save(path)

    assert DocumentTree.load(path) == tree


def test_page_end_before_page_start_is_rejected():
    with pytest.raises(ValidationError):
        Node(title="Bad pages", page_start=5, page_end=3)
