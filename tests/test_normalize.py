import unittest

from say_my_name import normalize as nz


class NormalizeTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(nz.basic("Climatización Ñandú, S.L."), "CLIMATIZACION NANDU S L")
        self.assertEqual(nz.basic("Pº del Mar, nº 3"), "PO DEL MAR NO 3")

    def test_legal_forms(self):
        cases = {
            "TALVORA S L": "SL", "TALVORA SOCIEDAD LIMITADA": "SL", "TALVORA S L U": "SLU",
            "TALVORA S L UNIPERSONAL": "SLU", "TALVORA SOCIEDAD ANONIMA": "SA",
            "TALVORA S COOP": "SCOOP", "TALVORA S L L": "SLL", "TALVORA": "",
        }
        for name, form in cases.items():
            core, legal = nz.split_legal_form(name)
            self.assertEqual((core, legal), ("TALVORA", form), name)

    def test_name_with_legal_form_in_name2(self):
        tokens, legal = nz.parse_name("Dist. Talvora del Norte", "S.L.U.")
        self.assertEqual((tokens, legal), (["DISTRIBUCIONES", "TALVORA", "NORTE"], "SLU"))

    def test_rare_abbreviations(self):
        cases = {"CIAL": "COMERCIAL", "DTBCIONES": "DISTRIBUCIONES", "MAQRIA": "MAQUINARIA",
                 "HRMNOS": "HERMANOS", "TLLS": "TALLERES", "INGA": "INGENIERIA",
                 "CNES": "CNES",  # fits CONSTRUCCIONES and COMPONENTES: left alone
                 "TALVORA": "TALVORA", "COMERCIAL": "COMERCIAL"}
        for token, expected in cases.items():
            self.assertEqual(nz.expand_abbreviation(token), expected, token)

    def test_street_variants_agree(self):
        expected = (["MAYOR"], "12")
        for raw in ("Calle Mayor, 12", "C/ Mayor 12", "C/. Mayor, nº 12", "CL. MAYOR Nº 012"):
            self.assertEqual(nz.parse_street(raw), expected, raw)
        self.assertEqual(nz.parse_street("Pol. Ind. La Vega, nave 7"), (["VEGA"], "7"))
        self.assertEqual(nz.parse_street("P.I. La Vega, nave 7"), (["VEGA"], "7"))
        self.assertEqual(nz.parse_street("Avda. de la Paz, s/n"), (["PAZ"], "SN"))

    def test_city_aliases(self):
        self.assertEqual(nz.canonical_city("S/C de Tenerife"), "SANTA CRUZ DE TENERIFE")
        self.assertEqual(nz.canonical_city("La Laguna"), "SAN CRISTOBAL DE LA LAGUNA")
        self.assertEqual(nz.canonical_city("Torrelodones"), "TORRELODONES")

    def test_postcode(self):
        self.assertEqual(nz.normalize_postcode("8012"), "08012")
        self.assertEqual(nz.normalize_postcode("38-001"), "38001")
        self.assertEqual(nz.normalize_postcode(""), "")


if __name__ == "__main__":
    unittest.main()
