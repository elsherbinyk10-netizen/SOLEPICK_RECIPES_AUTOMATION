"""Create conservative, complete recipe candidates from recognizable live food trends.

Only explicit, pre-authored recipe patterns are generated. Generic trend phrases are
never turned into invented recipes. Candidates still pass the normal video, image,
instruction and Shopify publication gates in recipe_worker.py.
"""
import re
import unicodedata


def _slug(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value)).strip("-")


# Each pattern is a complete editorially-authored recipe, not scraped/copied content.
# These patterns are intentionally narrow; expand only with reviewed, testable recipes.
PATTERNS = (
    {
        "key": "cottage-cheese",
        "needles": ("cottage cheese",),
        "title": "High-Protein Cottage Cheese Breakfast Bowl",
        "description": "A creamy, protein-rich cottage cheese bowl with berries, oats, chia seeds and honey for an easy make-ahead breakfast.",
        "tags": ["breakfast", "high protein", "cottage cheese", "meal prep"],
        "ingredients": ["1 cup (225 g) cottage cheese", "1/2 cup fresh strawberries, sliced", "1/3 cup blueberries", "1/4 cup rolled oats", "1 tablespoon chia seeds", "1 teaspoon honey", "1 tablespoon chopped walnuts"],
        "instructions": ["Spoon the cottage cheese into a serving bowl and smooth the top.", "Arrange the strawberries and blueberries over the cottage cheese.", "Scatter the rolled oats, chia seeds and chopped walnuts over the fruit.", "Drizzle with honey and serve immediately, or refrigerate covered for up to 1 day; add the oats just before serving for the best texture."],
        "prep_minutes": 8, "cook_minutes": 0, "servings": 1,
    },
    {
        "key": "hot-honey-chicken",
        "needles": ("hot honey chicken", "hot honey"),
        "title": "Hot Honey Chicken Rice Bowls",
        "description": "Golden hot-honey chicken served over rice with crunchy cucumber and a bright lime dressing.",
        "tags": ["dinner", "chicken", "hot honey", "rice bowl", "high protein"],
        "ingredients": ["500 g boneless skinless chicken breast, cut into 2 cm pieces", "2 tablespoons olive oil, divided", "1 teaspoon smoked paprika", "1/2 teaspoon garlic powder", "1/2 teaspoon fine salt", "3 tablespoons honey", "1 tablespoon hot sauce", "1 tablespoon lime juice", "2 cups cooked rice", "1 cucumber, diced", "2 tablespoons chopped fresh coriander"],
        "instructions": ["Pat the chicken dry. Toss with 1 tablespoon olive oil, smoked paprika, garlic powder and salt.", "Heat the remaining olive oil in a large skillet over medium-high heat. Cook the chicken in a single layer for 5–7 minutes, turning until browned and the thickest pieces reach 74°C (165°F) on a food thermometer.", "Stir honey, hot sauce and lime juice together in a small bowl.", "Reduce the skillet heat to low, pour in the hot-honey mixture and toss for 30–60 seconds until the chicken is coated. Remove from the heat.", "Divide the hot cooked rice between bowls. Add cucumber and the chicken, spoon over any pan glaze and finish with coriander."],
        "prep_minutes": 12, "cook_minutes": 12, "servings": 2,
    },
    {
        "key": "baked-feta-pasta",
        "needles": ("baked feta pasta", "feta pasta"),
        "title": "Creamy Baked Feta Tomato Pasta",
        "description": "A simple baked feta and tomato pasta with garlic, olive oil and fresh basil.",
        "tags": ["dinner", "pasta", "feta", "vegetarian", "comfort food"],
        "ingredients": ["300 g short pasta", "200 g block feta cheese", "400 g cherry tomatoes", "3 tablespoons olive oil", "3 garlic cloves, thinly sliced", "1/2 teaspoon dried oregano", "1/4 teaspoon black pepper", "1/4 cup reserved pasta water", "1/4 cup fresh basil leaves"],
        "instructions": ["Heat the oven to 200°C (400°F). Put the cherry tomatoes and sliced garlic in a baking dish. Drizzle with olive oil and season with oregano and black pepper.", "Place the feta block in the centre and turn it once to coat lightly with oil. Bake for 25–30 minutes, until the tomatoes have burst and the feta is soft.", "Meanwhile, cook the pasta in salted boiling water according to the packet directions. Reserve 1/4 cup pasta water, then drain.", "Mash the baked feta and tomatoes together in the dish until creamy. Stir in a splash of pasta water to loosen the sauce.", "Add the drained pasta and toss until coated. Finish with fresh basil and serve warm."],
        "prep_minutes": 10, "cook_minutes": 30, "servings": 4,
    },
    {
        "key": "crispy-salmon-rice",
        "needles": ("crispy salmon rice", "salmon rice bowl", "salmon bowl"),
        "title": "Crispy Salmon Rice Bowls",
        "description": "Crisp-edged salmon rice bowls with cucumber, avocado and a quick sesame-soy dressing.",
        "tags": ["dinner", "salmon", "rice bowl", "seafood", "high protein"],
        "ingredients": ["450 g skinless salmon fillet, cut into 2 cm cubes", "1 tablespoon neutral oil", "1 tablespoon soy sauce", "1 teaspoon sesame oil", "1/2 teaspoon garlic powder", "2 cups cooked rice", "1 cucumber, diced", "1 ripe avocado, sliced", "1 tablespoon rice vinegar", "1 teaspoon sesame seeds"],
        "instructions": ["Pat the salmon cubes dry. Toss with neutral oil, soy sauce, sesame oil and garlic powder.", "Heat a non-stick skillet over medium-high heat. Arrange the salmon in one layer and cook for 2–3 minutes per side, turning carefully, until opaque and the centre reaches 63°C (145°F) for food safety.", "Season the cucumber with rice vinegar and toss.", "Divide the cooked rice between bowls. Add the salmon, cucumber and sliced avocado.", "Sprinkle with sesame seeds and serve immediately."],
        "prep_minutes": 12, "cook_minutes": 8, "servings": 2,
    },
)


def generate_trend_recipe_candidates(signals, existing_slugs=(), limit=3):
    """Return up to limit new, complete recipes only when current signals match a reviewed pattern."""
    existing = set(existing_slugs)
    found = []
    for pattern in PATTERNS:
        matching = []
        for signal in signals or []:
            text = signal.get("text", "") if isinstance(signal, dict) else str(signal)
            normalized = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
            if any(needle in normalized for needle in pattern["needles"]):
                matching.append(signal)
        if not matching:
            continue
        recipe = {key: value for key, value in pattern.items() if key not in {"key", "needles"}}
        recipe["slug"] = _slug(recipe["title"])
        if recipe["slug"] in existing:
            continue
        recipe["trend_sources"] = sorted({
            item.get("source", "unknown") if isinstance(item, dict) else "google_news"
            for item in matching
        })
        recipe["trend_evidence_count"] = len(matching)
        recipe["seo_title"] = recipe["title"] + " | SolePick Recipes"
        recipe["seo_description"] = recipe["description"][:155]
        found.append(recipe)
        existing.add(recipe["slug"])
        if len(found) >= max(1, min(3, int(limit))):
            break
    return found
