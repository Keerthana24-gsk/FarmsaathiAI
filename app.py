"""FarmSaathi AI - prototype backend (Flask + Open-Meteo + FAO-56 water balance)."""
import requests, re, io, math, os
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from datetime import date, timedelta
from flask import Flask, request, jsonify, render_template, send_file
from agents import (CropPlanningAgent, WeatherIntelligenceAgent, IrrigationAgent,
                    SoilFertilizerAgent, CropHealthAgent, ProfitabilityAgent,
                    MultilingualAgent, MasterCoordinatorAgent)
from i18n import LANGUAGES, translate_ui, translate_advice_payload, translate_advice_text

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.errorhandler(500)
def farm_error_response(error):
    app.logger.exception("FarmSaathi server error while processing a request")
    payload = request.get_json(silent=True) or {}
    lang = payload.get("language", "en")
    messages = {
        "en": "Advice could not be generated because the server encountered an error. Check the VS Code terminal for the traceback.",
        "hi": "सर्वर में त्रुटि के कारण सलाह तैयार नहीं हो सकी। कृपया VS Code टर्मिनल में त्रुटि देखें।",
        "kn": "ಸರ್ವರ್ ದೋಷದಿಂದ ಸಲಹೆ ಸಿದ್ಧವಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು VS Code ಟರ್ಮಿನಲ್‌ನಲ್ಲಿ ದೋಷವನ್ನು ಪರಿಶೀಲಿಸಿ.",
        "te": "సర్వర్ లోపం వల్ల సలహా రూపొందించలేకపోయాము. దయచేసి VS Code టెర్మినల్‌లో లోపాన్ని చూడండి."
    }
    return jsonify(error=messages.get(lang, messages["en"])), 500


STAGES = ["Initial", "Development", "Mid-season", "Late-season"]
DEPTH = [0.3, 0.6, 1.0, 1.0]  # root depth multiplier per stage
# kc per stage (FAO-56 approx.), mid-season root depth (m), depletion fraction p
CROPS = {
    "Rice":      {"kc": [1.05, 1.10, 1.20, 0.90], "root": 0.5, "p": 0.20},
    "Wheat":     {"kc": [0.30, 0.70, 1.15, 0.35], "root": 1.0, "p": 0.55},
    "Maize":     {"kc": [0.30, 0.70, 1.20, 0.60], "root": 1.0, "p": 0.55},
    "Tomato":    {"kc": [0.60, 0.90, 1.15, 0.80], "root": 0.7, "p": 0.40},
    "Cotton":    {"kc": [0.35, 0.75, 1.15, 0.70], "root": 1.0, "p": 0.65},
    "Sugarcane": {"kc": [0.40, 0.90, 1.25, 0.75], "root": 1.2, "p": 0.65},
}
# available water capacity, mm per metre of soil (approximate)
SOILS = {"Sandy": 70, "Red": 100, "Loamy": 140, "Clay": 170, "Black": 190}
STAGE_TIPS = [
    "Seedlings are shallow-rooted: give light, frequent water and protect from heat.",
    "Roots are growing: keep soil evenly moist and apply the first fertilizer dose as advised locally.",
    "Peak water demand: avoid any moisture stress now, it hurts yield the most.",
    "Water need is falling: reduce irrigation gradually and plan harvest around dry weather.",
]
CROP_NOTES = {
    "Rice": "Paddy is usually kept flooded; treat the amount shown as the top-up needed.",
    "Tomato": "Water at the base and avoid wetting leaves to reduce blight risk.",
    "Cotton": "Excess water at flowering causes boll drop; avoid waterlogging.",
    "Sugarcane": "Heavy feeder of water; mulch trash to cut evaporation.",
    "Wheat": "Crown-root and flowering stages are most sensitive to dry soil.",
    "Maize": "Tasseling and silking are critical: do not let soil dry out.",
}
DAILY = ("temperature_2m_max,temperature_2m_min,precipitation_sum,"
         "precipitation_probability_max,et0_fao_evapotranspiration,wind_speed_10m_max")

# Additional common Indian crops (Kc/economics are prototype estimates; verify locally).
CROPS.update({'Ragi': {'kc': [0.35, 0.75, 1.05, 0.45], 'root': 0.8, 'p': 0.5}, 'Groundnut': {'kc': [0.4, 0.75, 1.05, 0.6], 'root': 0.6, 'p': 0.5}, 'Soybean': {'kc': [0.4, 0.8, 1.15, 0.5], 'root': 0.8, 'p': 0.5}, 'Chickpea': {'kc': [0.4, 0.7, 1.0, 0.35], 'root': 0.8, 'p': 0.5}, 'Sorghum': {'kc': [0.3, 0.7, 1.0, 0.55], 'root': 1.0, 'p': 0.55}, 'Pearl Millet': {'kc': [0.3, 0.7, 1.0, 0.55], 'root': 1.0, 'p': 0.55}, 'Potato': {'kc': [0.5, 0.8, 1.15, 0.75], 'root': 0.5, 'p': 0.35}, 'Onion': {'kc': [0.7, 0.85, 1.05, 0.75], 'root': 0.4, 'p': 0.3}, 'Chilli': {'kc': [0.6, 0.85, 1.05, 0.8], 'root': 0.6, 'p': 0.4}, 'Banana': {'kc': [0.6, 0.9, 1.1, 1.0], 'root': 0.8, 'p': 0.4}})


