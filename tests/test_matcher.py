import unittest

from say_my_name.matcher import cluster, prepare, score_pair


def row(rid, name1, stras="Calle Mayor, 12", pstlz="38001", ort01="Santa Cruz de Tenerife",
        stcd1="", name2="", regio="38"):
    return {"RECORD_ID": rid, "NAME1": name1, "NAME2": name2, "STRAS": stras, "PSTLZ": pstlz,
            "ORT01": ort01, "REGIO": regio, "STCD1": stcd1, "STCEG": ""}


class MatcherTest(unittest.TestCase):
    def test_same_valid_tax_id_merges(self):
        a = prepare(row("a", "Distribuciones Talvora, S.L.", stcd1="B12345674"))
        b = prepare(row("b", "DIST. TALVORA SL", stcd1="ESB-12345674", stras="C/ Mayor 12"))
        self.assertEqual(score_pair(a, b).band, "AUTO")

    def test_different_valid_tax_ids_never_merge(self):
        a = prepare(row("a", "Distribuciones Talvora, S.L.", stcd1="B12345674"))
        b = prepare(row("b", "Distribuciones Talvora, S.L.", stcd1="B00000000"))
        self.assertTrue(b.cif)  # B00000000 has a valid check digit (0)
        self.assertEqual(score_pair(a, b).band, "NO")

    def test_invalid_tax_id_is_ignored(self):
        a = prepare(row("a", "Distribuciones Talvora, S.L.", stcd1="B12345675"))
        self.assertEqual(a.cif, "")

    def test_tax_id_one_typo_apart_merges(self):
        a = prepare(row("a", "Distribuciones Talvora, S.L.", stcd1="B12345674"))
        b = prepare(row("b", "DIST. TALVORA SL", stcd1="B12845674"))  # invalid: one digit changed
        self.assertEqual(b.bad_cif, "B12845674")
        result = score_pair(a, b)
        self.assertEqual((result.band, result.reason), ("AUTO", "tax ID one typo apart"))

    def test_same_tax_id_in_another_province_goes_to_review(self):
        a = prepare(row("a", "Distribuciones Talvora, S.L.", stcd1="B12345674"))
        b = prepare(row("b", "Distribuciones Talvora, S.L.", stcd1="B12345674", stras="Calle Real, 3",
                        pstlz="41001", ort01="Sevilla", regio="41"))
        self.assertEqual(score_pair(a, b).band, "REVIEW")

    def test_same_name_in_another_province_without_tax_id_goes_to_review(self):
        a = prepare(row("a", "Distribuciones Talvora, S.L.", stcd1="B12345674"))
        b = prepare(row("b", "DISTRIBUCIONES TALVORA SL", stras="Calle Real, 3",
                        pstlz="41001", ort01="Sevilla", regio="41"))
        result = score_pair(a, b)
        self.assertEqual((result.band, result.reason), ("REVIEW", "same name, another province"))

    def test_sibling_without_tax_id_goes_to_review(self):
        a = prepare(row("a", "Distribuciones Talvora del Norte, S.L."))
        b = prepare(row("b", "Distribuciones Talvora del Sur, S.L."))
        self.assertEqual(score_pair(a, b).band, "REVIEW")

    def test_cluster_refuses_two_tax_ids(self):
        recs = [prepare(row("a", "X", stcd1="B12345674")), prepare(row("b", "X")),
                prepare(row("c", "X", stcd1="B00000000"))]
        merges = [score_pair(recs[0], recs[1]), score_pair(recs[1], recs[2])]
        for m in merges:
            m.band, m.score = "AUTO", 1.0
        clusters, refused = cluster(recs, merges)
        self.assertEqual(refused, 1)
        self.assertNotEqual(clusters["a"], clusters["c"])


if __name__ == "__main__":
    unittest.main()
