import unittest
from src.rag.block_classifier import classify_block

class TestBlockClassifier(unittest.TestCase):
    def test_garbage(self):
        # Empty string
        self.assertEqual(classify_block(""), "garbage")
        self.assertEqual(classify_block("   "), "garbage")
        # Low alphanumeric ratio
        self.assertEqual(classify_block("!!! --- !!!"), "garbage")
        self.assertEqual(classify_block("... ... ..."), "garbage")

    def test_page_header_footer(self):
        # Bare page number at top vs bottom
        self.assertEqual(classify_block("297", position_on_page=0.05), "page_header")
        self.assertEqual(classify_block("297", position_on_page=0.95), "page_footer")

        # "Page 123" at top
        self.assertEqual(classify_block("Page 123", position_on_page=0.05), "page_header")

        # Running header from allowlist/set
        running_headers = {"# ALCOHOLICS ANONYMOUS COMES OF AGE"}
        block = "50 ALCOHOLICS ANONYMOUS COMES OF AGE"
        self.assertEqual(
            classify_block(block, position_on_page=0.05, running_headers=running_headers),
            "page_header"
        )

    def test_toc(self):
        # CONTENTS heading
        self.assertEqual(classify_block("CONTENTS"), "toc")
        self.assertEqual(classify_block("Table of Contents"), "toc")

        # Multiple enumeration markers in one block
        multi_enum = (
            "Step One: We admitted... "
            "Step Two: Came to believe... "
            "Step Three: Made a decision..."
        )
        self.assertEqual(classify_block(multi_enum), "toc")

    def test_index(self):
        index_block = (
            "Abstinence, 4, 12, 18\n"
            "Acceptance, 10-15, 33\n"
            "Admission, 88"
        )
        self.assertEqual(classify_block(index_block), "index")

    def test_list(self):
        self.assertEqual(classify_block("* Item one"), "list")
        self.assertEqual(classify_block("- Item two"), "list")
        self.assertEqual(classify_block("1. Numbered item"), "list")
        self.assertEqual(classify_block("(a) Alphabetical list"), "list")

    def test_heading(self):
        # Chapter headings
        self.assertEqual(classify_block("Step Ten"), "heading")
        self.assertEqual(classify_block("CHAPTER ONE"), "heading")
        self.assertEqual(classify_block("Twelve Steps and Twelve Traditions"), "heading")
        # Heading ending in a period should be paragraph, not heading
        self.assertEqual(classify_block("Step Ten."), "paragraph")

    def test_epigraph(self):
        # Quotes
        self.assertEqual(classify_block('“Continued to take personal inventory…”'), "epigraph")
        self.assertEqual(classify_block('"Sustained and personal exertion..."'), "epigraph")

    def test_footnote(self):
        # Footnote at the bottom of the page
        self.assertEqual(classify_block("* This is a footnote", position_on_page=0.85), "footnote")
        self.assertEqual(classify_block("1 This is another footnote", position_on_page=0.90), "footnote")
        # Standard bullet at the top is a list, not a footnote
        self.assertEqual(classify_block("* This is a normal list item", position_on_page=0.30), "list")

    def test_paragraph(self):
        # Default fallback
        para = "As we work the first nine Steps, we prepare ourselves for the tenth."
        self.assertEqual(classify_block(para), "paragraph")

if __name__ == '__main__':
    unittest.main()
