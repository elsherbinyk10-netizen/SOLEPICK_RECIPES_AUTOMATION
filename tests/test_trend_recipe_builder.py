import unittest

from trend_recipe_builder import generate_trend_recipe_candidates


class TrendRecipeBuilderTests(unittest.TestCase):
    def test_known_current_trend_creates_complete_new_recipe(self):
        signals = [
            {"text": "Cottage cheese bowls trending for high protein breakfast", "source": "google_trends"},
            {"text": "Creators share cottage cheese breakfast bowls", "source": "tiktok_creative_center"},
        ]
        recipes = generate_trend_recipe_candidates(signals, existing_slugs={"old-recipe"})
        self.assertEqual(len(recipes), 1)
        recipe = recipes[0]
        self.assertEqual(recipe["title"], "High-Protein Cottage Cheese Breakfast Bowl")
        self.assertTrue(recipe["ingredients"])
        self.assertGreaterEqual(len(recipe["instructions"]), 4)
        self.assertIn("seo_title", recipe)
        self.assertIn("google_trends", recipe["trend_sources"])

    def test_unmatched_trend_never_invents_a_recipe(self):
        recipes = generate_trend_recipe_candidates(
            [{"text": "A new viral purple moon dessert", "source": "google_trends"}]
        )
        self.assertEqual(recipes, [])

    def test_existing_recipe_is_not_generated_twice(self):
        slug = "high-protein-cottage-cheese-breakfast-bowl"
        recipes = generate_trend_recipe_candidates(
            [{"text": "cottage cheese breakfast bowl"}], existing_slugs={slug}
        )
        self.assertEqual(recipes, [])

    def test_multiple_supported_trends_generate_multiple_candidates(self):
        signals = [
            {"text": "hot honey chicken is trending"},
            {"text": "baked feta pasta is popular"},
            {"text": "crispy salmon rice bowls"},
        ]
        recipes = generate_trend_recipe_candidates(signals, limit=3)
        self.assertEqual(len(recipes), 3)
        self.assertEqual(len({item["slug"] for item in recipes}), 3)

    def test_generation_is_limited_to_three_per_run(self):
        signals = [
            "cottage cheese breakfast bowl",
            "hot honey chicken",
            "baked feta pasta",
            "crispy salmon rice",
        ]
        self.assertLessEqual(len(generate_trend_recipe_candidates(signals, limit=20)), 3)


if __name__ == "__main__":
    unittest.main()



    def test_curated_fallback_replenishes_only_unused_complete_patterns(self):
        from trend_recipe_builder import generate_curated_recipe_candidates
        candidates = generate_curated_recipe_candidates(
            existing_slugs={"high-protein-cottage-cheese-breakfast-bowl",
                            "hot-honey-chicken-rice-bowls",
                            "creamy-baked-feta-tomato-pasta",
                            "crispy-salmon-rice-bowls"},
            limit=3,
        )
        self.assertEqual(len(candidates), 3)
        self.assertTrue(all(item["ingredients"] and len(item["instructions"]) >= 4 for item in candidates))
        self.assertEqual(
            [item["slug"] for item in candidates],
            ["crispy-smash-burger-tacos", "chili-crisp-peanut-noodles", "creamy-marry-me-chickpeas"],
        )
        self.assertTrue(all(item["trend_evidence_count"] == 0 for item in candidates))
