import unittest

from app.pipeline.brands import (
    generate_aliases,
    match_brand_ids,
    norm,
    prepare_brands,
)
from app.schemas import BrandInput


def _catalog() -> list:
    return prepare_brands(
        [
            BrandInput(id="nettplus", name="NETT plus"),
            BrandInput(id="lions", name="Lions Sports & Media"),
        ]
    )


class BrandNormTests(unittest.TestCase):
    def test_norm_rewrites_plus_and_ampersand(self):
        self.assertEqual(norm("NETT plus"), "NETT PLUS")
        self.assertEqual(norm("Lions Sports & Media"), "LIONS SPORTS AND MEDIA")
        self.assertEqual(norm("nett+"), "NETT PLUS")

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


class BrandMatchTests(unittest.TestCase):
    def test_nettplus_on_led_text(self):
        hits = match_brand_ids("NETT plus NETT plus NETT plus", _catalog())
        self.assertEqual(hits, {"nettplus"})

    def test_lions_does_not_count_as_nettplus(self):
        hits = match_brand_ids("LIONS SPORTS AND MEDIA", _catalog())
        self.assertEqual(hits, {"lions"})
        self.assertNotIn("nettplus", hits)

    def test_lions_alias_variants(self):
        for raw in (
            "LIONS SPORTS & MEDIA",
            "LIONS SPORT AND MEDIA",
            "LIONS SPORTS MEDIA",
        ):
            hits = match_brand_ids(raw, _catalog())
            self.assertEqual(hits, {"lions"}, raw)

    def test_ocr_noise_still_matches_nettplus(self):
        hits = match_brand_ids("NETT PLU5", _catalog())
        self.assertIn("nettplus", hits)

    def test_empty_ocr_matches_nothing(self):
        self.assertEqual(match_brand_ids("", _catalog()), set())


if __name__ == "__main__":
    unittest.main()
