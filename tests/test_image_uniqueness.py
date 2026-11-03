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

    def test_retail_shelf_and_supermarket_photos_are_rejected(self):
        self.assertTrue(recipe_worker._is_retail_product_image(
            "File: pasta products on supermarket shelves.jpg",
            "https://images.example.com/pasta-shelf.jpg",
            {"ImageDescription": {"value": "Rows of boxed pasta displayed in a grocery store aisle"}}
        ))
        self.assertTrue(recipe_worker._is_retail_product_image(
            "File: grocery store aisle.jpg",
            "https://images.example.com/aisle.jpg",
            {}
        ))

    def test_prepared_food_photographs_are_not_rejected_as_retail(self):
        self.assertFalse(recipe_worker._is_retail_product_image(
            "File: roasted vegetable pasta served in a bowl.jpg",
            "https://images.example.com/roasted-vegetable-pasta.jpg",
            {"ImageDescription": {"value": "Prepared roasted vegetable pasta on a ceramic plate"}}
        ))

    def test_featured_image_rejects_supermarket_shelf_photo(self):
        with self.assertRaisesRegex(RuntimeError, "grocery-store, retail-shelf"):
            recipe_worker.featured_image_for(
                {"title": "Easy Roasted Vegetable Pasta"},
                {
                    "url": "https://images.example.com/pasta-supermarket-shelf.jpg",
                    "altText": "Pasta products displayed on grocery store shelves"
                }
            )

    def test_catalogue_fallback_rejects_retail_shelf_photo(self):
        with tempfile.TemporaryDirectory() as directory:
            catalogue_path = Path(directory) / "recipes.json"
            catalogue_path.write_text(json.dumps([
                {"slug": "today", "image_url": "https://images.example.com/pasta-shelf.jpg",
                 "image_alt": "Pasta products on supermarket shelves"}
            ]), encoding="utf-8")
            with patch.object(recipe_worker, "RECIPES_PATH", catalogue_path):
                result = recipe_worker.catalogue_image_fallback(
                    {"slug": "today", "title": "Easy Roasted Vegetable Pasta",
                     "image_url": "https://images.example.com/pasta-shelf.jpg",
                     "image_alt": "Pasta products on supermarket shelves"},
                    [],
                )
        self.assertIsNone(result)

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




    def test_retail_display_is_rejected_from_structured_commons_metadata(self):
        self.assertTrue(recipe_worker._is_retail_product_image(
            "File: pasta display.jpg",
            "https://upload.wikimedia.org/wikipedia/commons/pasta-display.jpg",
            {
                "ObjectName": {"value": "Pasta products"},
                "Categories": {"value": "Supermarkets; Grocery store interiors; Retail displays"},
                "ImageDescription": {"value": "Packaged pasta arranged for sale"},
            },
        ))

    def test_prepared_pasta_photo_with_packaging_word_in_unrelated_metadata_is_not_used(self):
        self.assertFalse(recipe_worker._is_retail_product_image(
            "File: roasted vegetable pasta bowl.jpg",
            "https://images.example.com/roasted-vegetable-pasta-bowl.jpg",
            {"ImageDescription": {"value": "Cooked roasted vegetable pasta served in a bowl"}},
        ))


if __name__ == "__main__":
    unittest.main()
