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

    def test_daily_guard_blocks_second_publication(self):
        cairo = ZoneInfo("Africa/Cairo")
        now = datetime(2026, 10, 14, 10, 0, tzinfo=cairo)
        same_day = {"publishedAt": "2026-10-14T07:05:00Z", "isPublished": True, "handle": "already-published"}
        other_day = {"publishedAt": "2026-10-13T07:05:00Z", "isPublished": True, "handle": "yesterday"}
        self.assertEqual(recipe_worker.already_published_today({"one": same_day}, now), same_day)
        self.assertIsNone(recipe_worker.already_published_today({"one": other_day}, now))

    def test_video_match_rejects_unrelated_titles(self):
        self.assertLess(recipe_worker._video_title_score("Creamy Tomato Spinach Pasta", "How to make chocolate cake"), 0.45)
        self.assertGreaterEqual(recipe_worker._video_title_score("Honey Garlic Salmon Bowls", "Honey Garlic Salmon Bowl Recipe"), 0.45)

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


if __name__ == "__main__":
    unittest.main()
