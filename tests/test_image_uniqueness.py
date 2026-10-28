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


    def test_catalogue_fallback_rejects_archived_document_image(self):
        with tempfile.TemporaryDirectory() as directory:
            catalogue_path = Path(directory) / "recipes.json"
            catalogue_path.write_text(json.dumps([
                {"slug": "today", "image_url": "https://cdn.shopify.com/articles/page1.pdf.jpg",
                 "image_alt": "Historic archived document PDF page"}
            ]), encoding="utf-8")
            with patch.object(recipe_worker, "RECIPES_PATH", catalogue_path):
                result = recipe_worker.catalogue_image_fallback(
                    {"slug": "today", "title": "Turkey and Herb Breakfast Hash",
                     "image_url": "https://cdn.shopify.com/articles/page1.pdf.jpg",
                     "image_alt": "Historic archived document PDF page"},
                    [],
                )
        self.assertIsNone(result)

    def test_featured_image_rejects_pdf_thumbnail_even_if_named_as_food(self):
        with self.assertRaisesRegex(RuntimeError, "document/PDF-style image"):
            recipe_worker.featured_image_for(
                {"title": "Turkey and Herb Breakfast Hash"},
                {"url": "https://cdn.shopify.com/articles/page1.pdf.jpg",
                 "altText": "Turkey breakfast hash"},
            )

    def test_document_like_image_rejects_pdf_thumbnail_even_when_jpeg(self):
        self.assertTrue(recipe_worker._is_document_like_image(
            "File: scanned_recipe.pdf.jpg",
            "https://upload.wikimedia.org/wikipedia/commons/scanned_recipe.pdf.jpg",
            {},
        ))

    def test_document_like_image_rejects_scan_from_metadata_without_pdf_url(self):
        self.assertTrue(recipe_worker._is_document_like_image(
            "File: old archive scan.jpg",
            "https://upload.wikimedia.org/wikipedia/commons/food-photo.jpg",
            {"ImageDescription": {"value": "Scanned page from a historical archive"}},
        ))

    def test_document_like_image_allows_food_photo_with_clean_metadata(self):
        self.assertFalse(recipe_worker._is_document_like_image(
            "File: turkey breakfast hash.jpg",
            "https://upload.wikimedia.org/wikipedia/commons/turkey-hash.jpg",
            {"ImageDescription": {"value": "Turkey and vegetable breakfast hash served on a plate"}},
        ))

    def test_featured_image_rejects_archived_document_alt_text(self):
        with self.assertRaisesRegex(RuntimeError, "document/PDF-style image"):
            recipe_worker.featured_image_for(
                {"title": "Turkey and Herb Breakfast Hash"},
                {"url": "https://cdn.shopify.com/articles/food.jpg",
                 "altText": "Historic archived document"},
            )




if __name__ == "__main__":
    unittest.main()
