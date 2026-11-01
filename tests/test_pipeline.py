import random
import tempfile
import unittest
from pathlib import Path

from say_my_name import taxid
from say_my_name.evaluate import bcubed, evaluate, pairwise
from say_my_name.generator import _new_brand, generate, write_dataset
from say_my_name.matcher import match


class GeneratorTest(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(generate(3, 50), generate(3, 50))

    def test_enough_brand_names_for_large_runs(self):
        # v0.1 had ~3,100 combinations and hung forever above ~3,000 companies.
        rng, used = random.Random(1), set()
        for _ in range(15000):
            _new_brand(rng, used)
        self.assertEqual(len(used), 15000)

    def test_fields_and_truth(self):
        records, truth = generate(3, 200)
        self.assertEqual(len(records), len(truth))
        self.assertEqual(len({r["RECORD_ID"] for r in records}), len(records))
        for r, t in zip(records, truth):
            self.assertEqual(r["RECORD_ID"], t["RECORD_ID"])
            for field in ("NAME1", "NAME2", "STRAS", "ORT01"):
                self.assertLessEqual(len(r[field]), 35, (field, r[field]))
            if "tax_copy_error" in t["OPS"]:
                continue
            if r["STCD1"] and "tax_typo" not in t["OPS"]:
                self.assertTrue(taxid.is_valid(taxid.normalize(r["STCD1"])), r)
            if "tax_typo" in t["OPS"]:
                self.assertFalse(taxid.is_valid(taxid.normalize(r["STCD1"])), r)


class MetricsTest(unittest.TestCase):
    def test_perfect_and_split(self):
        truth = {"a": "1", "b": "1", "c": "2"}
        self.assertEqual(pairwise(truth, truth)["f1"], 1.0)
        split = {"a": "x", "b": "y", "c": "z"}
        self.assertEqual(pairwise(split, truth)["recall"], 0.0)
        self.assertAlmostEqual(bcubed(split, truth)["recall"], (0.5 + 0.5 + 1) / 3)


class PipelineTest(unittest.TestCase):
    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            records, truth = write_dataset(Path(tmp) / "data", seed=5, n_entities=150)
            out = Path(tmp) / "out"
            match(records, out)
            metrics = evaluate(records, truth, out)
            self.assertTrue((out / "report.md").exists())
            baseline = metrics["scenarios"]["baseline: AUTO only"]["pairwise"]
            self.assertGreater(baseline["precision"], 0.9)
            self.assertGreater(baseline["recall"], 0.8)


if __name__ == "__main__":
    unittest.main()
