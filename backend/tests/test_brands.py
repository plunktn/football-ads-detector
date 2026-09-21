import unittest

from app.pipeline.brands import (
    generate_aliases,
    match_brand_ids,
    norm,
    prepare_brands,
)
from app.pipeline.ocr import OcrHit
from app.schemas import BrandInput


def _catalog() -> list:
    return prepare_brands(
        [
            BrandInput(id="nettplus", name="NETT plus"),
            BrandInput(id="lions", name="Lions Sports & Media"),
            BrandInput(id="ecuabet", name="ECUABET"),
        ]
    )


class BrandNormTests(unittest.TestCase):
    def test_norm_rewrites_plus_and_ampersand(self):
        self.assertEqual(norm("NETT plus"), "NETT PLUS")
        self.assertEqual(norm("Lions Sports & Media"), "LIONS SPORTS AND MEDIA")
        self.assertEqual(norm("nett+"), "NETT PLUS")

    def test_phone_plus_does_not_become_brand_plus(self):
        self.assertEqual(norm("+593 96 7"), "593 96 7")
        self.assertNotIn("PLUS", norm("+593967 LioaEcuabet +593567"))

    def test_strong_aliases_for_canonical_brands(self):
        nett = set(generate_aliases("NETT plus"))
        self.assertTrue({"NETT PLUS", "NETTPLUS", "NETPLUS", "NET PLUS"} <= nett)

        lions = set(generate_aliases("Lions Sports & Media"))
        self.assertTrue(
            {
                "LIONS SPORTS AND MEDIA",
                "LIONS SPORT AND MEDIA",
                "LIONS SPORTS MEDIA",
            }
            <= lions
        )
        ecuabet = set(generate_aliases("ECUABET"))
        self.assertIn("ECUABET", ecuabet)
        self.assertNotIn("LIGAECUABET", ecuabet)
        self.assertNotIn("LIGA ECUABET", ecuabet)


class BrandMatchTests(unittest.TestCase):
    def test_nettplus_on_led_text(self):
        hits = match_brand_ids("NETT plus NETT plus NETT plus", _catalog())
        self.assertEqual(hits, {"nettplus"})

    def test_single_nettplus_is_not_enough(self):
        self.assertNotIn("nettplus", match_brand_ids("NETT plus", _catalog()))

    def test_lions_does_not_count_as_nettplus(self):
        raw = "LIONS SPORTS AND MEDIA LIONS SPORTS AND MEDIA"
        hits = match_brand_ids(raw, _catalog())
        self.assertEqual(hits, {"lions"})
        self.assertNotIn("nettplus", hits)

    def test_phone_numbers_do_not_match_nettplus(self):
        hits = match_brand_ids(
            "+593967 LioaEcuabet A 693967 +593567 LivaEcuabet +59396 7",
            _catalog(),
        )
        self.assertNotIn("nettplus", hits)

    def test_lions_alias_variants(self):
        for raw in (
            "LIONS SPORTS & MEDIA",
            "LIONS SPORT AND MEDIA",
            "LIONS SPORTS MEDIA",
        ):
            hits = match_brand_ids(f"{raw} {raw}", _catalog())
            self.assertEqual(hits, {"lions"}, raw)

    def test_ocr_noise_still_matches_nettplus(self):
        hits = match_brand_ids("NETT PLU5 NETT PLU5", _catalog())
        self.assertIn("nettplus", hits)

    def test_empty_ocr_matches_nothing(self):
        self.assertEqual(match_brand_ids("", _catalog()), set())

    def test_repeated_ecuabet_on_led_matches(self):
        hits = match_brand_ids("ECUABET ECUABET ECUABET", _catalog())
        self.assertEqual(hits, {"ecuabet"})

    def test_single_ligaecuabet_does_not_match(self):
        self.assertNotIn("ecuabet", match_brand_ids("LigaEcuabet", _catalog()))

    def test_other_led_plus_one_ligaecuabet_does_not_match(self):
        hits = match_brand_ids("UTPL POSGRADO LigaEcuabet UTPL", _catalog())
        self.assertNotIn("ecuabet", hits)

    def test_led_ecuabet_plus_fixed_insert_still_matches(self):
        hits = match_brand_ids("ECUABET LigaEcuabet ECUABET", _catalog())
        self.assertIn("ecuabet", hits)

    def test_spatial_boxes_require_two_separated_panels(self):
        brands = _catalog()
        one = [OcrHit(text="ECUABET", x_center=0.50)]
        self.assertNotIn("ecuabet", match_brand_ids("ECUABET", brands, one))
        two = [
            OcrHit(text="ECUABET", x_center=0.20),
            OcrHit(text="ECUABET", x_center=0.70),
        ]
        self.assertIn("ecuabet", match_brand_ids("ECUABET ECUABET", brands, two))

    def test_cyan_led_ocr_garble_counts_repeated_nettplus(self):
        """Real crop at 00:08:33: RapidOCR reads PLUS as OIUS/OLUS on two panels."""
        raw = "E NETT OIUS 1E NETT OluS DENTROY FUERA DECA"
        hits = [
            OcrHit(text="E", x_center=0.502),
            OcrHit(text="NETT OIUS", x_center=0.757),
            OcrHit(text="1E", x_center=0.183),
            OcrHit(text="NETT OluS", x_center=0.318),
            OcrHit(text="DENTROY", x_center=0.581),
            OcrHit(text="FUERA DECA", x_center=0.587),
        ]
        self.assertIn("nettplus", match_brand_ids(raw, _catalog(), hits))

    def test_single_garbled_nettplus_is_not_enough(self):
        self.assertNotIn("nettplus", match_brand_ids("NETT OIUS", _catalog()))

    def test_nettplus_glued_to_gratis_still_repeats(self):
        self.assertIn(
            "nettplus",
            match_brand_ids("NETTOIUGRATIS NETTPIUS GRATIS", _catalog()),
        )

    def test_ecuebet_typo_id_matches_ecuabet_ocr(self):
        brands = prepare_brands(
            [
                BrandInput(
                    id="ecuebet",
                    name="Ecuabet",
                    aliases=["ECUEBET", "ECUABET"],
                )
            ]
        )
        hits = match_brand_ids("ECUABET ECUABET", brands)
        self.assertEqual(hits, {"ecuebet"})

    def test_siete_and_1xbet_aliases(self):
        brands = prepare_brands(
            [
                BrandInput(id="siete-com", name="SIETE.COM", aliases=["SIETE"]),
                BrandInput(id="1xbet", name="1xbet", aliases=["1XBET"]),
                BrandInput(
                    id="grand-aviation",
                    name="GRAND AVIATION",
                    aliases=["GRANDAVIATION"],
                ),
            ]
        )
        self.assertEqual(
            match_brand_ids("SIETE.COM SIETE.COM", brands),
            {"siete-com"},
        )
        self.assertEqual(match_brand_ids("1XBET 1XBET", brands), {"1xbet"})
        self.assertEqual(
            match_brand_ids("GRAND AVIATION GRAND AVIATION", brands),
            {"grand-aviation"},
        )

    def test_generate_aliases_includes_ecuebet_typo(self):
        aliases = set(generate_aliases("Ecuebet"))
        self.assertIn("ECUABET", aliases)
        self.assertIn("ECUEBET", aliases)


if __name__ == "__main__":
    unittest.main()