def geocode(q):
    r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                     params={"name": q, "count": 1}, timeout=8).json()
    h = r["results"][0]
    return h["latitude"], h["longitude"], f'{h["name"]}, {h.get("admin1", "")}'


def forecast(lat, lon):
    p = {"latitude": lat, "longitude": lon, "timezone": "auto",
         "forecast_days": 7, "daily": DAILY}
    r = requests.get("https://api.open-meteo.com/v1/forecast", params=p, timeout=8)
    r.raise_for_status()
    return r.json()["daily"]


def sample_weather():  # offline fallback so the demo never breaks
    d0 = date.today()
    return {"time": [(d0 + timedelta(i)).isoformat() for i in range(7)],
            "temperature_2m_max": [34, 35, 33, 31, 32, 33, 34], "temperature_2m_min": [22, 23, 22, 21, 21, 22, 22],
            "precipitation_sum": [0, 0, 12, 6, 0, 0, 2], "precipitation_probability_max": [10, 20, 80, 60, 15, 10, 25],
            "et0_fao_evapotranspiration": [5.2, 5.4, 4.1, 3.8, 4.9, 5.1, 5.3], "wind_speed_10m_max": [12, 14, 22, 18, 10, 11, 13]}


def nz(a):
    return [x or 0 for x in a]


def advise(w, crop, stage, soil, sm):
    c = CROPS[crop]
    kc, root = c["kc"][stage], c["root"] * DEPTH[stage]
    taw = SOILS[soil] * root            # total available water (mm)
    raw = c["p"] * taw                  # readily available water (stress limit)
    dep0 = taw * (1 - sm / 100)         # water already used up
    et0, rain, prob = nz(w["et0_fao_evapotranspiration"]), nz(w["precipitation_sum"]), nz(w["precipitation_probability_max"])
    d, sim, trig = dep0, [], (0 if dep0 >= raw else None)
    for i in range(len(rain)):
        etc = et0[i] * kc
        eff = 0.8 * rain[i] if rain[i] >= 3 else 0
        d = min(taw, max(0, d + etc - eff))
        sim.append({"etc": round(etc, 1), "eff_rain": round(eff, 1), "depletion": round(d, 1)})
        if trig is None and d >= raw:
            trig = i
    if trig is None:
        action, level, detail = "No irrigation needed", "ok", "Soil water stays above the stress limit for the next 7 days."
    elif trig == 0 and prob[0] >= 60 and rain[0] >= 5:
        action, level, detail = "Delay irrigation", "warn", f"Soil is getting dry but about {rain[0]:.0f} mm of rain is likely today. Re-check tomorrow."
    elif trig == 0 and dep0 < raw:
        need = round(sim[0]["depletion"])
        action, level, detail = "Irrigate by tomorrow morning", "warn", f"Soil will hit the stress limit by tonight. Plan about {need} mm."
    elif trig == 0:
        need = round(sim[0]["depletion"])
        action, level, detail = "Irrigate today", "danger", f"Apply about {need} mm (about {need * 4047:,} litres per acre) to refill the root zone."
    else:
        need = round(sim[trig]["depletion"])
        action, level = f"Irrigate in {trig} day(s)", ("warn" if trig <= 2 else "ok")
        detail = f"Soil reaches the stress limit around {w['time'][trig]}. Plan about {need} mm."
    why = [f"{soil} soil holds about {taw:.0f} mm of usable water in the root zone ({root:.2f} m deep); roughly {dep0:.0f} mm is already used.",
           f"Stress starts once {raw:.0f} mm is used up, so that is the trigger level.",
           f"{crop} at the {STAGES[stage].lower()} stage has crop factor Kc {kc}; with ET\u2080 {et0[0]:.1f} mm/day it uses about {et0[0] * kc:.1f} mm/day.",
           f"Forecast rain over 7 days: {sum(rain):.0f} mm (only {sum(s['eff_rain'] for s in sim):.0f} mm counted as useful)."]
    return {"action": action, "level": level, "detail": detail, "why": why, "sim": sim,
            "tips": [STAGE_TIPS[stage], CROP_NOTES[crop]]}


def risks(w):
    out, tx, tn = [], nz(w["temperature_2m_max"]), nz(w["temperature_2m_min"])
    rn, pb, wd = nz(w["precipitation_sum"]), nz(w["precipitation_probability_max"]), nz(w["wind_speed_10m_max"])
    for i, t in enumerate(w["time"]):
        if tx[i] >= 40: out.append(("danger", t, f"Heatwave risk ({tx[i]:.0f}\u00b0C): irrigate early morning or evening."))
        if tn[i] <= 4: out.append(("danger", t, f"Frost risk ({tn[i]:.0f}\u00b0C): cover or irrigate lightly the evening before."))
        if rn[i] >= 50: out.append(("danger", t, f"Very heavy rain ({rn[i]:.0f} mm): clear drainage, skip fertilizer and spraying."))
        elif rn[i] >= 20 and pb[i] >= 60: out.append(("warn", t, f"Heavy rain likely ({rn[i]:.0f} mm): postpone spraying and fertilizer."))
        if wd[i] >= 25: out.append(("warn", t, f"Strong wind ({wd[i]:.0f} km/h): do not spray pesticides."))
    if sum(rn) < 1 and max(tx) >= 35:
        out.append(("warn", w["time"][0], "Dry and hot spell ahead: watch for crop water stress."))
    return [{"level": l, "date": t, "msg": m} for l, t, m in out]



