"""PDF parser tests. Every PDF is generated on the fly, so no third-party text is committed."""

import pymupdf
import pytest

from regtrace.parsing import parse_pdf

BODY = "This paragraph is ordinary body text that explains what the section covers."


def make_pdf(path, pages, *, toc=None, title=None):
    """Write a PDF. `pages` is a list of pages; each page is a list of
    `(text, font_size)` or `(text, font_size, y)` tuples."""
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page()  # A4: 595 x 842 pt
        y = 100
        for line in lines:
            text, size, *fixed_y = line
            page.insert_text((72, fixed_y[0] if fixed_y else y), text, fontsize=size)
            if not fixed_y:
                y += size + 10
    if toc:
        doc.set_toc(toc)
    if title:
        doc.set_metadata({"title": title})
    doc.save(path)
    doc.close()
    return path


def titles(tree):
    return [(node.id, node.title) for node in tree.walk()][1:]


# --- font-size strategy ---


@pytest.fixture
def font_pdf(tmp_path):
    return make_pdf(
        tmp_path / "font_policy.pdf",
        [
            [
                ("Example Privacy Policy", 22),
                (BODY, 11),
                ("1. Who we are", 16),
                (BODY, 11),
                (BODY, 11),
                ("1.1 Contact details", 13),
                (BODY, 11),
                ("2. Your rights", 16),
                (BODY, 11),
            ]
        ],
    )


def test_font_sizes_become_heading_levels(font_pdf):
    tree = parse_pdf(font_pdf)

    assert titles(tree) == [
        ("1", "1. Who we are"),
        ("1.1", "1.1 Contact details"),
        ("2", "2. Your rights"),
    ]


def test_unique_largest_first_heading_is_document_title(font_pdf):
    tree = parse_pdf(font_pdf)

    assert tree.title == "Example Privacy Policy"
    assert tree.root.title == "Example Privacy Policy"


def test_text_goes_to_nearest_heading(font_pdf):
    tree = parse_pdf(font_pdf)

    assert tree.root.text == BODY  # preamble before the first section
    assert tree.get("1").text.count(BODY) == 2
    assert tree.get("1.1").text == BODY
    assert tree.get("2").text == BODY
    assert "Who we are" not in tree.get("1").text  # heading lines are not body text


def test_page_ranges_cover_section_content(tmp_path):
    path = make_pdf(
        tmp_path / "pages.pdf",
        [
            [("Section A", 16), (BODY, 11)],
            [(BODY, 11)],
            [("Section B", 16), (BODY, 11)],
        ],
    )

    tree = parse_pdf(path)

    assert (tree.get("1").page_start, tree.get("1").page_end) == (1, 2)
    assert (tree.get("2").page_start, tree.get("2").page_end) == (3, 3)
    assert (tree.root.page_start, tree.root.page_end) == (1, 3)


def test_pdf_without_headings_keeps_all_text_in_root(tmp_path):
    path = make_pdf(tmp_path / "plain.pdf", [[(BODY, 11), (BODY, 11)]])

    tree = parse_pdf(path)

    assert tree.root.children == []
    assert tree.root.text.count(BODY) == 2
    assert tree.title == "plain"


# --- bookmark strategy ---


@pytest.fixture
def bookmark_pdf(tmp_path):
    return make_pdf(
        tmp_path / "bookmarks.pdf",
        [
            [("Who we are", 11), (BODY, 11), ("Contact", 11), (BODY, 11)],
            [("Your rights", 11), (BODY, 11)],
        ],
        toc=[[1, "Who we are", 1], [2, "Contact", 1], [1, "Your rights", 2]],
        title="Bookmarked Policy",
    )


def test_bookmarks_define_the_tree(bookmark_pdf):
    tree = parse_pdf(bookmark_pdf)

    assert titles(tree) == [("1", "Who we are"), ("1.1", "Contact"), ("2", "Your rights")]
    assert tree.title == "Bookmarked Policy"
    assert tree.get("1").text == BODY
    assert tree.get("1.1").text == BODY
    assert (tree.get("2").page_start, tree.get("2").page_end) == (2, 2)


def test_unmatched_bookmark_starts_at_top_of_its_page(tmp_path):
    path = make_pdf(
        tmp_path / "unmatched.pdf",
        [[("First page text.", 11)], [("Second page text.", 11)]],
        toc=[[1, "Part one", 1], [1, "Part two", 2]],
    )

    tree = parse_pdf(path)

    assert tree.get("1").text == "First page text."
    assert tree.get("2").text == "Second page text."


def test_fonts_strategy_ignores_bookmarks(bookmark_pdf):
    tree = parse_pdf(bookmark_pdf, strategy="fonts")

    assert tree.root.children == []
    assert "Who we are" in tree.root.text


def test_auto_ignores_a_single_bookmark_and_uses_fonts(tmp_path):
    path = make_pdf(
        tmp_path / "one_bookmark.pdf",
        [[("Intro", 16), (BODY, 11), ("Details", 16), (BODY, 11)]],
        toc=[[1, "Whole document", 1]],
    )

    tree = parse_pdf(path)

    assert titles(tree) == [("1", "Intro"), ("2", "Details")]


# --- cleanup and errors ---


