import re

import pytest

from regtrace.llm import LLMConnectionError, LLMResponseError
from regtrace.tree import DocumentTree, Node, NodeSummary, assign_ids, build_prompt, summarize_tree
from regtrace.tree.summarize import SYSTEM_PROMPT, TRUNCATION_MARK


class FakeClient:
    """Records every prompt and replies with 'Summary of <section title>'."""

    model = "fake-model"

    def __init__(self, fail_on=(), error=None):
        self.fail_on = set(fail_on)
        self.error = error or LLMResponseError("bad JSON")
        self.prompts = []
        self.systems = []

    def generate_structured(self, prompt, schema, *, system=None):
        self.prompts.append(prompt)
        self.systems.append(system)
        title = re.search(r"^Section: (.*)$", prompt, re.MULTILINE).group(1)
        if title in self.fail_on:
            raise self.error
        return schema(summary=f"Summary of {title}")


def make_tree():
    root = Node(
        title="Policy",
        text="Intro text.",
        children=[
            Node(
                title="Who we are",
                text="We are Example Ltd.",
                children=[Node(title="Contact", text="Email privacy@example.com.")],
            ),
            Node(title="Empty heading"),
            Node(title="Your rights", text="You may access your data."),
        ],
    )
    assign_ids(root)
    return DocumentTree(
        doc_id="policy", title="Example Policy", source="policy.pdf", source_type="pdf", root=root
    )


def prompt_for(client, section):
    return next(p for p in client.prompts if f"Section: {section}\n" in p)


def test_every_node_with_content_gets_a_summary():
    tree = make_tree()

    stats = summarize_tree(tree, FakeClient())

    assert tree.get("1").summary == "Summary of Who we are"
    assert tree.get("1.1").summary == "Summary of Contact"
    assert tree.get("3").summary == "Summary of Your rights"
    assert tree.root.summary == "Summary of (the whole document)"
    assert stats.summarized == 4
    assert stats.skipped == 1
    assert stats.failed == []


def test_children_are_summarized_before_their_parent():
    tree = make_tree()
    client = FakeClient()

    summarize_tree(tree, client)

    order = [re.search(r"^Section: (.*)$", p, re.MULTILINE).group(1) for p in client.prompts]
    assert order.index("Contact") < order.index("Who we are")
    assert order[-1] == "(the whole document)"


def test_parent_prompt_contains_child_summaries_not_child_text():
    tree = make_tree()
    client = FakeClient()

    summarize_tree(tree, client)

    parent_prompt = prompt_for(client, "Who we are")
    assert "We are Example Ltd." in parent_prompt
    assert "- Contact: Summary of Contact" in parent_prompt
    assert "privacy@example.com" not in parent_prompt


def test_empty_node_is_skipped_without_an_llm_call():
    tree = make_tree()
    client = FakeClient()

    summarize_tree(tree, client)

    assert tree.get("2").summary is None
    assert not any("Section: Empty heading\n" in p for p in client.prompts)


def test_parent_with_only_children_is_summarized():
    root = Node(title="Policy", children=[Node(title="Data we collect", text="Name, email.")])
    assign_ids(root)
    tree = DocumentTree(doc_id="p", title="P", source="p.pdf", source_type="pdf", root=root)

    summarize_tree(tree, FakeClient())

    assert tree.root.summary is not None


def test_failed_node_does_not_stop_the_run():
    tree = make_tree()
    client = FakeClient(fail_on={"Contact"})

    stats = summarize_tree(tree, client)

    assert tree.get("1.1").summary is None
    assert stats.failed == ["1.1"]
    assert tree.get("3").summary == "Summary of Your rights"
    # the parent falls back to the child's title
    assert "- Contact\n" in prompt_for(client, "Who we are")


def test_connection_error_is_raised():
    tree = make_tree()
    client = FakeClient(fail_on={"Contact"}, error=LLMConnectionError("server down"))

    with pytest.raises(LLMConnectionError):
        summarize_tree(tree, client)


def test_long_text_is_truncated():
    tree = make_tree()
    tree.get("3").text = "x" * 500

    prompt = build_prompt(tree, tree.get("3"), max_chars=100)

    assert "x" * 100 + TRUNCATION_MARK in prompt
    assert "x" * 101 not in prompt


def test_invalid_max_chars_is_rejected():
    with pytest.raises(ValueError):
        summarize_tree(make_tree(), FakeClient(), max_chars=0)


def test_summary_whitespace_is_collapsed():
    class Messy(FakeClient):
        def generate_structured(self, prompt, schema, *, system=None):
            return schema(summary="  Lists data\n  we collect.  ")

    tree = make_tree()
    summarize_tree(tree, Messy())

    assert tree.get("3").summary == "Lists data we collect."


def test_system_prompt_and_schema_are_used():
    client = FakeClient()

    summarize_tree(make_tree(), client)

    assert set(client.systems) == {SYSTEM_PROMPT}
    assert NodeSummary.model_json_schema()["required"] == ["summary"]


def test_progress_reports_every_node():
    calls = []

    summarize_tree(make_tree(), FakeClient(), on_progress=lambda d, t, n: calls.append((d, t)))

    assert calls == [(i, 5) for i in range(1, 6)]


def test_summaries_survive_save_and_load(tmp_path):
    tree = make_tree()
    summarize_tree(tree, FakeClient())
    path = tmp_path / "policy.json"

    tree.save(path)
    loaded = DocumentTree.load(path)

    assert loaded.get("1.1").summary == "Summary of Contact"
    assert "1  Who we are: Summary of Who we are" in loaded.outline()
