import unittest
from unittest.mock import patch
from image_quality import is_high_quality_image


class ImageQualityTests(unittest.TestCase):
    def test_accepts_verified_large_sharp_photo(self):
        self.assertTrue(is_high_quality_image({"ok": True, "width": 1600, "height": 1067, "edge_variance": 42}))

    def test_rejects_small_photo(self):
        self.assertFalse(is_high_quality_image({"ok": True, "width": 900, "height": 600, "edge_variance": 42}))

    def test_rejects_soft_photo(self):
        self.assertFalse(is_high_quality_image({"ok": True, "width": 1600, "height": 1067, "edge_variance": 5}))

    def test_rejects_failed_download(self):
        self.assertFalse(is_high_quality_image({"ok": False, "reason": "download failed"}))


if __name__ == "__main__":
    unittest.main()