# ---------------- Crop recommendation (ML) ----------------
NL = {"Low": 40, "Medium": 80, "High": 120}   # soil-health-card level -> N index
PL = {"Low": 25, "Medium": 50, "High": 75}
KL = {"Low": 20, "Medium": 45, "High": 70}
# ILLUSTRATIVE (mean, sd) per feature: N, P, K, temp C, humidity %, pH, rain mm/month.
# Replace with real data (e.g. Kaggle Crop Recommendation) before claiming accuracy.
PROFILES = {
    "Rice":      [(80, 20), (48, 12), (40, 10), (24, 3), (82, 6), (6.4, .6), (200, 50)],
    "Wheat":     [(100, 20), (50, 12), (40, 10), (18, 3), (60, 10), (6.8, .5), (60, 25)],
    "Maize":     [(80, 20), (48, 12), (20, 8), (23, 3), (65, 8), (6.2, .5), (85, 25)],
    "Tomato":    [(100, 20), (60, 15), (70, 15), (24, 3), (70, 8), (6.3, .4), (70, 25)],
    "Cotton":    [(118, 20), (46, 12), (20, 8), (25, 3), (78, 6), (6.9, .6), (80, 25)],
    "Sugarcane": [(120, 25), (50, 12), (60, 15), (27, 3), (75, 8), (7.0, .6), (150, 40)],
}

# Illustrative feature profiles for additional crop classes.
PROFILES.update({'Ragi': [(70, 18), (45, 12), (18, 8), (24, 3), (65, 8), (6.2, 0.5), (55, 20)], 'Groundnut': [(85, 20), (45, 12), (25, 10), (26, 3), (70, 8), (6.3, 0.5), (65, 20)], 'Soybean': [(90, 20), (48, 12), (35, 12), (25, 3), (75, 8), (6.5, 0.5), (75, 25)], 'Chickpea': [(85, 18), (40, 10), (20, 8), (22, 3), (60, 8), (7.0, 0.5), (45, 15)], 'Sorghum': [(75, 18), (42, 10), (18, 8), (27, 3), (65, 8), (6.5, 0.5), (45, 18)], 'Pearl Millet': [(65, 16), (38, 10), (15, 7), (28, 3), (60, 8), (6.5, 0.5), (35, 15)], 'Potato': [(95, 18), (55, 12), (45, 12), (20, 3), (75, 8), (6.0, 0.4), (90, 25)], 'Onion': [(95, 18), (50, 12), (35, 10), (22, 3), (70, 8), (6.5, 0.4), (65, 20)], 'Chilli': [(100, 20), (55, 12), (45, 12), (25, 3), (75, 8), (6.3, 0.5), (65, 20)], 'Banana': [(110, 20), (55, 12), (50, 12), (27, 3), (80, 8), (6.5, 0.5), (120, 30)]})


def train_model():
    rng = np.random.default_rng(42)
    X, y = [], []
    for crop, prof in PROFILES.items():
        X.append(np.column_stack([rng.normal(m, sd, 300) for m, sd in prof]))
        y += [crop] * 300
    X = np.vstack(X)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=1, stratify=y)
    acc = RandomForestClassifier(n_estimators=150, random_state=0).fit(Xtr, ytr).score(Xte, yte)
    return RandomForestClassifier(n_estimators=150, random_state=0).fit(X, y), round(acc * 100, 1)


MODEL, MODEL_ACC = train_model()


def recommend(feat, chosen):
    pr = dict(zip(MODEL.classes_, MODEL.predict_proba([feat])[0]))
    order = sorted(pr, key=pr.get, reverse=True)
    top = [{"crop": c, "score": round(pr[c] * 100)} for c in order[:3]]
    ratio = pr[chosen] / max(pr.values())
    if chosen == order[0]: msg = f"Great match: {chosen} is the best fit for your soil and climate."
    elif ratio >= 0.5: msg = f"Reasonable match for {chosen}, but {order[0]} fits slightly better."
    else: msg = f"Weak match for {chosen}. Your soil and climate suit {order[0]} much better."
    return {"top": top, "chosen_score": round(pr[chosen] * 100), "msg": msg, "acc": MODEL_ACC}, pr


# ---------------- Fertilizer recommendation ----------------
REQ = {"Rice": (100, 50, 50), "Wheat": (120, 60, 40), "Maize": (120, 60, 40),
       "Tomato": (120, 80, 60), "Cotton": (120, 60, 60), "Sugarcane": (250, 100, 120)}  # kg/ha N, P2O5, K2O
# Indicative nutrient targets (kg/ha N, P2O5, K2O) for the expanded crop list.
# These are demo defaults only; local soil-test recommendations must take priority.
REQ_EXTRA = {
    "Ragi": (40, 20, 20), "Groundnut": (25, 50, 45), "Soybean": (30, 60, 40),
    "Chickpea": (20, 40, 20), "Sorghum": (80, 40, 40), "Pearl Millet": (60, 30, 20),
    "Potato": (150, 75, 100), "Onion": (100, 50, 50), "Chilli": (120, 60, 60),
    "Banana": (200, 60, 300)
}
for _crop in CROPS:
    REQ.setdefault(_crop, REQ_EXTRA.get(_crop, (80, 40, 40)))
ADJ = {"Low": 1.25, "Medium": 1.0, "High": 0.75}   # soil test rating -> dose multiplier
PRICE_KG = {"Urea": 6, "DAP": 27, "MOP": 33}      # Rs/kg, approximate


