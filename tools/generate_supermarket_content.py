"""Generate the supermarket cardset's cards, pack, recipes, and bake tasks.

The authored source of truth is the table in this module. The emitted YAML and
JSON live beside the cardset art so the runtime can load them directly.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CARDSET_DIR = REPO_ROOT / "data" / "cardsets" / "supermarket"
CARD_ART_SIZE = 768
CARD_SEED_BASE = 92000
PACK_BACK = "supermarket-pack-back.png"

QWEN_STYLE = "flat vector illustration, clean bold shapes, cheerful supermarket storybook style"
NO_TEXT = "no text, no letters, no words, no numbers, no captions, no labels, no watermark, textless image"


PRODUCE: tuple[tuple[str, str], ...] = (
    ("carrot", "Carrot"),
    ("potato", "Potato"),
    ("onion", "Onion"),
    ("garlic", "Garlic"),
    ("tomato", "Tomato"),
    ("lettuce", "Lettuce"),
    ("spinach", "Spinach"),
    ("broccoli", "Broccoli"),
    ("cauliflower", "Cauliflower"),
    ("bell-pepper", "Bell Pepper"),
    ("chili-pepper", "Chili Pepper"),
    ("cucumber", "Cucumber"),
    ("zucchini", "Zucchini"),
    ("eggplant", "Eggplant"),
    ("pumpkin", "Pumpkin"),
    ("corn", "Sweet Corn"),
    ("peas", "Green Peas"),
    ("green-beans", "Green Beans"),
    ("mushroom", "Mushroom"),
    ("celery", "Celery"),
    ("kale", "Kale"),
    ("sweet-potato", "Sweet Potato"),
    ("ginger", "Ginger"),
    ("lemon", "Lemon"),
    ("apple", "Apple"),
    ("banana", "Banana"),
    ("strawberry", "Strawberry"),
    ("blueberry", "Blueberry"),
    ("avocado", "Avocado"),
    ("basil", "Basil"),
    ("coconut", "Coconut"),
)

GROCERIES: tuple[tuple[str, str], ...] = (
    ("water", "Spring Water"),
    ("flour", "Flour"),
    ("sugar", "Sugar"),
    ("salt", "Salt"),
    ("black-pepper", "Black Pepper"),
    ("olive-oil", "Olive Oil"),
    ("butter", "Butter"),
    ("milk", "Milk"),
    ("cream", "Cream"),
    ("cheese", "Cheese"),
    ("egg", "Egg"),
    ("yeast", "Yeast"),
    ("baking-powder", "Baking Powder"),
    ("vanilla-extract", "Vanilla Extract"),
    ("honey", "Honey"),
    ("rice", "Rice"),
    ("pasta", "Dry Pasta"),
    ("noodles", "Noodles"),
    ("bread", "Bread"),
    ("breadcrumbs", "Breadcrumbs"),
    ("vinegar", "Vinegar"),
    ("soy-sauce", "Soy Sauce"),
    ("ketchup", "Ketchup"),
    ("mayonnaise", "Mayonnaise"),
    ("mustard", "Mustard"),
    ("yogurt", "Yogurt"),
    ("oats", "Oats"),
    ("cereal", "Cereal"),
    ("chocolate", "Chocolate"),
    ("cocoa", "Cocoa Powder"),
    ("coffee", "Coffee"),
    ("tea", "Tea"),
    ("chickpeas", "Chickpeas"),
    ("chicken", "Chicken"),
    ("beef", "Beef"),
    ("bacon", "Bacon"),
    ("fish", "Fish"),
    ("tofu", "Tofu"),
    ("coconut-milk", "Coconut Milk"),
)

CRAFTED: tuple[tuple[str, str], ...] = (
    ("chopped-vegetables", "Chopped Vegetables"),
    ("tomato-paste", "Tomato Paste"),
    ("tomato-sauce", "Tomato Sauce"),
    ("vegetable-stock", "Vegetable Stock"),
    ("bread-dough", "Bread Dough"),
    ("pasta-dough", "Pasta Dough"),
    ("salad-dressing", "Salad Dressing"),
    ("cooked-rice", "Cooked Rice"),
    ("mashed-potatoes", "Mashed Potatoes"),
    ("pie-crust", "Pie Crust"),
    ("cake-batter", "Cake Batter"),
    ("cookie-dough", "Cookie Dough"),
    ("pesto", "Pesto"),
    ("hummus", "Hummus"),
    ("smoothie-base", "Smoothie Base"),
    ("curry-paste", "Curry Paste"),
)

DISHES: tuple[tuple[str, str, str, int], ...] = (
    ("omelette", "Omelette", "Rare", 25),
    ("fish-and-chips", "Fish and Chips", "Rare", 30),
    ("cooked-pasta", "Cooked Pasta", "Rare", 20),
    ("baked-bread", "Baked Bread", "Rare", 18),
    ("pizza", "Pizza", "Epic", 40),
    ("apple-pie", "Apple Pie", "Epic", 30),
    ("cake", "Celebration Cake", "Epic", 35),
    ("cookies", "Cookies", "Rare", 20),
    ("blueberry-muffins", "Blueberry Muffins", "Rare", 22),
    ("roasted-vegetables", "Roasted Vegetables", "Rare", 20),
    ("garden-salad", "Garden Salad", "Rare", 18),
    ("soup", "Vegetable Soup", "Rare", 24),
    ("stir-fry", "Tofu Stir-Fry", "Rare", 24),
    ("curry", "Chicken Curry", "Epic", 40),
)

MEDICINES: tuple[tuple[str, str, str, str, int, int], ...] = (
    ("bandage", "Bandage", "Common", "health", 10, 1),
    ("painkillers", "Painkillers", "Common", "health", 15, 2),
    ("cough-syrup", "Cough Syrup", "Common", "health", 10, 1),
    ("vitamins", "Vitamins", "Uncommon", "health", 15, 2),
    ("antiseptic-cream", "Antiseptic Cream", "Uncommon", "health", 20, 3),
    ("cold-pack", "Cold Pack", "Common", "health", 10, 1),
    ("herbal-tea", "Herbal Tea", "Common", "health", 10, 1),
    ("stomach-settler", "Stomach Settler", "Uncommon", "health", 15, 2),
)



QUIPS: dict[str, str] = {
    "carrot": "Crunchy, orange, and absolutely certain it helps you see in the dark.",
    "potato": "A lumpy little multitasker. Boil it, mash it, or hide it in a sock.",
    "onion": "Sweet until betrayed. Keep a tissue nearby.",
    "garlic": "Breath weapon first, flavor second.",
    "tomato": "Technically a fruit. Emotionally a ketchup delivery system.",
    "lettuce": "Mostly water with a crisp attitude.",
    "spinach": "Leafy greens with a sudden burst of cartoon strength.",
    "broccoli": "A tiny tree that tastes better than it looks. Usually.",
    "cauliflower": "Broccoli's pale cousin, plotting a comeback.",
    "bell-pepper": "Crunchy, colorful, and hollow enough to stuff with secrets.",
    "chili-pepper": "A small pepper with strong opinions about your tongue.",
    "cucumber": "Cool, crisp, and mostly water. The rest is smugness.",
    "zucchini": "A garden zucchini. There is always another one.",
    "eggplant": "Purple, glossy, and deeply misunderstood.",
    "pumpkin": "A big orange vegetable with autumn on the brain.",
    "corn": "A row of tiny yellow teeth that tastes like summer.",
    "peas": "Small, green, and impossible to eat one at a time.",
    "green-beans": "Long, snappy, and ready for a casserole argument.",
    "mushroom": "A mysterious little umbrella from the shady part of the forest.",
    "celery": "Crunchy water with a built-in handle.",
    "kale": "Extremely leafy. Extremely pleased with itself.",
    "sweet-potato": "A potato that went to the beach and came back orange.",
    "ginger": "A knobby root with a spicy kick and zero patience.",
    "lemon": "A sunny citrus with a sour personality.",
    "apple": "A crisp classic. Keep the doctor confused.",
    "banana": "Nature's pocket snack, with a built-in wrapper.",
    "strawberry": "A tiny red heart with seeds on the outside.",
    "blueberry": "A blue little bomb of juice and purple fingers.",
    "avocado": "Creamy green gold. Toast's best friend.",
    "basil": "A fragrant little leaf that thinks it runs the kitchen.",
    "coconut": "A hairy sphere with a refreshing secret inside.",
    "water": "Bottled water. Fancy, but still mostly water.",
    "flour": "A bag of dust that becomes bread with enough encouragement.",
    "sugar": "Sweet, sparkly, and dangerously easy to spill.",
    "salt": "A tiny crystal that makes everything taste more like itself.",
    "black-pepper": "A sneeze waiting to happen, but in a good way.",
    "olive-oil": "Liquid sunshine for pans, salads, and dramatic drizzles.",
    "butter": "A golden brick of culinary confidence.",
    "milk": "A dependable white drink. Cookies approve.",
    "cream": "Milk that went to finishing school.",
    "cheese": "Aged, salty, and always ready to melt under pressure.",
    "egg": "A small oval miracle with a shell.",
    "yeast": "Tiny organisms with a big rise-and-shine attitude.",
    "baking-powder": "The reason your pancakes have ambitions.",
    "vanilla-extract": "A tiny bottle of expensive-smelling magic.",
    "honey": "Sticky sunshine from very busy bees.",
    "rice": "Tiny grains that multiply in the pot like magic.",
    "pasta": "A bag of dry noodles waiting for a hot bath.",
    "noodles": "Long, slurpable, and dangerously fun to twirl.",
    "bread": "A loaf of everyday heroism. Toast it.",
    "breadcrumbs": "Yesterday's bread, now with a career in coating.",
    "vinegar": "Sharp, sour, and surprisingly good at making pickles.",
    "soy-sauce": "A salty little bottle of umami.",
    "ketchup": "Tomato's loud, tangy cousin.",
    "mayonnaise": "A creamy condiment with a mysterious ingredient list.",
    "mustard": "Yellow, tangy, and not afraid to make a face.",
    "yogurt": "Creamy, tangy, and full of friendly bacteria.",
    "oats": "A bowl of tiny flakes that sticks to your ribs.",
    "cereal": "A box of breakfast optimism and cartoon mascots.",
    "chocolate": "A square of happiness with a melt-in-your-mouth plan.",
    "cocoa": "Chocolate's dusty, unsweetened ancestor.",
    "coffee": "A bitter little bean that powers the whole school.",
    "tea": "A cozy cup of leaf water with big opinions.",
    "chickpeas": "Little round legumes plotting to become hummus.",
    "chicken": "A dependable dinner with feathers removed.",
    "beef": "A hearty cut for serious cooking.",
    "bacon": "Crispy, salty, and impossible to resist.",
    "fish": "A slippery supper that goes well with chips.",
    "tofu": "A mild-mannered block that absorbs everyone else's personality.",
    "coconut-milk": "Tropical cream in a can. Shake well.",
    "chopped-vegetables": "A colorful pile of chopped things. Very chef-like.",
    "tomato-paste": "Tomatoes concentrated into a tiny red powerhouse.",
    "tomato-sauce": "A smooth red sauce with big pizza energy.",
    "vegetable-stock": "Liquid vegetable wisdom, ready for soup.",
    "bread-dough": "A bouncy dough that has clearly been working out.",
    "pasta-dough": "A springy dough just waiting to be rolled.",
    "salad-dressing": "A glossy dressing that makes lettuce feel important.",
    "cooked-rice": "Fluffy rice, ready to soak up whatever comes next.",
    "mashed-potatoes": "A creamy mountain of buttery comfort.",
    "pie-crust": "A flaky crust with a golden future.",
    "cake-batter": "Sweet batter with a dangerous raw-spoon temptation.",
    "cookie-dough": "Cookie dough. Yes, it is a food. Move along.",
    "pesto": "A bright green sauce with a garlicky attitude.",
    "hummus": "A creamy chickpea dip with a lemony wink.",
    "smoothie-base": "A thick fruit blend. Add milk and a tiny umbrella.",
    "curry-paste": "A fiery paste with a very strong personality.",
    "omelette": "A folded egg masterpiece, best served with a proud little flourish.",
    "fish-and-chips": "Crispy fish meets golden chips. A classic double act.",
    "cooked-pasta": "Tender pasta, ready for sauce, cheese, or a dramatic twirl.",
    "baked-bread": "A warm loaf with a crust that crackles when you cut it.",
    "pizza": "A cheesy, saucy disc of pure happiness.",
    "apple-pie": "Sweet apples under a golden crust. A dessert legend.",
    "cake": "A tall cake for celebrating absolutely anything.",
    "cookies": "Warm cookies with melty chocolate pockets.",
    "blueberry-muffins": "Little blueberry treasures in a tender muffin coat.",
    "roasted-vegetables": "Caramelized vegetables, accidentally eaten straight from the pan.",
    "garden-salad": "A crisp garden in a bowl, with dressing invited.",
    "soup": "A warm bowl of soup. Soup fixes most things.",
    "stir-fry": "A fast, sizzling pan of vegetables and tofu.",
    "curry": "A rich, glowing curry with just enough kick.",
    "bandage": "A classic sticky strip for life's little paper cuts.",
    "painkillers": "A tiny tablet with a big 'not today, headache' energy.",
    "cough-syrup": "A syrupy cough medicine with a lingering licorice grudge.",
    "vitamins": "A bright little tablet that promises to fix your whole day.",
    "antiseptic-cream": "A cooling cream that stings just enough to feel useful.",
    "cold-pack": "A squishy cold pack for bumps, bruises, and dramatic sighs.",
    "herbal-tea": "A soothing cup of herbs. Sometimes the best medicine is a sit-down.",
    "stomach-settler": "A chalky little helper for a tummy that has seen things.",
}

RECIPE_QUIPS: dict[str, str] = {
    "market-chopped-vegetables": "Chop three vegetables and feel instantly qualified for a cooking show.",
    "market-tomato-paste": "Squash three tomatoes until they confess.",
    "market-tomato-sauce": "Onion and garlic argue; tomato smooths things over.",
    "market-vegetable-stock": "Vegetables give their last words to a pot of water.",
    "market-bread-dough": "Flour, water, yeast, sugar. Now do some kneading.",
    "market-pasta-dough": "Roll it thin, or roll it thick. Pasta is forgiving.",
    "market-salad-dressing": "Oil and vinegar make up, with mustard as the mediator.",
    "market-cooked-rice": "Rice plus water plus heat equals dinner's dependable sidekick.",
    "market-mashed-potatoes": "Potatoes surrender to butter and milk. Deliciously.",
    "market-pie-crust": "Butter and flour become a flaky little stage for fruit.",
    "market-cake-batter": "Beat everything together. Lick the spoon at your own risk.",
    "market-cookie-dough": "The dough is technically for cookies. Technically.",
    "market-pesto": "Basil, cheese, oil, garlic. Blend until aggressively green.",
    "market-hummus": "Chickpeas blend into a creamy, lemony crowd-pleaser.",
    "market-smoothie-base": "Strawberries and banana surrender to the blender.",
    "market-curry-paste": "Pound the spices until they promise to behave.",
    "market-omelette": "Fold the eggs before they get any ideas.",
    "market-fish-and-chips": "Fish, potatoes, and hot oil. A very good decision.",
    "market-cooked-pasta": "Boil the fresh pasta until it still has a little bounce.",
    "market-baked-bread": "A loaf rises. The kitchen smells like a hug.",
    "market-pizza": "Sauce, cheese, dough. Bake until the cheese believes in itself.",
    "market-apple-pie": "Apples, sugar, and a crust. A pie with strong opinions.",
    "market-cake": "Batter in, cake out. Somehow, that is always surprising.",
    "market-cookies": "Scoop, bake, and guard the tray with your life.",
    "market-blueberry-muffins": "Blueberries hide inside tender little muffins. Sneaky.",
    "market-roasted-vegetables": "Chopped vegetables get crispy edges and main-character energy.",
    "market-garden-salad": "Toss everything together until the salad looks intentional.",
    "market-soup": "Stock, vegetables, noodles. Simmer until the room smells like home.",
    "market-stir-fry": "Hot pan, fast hands, tofu that finally gets some flavor.",
    "market-curry": "Curry paste, chicken, coconut milk, rice. Dinner with a warm glow.",
}

RECIPES: tuple[dict[str, object], ...] = (
    {
        "id": "market-chopped-vegetables",
        "label": "Chop vegetables",
        "description": "A tidy pile of carrot, onion, and celery ready for the pot.",
        "station": "prep-table",
        "ingredients": {"market-carrot": 2, "market-onion": 1, "market-celery": 1},
        "output": {"market-chopped-vegetables": 1},
        "energy_cost": 2,
    },
    {
        "id": "market-tomato-paste",
        "label": "Make tomato paste",
        "description": "Reduce ripe tomatoes into a thick, sweet paste.",
        "station": "prep-table",
        "ingredients": {"market-tomato": 3},
        "output": {"market-tomato-paste": 1},
        "energy_cost": 2,
    },
    {
        "id": "market-tomato-sauce",
        "label": "Simmer tomato sauce",
        "description": "Tomato, onion, garlic, and olive oil cooked into a smooth sauce.",
        "station": "prep-table",
        "ingredients": {"market-tomato": 2, "market-onion": 1, "market-garlic": 1, "market-olive-oil": 1},
        "output": {"market-tomato-sauce": 1},
        "energy_cost": 3,
    },
    {
        "id": "market-vegetable-stock",
        "label": "Brew vegetable stock",
        "description": "A savory base simmered from carrot, onion, and celery.",
        "station": "prep-table",
        "ingredients": {
            "market-carrot": 1,
            "market-onion": 1,
            "market-celery": 1,
            "market-water": 1,
            "market-salt": 1,
        },
        "output": {"market-vegetable-stock": 1},
        "energy_cost": 3,
    },
    {
        "id": "market-bread-dough",
        "label": "Knead bread dough",
        "description": "Flour, water, yeast, and sugar worked into a springy dough.",
        "station": "prep-table",
        "ingredients": {
            "market-flour": 2,
            "market-water": 1,
            "market-yeast": 1,
            "market-sugar": 1,
        },
        "output": {"market-bread-dough": 1},
        "energy_cost": 4,
    },
    {
        "id": "market-pasta-dough",
        "label": "Roll pasta dough",
        "description": "A simple egg pasta dough, ready to shape.",
        "station": "prep-table",
        "ingredients": {"market-flour": 2, "market-egg": 1, "market-olive-oil": 1},
        "output": {"market-pasta-dough": 1},
        "energy_cost": 3,
    },
    {
        "id": "market-salad-dressing",
        "label": "Whisk salad dressing",
        "description": "Oil, vinegar, mustard, and honey whisked into a glossy dressing.",
        "station": "prep-table",
        "ingredients": {
            "market-olive-oil": 1,
            "market-vinegar": 1,
            "market-mustard": 1,
            "market-honey": 1,
        },
        "output": {"market-salad-dressing": 1},
        "energy_cost": 2,
    },
    {
        "id": "market-cooked-rice",
        "label": "Steam rice",
        "description": "Fluffy rice, steamed and ready to serve.",
        "station": "prep-table",
        "ingredients": {"market-rice": 1, "market-water": 1},
        "output": {"market-cooked-rice": 1},
        "energy_cost": 2,
    },
    {
        "id": "market-mashed-potatoes",
        "label": "Mash potatoes",
        "description": "Potatoes mashed with butter and milk until silky.",
        "station": "prep-table",
        "ingredients": {"market-potato": 2, "market-butter": 1, "market-milk": 1},
        "output": {"market-mashed-potatoes": 1},
        "energy_cost": 3,
    },
    {
        "id": "market-pie-crust",
        "label": "Make pie crust",
        "description": "A buttery, flaky crust rolled and ready for filling.",
        "station": "prep-table",
        "ingredients": {"market-flour": 2, "market-butter": 1, "market-salt": 1},
        "output": {"market-pie-crust": 1},
        "energy_cost": 3,
    },
    {
        "id": "market-cake-batter",
        "label": "Mix cake batter",
        "description": "A smooth batter ready for the oven.",
        "station": "mixer",
        "ingredients": {
            "market-flour": 2,
            "market-sugar": 1,
            "market-butter": 1,
            "market-egg": 2,
        },
        "output": {"market-cake-batter": 1},
        "energy_cost": 4,
    },
    {
        "id": "market-cookie-dough",
        "label": "Mix cookie dough",
        "description": "Buttery cookie dough studded with chocolate.",
        "station": "mixer",
        "ingredients": {
            "market-flour": 2,
            "market-sugar": 1,
            "market-butter": 1,
            "market-chocolate": 1,
        },
        "output": {"market-cookie-dough": 1},
        "energy_cost": 4,
    },
    {
        "id": "market-pesto",
        "label": "Blend pesto",
        "description": "Basil, olive oil, cheese, and garlic blended into a bright green sauce.",
        "station": "mixer",
        "ingredients": {
            "market-basil": 2,
            "market-olive-oil": 1,
            "market-cheese": 1,
            "market-garlic": 1,
        },
        "output": {"market-pesto": 1},
        "energy_cost": 3,
    },
    {
        "id": "market-hummus",
        "label": "Blend hummus",
        "description": "Chickpeas, olive oil, lemon, and garlic blended until creamy.",
        "station": "mixer",
        "ingredients": {
            "market-chickpeas": 2,
            "market-olive-oil": 1,
            "market-lemon": 1,
            "market-garlic": 1,
        },
        "output": {"market-hummus": 1},
        "energy_cost": 3,
    },
    {
        "id": "market-smoothie-base",
        "label": "Blend smoothie base",
        "description": "Banana, strawberries, and yogurt blended smooth.",
        "station": "mixer",
        "ingredients": {
            "market-banana": 1,
            "market-strawberry": 2,
            "market-yogurt": 1,
        },
        "output": {"market-smoothie-base": 1},
        "energy_cost": 3,
    },
    {
        "id": "market-curry-paste",
        "label": "Pound curry paste",
        "description": "Chili, ginger, garlic, and tomato pounded into a fragrant paste.",
        "station": "mixer",
        "ingredients": {
            "market-chili-pepper": 1,
            "market-ginger": 1,
            "market-garlic": 1,
            "market-tomato": 2,
        },
        "output": {"market-curry-paste": 1},
        "energy_cost": 3,
    },
    {
        "id": "market-omelette",
        "label": "Fold an omelette",
        "description": "Eggs, milk, and cheese folded into a warm omelette.",
        "station": "oven",
        "ingredients": {"market-egg": 2, "market-milk": 1, "market-cheese": 1},
        "output": {"market-omelette": 1},
        "energy_cost": 4,
    },
    {
        "id": "market-fish-and-chips",
        "label": "Fry fish and chips",
        "description": "Crispy fish and golden potatoes, fresh from the oven.",
        "station": "oven",
        "ingredients": {
            "market-fish": 1,
            "market-potato": 2,
            "market-flour": 1,
            "market-olive-oil": 1,
        },
        "output": {"market-fish-and-chips": 1},
        "energy_cost": 5,
    },
    {
        "id": "market-cooked-pasta",
        "label": "Cook pasta",
        "description": "Fresh pasta dough boiled until tender.",
        "station": "prep-table",
        "ingredients": {"market-pasta-dough": 1, "market-water": 1, "market-salt": 1},
        "output": {"market-cooked-pasta": 1},
        "energy_cost": 4,
    },
    {
        "id": "market-baked-bread",
        "label": "Bake bread",
        "description": "A warm loaf with a crisp crust.",
        "station": "oven",
        "ingredients": {"market-bread-dough": 1},
        "output": {"market-baked-bread": 1},
        "energy_cost": 5,
    },
    {
        "id": "market-pizza",
        "label": "Bake a pizza",
        "description": "Dough, tomato sauce, and plenty of cheese baked together.",
        "station": "oven",
        "ingredients": {
            "market-bread-dough": 1,
            "market-tomato-sauce": 1,
            "market-cheese": 2,
        },
        "output": {"market-pizza": 1},
        "energy_cost": 8,
    },
    {
        "id": "market-apple-pie",
        "label": "Bake an apple pie",
        "description": "Sweet apples tucked into a golden crust.",
        "station": "oven",
        "ingredients": {
            "market-pie-crust": 1,
            "market-apple": 2,
            "market-sugar": 1,
        },
        "output": {"market-apple-pie": 1},
        "energy_cost": 7,
    },
    {
        "id": "market-cake",
        "label": "Bake a cake",
        "description": "A tall, celebratory cake fresh from the oven.",
        "station": "oven",
        "ingredients": {"market-cake-batter": 1},
        "output": {"market-cake": 1},
        "energy_cost": 8,
    },
    {
        "id": "market-cookies",
        "label": "Bake cookies",
        "description": "A tray of warm chocolate chip cookies.",
        "station": "oven",
        "ingredients": {"market-cookie-dough": 1},
        "output": {"market-cookies": 2},
        "energy_cost": 6,
    },
    {
        "id": "market-blueberry-muffins",
        "label": "Bake blueberry muffins",
        "description": "Light muffins bursting with blueberries.",
        "station": "oven",
        "ingredients": {"market-cake-batter": 1, "market-blueberry": 2},
        "output": {"market-blueberry-muffins": 2},
        "energy_cost": 7,
    },
    {
        "id": "market-roasted-vegetables",
        "label": "Roast vegetables",
        "description": "Chopped vegetables roasted with olive oil and salt.",
        "station": "oven",
        "ingredients": {
            "market-chopped-vegetables": 1,
            "market-olive-oil": 1,
            "market-salt": 1,
        },
        "output": {"market-roasted-vegetables": 1},
        "energy_cost": 5,
    },
    {
        "id": "market-garden-salad",
        "label": "Toss a garden salad",
        "description": "Crisp lettuce, tomato, and cucumber with fresh dressing.",
        "station": "prep-table",
        "ingredients": {
            "market-salad-dressing": 1,
            "market-lettuce": 2,
            "market-tomato": 1,
            "market-cucumber": 1,
        },
        "output": {"market-garden-salad": 1},
        "energy_cost": 5,
    },
    {
        "id": "market-soup",
        "label": "Simmer vegetable soup",
        "description": "Stock, chopped vegetables, and noodles simmered into a cozy soup.",
        "station": "prep-table",
        "ingredients": {
            "market-vegetable-stock": 1,
            "market-chopped-vegetables": 1,
            "market-noodles": 1,
        },
        "output": {"market-soup": 1},
        "energy_cost": 6,
    },
    {
        "id": "market-stir-fry",
        "label": "Sizzle a stir-fry",
        "description": "Chopped vegetables and tofu tossed with soy sauce.",
        "station": "prep-table",
        "ingredients": {
            "market-chopped-vegetables": 1,
            "market-tofu": 1,
            "market-soy-sauce": 1,
        },
        "output": {"market-stir-fry": 1},
        "energy_cost": 5,
    },
    {
        "id": "market-curry",
        "label": "Cook chicken curry",
        "description": "Curry paste, chicken, and coconut milk over steamed rice.",
        "station": "prep-table",
        "ingredients": {
            "market-curry-paste": 1,
            "market-chicken": 1,
            "market-coconut-milk": 1,
            "market-cooked-rice": 1,
        },
        "output": {"market-curry": 1},
        "energy_cost": 8,
    },
)


def _yscalar(text: str) -> str:
    return json.dumps(str(text))


def _card_id(slug: str) -> str:
    return f"market-{slug}"


def _description(slug: str, label: str, category: str) -> str:
    if slug in QUIPS:
        return QUIPS[slug]
    if category == "produce":
        return f"A fresh {label.lower()} from the supermarket produce aisle."
    if category == "grocery":
        return f"An everyday pantry staple for home cooking: {label.lower()}."
    if category == "crafted":
        return f"A prepared {label.lower()}, ready for the next recipe."
    if category == "dish":
        return f"A finished {label.lower()}. Use it for a quick boost of Energy."
    return f"A basic {label.lower()} that helps you recover."


def _art_prompt(label: str, category: str) -> str:
    hints = {
        "produce": "fresh produce, cheerful market display illustration",
        "grocery": "packaged pantry staple, clean product illustration",
        "crafted": "prepared food ingredient in a small bowl or jar",
        "dish": "a plated finished dish, appetizing and colorful",
        "medicine": "a friendly medicine package, clean pharmacy illustration",
    }
    return f"a centered supermarket card illustration of {label.lower()}, {hints[category]}, {QWEN_STYLE}, plain warm cream background, {NO_TEXT}"


def _card_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, (slug, label) in enumerate(PRODUCE):
        rows.append(
            {
                "id": _card_id(slug),
                "label": label,
                "slug": slug,
                "description": _description(slug, label, "produce"),
                "category": "produce",
                "rarity": "Common",
                "energy": 5 + index % 4,
                "tags": ["supermarket", "food", "produce"],
            }
        )
    for index, (slug, label) in enumerate(GROCERIES):
        rows.append(
            {
                "id": _card_id(slug),
                "label": label,
                "slug": slug,
                "description": _description(slug, label, "grocery"),
                "category": "grocery",
                "rarity": "Common",
                "energy": 6 + index % 5,
                "tags": ["supermarket", "food", "ingredient"],
            }
        )
    for index, (slug, label) in enumerate(CRAFTED):
        rows.append(
            {
                "id": _card_id(slug),
                "label": label,
                "slug": slug,
                "description": _description(slug, label, "crafted"),
                "category": "crafted",
                "rarity": "Uncommon",
                "energy": 10 + index % 6,
                "tags": ["supermarket", "food", "crafted-ingredient"],
            }
        )
    for slug, label, rarity, energy in DISHES:
        rows.append(
            {
                "id": _card_id(slug),
                "label": label,
                "slug": slug,
                "description": _description(slug, label, "dish"),
                "category": "dish",
                "rarity": rarity,
                "energy": energy,
                "tags": ["supermarket", "food", "dish"],
            }
        )
    for slug, label, rarity, effect, amount, energy_cost in MEDICINES:
        rows.append(
            {
                "id": _card_id(slug),
                "label": label,
                "slug": slug,
                "description": _description(slug, label, "medicine"),
                "category": "medicine",
                "rarity": rarity,
                "effect": effect,
                "amount": amount,
                "energy_cost": energy_cost,
                "tags": ["supermarket", "medicine", "utility"],
            }
        )
    return rows

def write_cards() -> list[dict[str, object]]:
    CARDSET_DIR.mkdir(parents=True, exist_ok=True)
    rows = _card_rows()
    lines = ["# Generated by tools/generate_supermarket_content.py", ""]
    for row in rows:
        card_id = str(row["id"])
        lines += [
            f"{card_id}:",
            f"  label: {_yscalar(str(row['label']))}",
            f"  description: {_yscalar(str(row['description']))}",
            f"  image: {card_id}.png",
            "  type: item",
            f"  rarity: {row['rarity']}",
            f"  tags: [{', '.join(row['tags'])}]",
        ]
        if row["category"] == "medicine":
            lines += [
                "  one_use: true",
                f"  energy_cost: {row['energy_cost']}",
                "  target: self",
                f"  effect: {row['effect']}",
                f"  amount: {row['amount']}",
            ]
        else:
            lines += [
                "  one_use: true",
                "  energy_cost: 0",
                "  target: self",
                "  effect: energy",
                f"  amount: {row['energy']}",
            ]
        lines.append("")
    (CARDSET_DIR / "cards.yaml").write_text("\n".join(lines), encoding="utf-8")
    return rows


def write_pack(rows: list[dict[str, object]]) -> None:
    card_ids = [str(row["id"]) for row in rows]
    lines = [
        "# Generated by tools/generate_supermarket_content.py",
        "label: Tinyrooms Supermarket Pack",
        "description: Everyday ingredients, comforting dishes, and basic medicines from the supermarket.",
        f"back_image: {PACK_BACK}",
        "price: 10",
        "size: 3",
        f"cards: [{', '.join(card_ids)}]",
        "",
    ]
    (CARDSET_DIR / "pack.yaml").write_text("\n".join(lines), encoding="utf-8")


def write_recipes() -> None:
    lines = ["# Generated by tools/generate_supermarket_content.py", ""]
    for recipe in RECIPES:
        ingredients = ", ".join(f"{card_id}: {quantity}" for card_id, quantity in recipe["ingredients"].items())
        output = ", ".join(f"{card_id}: {quantity}" for card_id, quantity in recipe["output"].items())
        lines += [
            f"{recipe['id']}:",
            f"  label: {_yscalar(str(recipe['label']))}",
            f"  description: {_yscalar(RECIPE_QUIPS.get(str(recipe['id']), str(recipe['description'])))}",
            f"  station: {recipe['station']}",
            f"  ingredients: {{{ingredients}}}",
            f"  output: {{{output}}}",
            f"  energy_cost: {recipe['energy_cost']}",
            "",
        ]
    (CARDSET_DIR / "recipes.yaml").write_text("\n".join(lines), encoding="utf-8")


def write_bake(rows: list[dict[str, object]]) -> None:
    tasks: list[dict[str, object]] = [
        {
            "label": "supermarket-pack-back",
            "tool": "image",
            "prompt": (
                "a symmetrical collectible card back for a friendly supermarket, showing a "
                "paper grocery bag full of vegetables and a small blue pharmacy cross on a warm "
                f"cream field with a green border, {QWEN_STYLE}, {NO_TEXT}"
            ),
            "output": str(CARDSET_DIR / PACK_BACK).replace("\\", "/"),
            "args": {"width": 768, "height": 1152, "seed": CARD_SEED_BASE - 1, "steps": 25},
        }
    ]
    for index, row in enumerate(rows):
        card_id = str(row["id"])
        tasks.append(
            {
                "label": card_id,
                "tool": "image",
                "prompt": _art_prompt(str(row["label"]), str(row["category"])),
                "output": str(CARDSET_DIR / f"{card_id}.png").replace("\\", "/"),
                "args": {
                    "width": CARD_ART_SIZE,
                    "height": CARD_ART_SIZE,
                    "seed": CARD_SEED_BASE + index,
                    "steps": 25,
                },
            }
        )
    (CARDSET_DIR / "bake.json").write_text(
        json.dumps({"tasks": tasks}, indent=2) + "\n",
        encoding="utf-8",
    )


def write_placeholder_art(rows: list[dict[str, object]]) -> None:
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 30)
    except OSError:
        font = ImageFont.load_default()
    size = 256
    palette = {
        "produce": ("#e7f4dc", "#3f7a36"),
        "grocery": ("#f7ecd2", "#8a5a22"),
        "crafted": ("#e7eef8", "#2f4f7a"),
        "dish": ("#fbe5dc", "#9a3d24"),
        "medicine": ("#e5f2f3", "#2c6b73"),
    }

    for row in rows:
        card_id = str(row["id"])
        label = str(row["label"])
        background, ink = palette[str(row["category"])]
        image = Image.new("RGB", (size, size), background)
        draw = ImageDraw.Draw(image)
        draw.ellipse([20, 20, size - 20, size - 20], outline=ink, width=7)
        words = label.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) > size - 52 and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        y = (size - len(lines) * 36) / 2
        for line in lines:
            width = draw.textlength(line, font=font)
            draw.text(((size - width) / 2, y), line, fill=ink, font=font)
            y += 36
        image.save(CARDSET_DIR / f"{card_id}.png")

    back = Image.new("RGB", (384, 576), "#f6eedb")
    draw = ImageDraw.Draw(back)
    draw.rounded_rectangle([22, 22, 362, 554], radius=22, outline="#3f7a36", width=9)
    draw.rectangle([120, 210, 264, 330], fill="#d9b77a", outline="#7a5224", width=5)
    draw.ellipse([158, 150, 226, 225], fill="#8fbf6a", outline="#3f7a36", width=4)
    draw.text((134, 380), "SUPERMARKET", fill="#3f7a36", font=font)
    back.save(CARDSET_DIR / PACK_BACK)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--art", action="store_true", help="also write placeholder card art")
    args = parser.parse_args()
    rows = write_cards()
    write_pack(rows)
    write_recipes()
    write_bake(rows)
    if args.art:
        write_placeholder_art(rows)
    print(f"generated {len(rows)} cards and {len(RECIPES)} recipes")


if __name__ == "__main__":
    main()
