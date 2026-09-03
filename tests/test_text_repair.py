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

    def test_reflow_paragraphs_abbreviations(self):
        # Abbreviation endings should not falsely terminate paragraphs
        lines = [
            "“You know, it never dawned on me until later how long Dr.",
            "Bob and Bill had been sober. If I’d known it was just a short",
            "while, I might not have been so sure it was going to work for",
            "my Bill.” When Bill D. came out of the hospital, Dr. Bob had",
            "been sober only three weeks. “I thought they’d been sober for",
            "years. I think my husband thought so, too."
        ]
        result = reflow_paragraphs(lines)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].startswith("“You know, it never dawned on me until later how long Dr. Bob and Bill had been sober."))
        self.assertTrue(result[0].endswith("I think my husband thought so, too."))

        # Multiple other abbreviations (St., Bill W., A.A., etc.)
        lines2 = [
            "We visited St.",
            "Thomas hospital with Bill W.",
            "and talked about A.A.",
            "principles, recovery, etc.",
            "Next day we met again."
        ]
        result2 = reflow_paragraphs(lines2)
        # Should join all lines within the same paragraph
        self.assertEqual(result2[0], "We visited St. Thomas hospital with Bill W. and talked about A.A. principles, recovery, etc. Next day we met again.")

        # With explicit paragraph break
        lines3 = [
            "We visited St.",
            "Thomas hospital with Bill W.",
            "and talked about A.A.",
            "principles, recovery, etc.",
            "",
            "Next day we met again."
        ]
        result3 = reflow_paragraphs(lines3)
        self.assertEqual(len(result3), 2)
        self.assertEqual(result3[0], "We visited St. Thomas hospital with Bill W. and talked about A.A. principles, recovery, etc.")
        self.assertEqual(result3[1], "Next day we met again.")


if __name__ == '__main__':
    unittest.main()
