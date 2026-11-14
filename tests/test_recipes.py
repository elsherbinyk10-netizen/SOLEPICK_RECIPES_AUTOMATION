import json
import sys
import unittest
from unittest.mock import patch
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import recipe_worker


class RecipeLibraryTests(unittest.TestCase):
    def test_openverse_anonymous_search_uses_supported_page_size(self):
        import io
        import urllib.parse
        responses = [io.BytesIO(b'{"results": []}')]
        with patch("recipe_worker.urllib.request.urlopen", side_effect=responses) as mocked:
            result = recipe_worker.search_openverse_recipe_image(
                {"title": "Creamy Lentil Curry"}, set(), set(),
                ["Creamy Lentil Curry food"], "lentil", {"curry"}, set()
            )
        self.assertIsNone(result)
        self.assertEqual(mocked.call_count, 1)
        request = mocked.call_args.args[0]
        params = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
        self.assertEqual(params["page_size"], ["20"])
        self.assertEqual(params["license_type"], ["commercial"])
        self.assertEqual(params["mature"], ["false"])
        self.assertNotIn("category", params)
        self.assertNotIn("aspect_ratio", params)
        self.assertNotIn("size", params)
        self.assertNotIn("extension", params)

    def test_openverse_search_uses_all_prepared_aliases_up_to_fourteen(self):
        import io
        responses = [io.BytesIO(b'{"results": []}') for _ in range(10)]
        searches = [f"lentil curry food alias {index}" for index in range(10)]
        with patch("recipe_worker.urllib.request.urlopen", side_effect=responses) as mocked:
            result = recipe_worker.search_openverse_recipe_image(
                {"title": "Creamy Lentil Curry"}, set(), set(), searches,
                "lentil", {"curry"}, set()
            )
        self.assertIsNone(result)
        self.assertEqual(mocked.call_count, 10)

    def test_shopify_client_credentials_exchange_returns_access_token(self):
        import io
        import urllib.parse
        response = io.BytesIO(b'{"access_token":"short_lived_test_token","scope":"write_content"}')
        with patch.dict("os.environ", {
            "SHOPIFY_CLIENT_ID": "test-client-id",
            "SHOPIFY_CLIENT_SECRET": "test-client-secret",
            "SHOPIFY_ADMIN_ACCESS_TOKEN": "",
            "SHOPIFY_ACCESS_TOKEN": "",
        }, clear=False):
            with patch("recipe_worker.urllib.request.urlopen", return_value=response) as mocked:
                token = recipe_worker.get_access_token("example.myshopify.com")
        self.assertEqual(token, "short_lived_test_token")
        request = mocked.call_args.args[0]
        payload = urllib.parse.parse_qs(request.data.decode("ascii"))
        self.assertEqual(payload["grant_type"], ["client_credentials"])
        self.assertEqual(payload["client_id"], ["test-client-id"])
        self.assertEqual(payload["client_secret"], ["test-client-secret"])
        self.assertEqual(request.full_url, "https://example.myshopify.com/admin/oauth/access_token")

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

    def test_newly_replenished_recipes_have_complete_specific_methods(self):
        recipes = recipe_worker.load_recipes()
        expected = {
            "lemon-herb-chicken-couscous-bowls",
            "garlic-butter-shrimp-rice-skillet",
            "greek-chicken-pita-salad",
            "turkey-meatballs-tomato-orzo",
            "roasted-vegetable-chickpea-couscous",
            "blueberry-banana-overnight-oats",
            "sheet-pan-sausage-peppers-potatoes",
            "creamy-mushroom-spinach-risotto",
        }
        selected = {item["slug"]: item for item in recipes if item["slug"] in expected}
        self.assertEqual(set(selected), expected)
        for recipe in selected.values():
            self.assertGreaterEqual(len(recipe["ingredients"]), 6)
            self.assertGreaterEqual(len(recipe["instructions"]), 4)
            self.assertGreater(recipe["servings"], 0)
            self.assertTrue(recipe.get("seo_title"))
            self.assertTrue(recipe.get("seo_description"))
            self.assertEqual(recipe.get("editorial_status"), "original-recipe-written-awaiting-media-verification")
            # No guessed image or video is attached; the normal live media gates must find and verify both.
            self.assertFalse(recipe.get("image_url"))
            self.assertFalse(recipe.get("video_url"))
            reviewed = recipe_worker.make_recipe_specific(recipe)
            self.assertEqual(reviewed["instructions"], recipe["instructions"])

    def test_generated_trend_recipes_are_persisted_without_duplicates(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recipes.json"
            original = [{"slug": "existing", "title": "Existing"}]
            path.write_text(json.dumps(original), encoding="utf-8")
            candidate = {
                "slug": "new-trend-meal", "title": "New Trend Meal",
                "description": "A complete new meal.",
                "ingredients": ["1 cup rice"],
                "instructions": ["Step one.", "Step two.", "Step three.", "Step four."],
                "prep_minutes": 5, "cook_minutes": 10, "servings": 2,
            }
            added = recipe_worker.persist_generated_recipe_candidates(original, [candidate], path)
            self.assertEqual([item["slug"] for item in added], ["new-trend-meal"])
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([item["slug"] for item in saved], ["existing", "new-trend-meal"])
            self.assertEqual(recipe_worker.persist_generated_recipe_candidates(saved, [candidate], path), [])
            self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))), 2)

    def test_daily_batch_limit_is_configurable_but_capped_at_three(self):
        with patch.dict("os.environ", {"MAX_RECIPES_PER_RUN": "3"}, clear=False):
            self.assertEqual(recipe_worker.configured_max_recipes_per_run(), 3)
        with patch.dict("os.environ", {"MAX_RECIPES_PER_RUN": "9"}, clear=False):
            self.assertEqual(recipe_worker.configured_max_recipes_per_run(), 3)
        with patch.dict("os.environ", {"MAX_RECIPES_PER_RUN": "0"}, clear=False):
            with self.assertRaisesRegex(ValueError, "from 1 to 3"):
                recipe_worker.configured_max_recipes_per_run()

    def test_targeted_recipe_slug_list_preserves_requested_order(self):
        recipes = [{"slug": "first"}, {"slug": "second"}]
        with patch.dict("os.environ", {"TARGET_RECIPE_SLUGS": "second,first"}, clear=False):
            selected = recipe_worker.requested_target_recipes(recipes)
        self.assertEqual([item["slug"] for item in selected], ["second", "first"])
        with patch.dict("os.environ", {"TARGET_RECIPE_SLUGS": "missing"}, clear=False):
            with self.assertRaisesRegex(ValueError, "not found"):
                recipe_worker.requested_target_recipes(recipes)

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

    def test_orzo_photo_relevance_accepts_chicken_pasta_alias(self):
        overlap, has_main, has_format = recipe_worker._photo_title_relevance(
            "Creamy Lemon Garlic Chicken Orzo",
            "Chicken pasta with lemon sauce"
        )
        self.assertTrue(has_main)
        self.assertTrue(has_format)
        self.assertGreaterEqual(overlap, 0.40)

    def test_overnight_oats_photo_relevance_accepts_oatmeal_alias(self):
        overlap, has_main, has_format = recipe_worker._photo_title_relevance(
            "Blueberry Banana Overnight Oats",
            "Banana blueberry oatmeal"
        )
        self.assertTrue(has_main)
        self.assertTrue(has_format)
        self.assertEqual(overlap, 1.0)

    def test_orzo_photo_relevance_rejects_wrong_protein(self):
        overlap, has_main, has_format = recipe_worker._photo_title_relevance(
            "Creamy Lemon Garlic Chicken Orzo",
            "Lemon shrimp pasta"
        )
        self.assertFalse(has_main)

    def test_video_audit_flags_missing_or_invalid_embeds_only(self):
        valid = '<h2>Watch the Recipe Video Here</h2><iframe src="https://www.youtube-nocookie.com/embed/abcdefghijk"></iframe>'
        self.assertFalse(recipe_worker.article_needs_video_repair(valid))
        self.assertTrue(recipe_worker.article_needs_video_repair("<p>Watch on YouTube</p>"))
        self.assertTrue(recipe_worker.article_needs_video_repair('<iframe src="https://www.youtube.com/embed/abcdefghijk"></iframe>'))
        self.assertTrue(recipe_worker.article_needs_video_repair('<iframe src="https://www.youtube-nocookie.com/embed/abcdefghijk"></iframe>'))
        duplicate = valid + '<h2>Watch the Recipe Video</h2><iframe src="https://www.youtube-nocookie.com/embed/lmnopqrstuv"></iframe>'
        self.assertTrue(recipe_worker.article_needs_video_repair(duplicate))
        cleaned = recipe_worker.upsert_recipe_video_section(duplicate, {"title": "Example"}, {"id": "abcdefghijk", "embed_url": "https://www.youtube-nocookie.com/embed/abcdefghijk", "url": "https://www.youtube.com/watch?v=abcdefghijk", "publisher": "Food Network"})
        self.assertEqual(len(__import__("re").findall(r"<iframe\b", cleaned, flags=__import__("re").IGNORECASE)), 1)

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

    def test_generic_recipe_templates_are_blocked_before_substitution(self):
        recipe = {
            "title": "Lemon Garlic Chicken Rice Bowls",
            "ingredients": ["600 g chicken breast", "1 teaspoon garlic", "2 cups cooked rice"],
            "instructions": [
                "Season the main ingredient with the listed flavorings and a pinch of salt.",
                "Cook the main ingredient in a lightly oiled skillet until tender and safely cooked through.",
                "Divide the cooked rice between bowls.",
                "Serve with rice."
            ],
            "prep_minutes": 15, "cook_minutes": 15, "servings": 4,
        }
        with self.assertRaisesRegex(ValueError, "manual recipe-specific review"):
            recipe_worker.make_recipe_specific(recipe)

    def test_generic_choice_placeholders_are_blocked(self):
        recipe = {
            "title": "Lemon Garlic Chicken Rice Bowls",
            "ingredients": ["500 g chicken breast", "2 cups cooked rice"],
            "instructions": [
                "Season the chicken with seasonings of choice.",
                "Cook the chicken until it reaches 74°C (165°F).",
                "Divide the rice between bowls.",
                "Serve with your choice of vegetables."
            ],
            "prep_minutes": 10, "cook_minutes": 15, "servings": 2,
        }
        with self.assertRaisesRegex(ValueError, "manual recipe-specific review"):
            recipe_worker.make_recipe_specific(recipe)

    def test_curated_recipe_fallback_returns_complete_unique_patterns(self):
        from trend_recipe_builder import generate_curated_recipe_candidates
        candidates = generate_curated_recipe_candidates(existing_slugs={"crispy-smash-burger-tacos"}, limit=3)
        self.assertEqual(len(candidates), 3)
        self.assertTrue(all(len(item["instructions"]) >= 4 for item in candidates))
        self.assertNotIn("crispy-smash-burger-tacos", {item["slug"] for item in candidates})
        self.assertEqual(len({item["slug"] for item in candidates}), len(candidates))

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
        self.assertIn("sweet corn", " ".join(recipe["ingredients"]).lower())
        self.assertIn("bell pepper", " ".join(recipe["ingredients"]).lower())

    def test_official_channel_video_can_pass_without_optional_recipe_link(self):
        recipe = {"title": "Hot Honey Chicken Rice Bowls"}
        metadata = {"title": "Hot Honey Chicken Rice Bowl Recipe", "author_name": "Food Network"}
        response = __import__("io").BytesIO(json.dumps(metadata).encode("utf-8"))
        with patch("recipe_worker.urllib.request.urlopen", return_value=response):
            result = recipe_worker._check_video_candidate(
                recipe, "abcdefghijk", "Hot Honey Chicken Rice Bowl Recipe",
                recipe_worker.FOOD_NETWORK_CHANNEL_ID, ""
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["publisher"], "Food Network")
        self.assertEqual(result["source_article_url"], "")
        self.assertEqual(result["embed_url"], "https://www.youtube-nocookie.com/embed/abcdefghijk")

    def test_second_approved_publisher_video_is_verified_by_exact_channel_and_author(self):
        recipe = {"title": "Crispy Salmon Rice Bowls"}
        metadata = {"title": "Crispy Salmon Rice Bowl Recipe", "author_name": "Tasty"}
        response = __import__("io").BytesIO(json.dumps(metadata).encode("utf-8"))
        with patch("recipe_worker.urllib.request.urlopen", return_value=response):
            result = recipe_worker._check_video_candidate(
                recipe, "abcdefghijk", "Crispy Salmon Rice Bowl Recipe",
                "UCJFp8uSYCjXOMnkUyb3CQ3Q", ""
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["publisher"], "Tasty")

    def test_real_creator_channel_is_accepted_when_live_oembed_matches(self):
        recipe = {"title": "Crispy Salmon Rice Bowls"}
        metadata = {
            "title": "Crispy Salmon Rice Bowls You'll Want on Repeat",
            "author_name": "Delightful Dishes",
            "author_url": "https://www.youtube.com/@DelightfulDishes",
        }
        response = __import__("io").BytesIO(json.dumps(metadata).encode("utf-8"))
        channel_id = "UC" + ("A" * 22)
        with patch("recipe_worker.urllib.request.urlopen", return_value=response):
            result = recipe_worker._check_video_candidate(
                recipe, "abcdefghijk", metadata["title"], channel_id, "", "Delightful Dishes"
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["publisher"], "Delightful Dishes")

    def test_approved_channel_with_mismatched_oembed_author_is_rejected(self):
        recipe = {"title": "Crispy Salmon Rice Bowls"}
        metadata = {"title": "Crispy Salmon Rice Bowl Recipe", "author_name": "Imposter"}
        response = __import__("io").BytesIO(json.dumps(metadata).encode("utf-8"))
        with patch("recipe_worker.urllib.request.urlopen", return_value=response):
            result = recipe_worker._check_video_candidate(
                recipe, "abcdefghijk", "Crispy Salmon Rice Bowl Recipe",
                "UCJFp8uSYCjXOMnkUyb3CQ3Q", ""
            )
        self.assertIsNone(result)

    def test_video_title_match_rejects_different_flavour_variant(self):
        score = recipe_worker._video_title_score(
            "Hot Honey Chicken Rice Bowls",
            "Molly Yeh's Citrus Chicken Rice Bowls | Girl Meets Farm | Food Network",
        )
        self.assertLess(score, 0.72)

    def test_unapproved_video_channel_is_always_rejected(self):
        recipe = {"title": "Hot Honey Chicken Rice Bowls"}
        with patch("recipe_worker.urllib.request.urlopen") as mocked:
            result = recipe_worker._check_video_candidate(
                recipe, "abcdefghijk", "Hot Honey Chicken Rice Bowl Recipe",
                "unapproved-channel-id", ""
            )
        self.assertIsNone(result)
        mocked.assert_not_called()

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

    def test_recipe_specificity_rejects_generic_instructions_instead_of_inventing_steps(self):
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
        with self.assertRaisesRegex(ValueError, "manual recipe-specific review"):
            recipe_worker.make_recipe_specific(recipe)

    def test_featured_image_accepts_verified_commons_cc_by_photo(self):
        recipe = {"title": "Sample Salmon Pasta"}
        generated_image = {
            "url": "https://upload.wikimedia.org/wikipedia/commons/a/a1/sample.jpg",
            "altText": "Salmon pasta served on a plate",
            "source_type": "wikimedia_commons",
            "title": "Salmon pasta",
            "author": "Example Photographer",
            "source_url": "https://commons.wikimedia.org/wiki/File:Sample.jpg",
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
        }
        with patch.object(recipe_worker, "inspect_image_url", return_value={"ok": True, "width": 1600, "height": 1067, "edge_variance": 42}):
            image = recipe_worker.featured_image_for(recipe, generated_image)
        self.assertEqual(image["source_type"], "wikimedia_commons")
        self.assertEqual(image["license"], "CC BY 4.0")

    def test_featured_image_accepts_verified_openverse_cc_by_photo(self):
        recipe = {"title": "Sample Salmon Pasta"}
        generated_image = {
            "url": "https://images.example.org/salmon-pasta.jpg",
            "altText": "Salmon pasta served on a plate",
            "source_type": "openverse",
            "title": "Salmon pasta",
            "author": "Example Photographer",
            "provider": "example-provider",
            "source_url": "https://example.org/photos/salmon-pasta",
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
        }
        with patch.object(recipe_worker, "inspect_image_url", return_value={"ok": True, "width": 1600, "height": 1067, "edge_variance": 42}):
            image = recipe_worker.featured_image_for(recipe, generated_image)
        self.assertEqual(image["source_type"], "openverse")
        self.assertEqual(image["provider"], "example-provider")

    def test_featured_image_accepts_verified_creator_video_thumbnail(self):
        image = {
            "url": "https://img.youtube.com/vi/abcdefghijk/maxresdefault.jpg",
            "altText": "Food Network cooking video thumbnail for Sample Salmon Pasta",
            "source_type": "official_youtube_thumbnail",
            "publisher": "Food Network",
            "source_url": "https://www.youtube.com/watch?v=abcdefghijk",
            "video_id": "abcdefghijk",
        }
        with patch.object(recipe_worker, "inspect_image_url", return_value={"ok": True, "width": 1280, "height": 720, "edge_variance": 42}):
            result = recipe_worker.featured_image_for({"title": "Sample Salmon Pasta"}, image)
        self.assertEqual(result["source_type"], "official_youtube_thumbnail")
        self.assertEqual(result["publisher"], "Food Network")

    def test_featured_image_accepts_public_domain_without_creator_attribution(self):
        image = {
            "url": "https://upload.wikimedia.org/wikipedia/commons/a/a1/sample.jpg",
            "altText": "Salmon pasta",
            "source_type": "wikimedia_commons",
            "license": "Public domain",
        }
        with patch.object(recipe_worker, "inspect_image_url", return_value={"ok": True, "width": 1600, "height": 1067, "edge_variance": 42}):
            result = recipe_worker.featured_image_for({"title": "Salmon pasta"}, image)
        self.assertEqual(result["url"], image["url"])

    def test_featured_image_rejects_noncommercial_and_no_derivatives_licences(self):
        base = {
            "url": "https://upload.wikimedia.org/wikipedia/commons/a/a1/sample.jpg",
            "altText": "Salmon pasta",
            "source_type": "wikimedia_commons",
            "title": "Salmon pasta",
            "author": "Example Photographer",
            "source_url": "https://commons.wikimedia.org/wiki/File:Sample.jpg",
            "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
        }
        for licence in ("CC BY-NC 4.0", "CC BY-ND 4.0"):
            with self.subTest(licence=licence):
                candidate = {**base, "license": licence}
                with self.assertRaisesRegex(RuntimeError, "licence is not approved"):
                    recipe_worker.featured_image_for({"title": "Salmon pasta"}, candidate)

    def test_featured_image_rejects_unverified_recipe_fallback(self):
        recipe = {"title": "Sample Dish", "image_url": "https://images.example.com/sample-dish.jpg"}
        with self.assertRaisesRegex(RuntimeError, "verified Wikimedia Commons food photograph"):
            recipe_worker.featured_image_for(recipe, None)
        with self.assertRaises(RuntimeError):
            recipe_worker.featured_image_for({"title": "Sample Dish"}, {
                "url": "https://images.example.com/sample-dish.jpg",
                "altText": "Sample dish",
                "source_type": "unknown",
            })

    def test_category_archive_sync_updates_only_known_published_recipes(self):
        recipes = [
            {
                "slug": "creamy-baked-feta-tomato-pasta",
                "title": "Creamy Baked Feta Tomato Pasta",
                "description": "Savoury pasta with roasted tomatoes and feta.",
                "tags": ["pasta", "vegetarian", "dinner"],
                "prep_minutes": 10, "cook_minutes": 25,
            }
        ]
        articles = {
            "creamy-baked-feta-tomato-pasta": {
                "id": "gid://shopify/Article/1",
                "handle": "creamy-baked-feta-tomato-pasta",
                "isPublished": True,
                "tags": ["pasta", "vegetarian", "dinner", "fresh-and-green"],
            },
            "unrelated-editorial": {
                "id": "gid://shopify/Article/2",
                "handle": "unrelated-editorial",
                "isPublished": True,
                "tags": ["editorial"],
            },
        }
        response = {"articleUpdate": {"article": {"id": "gid://shopify/Article/1"}, "userErrors": []}}
        with patch.object(recipe_worker, "graphql", return_value=response) as mocked:
            updated = recipe_worker.sync_published_recipe_categories(articles, recipes)
        self.assertEqual(updated, 1)
        payload = mocked.call_args.args[1]
        self.assertEqual(payload["id"], "gid://shopify/Article/1")
        self.assertIn("comfort-food", payload["article"]["tags"])
        self.assertIn("quick-and-easy", payload["article"]["tags"])
        self.assertNotIn("fresh-and-green", payload["article"]["tags"])
        self.assertEqual(articles["unrelated-editorial"]["tags"], ["editorial"])

    def test_existing_article_update_payload_includes_canonical_category_tags(self):
        recipe = recipe_worker.add_recipe_category_tags({
            "title": "Creamy Tomato Pasta",
            "description": "A cosy family dinner.",
            "tags": ["pasta", "dinner"],
            "ingredients": ["300 g pasta", "1 cup tomatoes"],
            "instructions": ["Boil pasta.", "Cook sauce.", "Combine.", "Serve."],
            "prep_minutes": 10,
            "cook_minutes": 20,
            "servings": 2,
        })
        video = {
            "id": "abcdefghijk",
            "url": "https://www.youtube.com/watch?v=abcdefghijk",
            "embed_url": "https://www.youtube-nocookie.com/embed/abcdefghijk",
            "publisher": "Food Network",
        }
        image = {"url": "https://images.example.com/pasta.jpg", "altText": "Creamy tomato pasta"}
        with patch.object(recipe_worker, "article_html", return_value="<h2>Ingredients</h2><h2>Instructions</h2>"):
            payload = recipe_worker.recipe_article_update_input(recipe, video, set(), image)
        self.assertIn("comfort-food", payload["tags"])
        self.assertIn("quick-and-easy", payload["tags"])
        self.assertEqual(payload["image"]["url"], image["url"])
        self.assertTrue(payload["isPublished"])

    def test_vegetarian_pasta_is_not_automatically_fresh_and_green(self):
        recipe = recipe_worker.add_recipe_category_tags({
            "title": "Creamy Baked Feta Tomato Pasta",
            "description": "A savoury pasta with roasted tomatoes and feta.",
            "tags": ["pasta", "vegetarian", "dinner"],
            "prep_minutes": 10,
            "cook_minutes": 25,
        })
        self.assertIn("comfort-food", recipe["tags"])
        self.assertNotIn("fresh-and-green", recipe["tags"])
        self.assertNotIn("sweet-things", recipe["tags"])

    def test_category_tagging_assigns_canonical_collection_tags(self):
        quick = recipe_worker.add_recipe_category_tags({
            "title": "Quick Lemon Chicken Tacos",
            "description": "A fast weeknight dinner.",
            "tags": ["chicken", "quick"],
            "prep_minutes": 10,
            "cook_minutes": 15,
        })
        fresh = recipe_worker.add_recipe_category_tags({
            "title": "Mediterranean Chickpea Salad",
            "description": "Fresh vegetables and herbs.",
            "tags": ["vegetarian", "salad"],
            "prep_minutes": 15,
            "cook_minutes": 0,
        })
        comfort = recipe_worker.add_recipe_category_tags({
            "title": "Creamy Tomato Pasta",
            "description": "A cosy family dinner.",
            "tags": ["pasta", "dinner"],
            "prep_minutes": 10,
            "cook_minutes": 20,
        })
        sweet = recipe_worker.add_recipe_category_tags({
            "title": "Blueberry Muffins",
            "description": "Easy baked breakfast treats.",
            "tags": ["baking"],
            "prep_minutes": 10,
            "cook_minutes": 20,
        })
        self.assertIn("quick-and-easy", quick["tags"])
        self.assertIn("fresh-and-green", fresh["tags"])
        self.assertIn("comfort-food", comfort["tags"])
        self.assertIn("sweet-things", sweet["tags"])
        savory_baked = recipe_worker.add_recipe_category_tags({
            "title": "Creamy Baked Feta Tomato Pasta",
            "description": "A savoury pasta with roasted tomatoes, feta and basil.",
            "tags": ["pasta", "vegetarian", "dinner"],
            "prep_minutes": 10,
            "cook_minutes": 30,
        })
        self.assertNotIn("sweet-things", savory_baked["tags"])
        self.assertIn("comfort-food", savory_baked["tags"])

    def test_food_network_article_url_requires_official_recipe_path(self):
        self.assertEqual(
            recipe_worker.food_network_recipe_article_url(
                "Get the recipe: https://www.foodnetwork.com/recipes/ina-garten/pasta-recipe-123"
            ),
            "https://www.foodnetwork.com/recipes/ina-garten/pasta-recipe-123",
        )
        self.assertEqual(
            recipe_worker.food_network_recipe_article_url(
                "See https://example.com/recipes/pasta and https://www.foodnetwork.com/videos"
            ),
            "",
        )

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
        self.assertIn('<iframe', html)
        self.assertIn('aspect-ratio:16/9', html)
        self.assertIn('title="Sample Pasta recipe video"', html)
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
        self.assertIn("pasta", payload["keywords"].lower())

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


    def test_published_generated_image_is_in_recipe_json_ld(self):
        recipe = {
            "slug": "sample-salmon-pasta",
            "title": "Sample Salmon Pasta",
            "description": "A bright salmon pasta with lemon and herbs.",
            "prep_minutes": 10,
            "cook_minutes": 15,
            "servings": 2,
            "ingredients": ["200 g salmon", "200 g pasta", "1 lemon"],
            "instructions": [
                "Boil the pasta until al dente.",
                "Season and cook the salmon until safely cooked.",
                "Flake the salmon into bite-sized pieces.",
                "Toss pasta with lemon and salmon, then serve."
            ],
            "tags": ["Seafood", "Pasta"],
        }
        generated = {
            "url": "https://upload.wikimedia.org/wikipedia/commons/a/a1/sample.jpg",
            "altText": "Salmon pasta served on a plate",
            "source_type": "wikimedia_commons",
            "title": "Salmon pasta",
            "author": "Example Photographer",
            "source_url": "https://commons.wikimedia.org/wiki/File:Sample.jpg",
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
        }
        video = {
            "title": "Sample Salmon Pasta Recipe",
            "url": "https://www.youtube.com/watch?v=abcdefghijk",
            "embed_url": "https://www.youtube-nocookie.com/embed/abcdefghijk",
        }
        from unittest.mock import patch
        captured = {}
        def fake_graphql(_query, variables):
            captured.update(variables["article"])
            return {"articleCreate": {"article": {"isPublished": True}, "userErrors": []}}
        with patch.object(recipe_worker, "graphql", side_effect=fake_graphql), patch.object(recipe_worker, "inspect_image_url", return_value={"ok": True, "width": 1600, "height": 1067, "edge_variance": 42}):
            recipe_worker.create_published("gid://shopify/Blog/1", recipe, video, generated)
        body = captured["body"]
        self.assertIn(generated["url"], body)
        self.assertIn(generated["url"], captured["image"]["url"])
        self.assertEqual(set(captured["image"]), {"url", "altText"})
        self.assertNotIn("source_type", captured["image"])
        self.assertNotIn("publisher", captured["image"])
        self.assertIn("Example Photographer", body)
        self.assertIn("CC BY 4.0", body)
        self.assertIn("https://creativecommons.org/licenses/by/4.0/", body)
        self.assertIn("Video credit: YouTube creator", body)
        self.assertIn('"image": ["' + generated["url"] + '"]', body)
        self.assertIn('"url": "https://solepick.site/blogs/recipes/sample-salmon-pasta"', body)
        self.assertIn('"mainEntityOfPage"', body)
        self.assertIn('"VideoObject"', body)
        self.assertIn('"embedUrl": "https://www.youtube.com/watch?v=abcdefghijk"', body)



    def test_new_recipe_library_entries_include_practical_original_notes(self):
        recipes = json.loads((ROOT / "recipes.json").read_text(encoding="utf-8"))
        slugs = {item["slug"] for item in recipes}
        expected = {
            "crispy-harissa-chickpea-pitas",
            "lemony-orzo-with-peas-and-feta",
            "smoky-sweet-potato-black-bean-skillet",
            "ginger-sesame-tofu-noodle-bowls",
            "roasted-carrot-red-lentil-soup",
            "hot-honey-chicken-rice-bowls",
            "creamy-baked-feta-tomato-pasta",
            "crispy-salmon-rice-bowls",
        }
        self.assertTrue(expected.issubset(slugs))
        for recipe in recipes:
            if recipe["slug"] in expected:
                self.assertGreaterEqual(len(recipe["instructions"]), 5)
                self.assertGreaterEqual(len(recipe.get("cook_notes", [])), 2)
                self.assertGreaterEqual(len(recipe.get("substitutions", [])), 2)
                self.assertTrue(recipe.get("storage"))
                self.assertGreaterEqual(len(recipe["description"]), 110)
                self.assertGreaterEqual(len(set(recipe.get("tags", []))), 4)

    def test_recipe_editorial_sections_render_only_supplied_practical_notes(self):
        recipe = {
            "title": "Test Bowl",
            "cook_notes": ["Dry the chickpeas before roasting."],
            "substitutions": ["Use parsley instead of dill."],
            "storage": "Refrigerate in a sealed container for 3 days.",
        }
        markup = recipe_worker.recipe_editorial_sections(recipe)
        self.assertIn("Recipe Tips", markup)
        self.assertIn("Ingredient Swaps", markup)
        self.assertIn("Make-Ahead and Storage", markup)
        self.assertIn("Dry the chickpeas", markup)
        self.assertNotIn("FAQ", markup)

