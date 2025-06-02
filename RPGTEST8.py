import pandas as pd
import random
import textwrap
import math
import sys
from ambient_scene import describe_ambient_scene

# === Load Data ===
def load_biomes(path="data/biomes.csv"):
    df = pd.read_csv(path)
    # Normalize weather probabilities per row to sum to 1.0 (optional safeguard)
    weather_cols = ['clear', 'rain', 'fog', 'storm', 'cold', 'wind']
    df[weather_cols] = df[weather_cols].div(df[weather_cols].sum(axis=1), axis=0)
    return df

def load_items(path="data/items.csv"):
    df = pd.read_csv(path, encoding="ISO-8859-1")  # This tells Python how to read the weird characters
    return {row['name']: row.to_dict() for _, row in df.iterrows()}


# === Game State ===
current_hour = 6
energy = 80
hunger = 80
morale = 70
hours_since_sleep = 0
fire_hours_remaining = 0
has_fire = False
narrative_history = []

# Load biomes and items
biomes_df = load_biomes()
ITEM_DATA = load_items()

# ✅ Load narrative templates for dynamic fill
template_df = pd.read_csv("data/narrative_templates.csv")
recent_templates = {}

# Biome traversal tracking
current_biome_index = 0
current_biome = biomes_df.iloc[current_biome_index]
hours_walked = 0
required_hours = None

identified_items = set()
cooked_items = set()  # For cooking system coming later

# Inventory
inventory = {
    "jerky": 3,
    "flint_and_steel": 1,
    "tinder": 1,
    "pot": 1
}
identified_items.update(inventory.keys())

# === Helper Functions ===
import os
def split_screen(permanent_history, menu_lines, max_menu=25, max_narrative=10, wrap_width=35):
    os.system('cls' if os.name == 'nt' else 'clear')  # Clear terminal screen
    left_width = 45
    right_width = 45

    # Wrap narrative and menu
    wrapped_narrative = []
    for line in permanent_history[-max_narrative:]:
        wrapped_narrative.extend(textwrap.wrap(line, width=wrap_width) or [""])

    wrapped_menu = []
    for line in menu_lines:
        wrapped_menu.extend(textwrap.wrap(line, width=wrap_width) or [""])

    max_lines = max(len(wrapped_narrative), len(wrapped_menu))
    for i in range(max_lines):
        left = wrapped_narrative[i] if i < len(wrapped_narrative) else ""
        right = wrapped_menu[i] if i < len(wrapped_menu) else ""
        print(left.ljust(left_width) + right.ljust(right_width))

class PhraseBuilder:
    def __init__(self, game_state):
        self.s = game_state  # shorthand

    def get(self, key):
        h = self.s['hunger']
        m = self.s['morale']
        e = self.s['energy']
        w = self.s['weather']
        fire = self.s['has_fire']
        biome = self.s['biome']

        return {
            "hunger_level": "you’re starving" if h < 30 else "you’re a bit hungry" if h < 60 else "you feel fine",
            "morale_reaction": "You feel bleak." if m < 30 else "You doubt yourself." if m < 60 else "You’re steady.",
            "energy_feeling": "You move slowly." if e < 40 else "You’re still alert.",
            "weather_feeling": {
                "rain": "Rain clings to your gear.",
                "fog": "The fog dulls everything.",
                "storm": "Thunder rolls overhead.",
                "cold": "Your breath fogs the air.",
                "clear": "The sky is still.",
                "wind": "Wind pushes against you."
            }.get(w, "The weather presses in."),
            "fire_status": "The fire burns low." if fire else "No fire. Just cold.",
            "dream_hint": "Dreams flicker and vanish." if m < 40 else "Sleep holds nothing.",
            "biome": biome["biome_name"] if isinstance(biome, dict) or "biome_name" in biome else str(biome)
        }.get(key, f"<undefined:{key}>")

def fill_template(template_string, game_state):
    pb = PhraseBuilder(game_state)
    while "{" in template_string:
        start = template_string.find("{")
        end = template_string.find("}", start)
        key = template_string[start+1:end]
        phrase = pb.get(key)
        template_string = template_string[:start] + phrase + template_string[end+1:]
    return template_string

