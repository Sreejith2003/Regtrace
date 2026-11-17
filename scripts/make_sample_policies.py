"""Generate realistic sample privacy-policy PDFs for trying RegTrace end to end.

The companies are fictional (domains use the reserved `.example` TLD), so the
text is ours and safe to share. Each policy deliberately leaves out some
GDPR Art. 13 information ("planted gaps"); they are listed in PLANTED_GAPS and
written to `planted_gaps.json` so later phases can score against them.

The three PDFs exercise different parser paths:

- brightleaf-coffee.pdf   numbered headings in larger fonts, multi-page, header/footer
- stridewell-fitness.pdf  headings at body size, structure only in PDF bookmarks
- lumen-lark-studio.pdf   short one-page policy with a few headings

Usage (from the repo root, venv active):
    python scripts\\make_sample_policies.py            # writes to data\\samples\\
    python scripts\\make_sample_policies.py --out other\\folder
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf

PAGE_WIDTH, PAGE_HEIGHT = pymupdf.paper_size("a4")  # 595 x 842 pt
MARGIN_X = 64
TOP, BOTTOM = 80, PAGE_HEIGHT - 72

# Content blocks: ("title", text) | ("h1", text) | ("h2", text) | ("p", text) | ("ul", [items])
Block = tuple[str, object]


class PolicyWriter:
    """Lays out blocks on A4 pages with word wrapping, headers, footers and bookmarks."""

    def __init__(self, *, header: str, sizes: dict[str, float], bold_headings: bool) -> None:
        self.doc = pymupdf.open()
        self.header = header
        self.sizes = sizes
        self.bold_headings = bold_headings
        self.toc: list[list] = []
        self.page: pymupdf.Page | None = None
        self.y = TOP

    def write(self, blocks: list[Block]) -> None:
        for kind, content in blocks:
            if kind == "title":
                self._lines(str(content), self.sizes["title"], bold=True, gap_after=14)
            elif kind in ("h1", "h2"):
                self.y += 8
                self._ensure_space(self.sizes[kind] * 3)
                self.toc.append([1 if kind == "h1" else 2, str(content), self.doc.page_count])
                self._lines(str(content), self.sizes[kind], bold=self.bold_headings, gap_after=4)
            elif kind == "p":
                self._lines(str(content), self.sizes["body"], gap_after=7)
            elif kind == "ul":
                for item in content:  # type: ignore[union-attr]
                    self._lines(f"- {item}", self.sizes["body"], indent=14, gap_after=3)
                self.y += 4

    def save(self, path: Path, *, title: str, with_bookmarks: bool) -> None:
        for number, page in enumerate(self.doc, start=1):
            page.insert_text((MARGIN_X, 40), self.header, fontsize=8, color=(0.4, 0.4, 0.4))
            page.insert_text(
                (PAGE_WIDTH - MARGIN_X - 40, PAGE_HEIGHT - 30), f"Page {number}", fontsize=8
            )
        if with_bookmarks:
            self.doc.set_toc(self.toc)
        self.doc.set_metadata({"title": title})
        path.parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(path)
        self.doc.close()

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        self.y = TOP

    def _ensure_space(self, height: float) -> None:
        if self.page is None or self.y + height > BOTTOM:
            self._new_page()

    def _lines(
        self, text: str, size: float, *, bold: bool = False, indent: float = 0, gap_after: float
    ) -> None:
        font = "hebo" if bold else "helv"
        width = PAGE_WIDTH - 2 * MARGIN_X - indent
        line = ""
        wrapped: list[str] = []
        for word in text.split():
            candidate = f"{line} {word}".strip()
            if pymupdf.get_text_length(candidate, fontname=font, fontsize=size) <= width:
                line = candidate
            else:
                wrapped.append(line)
                line = word
        wrapped.append(line)

        leading = size * 1.35
        for text_line in wrapped:
            self._ensure_space(leading)
            self.y += size
            self.page.insert_text(
                (MARGIN_X + indent, self.y), text_line, fontsize=size, fontname=font
            )
            self.y += leading - size
        self.y += gap_after


# --- 1. Brightleaf Coffee Roasters: fairly complete, a few gaps -----------------------

BRIGHTLEAF: list[Block] = [
    ("title", "Brightleaf Coffee Roasters Privacy Policy"),
    (
        "p",
        "Last updated: 3 March 2026. This policy explains how Brightleaf Coffee Roasters Ltd "
        "collects and uses personal data when you visit brightleaf.example, buy coffee from our "
        "online shop, or subscribe to our monthly coffee box.",
    ),
    ("h1", "1. Who we are"),
    (
        "p",
        "Brightleaf Coffee Roasters Ltd is the controller of your personal data. We are a company "
        "registered in Ireland (company number 654321) with our registered office at Unit 4, "
        "Harbour Works, Galway H91 X2Y3, Ireland.",
    ),
    ("h2", "1.1 How to contact us"),
    (
        "p",
        "If you have any questions about this policy or how we handle your data, email "
        "privacy@brightleaf.example or write to us at the address above. We aim to reply within "
        "five working days.",
    ),
    ("h2", "1.2 Data protection officer"),
    (
        "p",
        "We have appointed a data protection officer, who can be reached at "
        "dpo@brightleaf.example.",
    ),
    ("h1", "2. Personal data we collect"),
    ("p", "Depending on how you interact with us, we collect the following categories of data:"),
    (
        "ul",
        [
            "Identity and contact data: your name, delivery address, email address and phone "
            "number.",
            "Order data: the products you buy, your subscription preferences and order history.",
            "Payment data: the last four digits of your card and the payment status. Full card "
            "details are handled by our payment provider and never stored by us.",
            "Technical data: IP address, browser type and pages visited on our website.",
            "Marketing data: whether you have opted in to our newsletter.",
        ],
    ),
    ("h1", "3. How we use your data and our legal basis"),
    (
        "p",
        "We process your data only where we have a legal basis under the General Data Protection "
        "Regulation (GDPR):",
    ),
    (
        "ul",
        [
            "To process and deliver your orders and manage your subscription, because it is "
            "necessary for the performance of our contract with you (Article 6(1)(b) GDPR).",
            "To send our newsletter, based on your consent (Article 6(1)(a) GDPR). You can "
            "withdraw consent at any time using the unsubscribe link in every email.",
            "To keep accounting records, because we are legally required to "
            "(Article 6(1)(c) GDPR).",
            "To prevent fraud and keep our website secure, based on our legitimate interest in "
            "protecting our business and customers (Article 6(1)(f) GDPR).",
        ],
    ),
    ("h1", "4. Who we share your data with"),
    (
        "p",
        "We share personal data only with service providers who help us run our business: our "
        "payment provider, our delivery partners, our email newsletter platform and our website "
        "hosting provider. These providers act on our instructions under data processing "
        "agreements.",
    ),
    ("h2", "4.1 International transfers"),
    (
        "p",
        "Our newsletter platform stores data in the United States. Where data is transferred "
        "outside the European Economic Area, we rely on the European Commission's Standard "
        "Contractual Clauses. You can request a copy of these safeguards by emailing "
        "privacy@brightleaf.example.",
    ),
    ("h1", "5. How long we keep your data"),
    (
        "p",
        "We keep order and accounting records for six years after the end of the financial year "
        "in which the order was placed, as required by Irish tax law. Newsletter data is kept "
        "until you unsubscribe. Technical data from our website is deleted after 13 months.",
    ),
    ("h1", "6. Your rights"),
    ("p", "Under the GDPR you have the right to:"),
    (
        "ul",
        [
            "access the personal data we hold about you;",
            "ask us to correct inaccurate data;",
            "ask us to erase your data in certain circumstances;",
            "restrict or object to our processing of your data;",
            "receive your data in a portable format;",
            "withdraw your consent at any time, without affecting processing before withdrawal.",
        ],
    ),
    (
        "p",
        "To exercise any of these rights, email privacy@brightleaf.example. We will respond within "
        "one month.",
    ),
    ("h1", "7. Cookies"),
    (
        "p",
        "Our website uses cookies that are strictly necessary for the shop to work, and analytics "
        "cookies only if you accept them in our cookie banner.",
    ),
    ("h1", "8. Changes to this policy"),
    (
        "p",
        "We may update this policy from time to time. We will post the new version on this page "
        "and, for significant changes, let you know by email.",
    ),
]

# --- 2. Stridewell Fitness app: structure only in bookmarks, several gaps -------------

STRIDEWELL: list[Block] = [
    ("title", "Stridewell Fitness App - Privacy Notice"),
    (
        "p",
        "Stridewell helps you track your runs, workouts and sleep. This notice describes how "
        "Stridewell Health GmbH handles your information when you use the Stridewell mobile app "
        "and website.",
    ),
    ("h1", "About Stridewell"),
    (
        "p",
        "The Stridewell app is operated by Stridewell Health GmbH, Torstrasse 101, 10119 Berlin, "
        "Germany. For privacy questions, contact support@stridewell.example.",
    ),
    ("h1", "Information we collect"),
    ("h2", "Account information"),
    (
        "p",
        "When you sign up we collect your name, email address, date of birth and a password. You "
        "may optionally add a profile photo.",
    ),
    ("h2", "Activity and health data"),
    (
        "p",
        "If you allow it, the app records GPS location during workouts, heart rate from connected "
        "wearables, step counts and sleep duration. You can turn each of these off in the app "
        "settings.",
    ),
    ("h2", "Device information"),
    (
        "p",
        "We collect your device model, operating system version, app version and crash reports to "
        "keep the app working reliably.",
    ),
    ("h1", "How we use information"),
    (
        "p",
        "We use your information to provide the app's features, show your progress, recommend "
        "training plans, improve our services and send you product updates. With your permission "
        "we also show personalised offers from our partners.",
    ),
    ("h1", "Sharing"),
    (
        "p",
        "We share data with cloud hosting and analytics providers that support the app, and with "
        "partners whose offers you choose to see. Some of these providers are located outside the "
        "European Union.",
    ),
    ("h1", "Keeping your data safe"),
    (
        "p",
        "We use encryption in transit and at rest, strict access controls and regular security "
        "testing to protect your data.",
    ),
    ("h1", "Your choices"),
    (
        "p",
        "You can view and edit your profile in the app at any time. You can delete your account "
        "under Settings > Account > Delete account, which removes your profile and activity "
        "history.",
    ),
    ("h1", "Children"),
    (
        "p",
        "Stridewell is not intended for children under 16 and we do not knowingly collect their "
        "data.",
    ),
]

# --- 3. Lumen & Lark Design Studio: short, many gaps ----------------------------------

LUMEN_LARK: list[Block] = [
    ("title", "Lumen & Lark Studio Privacy Policy"),
    (
        "p",
        "Lumen & Lark is a small design studio. We respect your privacy and only collect what we "
        "need.",
    ),
    ("h1", "What we collect"),
    (
        "p",
        "When you use the contact form on lumenlark.example we receive your name, email address "
        "and the message you send us. Our website also uses basic analytics.",
    ),
    ("h1", "Why we collect it"),
    (
        "p",
        "We use your details to reply to your enquiry and, if you become a client, to manage our "
        "project with you.",
    ),
    ("h1", "Contact"),
    ("p", "Questions? Email hello@lumenlark.example."),
]

# Information GDPR Art. 13 requires that each policy deliberately leaves out.
PLANTED_GAPS: dict[str, list[dict[str, str]]] = {
    "brightleaf-coffee": [
        {
            "article": "13(2)(d)",
            "missing": "right to lodge a complaint with a supervisory authority",
        },
        {
            "article": "13(2)(e)",
            "missing": "whether providing data is a statutory/contractual requirement "
            "and the consequences of not providing it",
        },
    ],
    "stridewell-fitness": [
        {"article": "13(1)(b)", "missing": "contact details of the data protection officer"},
        {"article": "13(1)(c)", "missing": "legal basis for each processing purpose"},
        {"article": "13(1)(f)", "missing": "safeguards for transfers outside the EU"},
        {"article": "13(2)(a)", "missing": "retention period or criteria"},
        {"article": "13(2)(b)", "missing": "full list of data subject rights"},
        {"article": "13(2)(c)", "missing": "right to withdraw consent"},
        {
            "article": "13(2)(d)",
            "missing": "right to lodge a complaint with a supervisory authority",
        },
    ],
    "lumen-lark-studio": [
        {"article": "13(1)(a)", "missing": "identity and address of the controller"},
        {"article": "13(1)(c)", "missing": "legal basis for processing"},
        {"article": "13(1)(e)", "missing": "recipients (e.g. the analytics provider)"},
        {"article": "13(2)(a)", "missing": "retention period or criteria"},
        {"article": "13(2)(b)", "missing": "data subject rights"},
        {
            "article": "13(2)(d)",
            "missing": "right to lodge a complaint with a supervisory authority",
        },
    ],
}


def build(out_dir: Path) -> list[Path]:
    specs = [
        # name, blocks, header, sizes, bold headings, bookmarks
        (
            "brightleaf-coffee",
            BRIGHTLEAF,
            "Brightleaf Coffee Roasters Ltd - Privacy Policy",
            {"title": 20, "h1": 15, "h2": 12.5, "body": 10.5},
            True,
            False,
        ),
        (
            "stridewell-fitness",
            STRIDEWELL,
            "Stridewell Health GmbH",
            {"title": 10.5, "h1": 10.5, "h2": 10.5, "body": 10.5},
            True,
            True,
        ),
        (
            "lumen-lark-studio",
            LUMEN_LARK,
            "Lumen & Lark",
            {"title": 18, "h1": 13, "h2": 11, "body": 10},
            True,
            False,
        ),
    ]
    paths = []
    for name, blocks, header, sizes, bold, bookmarks in specs:
        writer = PolicyWriter(header=header, sizes=sizes, bold_headings=bold)
        writer.write(blocks)
        path = out_dir / f"{name}.pdf"
        writer.save(path, title=str(blocks[0][1]), with_bookmarks=bookmarks)
        paths.append(path)

    (out_dir / "planted_gaps.json").write_text(json.dumps(PLANTED_GAPS, indent=2), encoding="utf-8")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("data/samples"), help="output folder")
    args = parser.parse_args()
    for path in build(args.out):
        print(f"wrote {path}")
    print(f"wrote {args.out / 'planted_gaps.json'}")


if __name__ == "__main__":
    main()