def test_repeated_headers_footers_and_page_numbers_are_removed(tmp_path):
    pages = [
        [("ACME Corp Privacy Policy", 9, 40), (BODY, 11), (f"Page {n}", 9, 820)]
        for n in range(1, 4)
    ]
    path = make_pdf(tmp_path / "furniture.pdf", pages)

    text = parse_pdf(path).full_text()

    assert "ACME Corp" not in text
    assert "Page " not in text
    assert text.count(BODY) == 3


def test_header_repeated_on_two_pages_is_removed(tmp_path):
    pages = [[("ACME Corp Privacy Policy", 9, 40), (BODY, 11)] for _ in range(2)]
    path = make_pdf(tmp_path / "two_pages.pdf", pages)

    assert "ACME Corp" not in parse_pdf(path).full_text()


def test_page_number_on_single_page_is_removed(tmp_path):
    path = make_pdf(tmp_path / "one_page.pdf", [[(BODY, 11), ("Page 1 of 1", 9, 820)]])

    assert parse_pdf(path).root.text == BODY


def test_number_in_body_text_is_kept(tmp_path):
    path = make_pdf(tmp_path / "numbers.pdf", [[(BODY, 11), ("42", 11)]])

    assert "42" in parse_pdf(path).root.text


def test_doc_id_defaults_to_slug_of_file_name(tmp_path):
    path = make_pdf(tmp_path / "My Policy 2024.pdf", [[(BODY, 11)]])

    tree = parse_pdf(path)

    assert tree.doc_id == "my-policy-2024"
    assert tree.source_type == "pdf"


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_pdf(tmp_path / "missing.pdf")


def test_non_pdf_file_is_rejected(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("just text", encoding="utf-8")

    with pytest.raises(ValueError, match="Not a PDF"):
        parse_pdf(path)


# --- legal strategy ---


@pytest.fixture
def legal_pdf(tmp_path):
    return make_pdf(
        tmp_path / "regulation.pdf",
        [
            [
                ("Whereas the recitals explain the purpose.", 10),
                ("CHAPTER I", 10),
                ("General provisions", 10),
                ("Article 1", 10),
                ("Subject-matter", 10),
                ("1.", 10),
                ("This Regulation lays down rules.", 10),
                ("2.", 10),
                ("It protects fundamental rights, see Article 2.", 10),
                ("CHAPTER II", 10),
                ("Rights of the data subject", 10),
                ("Section 1", 10),
                ("Transparency", 10),
                ("Article 12", 10),
                ("Transparent information", 10),
                ("The controller shall take appropriate measures.", 10),
                ("Article 13", 10),
                ("Information to be provided", 10),
                ("1.", 10),
                ("The controller shall provide the following:", 10),
                ("(a) the identity of the controller;", 10),
            ]
        ],
    )


def test_legal_structure_becomes_the_tree(legal_pdf):
    tree = parse_pdf(legal_pdf, strategy="legal")

    assert titles(tree) == [
        ("1", "CHAPTER I General provisions"),
        ("1.1", "Article 1 Subject-matter"),
        ("1.1.1", "Article 1(1)"),
        ("1.1.2", "Article 1(2)"),
        ("2", "CHAPTER II Rights of the data subject"),
        ("2.1", "Section 1 Transparency"),
        ("2.1.1", "Article 12 Transparent information"),
        ("2.1.2", "Article 13 Information to be provided"),
        ("2.1.2.1", "Article 13(1)"),
    ]


def test_legal_text_goes_to_paragraphs_and_preamble_to_root(legal_pdf):
    tree = parse_pdf(legal_pdf, strategy="legal")

    assert tree.root.text == "Whereas the recitals explain the purpose."
    assert tree.get("1.1.2").text == "It protects fundamental rights, see Article 2."
    assert tree.get("2.1.1").text == "The controller shall take appropriate measures."
    assert "(a) the identity of the controller;" in tree.get("2.1.2.1").text


def test_auto_detects_legal_structure(legal_pdf):
    assert titles(parse_pdf(legal_pdf))[0] == ("1", "CHAPTER I General provisions")


def test_auto_needs_several_articles_for_legal(tmp_path):
    path = make_pdf(
        tmp_path / "policy.pdf",
        [[("Intro", 16), ("Article 6", 11), ("Lawful basis", 11), ("Details", 16), (BODY, 11)]],
    )

    assert titles(parse_pdf(path)) == [("1", "Intro"), ("2", "Details")]


def test_article_number_without_title_is_not_a_heading(tmp_path):
    path = make_pdf(
        tmp_path / "no_title.pdf",
        [[("Article 5", 10), ("1.", 10), ("Personal data shall be processed lawfully.", 10)]],
    )

    tree = parse_pdf(path, strategy="legal")

    assert tree.root.children == []
    assert "Article 5" in tree.root.text


def test_wrapped_article_title_is_joined(tmp_path):
    path = make_pdf(
        tmp_path / "wrapped.pdf",
        [
            [
                ("Article 12", 10, 100),
                ("Transparent information and modalities for the rights of the data", 10, 120),
                ("subject", 10, 131),
                ("1.", 10, 160),
                ("The controller shall take appropriate measures.", 10, 180),
            ]
        ],
    )

    tree = parse_pdf(path, strategy="legal")

    assert titles(tree) == [
        (
            "1",
            "Article 12 Transparent information and modalities for the rights of the data subject",
        ),
        ("1.1", "Article 12(1)"),
    ]
    assert tree.get("1").text == ""
