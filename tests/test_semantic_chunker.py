import unittest
from src.rag.semantic_chunker import SemanticChunker

class TestSemanticChunker(unittest.TestCase):
    def setUp(self):
        self.chunker = SemanticChunker()

    def test_split_sentences_abbreviations(self):
        text = "When this proved impracticable, it became apparent that Dr. Bob’s biography should be written first, before Bill W.s."
        sentences = self.chunker._split_sentences(text)
        self.assertEqual(len(sentences), 1)
        self.assertEqual(sentences[0], text)

    def test_split_sentences_multiple_names_and_orgs(self):
        text = "Dr. Bob went to St. Thomas hospital for A.A. meetings with Bill W. and Hank P. to help others. Then they returned to Akron."
        sentences = self.chunker._split_sentences(text)
        self.assertEqual(len(sentences), 2)
        self.assertEqual(sentences[0], "Dr. Bob went to St. Thomas hospital for A.A. meetings with Bill W. and Hank P. to help others.")
        self.assertEqual(sentences[1], "Then they returned to Akron.")

    def test_split_sentences_standard(self):
        text = "This was in August 1939. Dr. Bob could never remember just what the policy was. He worked hard every day."
        sentences = self.chunker._split_sentences(text)
        self.assertEqual(len(sentences), 3)
        self.assertEqual(sentences[0], "This was in August 1939.")
        self.assertEqual(sentences[1], "Dr. Bob could never remember just what the policy was.")
        self.assertEqual(sentences[2], "He worked hard every day.")

    def test_chunk_from_blocks(self):
        blocks = [
            {
                "id": "b00001",
                "type": "heading",
                "text": "Chapter 1",
                "printed_page": 1,
                "physical_page": 1,
            },
            {
                "id": "b00002",
                "type": "paragraph",
                "text": "“You know, it never dawned on me until later how long Dr. Bob and Bill had been sober. If I’d known it was just a short while, I might not have been so sure it was going to work for my Bill.” When Bill D. came out of the hospital, Dr. Bob had been sober only three weeks. “I thought they’d been sober for years. I think my husband thought so, too.",
                "printed_page": 1,
                "physical_page": 1,
                "heading_context": "Chapter 1",
            }
        ]
        chunks = self.chunker.chunk_from_blocks(blocks)
        self.assertTrue(len(chunks) > 0)
        for c in chunks:
            self.assertIn("Dr. Bob and Bill had been sober", c["text"])
            self.assertIn("b00002", c["block_ids"])

if __name__ == '__main__':
    unittest.main()