class RecipeBlogRoutingTests(unittest.TestCase):
    def test_existing_recipes_blog_is_selected_by_handle(self):
        with patch.object(recipe_worker, "graphql", return_value={
            "blogs": {"nodes": [
                {"id": "gid://shopify/Blog/1", "title": "News", "handle": "news"},
                {"id": "gid://shopify/Blog/2", "title": "Recipes", "handle": "recipes"},
            ]}
        }) as mocked:
            self.assertEqual(
                recipe_worker.resolve_recipe_blog(),
                "gid://shopify/Blog/2",
            )
            mocked.assert_called_once()

    def test_missing_recipes_blog_is_created_and_verified(self):
        def fake_graphql(query, variables):
            if "query SolePickBlogs" in query:
                return {"blogs": {"nodes": [
                    {"id": "gid://shopify/Blog/1", "title": "News", "handle": "news"}
                ]}}
            return {"blogCreate": {
                "blog": {"id": "gid://shopify/Blog/3", "title": "Recipes", "handle": "recipes"},
                "userErrors": [],
            }}
        with patch.object(recipe_worker, "graphql", side_effect=fake_graphql):
            self.assertEqual(
                recipe_worker.resolve_recipe_blog(),
                "gid://shopify/Blog/3",
            )

    def test_blog_creation_errors_fail_closed(self):
        def fake_graphql(query, variables):
            if "query SolePickBlogs" in query:
                return {"blogs": {"nodes": []}}
            return {"blogCreate": {
                "blog": None,
                "userErrors": [{"field": ["handle"], "message": "Taken"}],
            }}
        with patch.object(recipe_worker, "graphql", side_effect=fake_graphql):
            with self.assertRaisesRegex(RuntimeError, "Unable to create dedicated Recipes blog"):
                recipe_worker.resolve_recipe_blog()


class RecipePhotoRelevanceTests(unittest.TestCase):
    def test_banana_oat_pancake_photo_matches_common_filename(self):
        score, has_main, has_format = recipe_worker._photo_title_relevance(
            "Banana Oat Breakfast Pancakes",
            "File:Banana pancakes with oats.jpg",
        )
        self.assertGreaterEqual(score, 0.4)
        self.assertTrue(has_main)
        self.assertTrue(has_format)

    def test_chicken_orzo_matches_risoni_synonym(self):
        score, has_main, has_format = recipe_worker._photo_title_relevance(
            "Creamy Lemon Garlic Chicken Orzo",
            "File:Chicken risoni pasta with lemon.jpg",
        )
        self.assertGreaterEqual(score, 0.4)
        self.assertTrue(has_main)
        self.assertTrue(has_format)

    def test_unrelated_dish_does_not_match(self):
        score, has_main, has_format = recipe_worker._photo_title_relevance(
            "Banana Oat Breakfast Pancakes",
            "File:Roasted salmon rice bowl.jpg",
        )
        self.assertLess(score, 0.4)
        self.assertFalse(has_main)
        self.assertFalse(has_format)


if __name__ == "__main__":
    unittest.main()
