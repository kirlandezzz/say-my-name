import random
import unittest

from say_my_name import taxid


class TaxIdTest(unittest.TestCase):
    def test_known_check_digit(self):
        # 1234567: doubled odd digits 2+6+(1+0)+(1+4)=14, even digits 2+4+6=12, total 26 -> 4
        self.assertEqual(taxid.control_value("1234567"), 4)
        self.assertTrue(taxid.is_valid("B12345674"))
        self.assertFalse(taxid.is_valid("B12345675"))

    def test_generated_ids_are_valid(self):
        rng = random.Random(1)
        for letter in "ABF":
            for _ in range(200):
                self.assertTrue(taxid.is_valid(taxid.make_cif(letter, rng)))

    def test_any_single_digit_change_is_detected(self):
        cif = "B12345674"
        for i in range(1, 8):
            for d in "0123456789":
                if d != cif[i]:
                    self.assertFalse(taxid.is_valid(cif[:i] + d + cif[i + 1:]))

    def test_normalize_formats(self):
        for raw in ("B-12345674", "b12345674", "ESB12345674", "B 1234567 4", "es b-1234567-4"):
            self.assertEqual(taxid.normalize(raw), "B12345674")

    def test_personal_nif_letters_rejected(self):
        self.assertFalse(taxid.is_valid("K12345674"))
        self.assertFalse(taxid.is_valid("12345678Z"))


if __name__ == "__main__":
    unittest.main()
