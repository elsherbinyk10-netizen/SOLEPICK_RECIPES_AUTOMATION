import json
import unittest
from pathlib import Path


class RecipeLibraryTests(unittest.TestCase):
    def test_recipes_have_unique_slugs_and_required_fields(self):
        path = Path(__file__).resolve().parents[1] / "recipes.json"
        recipes = json.loads(path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(recipes), 1)
        slugs = []
        for recipe in recipes:
            for key in (
                "slug", "title", "description", "ingredients",
                "instructions", "servings"
            ):
                self.assertIn(key, recipe)
            self.assertTrue(recipe["ingredients"])
            self.assertTrue(recipe["instructions"])
            self.assertGreater(recipe["servings"], 0)
            slugs.append(recipe["slug"])
        self.assertEqual(len(slugs), len(set(slugs)))


if __name__ == "__main__":
    unittest.main()
