import unittest

from app.config.aliases import is_overlay_name, resolve_catalog_name
from app.pipeline.brands import brands_from_names, generate_aliases, match_brand_ids
from app.pipeline.ocr import OcrHit
from tests.test_brands import _catalog


class AliasTableTests(unittest.TestCase):
    def test_playlist_spellings_resolve_to_catalog(self) -> None:
        self.assertEqual(resolve_catalog_name("CAMERO"), "CAMARA DE COMERCIO")
        self.assertEqual(resolve_catalog_name("GAMERO"), "CAMARA DE COMERCIO")
        self.assertEqual(resolve_catalog_name("NETT.plus"), "NETPLUS")
        self.assertEqual(resolve_catalog_name("GRAND VICTORIA"), "HOTEL VICTORIA")
        self.assertEqual(resolve_catalog_name("COBLERED"), "CABLE RED")

    def test_generate_aliases_includes_table(self) -> None:
        aliases = set(generate_aliases("CAMARA DE COMERCIO"))
        self.assertIn("CAMERO", aliases)
        self.assertIn("GAMERO", aliases)

    def test_brands_from_names_dedupes_aliases(self) -> None:
        brands = brands_from_names(["CAMERO", "CAMARA DE COMERCIO", "ZAPPING"])
        names = [brand.name for brand in brands]
        self.assertEqual(names, ["CAMARA DE COMERCIO"])
        self.assertNotIn("ZAPPING", names)

    def test_tv_overlays_are_not_counted(self) -> None:
        catalog = _catalog()
        hits = match_brand_ids(
            "ZAPPING SHOWTIME xtrim",
            catalog,
            [
                OcrHit(text="ZAPPING", x_center=0.2),
                OcrHit(text="SHOWTIME", x_center=0.8),
            ],
        )
        self.assertEqual(hits, set())


if __name__ == "__main__":
    unittest.main()
