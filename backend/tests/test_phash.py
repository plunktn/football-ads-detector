import unittest

import numpy as np

from app.pipeline.phash import dhash_hex, hamming_hex, order_by_similarity


class PhashTests(unittest.TestCase):
    def test_identical_images_same_hash(self) -> None:
        image = np.zeros((40, 200, 3), dtype=np.uint8)
        image[:, 20:80] = (255, 255, 255)
        self.assertEqual(dhash_hex(image), dhash_hex(image.copy()))

    def test_different_images_far_hash(self) -> None:
        a = np.zeros((40, 200, 3), dtype=np.uint8)
        a[:, :100] = 255
        b = np.zeros((40, 200, 3), dtype=np.uint8)
        b[:, 100:] = 255
        self.assertGreater(hamming_hex(dhash_hex(a), dhash_hex(b)), 5)

    def test_order_groups_similar_together(self) -> None:
        base = np.zeros((32, 160, 3), dtype=np.uint8)
        base[:, 40:90] = (0, 0, 255)
        near = base.copy()
        near[0:2, 0:2] = 10
        far = np.full((32, 160, 3), 200, dtype=np.uint8)
        items = [
            {"id": 1, "visual_hash": dhash_hex(base)},
            {"id": 2, "visual_hash": dhash_hex(far)},
            {"id": 3, "visual_hash": dhash_hex(near)},
        ]
        ordered = order_by_similarity(items, max_distance=10)
        ids = [item["id"] for item in ordered]
        self.assertEqual(ids[0], 1)
        self.assertEqual(ids[1], 3)
        self.assertEqual(ids[2], 2)
        self.assertEqual(ordered[0]["similarity_group"], ordered[1]["similarity_group"])
        self.assertNotEqual(ordered[0]["similarity_group"], ordered[2]["similarity_group"])


if __name__ == "__main__":
    unittest.main()
