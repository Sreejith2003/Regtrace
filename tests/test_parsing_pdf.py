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