def fertilizer(crop, nl, pl, kl):
    n, p, k = (r * ADJ[l] for r, l in zip(REQ[crop], (nl, pl, kl)))
    dap = p / 0.46
    urea = max(0, n - dap * 0.18) / 0.46
    mop = k / 0.60
    ac = 0.4047
    prod = {"Urea": urea * ac, "DAP": dap * ac, "MOP": mop * ac}
    return {"npk": [round(n), round(p), round(k)],
            "per_acre": {a: round(v) for a, v in prod.items()},
            "cost": round(sum(v * PRICE_KG[a] for a, v in prod.items())),
            "schedule": [f"Basal (at sowing): all DAP and MOP, plus 1/3 of urea (about {round(prod['Urea'] / 3)} kg/acre).",
                         f"First top-dressing: 1/3 of urea around the {'tillering' if crop in ('Rice', 'Wheat') else 'vegetative'} stage.",
                         "Second top-dressing: last 1/3 of urea near flowering. Skip it if heavy rain is forecast."]}


# ---------------- Profit estimate ----------------
# ILLUSTRATIVE per-acre economics (yield q/acre, cost Rs/acre, price Rs/quintal). Update from MSP / Agmarknet / local data.
ECON = {"Rice": {"yield": 20, "cost": 28000, "price": 2300}, "Wheat": {"yield": 16, "cost": 22000, "price": 2400},
        "Maize": {"yield": 22, "cost": 20000, "price": 2200}, "Tomato": {"yield": 100, "cost": 80000, "price": 1500},
        "Cotton": {"yield": 8, "cost": 35000, "price": 7000}, "Sugarcane": {"yield": 350, "cost": 55000, "price": 350}}

# Indicative sample economics only; replace with district/season market data.
ECON.update({'Ragi': {'yield': 12, 'cost': 18000, 'price': 4000}, 'Groundnut': {'yield': 10, 'cost': 30000, 'price': 6000}, 'Soybean': {'yield': 12, 'cost': 26000, 'price': 4500}, 'Chickpea': {'yield': 8, 'cost': 22000, 'price': 5500}, 'Sorghum': {'yield': 14, 'cost': 18000, 'price': 2500}, 'Pearl Millet': {'yield': 12, 'cost': 16000, 'price': 2400}, 'Potato': {'yield': 100, 'cost': 65000, 'price': 1200}, 'Onion': {'yield': 100, 'cost': 70000, 'price': 1500}, 'Chilli': {'yield': 15, 'cost': 60000, 'price': 8000}, 'Banana': {'yield': 250, 'cost': 90000, 'price': 1200}})


def net_profit(crop, ratio, price, area=1.0):
    e = ECON[crop]
    rev = e["yield"] * (0.5 + 0.5 * ratio) * price * area   # yield adjusted by suitability
    cost = e["cost"] * area
    return rev, cost, rev - cost


def profit(crop, fit, price, area):
    rev, cost, net = net_profit(crop, fit, price, area)
    low = net_profit(crop, fit, price * 0.8, area)[2]
    margin = net / cost * 100
    if net <= 0: verdict, level = "Likely LOSS", "danger"
    elif margin < 15 or low < 0: verdict, level = "Marginal profit (risky)", "warn"
    else: verdict, level = "PROFITABLE", "ok"
    return {"verdict": verdict, "level": level, "revenue": round(rev), "cost": round(cost), "net": round(net),
            "margin": round(margin), "net_low": round(low), "net_high": round(net_profit(crop, fit, price * 1.2, area)[2])}


# ---------------- Soil / season suitability and profit ranking ----------------
SOIL_FIT = {  # ILLUSTRATIVE suitability of each soil type for each crop (0-1)
    "Rice": {"Sandy": .4, "Red": .6, "Loamy": .85, "Clay": 1, "Black": .9},
    "Wheat": {"Sandy": .55, "Red": .7, "Loamy": 1, "Clay": .9, "Black": .9},
    "Maize": {"Sandy": .7, "Red": .85, "Loamy": 1, "Clay": .75, "Black": .85},
    "Tomato": {"Sandy": .7, "Red": .9, "Loamy": 1, "Clay": .65, "Black": .8},
    "Cotton": {"Sandy": .5, "Red": .8, "Loamy": .85, "Clay": .75, "Black": 1},
    "Sugarcane": {"Sandy": .5, "Red": .7, "Loamy": 1, "Clay": .85, "Black": .95}}
SEASON_FIT = {  # ILLUSTRATIVE sowing-season fit (varies by region)
    "Rice": {"Kharif": 1, "Rabi": .7, "Zaid": .6}, "Wheat": {"Kharif": .2, "Rabi": 1, "Zaid": .2},
    "Maize": {"Kharif": 1, "Rabi": .8, "Zaid": .7}, "Tomato": {"Kharif": .7, "Rabi": 1, "Zaid": .6},
    "Cotton": {"Kharif": 1, "Rabi": .2, "Zaid": .5}, "Sugarcane": {"Kharif": .9, "Rabi": 1, "Zaid": .8}}
