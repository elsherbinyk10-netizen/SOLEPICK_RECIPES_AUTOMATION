import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import recipe_worker


class RecipeLibraryTests(unittest.TestCase):
    def test_recipes_have_unique_slugs_and_required_fields(self):
        recipes = json.loads((ROOT / "recipes.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(recipes), 1)
        slugs = []
        for recipe in recipes:
            for key in ("slug", "title", "description", "ingredients", "instructions", "servings"):
                self.assertIn(key, recipe)
            self.assertTrue(recipe["ingredients"])
            self.assertTrue(recipe["instructions"])
            self.assertGreater(recipe["servings"], 0)
            slugs.append(recipe["slug"])
        self.assertEqual(len(slugs), len(set(slugs)))

    def test_cairo_seasonal_schedule_uses_correct_utc_cron(self):
        cairo = ZoneInfo("Africa/Cairo")
        summer = datetime(2026, 7, 1, 10, 0, tzinfo=cairo)
        winter = datetime(2026, 1, 15, 10, 0, tzinfo=cairo)
        self.assertEqual(recipe_worker.expected_schedule_cron(summer), "0 7 * * *")
        self.assertEqual(recipe_worker.expected_schedule_cron(winter), "0 8 * * *")

    def test_schedule_accepts_seasonal_primary_and_same_day_recovery(self):
        cairo = ZoneInfo("Africa/Cairo")
        summer_primary = datetime(2026, 7, 1, 10, 0, tzinfo=cairo)
        summer_recovery = datetime(2026, 7, 1, 11, 0, tzinfo=cairo)
        winter_primary = datetime(2026, 1, 15, 10, 0, tzinfo=cairo)
        winter_recovery = datetime(2026, 1, 15, 11, 0, tzinfo=cairo)
        before_publish_window = datetime(2026, 1, 15, 9, 0, tzinfo=cairo)
        self.assertTrue(recipe_worker.should_run_scheduled_event("0 7 * * *", summer_primary))
        self.assertTrue(recipe_worker.should_run_scheduled_event("0 8 * * *", winter_primary))
        self.assertTrue(recipe_worker.should_run_scheduled_event("0 8 * * *", summer_recovery))
        self.assertTrue(recipe_worker.should_run_scheduled_event("0 9 * * *", winter_recovery))
        self.assertFalse(recipe_worker.should_run_scheduled_event("0 7 * * *", before_publish_window))

    def test_daily_guard_blocks_second_publication(self):
        cairo = ZoneInfo("Africa/Cairo")
        now = datetime(2026, 10, 14, 10, 0, tzinfo=cairo)
        same_day = {"publishedAt": "2026-10-14T07:05:00Z", "isPublished": True, "handle": "already-published"}
        other_day = {"publishedAt": "2026-10-13T07:05:00Z", "isPublished": True, "handle": "yesterday"}
        self.assertEqual(recipe_worker.already_published_today({"one": same_day}, now), same_day)
        self.assertIsNone(recipe_worker.already_published_today({"one": other_day}, now))

    def test_daily_guard_ignores_unrelated_same_day_blog_articles(self):
        cairo = ZoneInfo("Africa/Cairo")
        now = datetime(2026, 10, 31, 10, 0, tzinfo=cairo)
        unrelated = {
            "publishedAt": "2026-10-31T07:05:00Z",
            "isPublished": True,
            "handle": "fast-mediterranean-inspired-recipes",
        }
        self.assertIsNone(
            recipe_worker.already_published_today(
                {"unrelated": unrelated},
                now,
                recipe_slugs={"one-pan-lemon-herb-chicken", "crispy-black-bean-tacos"},
            )
        )

    def test_daily_guard_still_blocks_a_published_recipe_from_today(self):
        cairo = ZoneInfo("Africa/Cairo")
        now = datetime(2026, 10, 31, 10, 0, tzinfo=cairo)
        recipe_article = {
            "publishedAt": "2026-10-31T07:05:00Z",
            "isPublished": True,
            "handle": "crispy-black-bean-tacos",
        }
        self.assertEqual(
            recipe_worker.already_published_today(
                {"recipe": recipe_article},
                now,
                recipe_slugs={"crispy-black-bean-tacos"},
            ),
            recipe_article,
        )

    def test_daily_guard_ignores_unrelated_same_day_blog_articles(self):
        cairo = ZoneInfo("Africa/Cairo")
        now = datetime(2026, 10, 31, 10, 0, tzinfo=cairo)
        unrelated = {
            "publishedAt": "2026-10-31T07:05:00Z",
            "isPublished": True,
            "handle": "fast-mediterranean-inspired-recipes",
        }
        self.assertIsNone(
            recipe_worker.already_published_today(
                {"unrelated": unrelated},
                now,
                recipe_slugs={"one-pan-lemon-herb-chicken", "crispy-black-bean-tacos"},
            )
        )

    def test_daily_guard_still_blocks_a_published_recipe_from_today(self):
        cairo = ZoneInfo("Africa/Cairo")
        now = datetime(2026, 10, 31, 10, 0, tzinfo=cairo)
        recipe_article = {
            "publishedAt": "2026-10-31T07:05:00Z",
            "isPublished": True,
            "handle": "crispy-black-bean-tacos",
        }
        self.assertEqual(
            recipe_worker.already_published_today(
                {"recipe": recipe_article},
                now,
                recipe_slugs={"crispy-black-bean-tacos"},
            ),
            recipe_article,
        )

    def test_white_bean_loaded_salad_has_specific_no_cook_steps(self):
        recipes = json.loads((ROOT / "recipes.json").read_text(encoding="utf-8"))
        recipe = next(item for item in recipes if item["slug"] == "mediterranean-white-bean-loaded-salad")
        self.assertEqual(recipe["cook_minutes"], 0)
        self.assertEqual(len(recipe["instructions"]), 5)
        text = " ".join(recipe["instructions"]).lower()
        for placeholder in ("main ingredient", "if it requires cooking", "flavorings", "cook until ready"):
            self.assertNotIn(placeholder, text)
        self.assertIn("cannellini beans", text)
        self.assertIn("lemon", text)

    def test_video_match_rejects_unrelated_titles(self):
        self.assertLess(recipe_worker._video_title_score("Creamy Tomato Spinach Pasta", "How to make chocolate cake"), 0.45)
        self.assertGreaterEqual(recipe_worker._video_title_score("Honey Garlic Salmon Bowls", "Honey Garlic Salmon Bowl Recipe"), 0.45)

    def test_video_compatibility_rejects_wrong_protein_even_if_keywords_overlap(self):
        recipe = {"title": "Honey Mustard Salmon Warm Grain Salad"}
        self.assertFalse(recipe_worker._video_title_is_compatible(
            recipe, "Honey Mustard Chicken, Avocado and Bacon Salad"
        ))
        self.assertTrue(recipe_worker._video_title_is_compatible(
            recipe, "Warm Grain Salad with Lemon Dijon Vinaigrette, Salmon and Crispy Chickpeas"
        ))
        self.assertFalse(recipe_worker._video_title_is_compatible(
            recipe, "Warm Grain Salad with Lemon Dijon Vinaigrette, Chicken and Crispy Chickpeas"
        ))

    def test_video_format_aliases_allow_equivalent_wording(self):
        recipe = {"title": "Honey Mustard Salmon Stuffed Sweet Potatoes"}
        self.assertTrue(recipe_worker._video_title_is_compatible(
            recipe, "Honey Mustard Salmon Stuffed Sweet Potato Recipe"
        ))

    def test_video_title_score_supports_partial_but_relevant_titles(self):
        self.assertGreaterEqual(
            recipe_worker._video_title_score(
                "Honey Mustard Salmon Stuffed Sweet Potatoes",
                "Honey Mustard Salmon Sweet Potato Recipe"
            ),
            0.45
        )

    def test_video_compatibility_requires_named_dish_format(self):
        self.assertFalse(recipe_worker._video_title_is_compatible(
            {"title": "Creamy Tomato Spinach Pasta"}, "Creamy Tomato Spinach Soup Recipe"
        ))
        self.assertTrue(recipe_worker._video_title_is_compatible(
            {"title": "Creamy Tomato Spinach Pasta"}, "Creamy Tomato Spinach Pasta Recipe"
        ))


    def test_video_match_rejects_wrong_starch_and_dish_format(self):
        recipe = {"title": "Honey Mustard Salmon Stuffed Sweet Potatoes"}
        self.assertFalse(recipe_worker._video_title_is_compatible(
            recipe, "Browned Butter Honey Garlic Salmon Recipe"
        ))
        self.assertFalse(recipe_worker._video_title_is_compatible(
            recipe, "Honey Mustard Salmon Pasta"
        ))
        self.assertTrue(recipe_worker._video_title_is_compatible(
            recipe, "Honey Mustard Salmon Stuffed Sweet Potatoes Recipe"
        ))

    def test_recipe_specificity_replaces_generic_instruction_placeholders(self):
        recipe = {
            "title": "Honey Mustard Salmon Stuffed Sweet Potatoes",
            "ingredients": [
                "4 salmon fillets", "1 teaspoon Dijon mustard", "1 teaspoon honey",
                "4 sweet potatoes", "1 avocado", "2 tablespoons yogurt"
            ],
            "instructions": [
                "Bake sweet potatoes until tender.",
                "Cook the main ingredient in a skillet with flavorings and oil.",
                "Split sweet potatoes and fluff centers.",
                "Fill with the cooked mixture and top with avocado and yogurt."
            ]
        }
        improved = recipe_worker.make_recipe_specific(recipe)
        joined = " ".join(improved["instructions"]).lower()
        self.assertIn("salmon", joined)
        self.assertIn("mustard", joined)
        self.assertNotIn("main ingredient", joined)
        self.assertNotIn("flavorings", joined)

    def test_featured_image_uses_verified_generated_recipe_photo(self):
        recipe = {"title": "Sample Salmon Pasta"}
        generated_image = {
            "url": "https://cdn.example.com/generated-salmon-pasta.jpg",
            "altText": "Creamy salmon pasta with parsley, photographed on a plate",
        }
        image = recipe_worker.featured_image_for(recipe, generated_image)
        self.assertEqual(image["url"], generated_image["url"])
        self.assertEqual(image["altText"], generated_image["altText"])

    def test_featured_image_rejects_unverified_recipe_fallback(self):
        recipe = {
            "title": "Sample Dish",
            "image_url": "https://images.example.com/sample-dish.jpg",
            "image_alt": "Sample dish on a plate",
        }
        # An image URL in recipe data is not proof that the photo matches the dish.
        # Keep the publisher's no-mismatched-image safeguard in place.
        with self.assertRaisesRegex(RuntimeError, "Refusing to publish a mismatched fallback photo"):
            recipe_worker.featured_image_for(recipe, None)
        with self.assertRaises(RuntimeError):
            recipe_worker.featured_image_for({"title": "Sample Dish"}, None)

    def test_recipe_video_is_embedded_in_article_html(self):
        recipe = {
            "title": "Sample Pasta", "description": "A simple pasta.", "prep_minutes": 5,
            "cook_minutes": 10, "servings": 2, "ingredients": ["pasta"],
            "instructions": ["Cook pasta."],
        }
        video = {
            "title": "Sample Pasta Recipe", "url": "https://www.youtube.com/watch?v=abcdefghijk",
            "embed_url": "https://www.youtube-nocookie.com/embed/abcdefghijk",
        }
        html = recipe_worker.article_html(recipe, video)
        self.assertIn("Recipe Video", html)
        self.assertIn(video["embed_url"], html)
        self.assertIn(video["url"], html)


    def test_saved_article_verification_requires_embedded_iframe(self):
        recipe = {"title": "Sample Pasta"}
        video = {
            "title": "Sample Pasta Recipe",
            "url": "https://www.youtube.com/watch?v=abcdefghijk",
            "embed_url": "https://www.youtube-nocookie.com/embed/abcdefghijk",
        }
        article = {
            "isPublished": True,
            "body": (
                "<h2>Watch the Recipe Video Here</h2>"
                "<div><iframe src=\"https://www.youtube-nocookie.com/embed/abcdefghijk?playsinline=1\"></iframe></div>"
                "<h2>Ingredients</h2><ul><li>pasta</li></ul>"
                "<h2>Instructions</h2><ol><li>Cook pasta.</li></ol>"
                '<script type="application/ld+json">{"@type": "Recipe"}</script>'
            ),
        }
        self.assertIs(recipe_worker.verify_published_article(article, recipe, video), article)
        article["body"] = "<p>Watch on YouTube</p><h2>Ingredients</h2><h2>Instructions</h2>"
        with self.assertRaisesRegex(RuntimeError, "did not return an iframe"):
            recipe_worker.verify_published_article(article, recipe, video)

    def test_repair_upserts_video_and_preserves_other_article_content(self):
        original = (
            "<p>Original recipe introduction.</p>"
            "<h2>Ingredients</h2><ul><li>shrimp</li></ul>"
            "<h2>Instructions</h2><ol><li>Cook shrimp.</li></ol>"
        )
        recipe = {"title": "Cajun Shrimp Tacos", "description": "Tacos."}
        first_video = {
            "title": "Cajun Shrimp Tacos Recipe", "url": "https://www.youtube.com/watch?v=abcdefghijk",
            "embed_url": "https://www.youtube-nocookie.com/embed/abcdefghijk",
        }
        updated = recipe_worker.upsert_recipe_video_section(original, recipe, first_video)
        self.assertIn("Original recipe introduction.", updated)
        self.assertIn("<h2>Ingredients</h2>", updated)
        self.assertIn(first_video["embed_url"], updated)
        second_video = {
            "title": "Cajun Shrimp Tacos Cook Along", "url": "https://www.youtube.com/watch?v=lmnopqrstuv",
            "embed_url": "https://www.youtube-nocookie.com/embed/lmnopqrstuv",
        }
        repaired_again = recipe_worker.upsert_recipe_video_section(updated, recipe, second_video)
        self.assertIn(second_video["embed_url"], repaired_again)
        self.assertNotIn(first_video["embed_url"], repaired_again)
        self.assertEqual(repaired_again.count("<h2>Watch the Recipe Video Here</h2>"), 1)
        self.assertNotIn("<h2>Recipe Video</h2>", repaired_again)
        self.assertIn("<iframe", repaired_again)
        self.assertIn("<h2>Instructions</h2>", repaired_again)

    def test_catalogue_image_fallback_requires_relevant_alt_text(self):
        relevant = {
            "title": "Creamy Tomato Spinach Pasta",
            "image_url": "https://images.example.com/pasta.jpg",
            "image_alt": "Pasta with sauce and fresh herbs",
        }
        fallback = recipe_worker.catalogue_image_fallback(relevant)
        self.assertEqual(fallback["url"], relevant["image_url"])
        self.assertTrue(fallback["altText"])

        unrelated = {
            "title": "Honey Garlic Salmon Bowls",
            "image_url": "https://images.example.com/salad.jpg",
            "image_alt": "Fresh colorful salad with vegetables and greens",
        }
        self.assertIsNone(recipe_worker.catalogue_image_fallback(unrelated))


    def test_recipe_seo_metadata_is_concise_and_uses_recipe_intent(self):
        recipe = {"title": "Creamy Tomato Spinach Pasta", "description": "A quick creamy tomato spinach pasta for a satisfying weeknight dinner."}
        meta = recipe_worker.seo_metadata(recipe)
        self.assertLessEqual(len(meta["title"]), 60)
        self.assertLessEqual(len(meta["description"]), 155)
        self.assertIn("pasta", meta["title"].lower())
        self.assertGreaterEqual(len(meta["description"]), 90)
        spaced = recipe_worker.seo_metadata({"title": "  Creamy   Tomato Pasta  ", "description": "  A useful   pasta recipe description for a weeknight meal.  "})
        self.assertEqual(spaced["title"], "Creamy Tomato Pasta")
        self.assertNotIn("  ", spaced["description"])

    def test_recipe_json_ld_has_required_recipe_fields_and_verified_image(self):
        recipe = {
            "title": "Creamy Tomato Spinach Pasta",
            "description": "A creamy pasta dinner.",
            "prep_minutes": 10, "cook_minutes": 20, "servings": 4,
            "tags": ["pasta", "dinner"],
            "ingredients": ["300 g pasta", "tomatoes"],
            "instructions": ["Boil pasta.", "Make sauce."],
            "published_image_url": "https://cdn.example.com/verified-pasta.jpg",
        }
        markup = recipe_worker.recipe_json_ld(recipe)
        payload = json.loads(markup.split(">", 1)[1].rsplit("</script>", 1)[0])
        self.assertEqual(payload["@type"], "Recipe")
        self.assertEqual(payload["image"], ["https://cdn.example.com/verified-pasta.jpg"])
        self.assertEqual(payload["prepTime"], "PT10M")
        self.assertEqual(payload["cookTime"], "PT20M")
        self.assertEqual(payload["totalTime"], "PT30M")
        self.assertEqual(len(payload["recipeInstructions"]), 2)

    def test_recipe_article_has_contextual_internal_links_and_json_ld(self):
        recipe = {
            "slug": "sample-pasta", "title": "Sample Pasta", "description": "A simple pasta dinner.",
            "prep_minutes": 5, "cook_minutes": 10, "servings": 2,
            "tags": ["pasta", "dinner"], "ingredients": ["pasta"],
            "instructions": ["Cook pasta."],
        }
        catalogue = json.loads((ROOT / "recipes.json").read_text(encoding="utf-8"))
        related = next(
            item for item in catalogue
            if item["slug"] != recipe["slug"] and set(item.get("tags", [])) & {"pasta", "dinner"}
        )
        markup = recipe_worker.article_html(recipe, published_handles={related["slug"]})
        self.assertIn("https://solepick.site/blogs/recipes/" + related["slug"], markup)
        self.assertIn('type="application/ld+json"', markup)
        self.assertIn("More Recipes to Try", markup)
        no_links = recipe_worker.article_html(recipe, published_handles=set())
        self.assertNotIn("More Recipes to Try", no_links)



if __name__ == "__main__":
    unittest.main()