def narrative_from_template(context, game_state, max_recent=3, require_stat=False):
    matches = template_df[template_df['context'] == context]

    # If 'type' column exists, use it for filtering
    if 'type' in matches.columns:
        if require_stat:
            matches = matches[matches['type'] == 'stat']
        else:
            matches = matches[matches['type'].isin(['universal', 'stat'])]

    if matches.empty:
        return "You continue in silence."

    recent = recent_templates.get(context, [])
    available = matches[~matches['template'].isin(recent)]
    if available.empty:
        available = matches

    row = available.sample(1).iloc[0]
    template = row['template']

    # Update recent
    recent.append(template)
    if len(recent) > max_recent:
        recent.pop(0)
    recent_templates[context] = recent

    return fill_template(template, game_state)

def choose_word_from_csv(action_type, stat_value, df):
    level = "low" if stat_value < 40 else "med" if stat_value < 75 else "high"
    matches = df[(df["action_type"] == action_type) & (df["level"] == level)]
    if not matches.empty:
        return random.choice(matches["variation"].tolist())
    return "[missing]"

# === Mechanics ===
def morale_change(amount):
    global morale
    morale = max(0, min(100, morale + amount))

def hunger_tick():
    global hunger
    hunger = max(0, hunger - 2)

def fatigue_tick():
    global energy
    energy = max(0, energy - 3)
    if hours_since_sleep > 24:
        morale_change(-5)

def apply_effect(effect_type, value):
    global hunger, morale, energy
    if effect_type == 'food':
        hunger = max(0, min(100, hunger + value))
    elif effect_type == 'morale':
        morale = max(0, min(100, morale + value))
    elif effect_type == 'energy':
        energy = max(0, min(100, energy + value))

def apply_effects(effects):
    for stat, val in effects:
        apply_effect(stat, val)

def purged_in_time():
    # 50% chance of surviving lethal poisoning
    return random.random() < 0.5


def weather_modifier(weather):
    return {
        "clear": 1.0,
        "rain": 1.2,
        "fog": 1.3,
        "storm": 1.4,
        "cold": 1.1,
        "wind": 1.1
    }.get(weather, 1.0)

def weather_effects(weather):
    global energy #This line is required to define the global variable
    if weather == "storm":
        morale_change(-2)
        narrative_history.append("The storm wears on your nerves.")
    elif weather == "cold":
        energy = max(0, energy - 1)
        narrative_history.append("The cold saps your strength.")
    elif weather == "fog":
        morale_change(-1)
    # You can expand this with walking penalties or fire suppression if desired


def elevation_modifier(angle_deg):
    angle_rad = math.radians(angle_deg)
    return 1 + math.tan(angle_rad)

def calculate_required_hours(biome, weather, morale, energy):
    base = biome["base_hours"]
    elev_mod = elevation_modifier(biome["avg_angle_deg"])
    weather_mod = weather_modifier(weather)
    morale_mod = max(0.4, morale / 100)
    energy_mod = max(0.4, energy / 100)
    return int(base * elev_mod * weather_mod / (morale_mod * energy_mod))

def update_weather():
    weather_cols = ['clear', 'rain', 'fog', 'storm', 'cold', 'wind']
    weights = [float(current_biome[col]) for col in weather_cols]
    return random.choices(weather_cols, weights=weights, k=1)[0]

def advance_time(hours, is_walking=False, sleep_bonus=0, rest_bonus=0, sleep_morale_bonus=0, fixed_weather=None):
    global current_hour, hours_since_sleep, fire_hours_remaining, has_fire, energy, hunger, morale

    for _ in range(hours):
        current_hour = (current_hour + 1) % 24
        current_weather = fixed_weather if fixed_weather else update_weather()
        weather_effects(current_weather)
        hours_since_sleep += 1

        hunger_tick()
        fatigue_tick()

        # Sleep recovery
        if sleep_bonus > 0:
            energy = min(100, energy + sleep_bonus)
            morale = min(100, morale + sleep_morale_bonus)

        # Rest recovery
        elif rest_bonus > 0:
            energy = min(100, energy + rest_bonus)
            hunger = max(0, hunger - 1)  # More hunger used while awake

        if has_fire:
            fire_hours_remaining -= 1
            if fire_hours_remaining <= 0:
                has_fire = False
                narrative_history.append("The fire dies to embers.")