STAGE_ACTIONS = {
    "Rice": ["Transplant healthy seedlings, keep 2-3 cm water and apply basal fertilizer.", "Weed at 20-25 days, top-dress urea at tillering and scout for stem borer.", "Keep about 5 cm water at flowering; watch for blast and planthopper.", "Drain the field about 10 days before harvest; harvest at 80-85% golden grains."],
    "Wheat": ["Sow at the right depth; give the first irrigation at 20-25 days (crown root stage).", "Weed at 30-35 days, top-dress urea and irrigate at tillering.", "Irrigate at flowering and grain filling; scout for rust.", "Stop irrigation as grains harden; harvest when grains are hard and dry."],
    "Maize": ["Thin plants, gap-fill and weed early.", "Earth up and top-dress urea at knee height; scout for fall armyworm.", "Never let soil dry at tasseling and silking; irrigate on time.", "Let cobs dry on the plant; harvest when husks turn dry."],
    "Tomato": ["Transplant in the evening, irrigate lightly and shade young plants.", "Stake plants, weed, top-dress; scout for early blight and whitefly.", "Irrigate lightly and regularly; spray only on dry days.", "Harvest at the breaker stage; keep water off the fruits."],
    "Cotton": ["Thin to one plant per hill, weed early and scout for sucking pests.", "Top-dress nitrogen at squaring; scout for bollworm.", "Irrigate at flowering and boll formation; avoid waterlogging.", "Stop irrigation; pick bolls when fully open and dry."],
    "Sugarcane": ["Plant setts in moist soil, irrigate lightly and gap-fill.", "Weed, earth up, top-dress nitrogen and mulch with trash.", "Irrigate every 7-10 days in hot weather; prop canes against lodging; scout for borers.", "Withhold water 3-4 weeks before harvest to raise sugar; harvest at maturity."]}
SOIL_NOTE = {"Sandy": "Sandy soil leaches nutrients: split nitrogen into 3-4 smaller doses and use mulch or compost to hold water.",
             "Red": "Red soil is low in organic matter: add compost or FYM and apply phosphorus near the roots.",
             "Loamy": "Loamy soil holds water and nutrients well: standard split doses work.",
             "Clay": "Clay soil drains slowly: avoid waterlogging, make drainage channels and avoid working it when wet.",
             "Black": "Black soil cracks when dry and sticks when wet: apply P and K as basal dose and avoid field work in wet spells."}
MICRO = {"Zn": (0.6, "Zinc is low: apply zinc sulphate about 10 kg/acre once as basal dose."),
         "B": (0.5, "Boron is low: apply borax about 4 kg/acre."),
         "S": (10, "Sulphur is low: apply gypsum about 100 kg/acre, or use SSP as your phosphorus source."),
         "Fe": (4.5, "Iron is low: spray 0.5% ferrous sulphate on the leaves."),
         "Mn": (1.0, "Manganese is low: spray 0.5% manganese sulphate on the leaves."),
         "Cu": (0.2, "Copper is low: apply copper sulphate about 2 kg/acre.")}
# Fill compatible agronomic tables for the expanded crop catalogue.
for _crop in CROPS:
    SOIL_FIT.setdefault(_crop, {"Sandy": .75, "Red": .85, "Loamy": 1.0, "Clay": .75, "Black": .85})
    SEASON_FIT.setdefault(_crop, {"Kharif": .85, "Rabi": .85, "Zaid": .65})
    STAGE_ACTIONS.setdefault(_crop, [
        f"Prepare a fine seedbed and sow healthy, certified {_crop.lower()} seed at the locally recommended spacing.",
        f"Keep the root zone evenly moist and remove weeds around the {_crop.lower()} crop.",
        f"Monitor flowering and early fruit or grain formation; avoid moisture stress.",
        f"Reduce irrigation as the crop matures and harvest at the locally recommended maturity."
    ])
    CROP_NOTES.setdefault(_crop, f"Follow local university or agriculture-department guidance for {_crop.lower()} spacing, nutrients and pest management.")



def season_of(m):
    return "Kharif" if 6 <= m <= 10 else ("Rabi" if m >= 11 or m <= 3 else "Zaid")


def agro_fit(crop, feat):
    z = [(x - m) / sd for x, (m, sd) in zip(feat, PROFILES[crop])]
    return math.exp(-0.25 * sum(v * v for v in z) / len(z))


def rank_crops(feat, soil, month):
    ses, fits, rows = season_of(month), {}, []
    for c in CROPS:
        fits[c] = agro_fit(c, feat) * SOIL_FIT[c][soil] * SEASON_FIT[c][ses]
        rows.append({"crop": c, "fit": round(fits[c] * 100), "net": round(net_profit(c, fits[c], ECON[c]["price"])[2]), "ok": fits[c] >= 0.3})
    rows.sort(key=lambda r: (not r["ok"], -r["net"]))
    return rows, fits, ses


def soil_advice(soil, ph, oc, ec, micro):
    out = [SOIL_NOTE[soil]]
    if ph < 6: out.append(f"Soil is acidic (pH {ph}): apply agricultural lime, typically 200-400 kg/acre, as per local advice.")
    elif ph > 8.2: out.append(f"Soil is alkaline (pH {ph}): apply gypsum (about 200 kg/acre) and plenty of organic matter.")
    if oc is not None and oc < 0.5: out.append(f"Organic carbon is low ({oc}%): add about 4 tonnes/acre of FYM or compost.")
    if ec is not None and ec > 2: out.append(f"Soil is saline (EC {ec} dS/m): improve drainage and prefer salt-tolerant crops.")
    out += [msg for k, (lim, msg) in MICRO.items() if micro.get(k) is not None and micro[k] < lim]
    return out


def level(v, lo, hi):
    return "Low" if v < lo else ("Medium" if v <= hi else "High")


