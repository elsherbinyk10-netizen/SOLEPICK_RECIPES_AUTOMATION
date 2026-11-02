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

    def test_search_and_social_signals_receive_stronger_weights(self):
        recipe = {"title": "Cottage Cheese Protein Bowl", "tags": ["high protein", "breakfast"]}
        news = [{"text": "Cottage cheese protein bowl", "source": "google_news"}]
        search = [{"text": "Cottage cheese protein bowl", "source": "google_trends", "traffic": "500K+"}]
        social = [{"text": "Cottage cheese protein bowl", "source": "tiktok_creative_center"}]
        news_score = score_recipe_trends(recipe, news)
        search_score = score_recipe_trends(recipe, search)
        social_score = score_recipe_trends(recipe, social)
        self.assertGreater(search_score, news_score)
        self.assertGreater(social_score, news_score)

    def test_signal_objects_and_legacy_strings_are_both_supported(self):
        recipe = {"title": "Lemon Herb Chicken", "tags": ["chicken"]}
        self.assertGreater(score_recipe_trends(recipe, ["lemon herb chicken"]), 0)
        self.assertGreater(score_recipe_trends(recipe, [{"text": "lemon herb chicken", "source": "google_trends"}]), 0)


if __name__ == "__main__":
    unittest.main()
