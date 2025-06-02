import pandas as pd
import random

# Load ambient CSVs
ambient_base = pd.read_csv("data/ambient_base.csv")
ambient_mod = pd.read_csv("data/ambient_modifier.csv")
ambient_resp = pd.read_csv("data/ambient_response.csv")

def describe_ambient_scene(state):
    """Generate an ambient message based on weather and stats."""
    w = state["weather"]
    h = state["hunger"]
    e = state["energy"]
    m = state["morale"]

    # Step 1: Filter base ambient by weather
    base_options = ambient_base[(ambient_base["weather_condition"] == "any") | 
                                 (ambient_base["weather_condition"] == w)]

    if base_options.empty:
        return ""

    base_row = base_options.sample(1).iloc[0]
    base_phrase = base_row["base_phrase"]
    category = base_row["category"]

    # Step 2: Add a modifier based on stat
    stat_choices = []
    if h < 40:
        stat_choices.append(("hunger", h))
    if m < 40:
        stat_choices.append(("morale", m))
    if e < 40:
        stat_choices.append(("energy", e))

    modifier_phrase = ""
    if stat_choices:
        stat_type, val = random.choice(stat_choices)
        level = "low" if val < 40 else "high"
        mod = ambient_mod[(ambient_mod["stat_type"] == stat_type) & (ambient_mod["stat_level"] == level)]
        if not mod.empty:
            modifier_phrase = mod.sample(1).iloc[0]["modifier_phrase"]

    # Step 3: Add response
    resp_options = ambient_resp[ambient_resp["category"] == category]
    if not resp_options.empty:
        response_phrase = resp_options.sample(1).iloc[0]["response_phrase"]
    else:
        response_phrase = ""

    return " ".join([base_phrase, modifier_phrase, response_phrase]).strip()