def extract_shc(text):
    def grab(names):
        for strict in (False, True):
            for n in names:
                pat = (n + r"\s*(?:\(\w{1,3}\))?[\s:|\-]{0,15}(\d+(?:\.\d+)?)") if strict else (n + r"[^0-9\n]{0,40}?(\d+(?:\.\d+)?)")
                m = re.search(pat, text, re.I)
                if m: return float(m.group(1))
    v = {"N": grab([r"nitrogen"]), "P": grab([r"phosph[oa]rus"]), "K": grab([r"potassium", r"potash"]),
         "ph": grab([r"\bpH\b"]), "ec": grab([r"electrical\s+conductivity", r"\bEC\b"]), "oc": grab([r"organic\s+carbon", r"\bOC\b"]),
         "S": grab([r"sulph?ur"]), "Zn": grab([r"\bzinc\b", r"\bZn\b"]), "B": grab([r"\bboron\b"]),
         "Fe": grab([r"\biron\b", r"\bFe\b"]), "Mn": grab([r"manganese", r"\bMn\b"]), "Cu": grab([r"\bcopper\b", r"\bCu\b"])}
    lv = {}
    for k, lo, hi in (("N", 280, 560), ("P", 11, 25), ("K", 110, 280)):
        if v[k] is not None: lv[k] = level(v[k], lo, hi)
    tex = next((nm for pat, nm in [(r"sandy", "Sandy"), (r"clay(ey)?", "Clay"), (r"loam(y)?", "Loamy"), (r"black", "Black"), (r"red", "Red")]
                if re.search(r"\b" + pat + r"\b", text, re.I)), None)
    return {"values": {k: x for k, x in v.items() if x is not None}, "levels": lv, "texture": tex}


def read_card(name, data):
    ext = name.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    if ext in ("png", "jpg", "jpeg"):
        try:
            import pytesseract
            from PIL import Image
            return pytesseract.image_to_string(Image.open(io.BytesIO(data)))
        except Exception:
            raise ValueError("Reading photos needs Tesseract OCR installed. Please upload the PDF card, or type the values.")
    raise ValueError("Please upload a PDF, PNG or JPG file.")


def outlook(w):
    tx, rn = nz(w["temperature_2m_max"]), nz(w["precipitation_sum"])
    i = max(range(len(rn)), key=lambda j: rn[j])
    wet = f", wettest day {w['time'][i]} ({rn[i]:.0f} mm)." if rn[i] >= 1 else ", essentially dry."
    return f"Forecast for the next {len(rn)} days: highs {min(tx):.0f} to {max(tx):.0f}\u00b0C, total rain {sum(rn):.0f} mm{wet}"


def next_steps(w, res, crop, stage, growing):
    tx, rn = nz(w["temperature_2m_max"]), nz(w["precipitation_sum"])
    pb, wd = nz(w["precipitation_probability_max"]), nz(w["wind_speed_10m_max"])
    st = [{"date": w["time"][0], "level": res["level"], "text": f"Irrigation: {res['action']}. {res['detail']}"}]
    good = [i for i in range(len(rn)) if rn[i] < 2 and pb[i] < 30 and wd[i] < 20]
    if good: st.append({"date": w["time"][good[0]], "level": "ok", "text": "Best dry, calm day for spraying and fertilizer top-dressing."})
    else: st.append({"date": w["time"][0], "level": "warn", "text": "No dry, calm day in the forecast: hold off spraying and fertilizer."})
    for i, t in enumerate(w["time"]):
        if rn[i] >= 20 and pb[i] >= 60:
            st.append({"date": t, "level": "warn", "text": f"Heavy rain ({rn[i]:.0f} mm) expected: clear drains" + ("; harvest early if the crop is ready." if growing and stage == 3 else ".")})
        if tx[i] >= 38: st.append({"date": t, "level": "danger", "text": f"Hot day ({tx[i]:.0f}\u00b0C): irrigate early morning or evening, avoid midday field work."})
    st.append({"date": w["time"][0], "level": "ok", "text": ("Stage task: " + STAGE_ACTIONS[crop][stage]) if growing else
               "Prepare the land, buy certified seed and sow on the first dry day once soil moisture is adequate."})
    return st[:9]


def care_measures(w, crop, stage, soil_notes):
    rn, tx = sum(nz(w["precipitation_sum"])), nz(w["temperature_2m_max"])
    out = [STAGE_ACTIONS[crop][stage]]
    if rn >= 30: out.append("Wet weather raises fungal disease risk: scout for leaf spots or blight and spray only on dry days.")
    if rn < 5 and max(tx) >= 33: out.append("Hot, dry weather favours mites, aphids and hoppers: scout twice a week.")
    return out + soil_notes[:3]


@app.route("/")
def home():
    """Serve the dashboard HTML directly from this project's templates folder.

    The dashboard is a self-contained HTML page (it does not use Jinja
    template variables), so send_file avoids template-loader path issues.
    """
    page_path = os.path.join(BASE_DIR, "templates", "index.html")
    if not os.path.isfile(page_path):
        app.logger.error("Dashboard file not found: %s", page_path)
        return ("FarmSaathi dashboard file is missing. Check that the "
                "templates/index.html file is present in the project folder."), 500
    try:
        return send_file(page_path, mimetype="text/html")
    except Exception:
        app.logger.exception("Could not serve the FarmSaathi dashboard")
        return ("FarmSaathi could not load the dashboard. Check the VS Code "
                "terminal for the detailed error."), 500


@app.route("/api/languages")
def languages():
    return jsonify({k: {"name": v["name"], "speech": v["speech"]} for k, v in LANGUAGES.items()})

