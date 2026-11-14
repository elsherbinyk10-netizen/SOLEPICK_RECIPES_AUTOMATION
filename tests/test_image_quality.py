import unittest
from unittest.mock import patch
from image_quality import is_high_quality_image
from recipe_worker import _photo_title_relevance


class ImageQualityTests(unittest.TestCase):
    def test_accepts_verified_large_sharp_photo(self):
        self.assertTrue(is_high_quality_image({"ok": True, "width": 1600, "height": 1067, "edge_variance": 42}))

    def test_rejects_small_photo(self):
        self.assertFalse(is_high_quality_image({"ok": True, "width": 900, "height": 600, "edge_variance": 42}))

    def test_rejects_soft_photo(self):
        self.assertFalse(is_high_quality_image({"ok": True, "width": 1600, "height": 1067, "edge_variance": 5}))

    def test_recognizes_couscous_as_a_dish_format(self):
        overlap, has_main, has_format = _photo_title_relevance(
            "Roasted Vegetable Chickpea Couscous",
            "Roasted chickpeas with couscous and vegetables"
        )
        self.assertTrue(has_main)
        self.assertTrue(has_format)

    def test_recognizes_orzo_as_pasta_format_without_assuming_chicken(self):
        overlap, has_main, has_format = _photo_title_relevance(
            "Lemony Orzo with Peas and Feta",
            "Lemony orzo pasta with peas and feta"
        )
        self.assertTrue(has_format)

    def test_rejects_failed_download(self):
        self.assertFalse(is_high_quality_image({"ok": False, "reason": "download failed"}))


if __name__ == "__main__":
    unittest.main()