# === Eat ===
def eat_item():
    items = [i for i in inventory if inventory[i] > 0]
    if not items:
        return ["You have nothing to eat."]

    # Show items and mark unidentified with question mark after count
    for idx, i in enumerate(items, 1):
        count = inventory[i]
        suffix = "?" if i not in identified_items else ""
        print(f"[{idx}] {i} ({count}{suffix})")

    choice = input("Eat which item? → ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(items)):
        return ["You put your food away."]

    item_name = items[int(choice) - 1]
    item = ITEM_DATA.get(item_name, {})
    inventory[item_name] -= 1

    if not item.get("edible", False):
        morale_change(-5)
        return [f"You try to eat the {item_name}. It doesn't go well."]

    # === Toxicity Check ===
    toxicity = item.get("toxicity_level", 0)
    cooked = item_name in cooked_items or not item.get("requires_cooking", False)


    if toxicity == 1 and not cooked:
        apply_effect("morale", -3)
        apply_effect("energy", -3)
        return [f"You eat the {item_name}. Your stomach tightens and your head fogs."]
    elif toxicity == 2:
        apply_effect("morale", -5)
        apply_effect("energy", -5)
        apply_effect("food", -5)
        return [f"You eat the {item_name}. You feel sick — sweating, nauseated, and drained."]
    elif toxicity == 3:
        if not purged_in_time():  # You can add this function later
            return [f"You eat the {item_name}. Moments later, the world spins. Everything fades..."]
        else:
            return [f"You eat the {item_name}, but your body violently rejects it. You might have survived."]

    # === Identification System ===
    if item_name not in identified_items:
        if random.random() < 0.4:
            return [f"You eat the {item_name} and feel sick."]
        identified_items.add(item_name)

    # === Normal Effects ===
    apply_effect("food", item.get("hunger", 0))
    apply_effect("morale", item.get("morale", 0))
    apply_effect("energy", item.get("energy", 0))

    return [f"You eat the {item_name}. {item.get('description', '')}"]

# === Travel ===
def travel():
    global hours_walked, required_hours, current_biome_index, current_biome

    # Use one consistent weather roll for both narrative + stat effects
    weather = update_weather()

    # Pull dynamic narrative using the new template system
    narrative = narrative_from_template("travel", {
        "biome": current_biome["biome_name"],
        "weather": weather,
        "hunger": hunger,
        "morale": morale,
        "energy": energy,
        "has_fire": has_fire
    })
    narrative_history.append(narrative)

    # Advance time and apply stat changes with fixed weather
    advance_time(1, fixed_weather=weather)
    
    ambient = describe_ambient_scene({
        "morale": morale,
        "energy": energy,
        "hunger": hunger,
        "weather": weather  # use the fixed weather, not current_weather
    })
    if ambient:
        narrative_history.append(ambient)


    # Setup required hours if not yet initialized
    if required_hours is None:
        required_hours = calculate_required_hours(current_biome, weather, morale, energy)

    hours_walked += 1
    if hours_walked >= required_hours:
        narrative_history.append("You’ve crossed the biome.")
        current_biome_index += 1
        if current_biome_index >= len(biomes_df):
            narrative_history.append("You have reached the final summit.")
            sys.exit()
        else:
            current_biome = biomes_df.iloc[current_biome_index]
            narrative_history.append(current_biome["intro_text"])
            reset_biome_progress()

def reset_biome_progress():
    global hours_walked, required_hours
    hours_walked = 0
    required_hours = None

# === Menus ===
def food_menu():
    while True:
        split_screen(narrative_history, [
            "[1] Eat Item",
            "[5] Back"
        ])
        c = input("→ ").strip()

        if c == "1":
            narrative_history.extend(eat_item())

            game_state = {
                "biome": current_biome["biome_name"],
                "weather": update_weather(),
                "hunger": hunger,
                "morale": morale,
                "energy": energy,
                "has_fire": has_fire
            }
            narrative = narrative_from_template("eat", game_state)
            narrative_history.append(narrative)

        elif c == "5":
            break



def rest_menu():
    while True:
        split_screen(narrative_history, [
            "[1] Wait",
            "[2] Sleep",
            "[5] Back"
        ])
        c = input("→ ").strip()

        if c == "1":
            duration = input("How many hours would you like to wait? → ").strip()
            if duration.isdigit():
                hours = int(duration)

                game_state = {
                    "biome": current_biome["biome_name"],
                    "weather": update_weather(),
                    "hunger": hunger,
                    "morale": morale,
                    "energy": energy,
                    "has_fire": has_fire
                }
                narrative = narrative_from_template("wait", game_state)
                narrative_history.append(narrative)

                advance_time(hours, rest_bonus=2)
            else:
                narrative_history.append("You fidget, unable to rest.")

        elif c == "2":
            duration = input("How many hours would you like to sleep? → ").strip()
            if duration.isdigit():
                hours = int(duration)

                game_state = {
                    "biome": current_biome["biome_name"],
                    "weather": update_weather(),
                    "hunger": hunger,
                    "morale": morale,
                    "energy": energy,
                    "has_fire": has_fire
                }
                narrative = narrative_from_template("sleep", game_state)
                narrative_history.append(narrative)

                advance_time(hours, sleep_bonus=4, sleep_morale_bonus=1)
            else:
                narrative_history.append("You lie down, but can't commit to sleeping.")

        elif c == "5":
            break

def inventory_menu():
    print("\n  Inventory system not finished yet.")
    input("Press Enter to return to Camp Menu.")
    
def notes_menu():
    print("\n  You flip through the notes you've gathered.")
    if "note_from_stranger" in inventory and inventory["note_from_stranger"] > 0:
        print(f"You have {inventory['note_from_stranger']} mysterious note(s) from strangers.")
        # In future: display contents or prompt to read one
    else:
        print("You haven't found any notes yet.")
    input("\nPress Enter to return to the Camp Menu.")

def camp_menu():
    while True:
        print("\n  Camp Menu")
        print("[1] Rest")
        print("[2] Inventory")
        print("[3] Start Fire")
        print("[4] Notes")
        print("[5] Back")

        choice = input("→ ").strip().lower()

        if choice == "1":
            rest_menu()
        elif choice == "2":
            inventory_menu()
        elif choice == "3":
            fire_menu()  # Fire menu already handles both start/cook paths
        elif choice == "4":
            notes_menu()
        elif choice == "5":
            break
        else:
            print("Invalid choice.")

        
def fire_menu():
    global has_fire, fire_hours_remaining

    if not has_fire:
        while True:
            print("\nYou need something to start a fire.")
            print("Inventory:")
            valid_items = []
            for item, qty in inventory.items():
                if qty > 0:
                    print(f"- {item} ({qty})")
                    valid_items.append(item)

            tool = input("Use what to start the fire? (or type 'back') → ").strip().lower()

            if tool == "back":
                return

            if tool == "flint and steel" and inventory.get("flint_and_steel", 0) > 0:
                print("You strike the flint. A fire catches.")
                has_fire = True
                fire_hours_remaining = 3
                print("  Fire is now burning.")
                break
            else:
                print("That won't work to start a fire. Try again.")

    # Fire is already active → show cooking options
    print("\n  The fire crackles.")
    print("[1] Cook")
    print("[2] Tend Fire")
    print("[3] Back")

    choice = input("→ ").strip().lower()
    if choice == "1":
        cook_menu()
    elif choice == "2":
        fire_hours_remaining += 2
        print("You add fuel. Fire lasts longer now.")
    elif choice == "3":
        return
    else:
        print("Invalid choice.")

        
def cook_menu():
    cookable = [item for item in inventory if inventory[item] > 0 and ITEM_DATA[item]["requires_cooking"] == "True"]
    
    if not cookable:
        print("\nYou have nothing that needs cooking.")
        return

    print("\n  Choose something to cook:")
    for i, item in enumerate(cookable, 1):
        print(f"[{i}] {ITEM_DATA[item]['display_name']} ({inventory[item]})")
    print("[5] Back")

    choice = input("→ ").strip()
    if choice == "5":
        return
    if not choice.isdigit() or int(choice) < 1 or int(choice) > len(cookable):
        print("Invalid choice.")
        return

    raw_item = cookable[int(choice) - 1]

    print("\nChoose how to cook it:")
    print("[1] Boil (needs pot + water)")
    print("[2] Roast (needs stick or place food near fire)")
    print("[3] Fry (needs pot)")
    print("[4] Steam (needs pot + water + leaves/sticks)")
    method_choice = input("→ ").strip()
    method_dict = {"1": "boiled", "2": "roasted", "3": "fried", "4": "steamed"}
    if method_choice not in method_dict:
        print("Invalid cooking method.")
        return

    method = method_dict[method_choice]
    cooked_name = f"{method}_{raw_item}"

    # === Placeholder Checks ===
    if method == "boiled":
        if "pot" not in inventory:  # water requirement to be added later
            print("You need a pot to boil.")
            return
    elif method == "roasted":
        if "stick" not in inventory and "branch" not in inventory:
            print("You’ll need a stick or branch to roast, or place food next to fire (not implemented yet).")
            return
    elif method == "fried":
        if "pot" not in inventory:
            print("You need a pot to fry.")
            return
    elif method == "steamed":
        if "pot" not in inventory:
            print("You need a pot to steam.")
            return
        # Additional checks for water, sticks, leaves to be added

    # === Cooking Time ===
    time_required = 2 if method == "roasted" else 1
    global current_hour
    current_hour += time_required
    if current_hour >= 24:
        current_hour -= 24  # wrap around

    # === Add Cooked Item ===
    if cooked_name not in ITEM_DATA:
        raw = ITEM_DATA[raw_item]
        ITEM_DATA[cooked_name] = {
            "display_name": f"{method.capitalize()} {raw['display_name']}",
            "scientific_name": raw["scientific_name"],
            "category": raw["category"],
            "lookalike_group": raw["lookalike_group"],
            "toxicity_level": raw["toxicity_level"],
            "requires_cooking": "False",
            "edible_raw": "True",
            "hunger": str(int(raw["hunger"]) + 1),
            "morale": str(int(raw["morale"]) + 1),
            "energy": str(int(raw["energy"]) + 1),
            "description": f"{method.capitalize()} version of {raw['display_name'].lower()}",
            "region": raw["region"],
            "identified": "True"
        }

    inventory[raw_item] -= 1
    if inventory[raw_item] == 0:
        del inventory[raw_item]

    if cooked_name in inventory:
        inventory[cooked_name] += 1
    else:
        inventory[cooked_name] = 1

    narrative_history.append(f"You {method} the {ITEM_DATA[raw_item]['display_name'].lower()}.")


def plant_guide_menu():
    item["show_in_guide"] == "True"
    while True:
        split_screen(narrative_history, ["Type a plant name to inspect.", "[5] Back"])
        print("\n📖 PLANT GUIDE\n")

        biomes = [
            "Cool Damp Coast",
            "Coastal Mountains",
            "Temperate Rainforest Valley",
            "Subalpine Forest",
            "Alpine Mountain Peak"
        ]

        for biome in biomes:
            print(f"\n== {biome.upper()} ==")
            for cat in ["mushroom", "fruit", "green"]:
                print(f"  — {cat.capitalize()}s —")
                plants = [p for p in ITEM_DATA.values() if p["region"] == biome and p["category"] == cat]
                for plant in plants:
                    icon = "✅" if plant["name"] in identified_items else "❓"
                    print(f"    {icon} {plant['display_name']}")

        c = input("\nEnter plant name or [5] to go back → ").strip().lower()

        if c == "5":
            break

        # Try to find plant by internal or display name
        match = next(
            (p for p in ITEM_DATA.values()
             if p["name"] == c or p["display_name"].lower() == c), None)

        if not match:
            narrative_history.append(f"No plant named '{c}' found.")
        else:
            print("\n--- PLANT INFO ---")
            print(f"Name       : {match['display_name']}")
            print(f"Type       : {match['category'].capitalize()}")
            print(f"Scientific : {match['scientific_name']}")
            print(f"Biome      : {match['region']}")
            print(f"Description: {match['description']}")
            print(f"Toxicity   : {match['toxicity_level']}")
            tox_index = int(match["toxicity_level"])
            tox_label = ["Safe", "Slightly Toxic", "Moderately Toxic", "Lethal Toxic"][tox_index]

            input("\nPress Enter to return to the guide.")

# === Main Menu ===
def main_menu():
    while True:
        if hunger <= 0 or energy <= 0:
            print("You collapse. Game over.")
            sys.exit()
        menu = [
            "=== STATUS ===",
            f"Biome   : {current_biome['biome_name']}",
            f"Time    : {str(current_hour).zfill(2)}:00",
            f"Hunger  : {hunger}/100",
            f"Energy  : {energy}/100",
            f"Morale  : {morale}/100",
            f"Progress: {hours_walked}/{required_hours or '?'} hrs",
            "==============",
            "[1] Eat",
            "[2] Travel",
            "[3] Camp"
        ]
        split_screen(narrative_history, menu)
        choice = input("→ ").strip().lower()
        if choice in ["1", "eat"]:
            food_menu()
        elif choice in ["2", "travel", "walk"]:
            travel()
        elif choice in ["3", "camp"]:
            camp_menu()
        else:
            narrative_history.append("You hesitate, unsure what to do.")

# === Game Start ===
def main():
    global narrative_history
    narrative_history = [""]
    main_menu()

if __name__ == "__main__":
    main()
