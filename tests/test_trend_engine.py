import unittest

from trend_engine import rank_trending_recipes, score_recipe_trends


class RecipeTrendTests(unittest.TestCase):
    def test_matching_current_trend_ranks_recipe_first(self):
        recipes = [
            {"title": "Creamy Tomato Pasta", "tags": ["pasta", "dinner"]},
            {"title": "High Protein Cottage Cheese Bowl", "tags": ["high protein", "cottage cheese"]},
            {"title": "Lemon Herb Chicken", "tags": ["chicken"]},
        ]
        signals = [
            "TikTok creators are sharing high protein cottage cheese bowls this week",
            "The cottage cheese bowl is a popular high protein lunch trend",
        ]
        ranked = rank_trending_recipes(recipes, signals)
        self.assertEqual(ranked[0]["title"], "High Protein Cottage Cheese Bowl")

    def test_no_signals_preserves_rotation_order(self):
        recipes = [{"title": "A"}, {"title": "B"}]
        self.assertEqual(rank_trending_recipes(recipes, []), recipes)

    def test_unrelated_signals_preserve_rotation_order(self):
        recipes = [{"title": "Lemon Herb Chicken"}, {"title": "Tomato Pasta"}]
        self.assertEqual(rank_trending_recipes(recipes, ["Space telescope discovers a galaxy"]), recipes)

    def test_score_uses_recipe_tags_as_well_as_title(self):
        recipe = {"title": "Simple Weeknight Bowl", "tags": ["cottage cheese", "high protein"]}
        self.assertGreater(score_recipe_trends(recipe, ["High protein cottage cheese bowls are trending"]), 0)


if __name__ == "__main__":
    unittest.main()
