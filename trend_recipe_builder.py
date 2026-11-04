"""Create conservative, complete recipe candidates from recognizable live food trends.

Only explicit, pre-authored recipe patterns are generated. Generic trend phrases are
never turned into invented recipes. Candidates still pass the normal video, image,
instruction and Shopify publication gates in recipe_worker.py.
"""
import re
import unicodedata  # Standard-library normalization keeps daily recipe slugs stable.


def _slug(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value)).strip("-")


# Each pattern is a complete editorially-authored recipe, not scraped/copied content.
# These patterns are intentionally narrow; expand only with reviewed, testable recipes. New matches are persisted to the daily library and checked before publication; regression suite covers the complete publish path.
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
    {
        "key": "smash-burger-tacos",
        "needles": ("smash burger tacos", "burger tacos"),
        "title": "Crispy Smash Burger Tacos",
        "description": "Thin, seared beef patties are pressed onto small tortillas and finished with crisp lettuce, pickles and a tangy burger-style sauce.",
        "tags": ["dinner", "beef", "tacos", "quick-and-easy"],
        "ingredients": ["450 g lean ground beef", "8 small flour tortillas", "1 teaspoon fine salt", "1/2 teaspoon black pepper", "1 teaspoon garlic powder", "1 cup shredded lettuce", "1/2 cup diced dill pickles", "1/2 cup grated cheddar", "3 tablespoons mayonnaise", "1 tablespoon ketchup", "1 teaspoon mustard", "1 teaspoon pickle brine"],
        "instructions": ["Divide the beef into eight equal portions and season with salt, pepper and garlic powder.", "Mix the mayonnaise, ketchup, mustard and pickle brine in a small bowl to make the sauce.", "Press one portion of beef into a very thin layer over one side of each tortilla, spreading it almost to the edges.", "Heat a large skillet over medium-high heat. Place a tortilla beef-side down and cook for 2–3 minutes until the beef is browned and reaches 71°C (160°F). Flip and warm the tortilla for 30–45 seconds.", "Top each taco with cheddar, lettuce, pickles and burger sauce. Serve immediately."],
        "prep_minutes": 15, "cook_minutes": 12, "servings": 4,
    },
    {
        "key": "chili-crisp-peanut-noodles",
        "needles": ("chili crisp noodles", "chilli crisp noodles", "peanut noodles"),
        "title": "Chili Crisp Peanut Noodles",
        "description": "Springy noodles are tossed in a creamy peanut, soy and chili-crisp sauce, then brightened with lime, cucumber and spring onions.",
        "tags": ["dinner", "noodles", "vegetarian", "quick-and-easy"],
        "ingredients": ["250 g dried wheat noodles", "3 tablespoons smooth peanut butter", "1 tablespoon soy sauce", "1 tablespoon chili crisp", "1 tablespoon lime juice", "1 teaspoon honey", "3–5 tablespoons hot noodle water", "1 cucumber, cut into matchsticks", "2 spring onions, thinly sliced", "1 teaspoon toasted sesame seeds"],
        "instructions": ["Cook the noodles in boiling water according to the packet directions. Reserve at least 1/2 cup of the cooking water, then drain.", "Whisk the peanut butter, soy sauce, chili crisp, lime juice and honey in a bowl.", "Whisk in hot noodle water one tablespoon at a time until the sauce is smooth and pourable.", "Add the warm noodles and toss until every strand is coated. Add another splash of noodle water if needed.", "Divide between bowls and top with cucumber, spring onions and sesame seeds. Serve warm or chilled."],
        "prep_minutes": 10, "cook_minutes": 10, "servings": 2,
    },
    {
        "key": "marry-me-chickpeas",
        "needles": ("marry me chickpeas", "creamy sun dried tomato chickpeas"),
        "title": "Creamy Marry Me Chickpeas",
        "description": "Tender chickpeas simmer in a creamy sun-dried tomato sauce with garlic, spinach and parmesan for a satisfying one-pan meal.",
        "tags": ["dinner", "chickpeas", "vegetarian", "comfort-food"],
        "ingredients": ["2 cans (400 g each) chickpeas, drained and rinsed", "1 tablespoon olive oil", "3 garlic cloves, minced", "1/3 cup chopped sun-dried tomatoes", "1 teaspoon dried oregano", "1/2 teaspoon smoked paprika", "3/4 cup vegetable stock", "1/2 cup single cream", "2 cups baby spinach", "1/3 cup finely grated parmesan", "1 tablespoon lemon juice"],
        "instructions": ["Warm the olive oil in a deep skillet over medium heat. Add the garlic and sun-dried tomatoes and cook for 1 minute until fragrant.", "Stir in the oregano and smoked paprika, then add the chickpeas and vegetable stock.", "Bring to a gentle simmer and cook for 5 minutes, stirring occasionally so the chickpeas absorb the flavour.", "Lower the heat and stir in the cream. Add the spinach and cook until just wilted, then mix in the parmesan.", "Finish with lemon juice and black pepper. Serve with toasted bread, rice or cooked grains."],
        "prep_minutes": 8, "cook_minutes": 15, "servings": 4,
    },
    {
        "key": "pesto-eggs-sourdough",
        "needles": ("pesto eggs", "pesto egg toast"),
        "title": "Pesto Eggs on Sourdough",
        "description": "Eggs cook gently in fragrant basil pesto and are served on toasted sourdough with creamy avocado and a squeeze of lemon.",
        "tags": ["breakfast", "eggs", "vegetarian", "quick-and-easy"],
        "ingredients": ["2 slices sourdough bread", "2 tablespoons basil pesto", "2 large eggs", "1/2 ripe avocado, sliced", "1 teaspoon lemon juice", "1 tablespoon crumbled feta", "Black pepper, to taste"],
        "instructions": ["Toast the sourdough until golden and crisp.", "Heat the pesto in a small non-stick skillet over medium-low heat until it loosens and becomes fragrant.", "Crack in the eggs, cover the skillet and cook for 3–5 minutes until the whites are fully set and the yolks are cooked to your preference.", "Toss the avocado with lemon juice and a little black pepper.", "Place one pesto egg on each toast slice, add avocado and finish with crumbled feta and black pepper."],
        "prep_minutes": 5, "cook_minutes": 6, "servings": 2,
    },
    {
        "key": "korean-ground-beef-bowls",
        "needles": ("korean ground beef bowls", "korean beef rice bowls", "gochujang ground beef"),
        "title": "Korean-Style Ground Beef Rice Bowls",
        "description": "Savoury ground beef is glazed with soy, garlic, ginger and a little gochujang, then served over rice with crunchy cucumber and sesame.",
        "tags": ["dinner", "beef", "rice bowl", "high protein", "quick-and-easy"],
        "ingredients": ["450 g lean ground beef", "2 cups cooked rice", "2 tablespoons low-sodium soy sauce", "1 tablespoon gochujang", "1 tablespoon honey", "2 garlic cloves, minced", "1 teaspoon grated fresh ginger", "1 teaspoon sesame oil", "1 cucumber, thinly sliced", "2 spring onions, sliced", "1 teaspoon toasted sesame seeds"],
        "instructions": ["Whisk the soy sauce, gochujang and honey together in a small bowl.", "Heat a large skillet over medium-high heat. Add the ground beef and cook for 6–8 minutes, breaking it into small pieces, until no pink remains and it reaches 71°C (160°F). Drain excess fat if needed.", "Add the garlic and ginger and cook for 30 seconds until fragrant.", "Pour in the sauce and simmer for 1–2 minutes, stirring until the beef is glossy and fully coated.", "Divide the rice between bowls. Spoon over the beef and finish with cucumber, spring onions and sesame seeds."],
        "prep_minutes": 10, "cook_minutes": 12, "servings": 4,
    },
    {
        "key": "air-fryer-salmon-bites",
        "needles": ("air fryer salmon bites", "crispy salmon bites", "salmon bites"),
        "title": "Air Fryer Salmon Bites with Lemon Yogurt",
        "description": "Bite-sized salmon pieces turn golden in the air fryer and are served with a cool lemon-yogurt dip, cucumber and warm grains.",
        "tags": ["dinner", "salmon", "seafood", "air fryer", "fresh-and-green"],
        "ingredients": ["450 g skinless salmon fillet, cut into 2.5 cm cubes", "1 tablespoon olive oil", "1 teaspoon smoked paprika", "1/2 teaspoon garlic powder", "1/2 teaspoon fine salt", "1/2 cup plain Greek yogurt", "1 tablespoon lemon juice", "1 teaspoon lemon zest", "2 cups cooked quinoa or rice", "1 cucumber, diced", "1 tablespoon chopped dill"],
        "instructions": ["Preheat the air fryer to 200°C (400°F) for 3 minutes.", "Pat the salmon cubes dry. Toss with olive oil, smoked paprika, garlic powder and salt.", "Arrange salmon in a single layer in the air-fryer basket. Cook for 7–9 minutes, shaking once, until the centre reaches 63°C (145°F) and the edges are lightly crisp.", "Stir the Greek yogurt with lemon juice, lemon zest and dill to make the dip.", "Serve the salmon over warm quinoa or rice with cucumber and the lemon-yogurt dip."],
        "prep_minutes": 12, "cook_minutes": 9, "servings": 2,
    },
    {
        "key": "crispy-potato-black-bean-tacos",
        "needles": ("crispy potato tacos", "potato black bean tacos", "crispy potato tacos black beans"),
        "title": "Crispy Potato and Black Bean Tacos",
        "description": "Spiced roast potatoes and warm black beans fill crisp-edged tortillas with cabbage, lime and a quick smoky yogurt sauce.",
        "tags": ["dinner", "vegetarian", "tacos", "comfort-food"],
        "ingredients": ["500 g potatoes, cut into 1.5 cm cubes", "1 tablespoon olive oil", "1 teaspoon ground cumin", "1 teaspoon smoked paprika", "1/2 teaspoon fine salt", "1 can (400 g) black beans, drained and rinsed", "8 small corn tortillas", "1 cup finely shredded red cabbage", "1/2 cup plain Greek yogurt", "1 tablespoon lime juice", "1/2 teaspoon chipotle powder"],
        "instructions": ["Heat the oven to 220°C (425°F). Toss the potatoes with olive oil, cumin, smoked paprika and salt.", "Spread the potatoes on a lined baking tray and roast for 25–30 minutes, turning once, until golden and crisp.", "Warm the black beans in a small saucepan with a splash of water for 3–4 minutes.", "Mix the Greek yogurt with lime juice and chipotle powder to make a smoky sauce.", "Warm the tortillas in a dry skillet. Fill with roast potatoes, black beans and cabbage, then drizzle with the sauce."],
        "prep_minutes": 12, "cook_minutes": 30, "servings": 4,
    },
    {
        "key": "honey-garlic-halloumi-bowls",
        "needles": ("honey garlic halloumi bowls", "halloumi veggie bowls", "crispy halloumi bowls"),
        "title": "Honey Garlic Halloumi and Veggie Bowls",
        "description": "Golden halloumi is tossed in a light honey-garlic glaze and paired with roasted vegetables, grains and a bright lemon dressing.",
        "tags": ["dinner", "halloumi", "vegetarian", "fresh-and-green"],
        "ingredients": ["250 g halloumi, cut into 1 cm slices", "1 tablespoon olive oil", "1 red bell pepper, sliced", "1 courgette, sliced", "1 red onion, cut into wedges", "2 cups cooked couscous or quinoa", "1 tablespoon honey", "1 garlic clove, minced", "1 tablespoon lemon juice", "1 teaspoon lemon zest", "2 tablespoons chopped parsley"],
        "instructions": ["Heat the oven to 210°C (410°F). Toss the pepper, courgette and onion with half the olive oil and roast for 18–22 minutes until tender and lightly browned.", "Whisk the honey, garlic, lemon juice and lemon zest in a small bowl.", "Heat the remaining oil in a non-stick skillet over medium heat. Cook the halloumi for 1–2 minutes per side until golden.", "Pour the honey-garlic mixture into the skillet and turn the halloumi for 20–30 seconds until lightly glazed.", "Divide the grains and roasted vegetables between bowls. Add the halloumi and finish with parsley."],
        "prep_minutes": 12, "cook_minutes": 22, "servings": 2,
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
