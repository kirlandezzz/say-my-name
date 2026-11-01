import unittest

from say_my_name.similarity import edit_distance, jaro_winkler, soft_dice, token_similarity


class SimilarityTest(unittest.TestCase):
    def test_reference_values(self):
        # Classic values from Winkler's paper.
        self.assertAlmostEqual(jaro_winkler("MARTHA", "MARHTA"), 0.9611, places=4)
        self.assertAlmostEqual(jaro_winkler("DIXON", "DICKSONX"), 0.8133, places=4)
        self.assertEqual(jaro_winkler("ABC", "ABC"), 1.0)
        self.assertEqual(jaro_winkler("", "ABC"), 0.0)

    def test_soft_dice_tolerates_typos(self):
        self.assertEqual(soft_dice(["TALVORA", "LOGISTICA"], ["TALVROA", "LOGISTICA"]), 1.0)
        self.assertEqual(soft_dice(["TALVORA"], ["BRENICA"]), 0.0)

    def test_one_typo_counts_as_same_token(self):
        # Jaro-Winkler alone gives 0.895 here, below the 0.9 threshold.
        self.assertEqual(soft_dice(["AMLMIVET", "INSTALACIONES"], ["AMIMIVET", "INSTALACIONES"]), 1.0)
        self.assertEqual(soft_dice(["VENCA"], ["VERCA"]), 1.0)
        self.assertEqual(soft_dice(["SOL"], ["SAL"]), 0.0)  # too short to tell

    def test_edit_distance(self):
        self.assertEqual(edit_distance("TALVORA", "TALVROA"), 1)
        self.assertEqual(edit_distance("KITTEN", "SITTING"), 3)

    def test_word_order_does_not_matter(self):
        self.assertEqual(token_similarity(["TALVORA", "LOGISTICA"], ["LOGISTICA", "TALVORA"]), 1.0)


if __name__ == "__main__":
    unittest.main()
