import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import recipe_worker


class ImageUniquenessTests(unittest.TestCase):
    def test_shopify_uuid_suffix_does_not_hide_same_original_image(self):
        original = "https://cdn.shopify.com/s/files/1/articles/photo-1551504734.jpg?v=1"
        copied = "https://cdn.shopify.com/s/files/1/articles/photo-1551504734_20434a4e-b7da-4a7d-ae7e-3d05cbb700ca.jpg?v=2"
        self.assertEqual(recipe_worker._image_identity(original), recipe_worker._image_identity(copied))

    def test_different_source_filenames_remain_distinct(self):
        self.assertNotEqual(
            recipe_worker._image_identity("https://cdn.shopify.com/articles/black-bean-salad.jpg"),
            recipe_worker._image_identity("https://cdn.shopify.com/articles/roasted-vegetable-tray.jpg"),
        )

    def test_catalogue_fallback_rejects_image_already_used_by_published_article(self):
        existing_image = "https://cdn.shopify.com/articles/photo-1551504734.jpg?v=1"
        copied_image = "https://cdn.shopify.com/articles/photo-1551504734_20434a4e-b7da-4a7d-ae7e-3d05cbb700ca.jpg?v=2"
        with tempfile.TemporaryDirectory() as directory:
            catalogue_path = Path(directory) / "recipes.json"
            catalogue_path.write_text(json.dumps([
                {"slug": "new-recipe", "image_url": copied_image, "image_alt": "black bean and corn roasted vegetable tray"},
                {"slug": "older-recipe", "image_url": "https://cdn.shopify.com/articles/different-photo.jpg", "image_alt": "different food"},
            ]), encoding="utf-8")
            with patch.object(recipe_worker, "RECIPES_PATH", catalogue_path):
                result = recipe_worker.catalogue_image_fallback(
                    {"slug": "new-recipe", "title": "Black Bean and Corn Roasted Vegetable Tray",
                     "image_url": copied_image, "image_alt": "black bean and corn roasted vegetable tray"},
                    [{"image": {"url": existing_image}}],
                )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
