import pytest

from regtrace.parsing import parse_html, parse_html_file

PAGE = """<!doctype html>
<html>
<head><title>Acme | Privacy</title><style>p { color: red }</style></head>
<body>
  <nav><a href="/">Home</a> <a href="/about">About</a></nav>
  <header><h2>Acme site banner</h2></header>
  <main>
    <article>
      <header><h1>Privacy Policy</h1></header>
      <p>Last updated: 1 May 2025.</p>
      <h2>1. Who we are</h2>
      <p>Acme Ltd, <b>London</b>, is the controller.<br>Email: privacy@acme.example</p>
      <h3>1.1 Our DPO</h3>
      <div>You can reach our data protection officer at dpo@acme.example.</div>
      <h2>2. Data we collect</h2>
      <ul>
        <li>Account data:
          <ul><li>name</li><li>email address</li></ul>
        </li>
      </ul>
      <!-- internal note -->
      <script>track()</script>
      <h2>3. Your rights</h2>
      <table><tr><td>Access</td><td>Article 15</td></tr></table>
    </article>
  </main>
  <footer>&copy; Acme Ltd</footer>
</body>
</html>"""


@pytest.fixture
def tree():
    return parse_html(PAGE, source="https://acme.example/privacy", doc_id="acme")


def titles(tree):
    return [(node.id, node.title) for node in tree.walk()][1:]


def test_headings_become_the_tree(tree):
    assert tree.title == "Privacy Policy"
    assert titles(tree) == [
        ("1", "1. Who we are"),
        ("1.1", "1.1 Our DPO"),
        ("2", "2. Data we collect"),
        ("3", "3. Your rights"),
    ]
    assert [node.level for node in tree.walk()] == [0, 1, 2, 1, 1]


def test_text_goes_to_nearest_heading(tree):
    assert tree.root.text == "Last updated: 1 May 2025."
    assert tree.get("1").text == "Acme Ltd, London, is the controller.\nEmail: privacy@acme.example"
    assert tree.get("1.1").text == (
        "You can reach our data protection officer at dpo@acme.example."
    )
    assert tree.get("2").text == "Account data:\n\nname\n\nemail address"
    assert tree.get("3").text == "Access\n\nArticle 15"


def test_page_chrome_scripts_and_comments_are_dropped(tree):
    text = tree.full_text()

    for unwanted in ["Home", "banner", "track()", "color: red", "internal note", "©"]:
        assert unwanted not in text


def test_source_metadata(tree):
    assert tree.doc_id == "acme"
    assert tree.source == "https://acme.example/privacy"
    assert tree.source_type == "html"
    assert tree.root.page_start is None


def test_heading_levels_are_ranked_not_copied():
    tree = parse_html(
        "<body><h2>A</h2><p>a</p><h4>B</h4><p>b</p><h2>C</h2></body>", source="x", doc_id="x"
    )

    assert [(node.id, node.level) for node in tree.walk()][1:] == [("1", 1), ("1.1", 2), ("2", 1)]


def test_page_title_is_used_without_a_single_h1():
    tree = parse_html(
        "<title>Example Policy</title><h1>One</h1><p>a</p><h1>Two</h1>", source="x", doc_id="x"
    )

    assert tree.title == "Example Policy"
    assert titles(tree) == [("1", "One"), ("2", "Two")]


def test_page_without_headings_keeps_text_in_root():
    tree = parse_html("<p>First.</p><p>Second.</p>", source="x", doc_id="plain")

    assert tree.root.children == []
    assert tree.root.text == "First.\n\nSecond."
    assert tree.title == "plain"


def test_parse_html_file(tmp_path):
    path = tmp_path / "Acme Policy.html"
    path.write_text(PAGE, encoding="utf-8")

    tree = parse_html_file(path)

    assert tree.doc_id == "acme-policy"
    assert tree.source == str(path)
    assert tree.get("2").title == "2. Data we collect"


def test_parse_html_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_html_file(tmp_path / "missing.html")