@app.route("/api/options")
def options():
    return jsonify(crops=list(CROPS), soils=list(SOILS), stages=STAGES, econ=ECON)


@app.route("/api/upload", methods=["POST"])
def api_upload():
    f = request.files.get("file")
    if not f: return jsonify(error="No file received."), 400
    try:
        text = read_card(f.filename or "", f.read())
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception:
        return jsonify(error="Could not open this file. Try the PDF version of the card."), 400
    if len(text.strip()) < 20:
        return jsonify(error="No readable text found (scanned image PDF?). Upload a text PDF or type the values."), 400
    r = extract_shc(text)
    if not r["values"]:
        return jsonify(error="Could not find soil values in this card. Please type them in."), 400
    return jsonify(r)


@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify(status="ok", service="FarmSaathi advice API", version="7.25")

@app.route("/api/advice", methods=["POST"])
def api_advice():
    """Generate a complete advisory; use sample weather if the live service is unavailable."""
    b = request.get_json(silent=True) or {}
    lang = str(b.get("language") or "en").strip().lower()
    if lang not in LANGUAGES:
        lang = "en"

    # Normalize form values before validating. Some browsers submit select values as strings.
    crop = str(b.get("crop") or "Auto").strip()
    soil = str(b.get("soil") or "Loamy").strip()
    aliases = {
        "auto": "Auto", "rice": "Rice", "paddy": "Rice", "wheat": "Wheat",
        "maize": "Maize", "corn": "Maize", "tomato": "Tomato", "cotton": "Cotton",
        "sugarcane": "Sugarcane", "ragi": "Ragi", "raagi": "Ragi",
        "groundnut": "Groundnut", "peanut": "Groundnut", "soybean": "Soybean",
        "chickpea": "Chickpea", "gram": "Chickpea", "sorghum": "Sorghum",
        "pearl millet": "Pearl Millet", "bajra": "Pearl Millet", "potato": "Potato",
        "onion": "Onion", "chilli": "Chilli", "chili": "Chilli", "banana": "Banana"
    }
    crop = aliases.get(crop.casefold(), crop)
    soil_aliases = {"sandy": "Sandy", "red": "Red", "loamy": "Loamy",
                    "clay": "Clay", "black": "Black"}
    soil = soil_aliases.get(soil.casefold(), soil)

    try:
        stage = int(float(b.get("stage", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        stage = 0
    growing = str(b.get("status") or "plan").strip().lower() in ("grow", "growing", "crop_growing")

    if crop not in CROPS and crop != "Auto":
        return jsonify(error=translate_advice_text("Please choose a valid crop.", lang)), 400
    if soil not in SOILS:
        return jsonify(error=translate_advice_text("Please choose a valid soil type.", lang)), 400
    if stage not in range(4):
        stage = 0
    if growing and crop == "Auto":
        return jsonify(error=translate_advice_text("Please select the crop you have already sown.", lang)), 400

    try:
        sm = max(0.0, min(100.0, float(b.get("moisture", 50) or 50)))
        nl = str(b.get("n") or "Medium").title()
        pl = str(b.get("p") or "Medium").title()
        kl = str(b.get("k") or "Medium").title()
        if nl not in NL: nl = "Medium"
        if pl not in PL: pl = "Medium"
        if kl not in KL: kl = "Medium"
        ph = float(b.get("ph") or 6.5)
        hum = float(b.get("humidity") or 65)
        mrain = float(b.get("rain") or 100)
        area = float(b.get("area") or 1)
        if not math.isfinite(area) or area <= 0 or area > 10000:
            raise ValueError("Invalid land area")
        if not math.isfinite(ph) or not 3 <= ph <= 10:
            raise ValueError("Invalid soil pH")
        if not math.isfinite(hum) or not 0 <= hum <= 100:
            raise ValueError("Invalid humidity")
        if not math.isfinite(mrain) or mrain < 0:
            raise ValueError("Invalid expected rainfall")
        shc = b.get("shc") if isinstance(b.get("shc"), dict) else {}
        oc = float(shc["oc"]) if shc.get("oc") not in (None, "") else None
        ec = float(shc["ec"]) if shc.get("ec") not in (None, "") else None
        micro_raw = shc.get("micro") if isinstance(shc.get("micro"), dict) else {}
        micro = {k: float(v) for k, v in micro_raw.items()
                 if k in MICRO and v not in (None, "") and math.isfinite(float(v))}
        price_in = float(b["price"]) if b.get("price") not in (None, "") else None
        if price_in is not None and (not math.isfinite(price_in) or price_in < 0):
            raise ValueError("Invalid crop price")
    except (TypeError, ValueError, OverflowError):
        return jsonify(error=translate_advice_text("Please check the numeric values in your farm details.", lang)), 400

    # Live weather is optional. A valid seven-day sample is used if geocoding/API is offline
    # or returns an incomplete response.
    place = str(b.get("location") or "Bengaluru").strip() or "Bengaluru"
    source = "live"
    try:
        lat, lon, place = geocode(place)
        w = forecast(lat, lon)
        required = ("time", "temperature_2m_max", "temperature_2m_min",
                    "precipitation_sum", "precipitation_probability_max",
                    "et0_fao_evapotranspiration", "wind_speed_10m_max")
        if not isinstance(w, dict) or any(k not in w for k in required):
            raise ValueError("Weather response is incomplete")
        if any(not isinstance(w[k], list) or len(w[k]) < 7 for k in required):
            raise ValueError("Weather response does not contain seven forecast days")
        w = {k: w[k][:7] for k in required}
        for key in required[1:]:
            w[key] = [float(x) if x is not None else 0.0 for x in w[key]]
    except Exception:
        app.logger.exception("Live weather unavailable; using sample weather")
        w, source = sample_weather(), "sample"
        place = place + " (sample data: no internet)"

    try:
        if not growing:
            stage = 0
        temp = float(np.mean([(float(a) + float(c)) / 2
                              for a, c in zip(nz(w["temperature_2m_max"]), nz(w["temperature_2m_min"]))]))
        feat = [NL[nl], PL[pl], KL[kl], temp, hum, ph, mrain]

        # All catalogue crops have matching profiles, soil-fit and economics. If a future
        # catalogue entry is incomplete, keep the advice available using known-safe defaults.
        for c in CROPS:
            if c not in PROFILES:
                PROFILES[c] = PROFILES["Maize"]
            SOIL_FIT.setdefault(c, {"Sandy": .75, "Red": .85, "Loamy": 1.0, "Clay": .75, "Black": .85})
            SEASON_FIT.setdefault(c, {"Kharif": .85, "Rabi": .85, "Zaid": .65})
            ECON.setdefault(c, {"yield": 12, "cost": 20000, "price": 3000})
            REQ.setdefault(c, (80, 40, 40))
            STAGE_ACTIONS.setdefault(c, [
                f"Prepare the field and sow healthy {c.lower()} seed at locally recommended spacing.",
                f"Remove weeds and keep the {c.lower()} root zone evenly moist.",
                "Monitor flowering and avoid moisture stress.",
                "Reduce irrigation as the crop matures and harvest at the right time."
            ])
            CROP_NOTES.setdefault(c, f"Follow local agriculture-department guidance for {c.lower()} crop care.")

        ranking, fits, season = rank_crops(feat, soil, date.today().month)
        best = next((row["crop"] for row in ranking if row.get("ok")), ranking[0]["crop"])
        auto = crop == "Auto"
        if auto:
            crop = best

        price = ECON[crop]["price"] if (auto or price_in is None) else price_in
        res = advise(w, crop, stage, soil, sm)
        rec, _ = recommend(feat, crop)
        notes = soil_advice(soil, ph, oc, ec, micro)
        fert = fertilizer(crop, nl, pl, kl)
        fert["notes"] = notes
        res.update(
            alerts=risks(w), weather=w, place=place, source=source, crop=crop,
            growing=growing, auto=auto, crop_rec=rec, fert=fert,
            profit=profit(crop, fits[crop], price, area), temp=round(temp, 1),
            ranking=ranking, best=best, season=season, fit=round(fits[crop] * 100),
            outlook=outlook(w), steps=next_steps(w, res, crop, stage, growing),
            care=care_measures(w, crop, stage, notes) if growing else []
        )

        # Agent summaries are supplemental; a non-critical agent must never block the core advice.
        try:
            agents = [
                CropPlanningAgent(lambda: {"ranking": ranking, "selected": crop, "fit": round(fits[crop] * 100)},
                                  lambda x: f"Ranked {len(x['ranking'])} crops; selected {x['selected']} ({x['fit']}% fit)."),
                WeatherIntelligenceAgent(lambda: {"forecast": outlook(w), "alerts": risks(w)},
                                         lambda x: f"Analysed 7 forecast days and found {len(x['alerts'])} weather alerts."),
                IrrigationAgent(lambda: advise(w, crop, stage, soil, sm),
                                lambda x: f"Irrigation decision: {x['action']}."),
                SoilFertilizerAgent(lambda: {"fertilizer": fertilizer(crop, nl, pl, kl), "soil": soil_advice(soil, ph, oc, ec, micro)},
                                    lambda x: "Prepared soil observations and NPK fertilizer schedule."),
                CropHealthAgent(lambda: care_measures(w, crop, stage, notes),
                                lambda x: f"Prepared {len(x)} crop-care and health checks."),
                ProfitabilityAgent(lambda: profit(crop, fits[crop], price, area),
                                   lambda x: f"{x['verdict']}; estimated net ₹{x['net']:,}."),
                MultilingualAgent(lambda: translate_ui(lang),
                                  lambda x: f"Selected communication language: {x['name']}.")
            ]
            res["agent_team"] = MasterCoordinatorAgent().coordinate(agents, lang)
        except Exception:
            app.logger.exception("Supplementary agent failed; continuing with core advisory")
            res["agent_team"] = {"language": lang, "agents_completed": 0, "agents": []}

        res["language"] = lang
        try:
            res = translate_advice_payload(res, lang)
        except Exception:
            app.logger.exception("Advice translation failed; returning core advisory")
        return jsonify(res)
    except Exception as exc:
        app.logger.exception("Advice generation failed")
        messages = {
            "en": "Advice generation failed. Check the Flask terminal for the detailed error.",
            "hi": "सलाह तैयार नहीं हो सकी। विस्तृत त्रुटि के लिए Flask टर्मिनल देखें।",
            "kn": "ಸಲಹೆ ಸಿದ್ಧವಾಗಲಿಲ್ಲ. ವಿವರವಾದ ದೋಷಕ್ಕಾಗಿ Flask ಟರ್ಮಿನಲ್ ಪರಿಶೀಲಿಸಿ.",
            "te": "సలహా రూపొందలేదు. పూర్తి వివరాల కోసం Flask టెర్మినల్‌ను చూడండి."
        }
        return jsonify(error=messages.get(lang, messages["en"]), debug=str(exc)), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
