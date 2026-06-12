import unittest
from src.rag.text_repair import (
    collapse_doubled_layers,
    repair_hyphenation,
    repair_ligatures,
    reflow_paragraphs
)

class TestTextRepair(unittest.TestCase):
    def test_collapse_doubled_layers(self):
        # Doubled character layer collapse
        doubled = "1122&&1122__IInnssiiddee__EEnnggglliisshh..iinndddd"
        self.assertEqual(collapse_doubled_layers(doubled), "12&12_Inside_English.indd")

        # Minimal case
        self.assertEqual(collapse_doubled_layers("AABBCC"), "ABC")

        # Below threshold (should remain unchanged)
        normal = "Continued to take personal inventory..."
        self.assertEqual(collapse_doubled_layers(normal), normal)

        # Mixed case with some double letters but below 60%
        mixed = "The bookkeeper went to the office."
        self.assertEqual(collapse_doubled_layers(mixed), mixed)

    def test_repair_hyphenation(self):
        # Document text containing occurrences of the words for the vocabulary
        doc_text = """
        We need to make a practical decision.
        He showed self-sufficiency in his work.
        This is another example of a hyphenation split.
        They lived in a high-tech home.
        """
        
        # 1. Join split word across line break when combined is in vocabulary
        # 'practi- cal' -> 'practical'
        input1 = "This was a practi-\ncal decision."
        self.assertTrue(repair_hyphenation(input1 + doc_text).startswith("This was a practical decision."))

        # 2. Join split word when one or both fragments are not valid words
        # 'hyphena- tion' -> 'hyphenation'
        input2 = "A hyphena-\ntion split."
        self.assertTrue(repair_hyphenation(input2 + doc_text).startswith("A hyphenation split."))

        # 3. Keep real hyphenated compounds (both parts are valid standalone words)
        # 'self-\nsufficiency' -> 'self-sufficiency'
        input3 = "Their self-\nsufficiency was key."
        self.assertTrue(repair_hyphenation(input3 + doc_text).startswith("Their self-sufficiency was key."))

        # 4. Keep real hyphenated compounds with space
        # 'self- sufficiency' -> 'self-sufficiency'
        input4 = "Their self- sufficiency was key."
        self.assertTrue(repair_hyphenation(input4 + doc_text).startswith("Their self-sufficiency was key."))

    def test_repair_ligatures(self):
        # 1. Word on the allowlist: 'first' split as 'fi rst'
        self.assertEqual(repair_ligatures("This is the fi rst time."), "This is the first time.")

        # 2. Word on the allowlist: 'sufficient' split as 'suffi cient'
        self.assertEqual(repair_ligatures("We need suffi cient funds."), "We need sufficient funds.")

        # 3. Word not on allowlist but appearing >= 2 times in doc_text
        self.assertEqual(repair_ligatures("His infl uence was great."), "His influence was great.")

    def test_reflow_paragraphs(self):
        lines = [
            "As we work the first nine Steps,",
            "we prepare ourselves for the tenth.",
            "",
            "Step Ten",
            "Continued to take personal inventory",
            "and when we were wrong promptly admitted it.",
            "* Item one",
            "* Item two",
            "1. First step",
            "2. Second step",
            "This is a paragraph",
            "and another line that joins.",
            "But this line ends in a period.",
            "This line starts after the period, so it shouldn't join."
        ]

        expected = [
            "As we work the first nine Steps, we prepare ourselves for the tenth.",
            "Step Ten",
            "Continued to take personal inventory and when we were wrong promptly admitted it.",
            "* Item one",
            "* Item two",
            "1. First step",
            "2. Second step",
            "This is a paragraph and another line that joins.",
            "But this line ends in a period.",
            "This line starts after the period, so it shouldn't join."
        ]

        self.assertEqual(reflow_paragraphs(lines), expected)

if __name__ == '__main__':
    unittest.main()
