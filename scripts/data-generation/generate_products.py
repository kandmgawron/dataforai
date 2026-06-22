#!/usr/bin/env python3
"""
Meridian Outdoor Co. — Product catalogue generation script.

Generates synthetic product records for the Ridge AI course dataset.
Amazon Bedrock Claude Haiku produces short and long descriptions; all
structural fields (SKU, pricing, attributes, stock) are deterministically
seeded for repeatability.

Usage:
    # 50-product spot-check sample (run first, review output, then scale up)
    python generate_products.py --count 50 --output ../../data/

    # Full 40,000-SKU dataset (run once, commit output — see cost note below)
    python generate_products.py --count 40000 --output ../../data/ --seed 42

    # Skip Bedrock — generates structural fields only, description fields left blank
    python generate_products.py --count 50 --no-bedrock --output ../../data/

Cost estimate:
    50 products:     ~£0.05  (sample run)
    40,000 products: ~£40-60 (full run, one-time cost)

Requirements:
    pip install boto3 pandas pyarrow tqdm
    AWS profile 'ridge-course-dev' with Bedrock model access in eu-west-2
    Bedrock model enabled: anthropic.claude-3-haiku-20240307-v1:0
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import boto3
import pandas as pd
from botocore.exceptions import ClientError
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AWS_PROFILE = "ridge-course-dev"
AWS_REGION = "eu-west-1"
BEDROCK_MODEL = "eu.amazon.nova-2-lite-v1:0"

# 12 Meridian physical store locations
STORES = [
    "EDI-NEWTOWN",
    "EDI-ROYALMILE",
    "GLA-CITYCENTRE",
    "MAN-ARNDALE",
    "LEE-HEADROW",
    "NEW-GRAINGER",
    "BHM-BULLRING",
    "BRS-CABOT",
    "LON-COVENTGARDEN",
    "LON-CANARYWHARF",
    "SHE-FARGATE",
    "KES-LAKEDISTRICT",
]

# Brand definitions: tier drives pricing multiplier and product range
BRANDS: dict[str, dict[str, Any]] = {
    "Pinnacle":       {"tier": "premium",  "markup": 1.35},
    "Nordic":         {"tier": "premium",  "markup": 1.30},
    "Cairn":          {"tier": "mid",      "markup": 1.00},
    "Stormline":      {"tier": "mid",      "markup": 1.05},
    "TrailForge":     {"tier": "mid",      "markup": 1.10},
    "Ascent":         {"tier": "mid",      "markup": 1.00},
    "Glacier":        {"tier": "premium",  "markup": 1.25},
    "Meridian Ridge": {"tier": "budget",   "markup": 0.70},
}

# Category taxonomy.
# Fields: l1, l2, l3, weight_min_g, weight_max_g, base_price_min, base_price_max,
#         activities, seasons, brands_pool, sku_prefix
TAXONOMY: list[dict[str, Any]] = [
    dict(l1="Clothing", l2="Jackets & Coats", l3="Waterproof Jackets",
         wmin=280, wmax=900, pmin=80, pmax=320,
         activities=["hiking", "mountaineering", "wild_camping", "trail_running"],
         seasons=["all_season"],
         brands=["Pinnacle", "Cairn", "Stormline", "Meridian Ridge"],
         prefix="WPJ"),
    dict(l1="Clothing", l2="Jackets & Coats", l3="Insulated Jackets",
         wmin=250, wmax=650, pmin=110, pmax=290,
         activities=["hiking", "mountaineering", "winter_camping", "skiing"],
         seasons=["autumn", "winter", "spring"],
         brands=["Pinnacle", "Cairn", "Nordic", "Meridian Ridge"],
         prefix="INJ"),
    dict(l1="Clothing", l2="Midlayers", l3="Fleece Jackets",
         wmin=300, wmax=550, pmin=40, pmax=140,
         activities=["hiking", "mountaineering", "camping", "climbing"],
         seasons=["spring", "autumn", "winter"],
         brands=["Cairn", "Nordic", "Meridian Ridge"],
         prefix="FLJ"),
    dict(l1="Clothing", l2="Base Layers", l3="Merino Base Layer Tops",
         wmin=150, wmax=280, pmin=45, pmax=115,
         activities=["hiking", "trail_running", "mountaineering", "skiing"],
         seasons=["all_season"],
         brands=["Nordic", "Cairn", "Meridian Ridge"],
         prefix="BLT"),
    dict(l1="Clothing", l2="Base Layers", l3="Merino Base Layer Bottoms",
         wmin=130, wmax=250, pmin=40, pmax=105,
         activities=["hiking", "trail_running", "mountaineering", "skiing"],
         seasons=["all_season"],
         brands=["Nordic", "Cairn", "Meridian Ridge"],
         prefix="BLB"),
    dict(l1="Clothing", l2="Trousers & Shorts", l3="Waterproof Over-Trousers",
         wmin=200, wmax=450, pmin=60, pmax=190,
         activities=["hiking", "mountaineering", "wild_camping"],
         seasons=["all_season"],
         brands=["Pinnacle", "Stormline", "Cairn", "Meridian Ridge"],
         prefix="WPT"),
    dict(l1="Footwear", l2="Boots", l3="Walking Boots",
         wmin=800, wmax=1400, pmin=100, pmax=250,
         activities=["hiking", "mountaineering", "walking"],
         seasons=["all_season"],
         brands=["TrailForge", "Pinnacle", "Meridian Ridge"],
         prefix="WLB"),
    dict(l1="Footwear", l2="Shoes", l3="Trail Running Shoes",
         wmin=450, wmax=800, pmin=80, pmax=165,
         activities=["trail_running", "fell_running", "hiking"],
         seasons=["spring", "summer", "autumn"],
         brands=["TrailForge", "Pinnacle", "Meridian Ridge"],
         prefix="TRS"),
    dict(l1="Footwear", l2="Shoes", l3="Approach Shoes",
         wmin=500, wmax=850, pmin=90, pmax=190,
         activities=["climbing", "scrambling", "hiking"],
         seasons=["spring", "summer", "autumn"],
         brands=["TrailForge", "Ascent"],
         prefix="APS"),
    dict(l1="Rucksacks & Bags", l2="Hiking Packs", l3="Day Packs (10-25L)",
         wmin=400, wmax=750, pmin=40, pmax=130,
         activities=["hiking", "trail_running", "climbing", "cycling"],
         seasons=["all_season"],
         brands=["Cairn", "Pinnacle", "Meridian Ridge"],
         prefix="DPK"),
    dict(l1="Rucksacks & Bags", l2="Hiking Packs", l3="Weekend Packs (25-50L)",
         wmin=900, wmax=1800, pmin=110, pmax=260,
         activities=["hiking", "wild_camping", "mountaineering"],
         seasons=["all_season"],
         brands=["Cairn", "Pinnacle", "Meridian Ridge"],
         prefix="WPK"),
    dict(l1="Rucksacks & Bags", l2="Hiking Packs", l3="Expedition Packs (50L+)",
         wmin=1600, wmax=2800, pmin=180, pmax=360,
         activities=["mountaineering", "expedition", "wild_camping"],
         seasons=["all_season"],
         brands=["Pinnacle", "Cairn"],
         prefix="EPK"),
    dict(l1="Tents & Shelters", l2="Backpacking Tents", l3="2-Person Tents",
         wmin=1200, wmax=2800, pmin=175, pmax=500,
         activities=["wild_camping", "backpacking", "mountaineering"],
         seasons=["spring", "summer", "autumn", "winter"],
         brands=["Nordic", "Cairn", "Meridian Ridge"],
         prefix="2PT"),
    dict(l1="Tents & Shelters", l2="Backpacking Tents", l3="1-Person Tents",
         wmin=800, wmax=1800, pmin=155, pmax=450,
         activities=["wild_camping", "solo_hiking", "ultralight"],
         seasons=["spring", "summer", "autumn"],
         brands=["Nordic", "Cairn", "Meridian Ridge"],
         prefix="1PT"),
    dict(l1="Sleeping", l2="Sleeping Bags", l3="Down Sleeping Bags",
         wmin=600, wmax=1400, pmin=150, pmax=450,
         activities=["wild_camping", "mountaineering", "backpacking"],
         seasons=["all_season"],
         brands=["Nordic", "Cairn", "Pinnacle"],
         prefix="DSB"),
    dict(l1="Sleeping", l2="Sleeping Bags", l3="Synthetic Sleeping Bags",
         wmin=800, wmax=1800, pmin=70, pmax=250,
         activities=["camping", "backpacking", "festivals"],
         seasons=["spring", "summer", "autumn"],
         brands=["Cairn", "Nordic", "Meridian Ridge"],
         prefix="SSB"),
    dict(l1="Sleeping", l2="Sleeping Mats", l3="Inflatable Sleeping Mats",
         wmin=350, wmax=700, pmin=55, pmax=185,
         activities=["camping", "backpacking", "mountaineering"],
         seasons=["all_season"],
         brands=["Nordic", "Cairn", "Meridian Ridge"],
         prefix="ISM"),
    dict(l1="Navigation & Safety", l2="Lighting", l3="Head Torches",
         wmin=60, wmax=180, pmin=25, pmax=110,
         activities=["hiking", "trail_running", "climbing", "camping"],
         seasons=["all_season"],
         brands=["Cairn", "Meridian Ridge"],
         prefix="HTR"),
    dict(l1="Navigation & Safety", l2="Navigation", l3="Compasses",
         wmin=50, wmax=120, pmin=18, pmax=80,
         activities=["hiking", "mountaineering", "orienteering"],
         seasons=["all_season"],
         brands=["Cairn", "Meridian Ridge"],
         prefix="CMP"),
    dict(l1="Climbing & Scrambling", l2="Head Protection", l3="Climbing Helmets",
         wmin=250, wmax=500, pmin=50, pmax=150,
         activities=["climbing", "mountaineering", "scrambling"],
         seasons=["spring", "summer", "autumn"],
         brands=["Ascent", "Pinnacle"],
         prefix="CHM"),
    dict(l1="Climbing & Scrambling", l2="Harnesses", l3="Sport Harnesses",
         wmin=350, wmax=550, pmin=50, pmax=145,
         activities=["climbing", "mountaineering", "via_ferrata"],
         seasons=["spring", "summer", "autumn"],
         brands=["Ascent", "Pinnacle"],
         prefix="SPH"),
    dict(l1="Ski & Snowsports", l2="Clothing", l3="Ski Jackets",
         wmin=600, wmax=1200, pmin=120, pmax=400,
         activities=["skiing", "snowboarding", "ski_touring"],
         seasons=["winter"],
         brands=["Glacier", "Pinnacle", "Meridian Ridge"],
         prefix="SKJ"),
    dict(l1="Ski & Snowsports", l2="Eyewear", l3="Ski Goggles",
         wmin=180, wmax=320, pmin=45, pmax=185,
         activities=["skiing", "snowboarding", "ski_touring"],
         seasons=["winter"],
         brands=["Glacier", "Meridian Ridge"],
         prefix="SKG"),
    dict(l1="Camping & Cooking", l2="Stoves", l3="Gas Stoves",
         wmin=80, wmax=400, pmin=28, pmax=135,
         activities=["camping", "backpacking", "mountaineering"],
         seasons=["all_season"],
         brands=["Cairn", "Nordic", "Meridian Ridge"],
         prefix="GST"),
    dict(l1="Camping & Cooking", l2="Water Treatment", l3="Water Filters",
         wmin=60, wmax=250, pmin=30, pmax=110,
         activities=["wild_camping", "backpacking", "mountaineering", "travel"],
         seasons=["all_season"],
         brands=["Cairn", "Meridian Ridge"],
         prefix="WFT"),
    dict(l1="Accessories", l2="Poles", l3="Trekking Poles",
         wmin=300, wmax=600, pmin=38, pmax=160,
         activities=["hiking", "trail_running", "mountaineering", "nordic_walking"],
         seasons=["all_season"],
         brands=["Cairn", "Pinnacle", "Meridian Ridge"],
         prefix="TKP"),
    dict(l1="Accessories", l2="Handwear", l3="Gloves & Mitts",
         wmin=80, wmax=280, pmin=18, pmax=90,
         activities=["hiking", "mountaineering", "skiing", "climbing"],
         seasons=["autumn", "winter", "spring"],
         brands=["Nordic", "Cairn", "Stormline", "Meridian Ridge"],
         prefix="GLV"),
]

# Products that must exist in every run (referenced in Module 5 notebook queries).
ANCHORED_PRODUCTS: list[dict[str, Any]] = [
    {
        "sku": "MER-WPK-CAI-001",
        "name": "Cairngorm 45L Backpack",
        "category_l1": "Rucksacks & Bags",
        "category_l2": "Hiking Packs",
        "category_l3": "Weekend Packs (25-50L)",
        "brand": "Cairn",
        "price_gbp": 175.00,
        "sale_price_gbp": None,
        "weight_grams": 1340,
        "materials": ["210D nylon ripstop main body", "500D Cordura base panel", "aluminium frame stay"],
        "attributes": {
            "volume_litres": 45,
            "back_length_options": ["short", "regular", "long"],
            "hipbelt": "padded_adjustable",
            "load_lifters": True,
            "sternum_strap": True,
            "laptop_sleeve": "fits_up_to_17in",
            "hydration_compatible": True,
            "rain_cover_included": True,
            "external_pockets": 4,
            "colours": ["slate_grey", "forest_green", "burnt_orange"],
        },
        "activity_tags": ["hiking", "wild_camping", "mountaineering"],
        "season": ["all_season"],
        "gender": "unisex",
    },
    {
        "sku": "MER-WPJ-CAI-001",
        "name": "Cairngorm Pro Shell Jacket",
        "category_l1": "Clothing",
        "category_l2": "Jackets & Coats",
        "category_l3": "Waterproof Jackets",
        "brand": "Pinnacle",
        "price_gbp": 280.00,
        "sale_price_gbp": None,
        "weight_grams": 420,
        "materials": ["3-layer 20D nylon ripstop hardshell", "recycled polyester face fabric", "mesh drop lining", "YKK AquaGuard zips"],
        "attributes": {
            "waterproof_rating_mm": 28000,
            "breathability_mvr": 25000,
            "seam_type": "fully_taped",
            "hood_type": "helmet_compatible",
            "packable": True,
            "pocket_count": 5,
            "pit_zips": True,
            "colours": ["black", "navy", "fiery_red"],
            "sizes": ["XS", "S", "M", "L", "XL", "XXL"],
            "gender": "unisex",
        },
        "activity_tags": ["hiking", "mountaineering", "trail_running", "wild_camping"],
        "season": ["all_season"],
        "gender": "unisex",
    },
    {
        "sku": "MER-2PT-CAI-001",
        "name": "Cairn 2 Backpacking Tent",
        "category_l1": "Tents & Shelters",
        "category_l2": "Backpacking Tents",
        "category_l3": "2-Person Tents",
        "brand": "Nordic",
        "price_gbp": 349.00,
        "sale_price_gbp": None,
        "weight_grams": 1850,
        "materials": ["20D ripstop nylon flysheet (3000mm HH)", "15D nylon inner", "DAC Featherlite NSL poles", "alloy pegs"],
        "attributes": {
            "inner_area_sqm": 2.8,
            "vestibule_area_sqm": 0.9,
            "peak_height_cm": 100,
            "pole_material": "DAC_aluminium",
            "season_rating": "3_season",
            "freestanding": True,
            "packed_dimensions_cm": "46 x 16",
            "doors": 2,
            "ventilation": "dual_mesh_inner",
            "colours": ["terra", "storm_grey"],
        },
        "activity_tags": ["wild_camping", "backpacking", "mountaineering"],
        "season": ["spring", "summer", "autumn"],
        "gender": "unisex",
    },
]

# ---------------------------------------------------------------------------
# Name fragments for procedural product naming
# ---------------------------------------------------------------------------

PLACE_NAMES = [
    "Ben Nevis", "Glencoe", "Skye", "Loch Lomond", "Hebrides", "Grampian",
    "Torridon", "Knoydart", "Affric", "Morar", "Arran", "Galloway",
    "Snowdon", "Brecon", "Dartmoor", "Exmoor", "Cheviot", "Howgill",
    "Langdale", "Scafell", "Helvellyn", "Blencathra", "Coniston", "Strathmore",
]
DESCRIPTORS = [
    "Pro", "Elite", "Ultra", "Lite", "Plus", "Sport", "Comp",
    "Trail", "Summit", "Alpine", "Apex", "Advance", "Active", "Expert",
]

# Per-category product type labels used in name generation (singular form)
L3_PRODUCT_LABEL: dict[str, str] = {
    "Waterproof Jackets": "Waterproof Jacket",
    "Insulated Jackets": "Insulated Jacket",
    "Fleece Jackets": "Fleece",
    "Merino Base Layer Tops": "Base Layer Top",
    "Merino Base Layer Bottoms": "Base Layer Bottom",
    "Waterproof Over-Trousers": "Over-Trousers",
    "Walking Boots": "Walking Boot",
    "Trail Running Shoes": "Trail Shoe",
    "Approach Shoes": "Approach Shoe",
    "Day Packs (10-25L)": "Daypack",
    "Weekend Packs (25-50L)": "Backpack",
    "Expedition Packs (50L+)": "Expedition Pack",
    "2-Person Tents": "2-Person Tent",
    "1-Person Tents": "1-Person Tent",
    "Down Sleeping Bags": "Down Sleeping Bag",
    "Synthetic Sleeping Bags": "Sleeping Bag",
    "Inflatable Sleeping Mats": "Sleeping Mat",
    "Head Torches": "Headtorch",
    "Compasses": "Compass",
    "Climbing Helmets": "Climbing Helmet",
    "Sport Harnesses": "Sport Harness",
    "Ski Jackets": "Ski Jacket",
    "Ski Goggles": "Ski Goggles",
    "Gas Stoves": "Gas Stove",
    "Water Filters": "Water Filter",
    "Trekking Poles": "Trekking Poles",
    "Gloves & Mitts": "Gloves",
}
MATERIALS_BY_CATEGORY: dict[str, list[str]] = {
    "Waterproof Jackets": [
        "2.5-layer 20D nylon ripstop", "3-layer hardshell nylon", "recycled polyester face fabric",
        "mesh lining", "YKK AquaGuard zips", "DWR treated outer",
    ],
    "Insulated Jackets": [
        "800-fill recycled down", "PrimaLoft Gold insulation", "recycled polyester shell",
        "anti-snag lining", "30D nylon ripstop",
    ],
    "Fleece Jackets": [
        "100% recycled polyester", "Polartec Classic 200", "grid fleece backer",
        "anti-pill face fabric", "flatlock seams",
    ],
    "Merino Base Layer Tops": [
        "87% merino wool 13% nylon", "100% 18.9 micron merino wool",
        "flatlock seams", "ribbed hem and cuffs",
    ],
    "Merino Base Layer Bottoms": [
        "87% merino wool 13% nylon", "100% merino wool",
        "flat seam construction", "ribbed waistband",
    ],
    "Waterproof Over-Trousers": [
        "2.5-layer nylon ripstop", "critically taped seams", "DWR treatment",
        "full-length side zips", "ankle zips",
    ],
    "Walking Boots": [
        "full-grain leather upper", "Gore-Tex lining", "Vibram outsole",
        "nylon midsole shank", "cushioned footbed",
    ],
    "Trail Running Shoes": [
        "engineered mesh upper", "sticky rubber outsole", "EVA midsole",
        "internal rock plate", "drainage ports",
    ],
    "Approach Shoes": [
        "suede leather rand", "sticky rubber outsole", "EVA foam midsole",
        "lace-to-toe lacing", "toecap reinforcement",
    ],
    "Day Packs (10-25L)": [
        "200D ripstop nylon", "recycled polyester mesh", "foam padding",
        "EVA back panel", "welded zips",
    ],
    "Weekend Packs (25-50L)": [
        "210D nylon ripstop", "500D Cordura base", "aluminium frame stay",
        "EVA foam hipbelt", "mesh back panel",
    ],
    "Expedition Packs (50L+)": [
        "420D nylon Multicam", "500D Cordura", "dual aluminium stays",
        "removable top lid", "compression straps",
    ],
    "2-Person Tents": [
        "20D ripstop nylon flysheet", "15D nylon inner", "DAC aluminium poles",
        "3000mm HH coating", "bathtub floor",
    ],
    "1-Person Tents": [
        "10D silnylon flysheet", "15D nylon inner", "carbon fibre poles",
        "3000mm HH coating", "silicone seam sealing",
    ],
    "Down Sleeping Bags": [
        "850-fill power recycled down", "20D ripstop nylon shell",
        "20D polyester lining", "YKK zip", "contoured hood",
    ],
    "Synthetic Sleeping Bags": [
        "PrimaLoft Silver insulation", "50D ripstop polyester shell",
        "lining fleece", "YKK zip", "draft collar",
    ],
    "Inflatable Sleeping Mats": [
        "40D nylon top sheet", "70D nylon base", "polyester baffles",
        "TPU laminate", "welded valve",
    ],
    "Head Torches": [
        "polycarbonate housing", "silicone strap", "ABS headband",
        "LED array", "IPX4 water resistance",
    ],
    "Compasses": [
        "acrylic baseplate", "liquid-filled capsule", "nylon lanyard",
        "tungsten carbide wear tip", "declination adjustment",
    ],
    "Climbing Helmets": [
        "polypropylene shell", "EPS foam liner", "nylon webbing",
        "UIAA 106 compliant", "EN 12492 certified",
    ],
    "Sport Harnesses": [
        "nylon webbing waistbelt", "polyamide leg loops", "Dyneema tie-in points",
        "aluminium belay loop", "UIAA certified",
    ],
    "Ski Jackets": [
        "20K waterproof membrane", "PrimaLoft Black insulation",
        "recycled polyester shell", "pit zip vents", "powder skirt",
    ],
    "Ski Goggles": [
        "polycarbonate lens", "dual-layer foam", "anti-fog inner coating",
        "silicone strap grip", "TPU frame",
    ],
    "Gas Stoves": [
        "stainless steel burner", "aluminium pot supports",
        "piezo ignition", "brass jet", "foldable design",
    ],
    "Water Filters": [
        "hollow-fibre membrane", "activated carbon core",
        "BPA-free housing", "silicone coupling", "0.1 micron absolute",
    ],
    "Trekking Poles": [
        "7075 aluminium shafts", "foam cork grip", "nylon strap",
        "carbide tip", "rubber tip protector",
    ],
    "Gloves & Mitts": [
        "soft shell outer", "100% merino liner", "silicone grip palm",
        "touch-screen compatible fingertips", "wrist cinch",
    ],
}

ATTRIBUTES_BY_CATEGORY: dict[str, dict[str, Any]] = {
    "Waterproof Jackets": {
        "waterproof_rating_mm": [10000, 15000, 20000, 28000],
        "breathability_mvr": [10000, 15000, 20000, 25000],
        "seam_type": ["critically_taped", "fully_taped"],
        "hood_type": ["adjustable", "helmet_compatible"],
        "packable": [True, False],
        "pocket_count": [3, 4, 5],
        "pit_zips": [True, False],
        "sizes": ["XS-XXL"],
        "gender": ["mens", "womens", "unisex"],
        "colours": [["black", "navy"], ["slate", "cobalt"], ["red", "orange"], ["green", "teal"]],
    },
    "Insulated Jackets": {
        "fill_type": ["down_800fp", "down_850fp", "primaloft_gold", "primaloft_silver"],
        "fill_weight_g": [80, 100, 120, 150],
        "baffle_type": ["sewn_through", "box_wall"],
        "packable": [True, False],
        "hood": [True, False],
        "pocket_count": [3, 4, 5],
        "sizes": ["XS-XXL"],
        "gender": ["mens", "womens", "unisex"],
    },
    "Fleece Jackets": {
        "fabric_weight_gsm": [100, 200, 300],
        "zip_type": ["full_zip", "half_zip"],
        "pocket_count": [2, 3, 4],
        "sizes": ["XS-XXL"],
        "gender": ["mens", "womens", "unisex"],
    },
    "Merino Base Layer Tops": {
        "merino_weight_gsm": [150, 175, 200, 260],
        "neck_style": ["crew", "half_zip", "zip_neck"],
        "sleeve": ["short", "long"],
        "sizes": ["XS-XXL"],
        "gender": ["mens", "womens", "unisex"],
    },
    "Merino Base Layer Bottoms": {
        "merino_weight_gsm": [150, 175, 200],
        "waist": ["flat_draw", "elastic"],
        "sizes": ["XS-XXL"],
        "gender": ["mens", "womens"],
    },
    "Waterproof Over-Trousers": {
        "waterproof_rating_mm": [10000, 15000, 20000],
        "seam_type": ["critically_taped", "fully_taped"],
        "waist": ["elastic", "draw_cord"],
        "ankle_zips": [True, False],
        "sizes": ["XS-XXL"],
        "gender": ["mens", "womens", "unisex"],
    },
    "Walking Boots": {
        "waterproofing": ["GORE-TEX", "eVent", "HydroGuard", "none"],
        "ankle_height": ["low", "mid", "high"],
        "sole": ["Vibram_Ecostep", "Vibram_Megagrip", "Continental"],
        "width": ["regular", "wide"],
        "uk_sizes": ["3-13"],
        "gender": ["mens", "womens", "unisex"],
    },
    "Trail Running Shoes": {
        "drop_mm": [0, 4, 6, 8],
        "stack_height_mm": [18, 22, 26, 30],
        "sole": ["Vibram_Megagrip", "Continental_TrailContact", "proprietary_rubber"],
        "rock_plate": [True, False],
        "uk_sizes": ["3-13"],
        "gender": ["mens", "womens"],
    },
    "Approach Shoes": {
        "closure": ["lace", "lace_and_velcro"],
        "rand": ["full", "partial"],
        "sole": ["Vibram_XS_Edge", "Vibram_XS_Trek", "Stealth_C4"],
        "uk_sizes": ["3-13"],
        "gender": ["mens", "womens"],
    },
    "Day Packs (10-25L)": {
        "volume_litres": [10, 15, 18, 20, 22, 25],
        "hydration_compatible": [True, False],
        "hipbelt": ["minimal", "padded", "none"],
        "laptop_sleeve": [True, False],
        "colours": [["black"], ["grey"], ["blue"], ["red"], ["green"]],
    },
    "Weekend Packs (25-50L)": {
        "volume_litres": [28, 32, 35, 40, 45, 50],
        "back_length_options": [["short", "regular", "long"], ["regular"]],
        "hipbelt": ["padded_adjustable"],
        "load_lifters": [True, False],
        "rain_cover": [True, False],
        "hydration_compatible": [True],
    },
    "Expedition Packs (50L+)": {
        "volume_litres": [55, 60, 65, 70, 80],
        "top_lid": ["removable", "fixed"],
        "hipbelt": ["padded_adjustable_with_pockets"],
        "compression_straps": [True],
        "ice_axe_loop": [True],
        "rain_cover": [True, False],
    },
    "2-Person Tents": {
        "inner_area_sqm": [2.2, 2.4, 2.6, 2.8, 3.0],
        "vestibule_area_sqm": [0.6, 0.8, 0.9, 1.0],
        "peak_height_cm": [90, 95, 100, 105, 110],
        "pole_material": ["DAC_aluminium", "7001_aluminium", "carbon_fibre"],
        "season_rating": ["2_season", "3_season", "4_season"],
        "freestanding": [True, False],
        "doors": [1, 2],
    },
    "1-Person Tents": {
        "inner_area_sqm": [1.1, 1.3, 1.5, 1.8],
        "vestibule_area_sqm": [0.4, 0.6, 0.8],
        "peak_height_cm": [75, 85, 90, 95],
        "pole_material": ["DAC_aluminium", "carbon_fibre"],
        "season_rating": ["2_season", "3_season"],
        "freestanding": [True, False],
    },
    "Down Sleeping Bags": {
        "temperature_comfort_c": [0, -5, -10, -15],
        "fill_power": [650, 700, 750, 800, 850],
        "fill_weight_g": [250, 300, 400, 500],
        "zip_side": ["left", "right"],
        "packed_diameter_cm": [14, 16, 18, 20],
        "gender": ["mens", "womens", "unisex"],
    },
    "Synthetic Sleeping Bags": {
        "temperature_comfort_c": [0, 5, -5],
        "insulation": ["PrimaLoft_Silver", "PrimaLoft_Sport", "Climashield_Apex"],
        "fill_weight_g": [350, 450, 600],
        "zip_side": ["left", "right"],
        "gender": ["mens", "womens", "unisex"],
    },
    "Inflatable Sleeping Mats": {
        "r_value": [1.5, 2.5, 3.5, 4.5, 5.5],
        "thickness_cm": [5, 7, 9, 10],
        "width_cm": [51, 55, 63],
        "valve_type": ["flat_valve", "multifunction_valve"],
        "packed_diameter_cm": [9, 11, 14],
    },
    "Head Torches": {
        "max_lumens": [100, 200, 350, 500, 750],
        "beam_distance_m": [30, 50, 80, 100, 120],
        "battery_type": ["AAA_x3", "rechargeable_USB", "rechargeable_USB_C"],
        "burn_time_max_hrs": [40, 60, 80, 100, 150],
        "ipx_rating": ["IPX4", "IPX6", "IPX8"],
        "modes": [["high", "mid", "low"], ["high", "mid", "low", "red"]],
    },
    "Compasses": {
        "type": ["baseplate", "mirrored_sighting"],
        "bezel_graduations": [2, 1],
        "scale_mm_per_km": [1, 2],
        "global_needle": [True, False],
        "declination_adjustment": [True, False],
        "glow_markings": [True, False],
    },
    "Climbing Helmets": {
        "construction": ["foam", "hardshell", "hybrid"],
        "adjuster": ["wheel", "boa", "dial"],
        "head_size_cm": ["51-56", "53-61", "55-63"],
        "certification": ["EN 12492", "UIAA 106"],
        "ventilation_slots": [6, 10, 14, 18],
    },
    "Sport Harnesses": {
        "waistbelt_width_mm": [65, 75, 85],
        "gear_loops": [3, 4, 5],
        "belay_loop": ["single", "reinforced"],
        "leg_loop_type": ["fixed", "adjustable"],
        "sizes": ["XS", "S", "M", "L", "XL"],
        "gender": ["mens", "womens", "unisex"],
    },
    "Ski Jackets": {
        "waterproof_rating_mm": [10000, 15000, 20000],
        "breathability_mvr": [10000, 15000, 20000],
        "insulation": ["none", "primaloft_60g", "primaloft_100g", "down_400g"],
        "powder_skirt": [True, False],
        "lift_pass_pocket": [True, False],
        "sizes": ["XS-XXL"],
        "gender": ["mens", "womens", "unisex"],
    },
    "Ski Goggles": {
        "lens_category": [1, 2, 3, 4],
        "vlt_percent": [5, 18, 30, 50, 75],
        "lens_shape": ["cylindrical", "spherical", "torical"],
        "otg": [True, False],
        "anti_fog": [True],
        "frame_fit": ["low_bridge", "medium", "high_bridge"],
    },
    "Gas Stoves": {
        "fuel_type": ["isobutane_propane", "butane"],
        "boil_time_1L_min": [2.5, 3.0, 3.5, 4.5],
        "max_output_kw": [2.5, 3.0, 3.5, 4.5],
        "piezo_ignition": [True, False],
        "simmer_control": [True, False],
        "fold_flat": [True, False],
    },
    "Water Filters": {
        "filter_type": ["hollow_fibre", "ceramic", "straw"],
        "pore_size_micron": [0.02, 0.1, 0.2],
        "flow_rate_l_per_min": [0.5, 1.0, 1.5, 2.0],
        "filter_life_litres": [1000, 2000, 4000, 100000],
        "removes_bacteria": [True],
        "removes_protozoa": [True],
        "removes_viruses": [False, True],
    },
    "Trekking Poles": {
        "material": ["7075_aluminium", "carbon_fibre", "6061_aluminium"],
        "sections": [2, 3],
        "lock_type": ["twist_lock", "lever_lock", "flick_lock"],
        "min_length_cm": [59, 65, 70],
        "max_length_cm": [125, 130, 135],
        "tip": ["carbide", "rubber"],
        "sold_as": ["pair"],
    },
    "Gloves & Mitts": {
        "shell_material": ["soft_shell", "hard_shell", "merino_knit"],
        "waterproof": [True, False],
        "liner_removable": [True, False],
        "touchscreen_compatible": [True, False],
        "sizes": ["XS", "S", "M", "L", "XL"],
        "gender": ["mens", "womens", "unisex"],
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sku(rng: random.Random, prefix: str, brand: str, seq: int) -> str:
    brand_code = brand.upper().replace(" ", "")[:3]
    return f"MER-{prefix}-{brand_code}-{seq:04d}"


def _round_price(price: float) -> float:
    """Round to nearest £0.99 / £4.99 / £9.99 pattern."""
    endings = [0.99, 4.99, 9.99]
    base = round(price)
    # pick the ending closest to the decimal portion
    ending = min(endings, key=lambda e: abs((base + e - round(base + e)) - (price - round(price))))
    return round(base + ending - int(base + ending) + int(base), 2) if base > 0 else round(price, 2)


def _stock(rng: random.Random, price: float) -> dict[str, int]:
    """Generate realistic store stock levels. Higher-priced items have lower stock."""
    if price < 60:
        stock_range = (8, 40)
    elif price < 150:
        stock_range = (4, 20)
    elif price < 300:
        stock_range = (2, 12)
    else:
        stock_range = (0, 8)

    stock: dict[str, int] = {}
    for store in STORES:
        # Keswick (Lake District) and Edinburgh typically carry more outdoor stock
        if store in ("KES-LAKEDISTRICT", "EDI-NEWTOWN", "EDI-ROYALMILE"):
            multiplier = 1.5
        else:
            multiplier = 1.0
        qty = int(rng.randint(*stock_range) * multiplier)
        # ~15% chance of zero stock at any given location
        if rng.random() < 0.15:
            qty = 0
        stock[store] = qty
    return stock


def _pick_attributes(rng: random.Random, l3: str) -> dict[str, Any]:
    spec = ATTRIBUTES_BY_CATEGORY.get(l3, {})
    out: dict[str, Any] = {}
    for key, options in spec.items():
        if not isinstance(options, list):
            out[key] = options
        elif key == "sizes":
            # sizes is always a range string or full list, not a random single value
            out[key] = options if len(options) == 1 else options
        elif key in ("colours", "back_length_options", "modes"):
            # these are pools of pools — pick one sub-list
            out[key] = rng.choice(options)
        else:
            out[key] = rng.choice(options)
    return out


def _pick_materials(rng: random.Random, l3: str, n: int = 3) -> list[str]:
    pool = MATERIALS_BY_CATEGORY.get(l3, ["nylon", "polyester", "aluminium"])
    return rng.sample(pool, min(n, len(pool)))


def _timestamps(rng: random.Random) -> tuple[str, str]:
    """Random created_at in the past 3 years, updated_at after that."""
    base = datetime(2022, 1, 1, tzinfo=timezone.utc)
    delta_days = rng.randint(0, 3 * 365)
    created = base + timedelta(days=delta_days)
    updated = created + timedelta(days=rng.randint(0, 90))
    return created.isoformat(), updated.isoformat()


def _name_from_parts(rng: random.Random, cat_spec: dict[str, Any], brand: str) -> str:
    """Generate a plausible product name: <Place> [Descriptor] <ProductType> [Suffix]."""
    place = rng.choice(PLACE_NAMES)
    descriptor = rng.choice(DESCRIPTORS)
    l3 = cat_spec["l3"]
    product_type = L3_PRODUCT_LABEL.get(l3, l3.split("(")[0].strip())

    # Packs: include litre volume
    if "Pack" in product_type or "Daypack" in product_type:
        if "Daypack" in product_type:
            vol = rng.choice([15, 18, 20, 22, 25])
        elif "Expedition" in product_type:
            vol = rng.choice([55, 60, 65, 70, 75])
        else:
            vol = rng.choice([28, 30, 32, 35, 40, 45])
        use_descriptor = rng.random() < 0.4
        if use_descriptor:
            return f"{place} {descriptor} {vol}L {product_type}"
        return f"{place} {vol}L {product_type}"

    # Sleeping bags: append temperature comfort rating
    if "Sleeping Bag" in product_type:
        temp = rng.choice([0, -3, -5, -8, -10, -15])
        return f"{place} {product_type} ({temp}°C)"

    # Headtorches: append lumen count
    if "Headtorch" in product_type:
        lumens = rng.choice([100, 200, 350, 500])
        return f"{place} {lumens}lm {product_type}"

    # Stoves/filters/mats: just place + descriptor + type
    if any(t in product_type for t in ["Stove", "Filter", "Mat", "Compass", "Poles"]):
        return f"{place} {product_type}"

    # Default: place + optional descriptor + product type
    use_descriptor = rng.random() < 0.55
    if use_descriptor:
        return f"{place} {descriptor} {product_type}"
    return f"{place} {product_type}"


# ---------------------------------------------------------------------------
# Bedrock description generation
# ---------------------------------------------------------------------------


def _build_description_prompt(product: dict[str, Any]) -> str:
    attr_str = json.dumps(
        {k: v for k, v in product["attributes"].items() if k not in ("sizes", "colours", "gender")},
        separators=(", ", ": "),
    )
    return f"""Generate product descriptions for Meridian Outdoor Co., a UK outdoor retailer.

Product:
  Name: {product["name"]}
  Category: {product["category_l1"]} > {product["category_l2"]} > {product["category_l3"]}
  Brand: {product["brand"]}
  Price: £{product["price_gbp"]:.2f}
  Weight: {product["weight_grams"]}g
  Materials: {", ".join(product["materials"])}
  Activities: {", ".join(product["activity_tags"])}
  Key attributes: {attr_str}

Instructions:
- Write in British English
- Do not mention competitor brand names
- SHORT_DESCRIPTION: exactly one sentence, 15–25 words, key selling point
- LONG_DESCRIPTION: 3–5 sentences, 80–120 words, covering intended use, technical features, and materials

Respond with valid JSON only, no extra text:
{{"short_description": "...", "long_description": "..."}}"""


def _describe_one(client: Any, product: dict[str, Any], model_id: str) -> dict[str, Any]:
    """Generate descriptions for a single product. Thread-safe — returns the product dict."""
    prompt = _build_description_prompt(product)
    body = json.dumps({
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"max_new_tokens": 350, "temperature": 0.7},
    })
    for attempt in range(4):
        try:
            response = client.invoke_model(
                modelId=model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read())
            text = result["output"]["message"]["content"][0]["text"].strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            desc = json.loads(text)
            product["short_description"] = desc.get("short_description", "")
            product["long_description"] = desc.get("long_description", "")
            return product
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("ThrottlingException", "ServiceUnavailableException") and attempt < 3:
                time.sleep(2 ** attempt * 2)
                continue
            print(f"  ⚠ Bedrock error on '{product['name']}': {code}", file=sys.stderr)
            break
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            print(f"  ⚠ Parse error on '{product['name']}': {exc}", file=sys.stderr)
            break
    product["short_description"] = ""
    product["long_description"] = ""
    return product


def generate_descriptions_bedrock(
    client: Any,
    products: list[dict[str, Any]],
    model_id: str = BEDROCK_MODEL,
    workers: int = 10,
) -> list[dict[str, Any]]:
    """
    Generate descriptions concurrently using a thread pool.
    workers=10 is a safe default; raise to 20-30 if throughput allows.
    """
    results: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_describe_one, client, product, model_id): i
            for i, product in enumerate(products)
        }
        with tqdm(total=len(products), desc="Generating descriptions", unit="product") as bar:
            for future in as_completed(futures):
                idx = futures[future]
                results[idx] = future.result()
                bar.update(1)

    return [results[i] for i in range(len(products))]


# ---------------------------------------------------------------------------
# Product assembly
# ---------------------------------------------------------------------------


def _distribute_counts(total: int, taxonomy: list[dict[str, Any]]) -> list[int]:
    """
    Proportionally distribute `total` products across taxonomy entries.
    Larger, more popular categories get more products.
    Uses category-level weights to approximate Meridian's real SKU distribution.
    """
    # Relative weights per L1 category
    l1_weights = {
        "Clothing": 3.0,
        "Footwear": 1.2,
        "Rucksacks & Bags": 1.4,
        "Tents & Shelters": 0.8,
        "Sleeping": 1.0,
        "Navigation & Safety": 0.6,
        "Climbing & Scrambling": 0.7,
        "Ski & Snowsports": 0.8,
        "Camping & Cooking": 0.7,
        "Accessories": 0.8,
    }
    weights = [l1_weights.get(t["l1"], 1.0) for t in taxonomy]
    total_w = sum(weights)
    # Raw allocation
    raw = [total * w / total_w for w in weights]
    # Floor and distribute remainder
    counts = [max(1, int(r)) for r in raw]
    remainder = total - sum(counts)
    # Add remainder to categories with highest fractional part
    fracs = sorted(range(len(raw)), key=lambda i: raw[i] - int(raw[i]), reverse=True)
    for i in range(remainder):
        counts[fracs[i % len(fracs)]] += 1
    return counts


def build_products(count: int, seed: int = 42) -> list[dict[str, Any]]:
    """
    Build `count` product records. Anchored products are always included;
    remaining slots are filled proportionally across the taxonomy.
    """
    rng = random.Random(seed)
    products: list[dict[str, Any]] = []

    # Start with anchored products (always present)
    anchored_skus = set()
    for product in ANCHORED_PRODUCTS:
        p = dict(product)
        p["short_description"] = ""
        p["long_description"] = ""
        stock = _stock(rng, p["price_gbp"])
        p["stock_by_location"] = stock
        p["total_stock"] = sum(stock.values())
        p["is_active"] = True
        p["sale_price_gbp"] = None
        p["created_at"], p["updated_at"] = _timestamps(rng)
        products.append(p)
        anchored_skus.add(p["sku"])

    remaining = max(0, count - len(ANCHORED_PRODUCTS))
    if remaining == 0:
        return products[:count]

    counts = _distribute_counts(remaining, TAXONOMY)
    seq_counter: dict[str, int] = {}

    for cat_spec, n in zip(TAXONOMY, counts):
        for _ in range(n):
            brand = rng.choice(cat_spec["brands"])
            prefix = cat_spec["prefix"]
            seq_counter[prefix] = seq_counter.get(prefix, 0) + 1
            seq = seq_counter[prefix]

            sku = _sku(rng, prefix, brand, seq)
            name = _name_from_parts(rng, cat_spec, brand)
            markup = BRANDS[brand]["markup"]
            base_price = rng.uniform(cat_spec["pmin"], cat_spec["pmax"]) * markup
            price = _round_price(base_price)

            # ~20% of products are on sale
            if rng.random() < 0.20:
                sale_price = _round_price(price * rng.uniform(0.65, 0.85))
            else:
                sale_price = None

            weight_g = rng.randint(cat_spec["wmin"], cat_spec["wmax"])
            materials = _pick_materials(rng, cat_spec["l3"])
            attributes = _pick_attributes(rng, cat_spec["l3"])
            activities = rng.sample(
                cat_spec["activities"],
                k=min(rng.randint(1, 3), len(cat_spec["activities"])),
            )
            seasons = cat_spec["seasons"]
            stock = _stock(rng, price)
            created_at, updated_at = _timestamps(rng)

            p: dict[str, Any] = {
                "sku": sku,
                "name": name,
                "category_l1": cat_spec["l1"],
                "category_l2": cat_spec["l2"],
                "category_l3": cat_spec["l3"],
                "brand": brand,
                "price_gbp": price,
                "sale_price_gbp": sale_price,
                "weight_grams": weight_g,
                "materials": materials,
                "attributes": attributes,
                "activity_tags": activities,
                "season": seasons,
                "gender": attributes.pop("gender", "unisex") if "gender" in attributes else "unisex",
                "stock_by_location": stock,
                "total_stock": sum(stock.values()),
                "is_active": rng.random() > 0.05,  # 5% discontinued
                "short_description": "",
                "long_description": "",
                "created_at": created_at,
                "updated_at": updated_at,
            }
            products.append(p)

    return products[:count]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def write_outputs(products: list[dict[str, Any]], output_dir: Path, count: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    label = "sample" if count <= 500 else "full"
    stem = f"products_{label}_{count}"

    # JSON — human-readable for spot-checking
    json_path = output_dir / f"{stem}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, default=str, ensure_ascii=False)
    print(f"  Wrote {json_path} ({len(products)} products)")

    # Parquet — flatten nested structures for DataFrame
    flat: list[dict[str, Any]] = []
    for p in products:
        row = {k: v for k, v in p.items() if k not in ("attributes", "stock_by_location", "materials", "activity_tags", "season")}
        row["materials"] = json.dumps(p["materials"])
        row["activity_tags"] = json.dumps(p["activity_tags"])
        row["season"] = json.dumps(p["season"])
        row["attributes"] = json.dumps(p["attributes"])
        for store in STORES:
            row[f"stock_{store}"] = p["stock_by_location"].get(store, 0)
        flat.append(row)

    df = pd.DataFrame(flat)
    parquet_path = output_dir / f"{stem}.parquet"
    df.to_parquet(parquet_path, index=False)
    print(f"  Wrote {parquet_path} ({df.shape[0]} rows × {df.shape[1]} columns)")

    # Summary to stdout
    print(f"\nCategory distribution:")
    dist = df.groupby(["category_l1", "category_l3"]).size().reset_index(name="count")
    for _, row in dist.iterrows():
        print(f"  {row['category_l1']:<28} {row['category_l3']:<35} {row['count']:>3}")
    print(f"\nBrand distribution:")
    for brand, n in df["brand"].value_counts().items():
        print(f"  {brand:<22} {n:>3}")
    print(f"\nPrice range: £{df['price_gbp'].min():.2f} – £{df['price_gbp'].max():.2f}  "
          f"(median £{df['price_gbp'].median():.2f})")
    on_sale = df["sale_price_gbp"].notna().sum()
    print(f"Products on sale: {on_sale} ({100 * on_sale / len(df):.1f}%)")
    desc_ok = (df["short_description"] != "").sum()
    print(f"Descriptions generated: {desc_ok}/{len(df)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate synthetic Meridian Outdoor Co. product catalogue",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--count", type=int, default=50,
                   help="Number of products to generate (default: 50)")
    p.add_argument("--seed", type=int, default=42,
                   help="Random seed for structural field generation (default: 42)")
    p.add_argument("--output", type=str, default="../../data/",
                   help="Output directory (default: ../../data/)")
    p.add_argument("--no-bedrock", action="store_true",
                   help="Skip Bedrock description generation (output will have empty description fields)")
    p.add_argument("--workers", type=int, default=10,
                   help="Concurrent Bedrock threads (default: 10; raise to 20-30 for large runs)")
    p.add_argument("--profile", type=str, default=AWS_PROFILE,
                   help=f"AWS profile name (default: {AWS_PROFILE})")
    p.add_argument("--region", type=str, default=AWS_REGION,
                   help=f"AWS region (default: {AWS_REGION})")
    p.add_argument("--model", type=str, default=BEDROCK_MODEL,
                   help=f"Bedrock model ID (default: {BEDROCK_MODEL})")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    print(f"Meridian product generation — {args.count} products (seed={args.seed})")
    print(f"Output: {Path(args.output).resolve()}")
    if args.no_bedrock:
        print("Bedrock: SKIPPED (--no-bedrock)")
    else:
        print(f"Bedrock: {args.model} in {args.region} (profile: {args.profile})")
    print()

    # 1. Build structural fields
    print("Building product records...")
    products = build_products(count=args.count, seed=args.seed)
    print(f"  {len(products)} records built ({len(ANCHORED_PRODUCTS)} anchored + {len(products) - len(ANCHORED_PRODUCTS)} generated)")

    # 2. Descriptions via Bedrock
    if not args.no_bedrock:
        try:
            session = boto3.Session(profile_name=args.profile, region_name=args.region)
            bedrock = session.client("bedrock-runtime")
        except Exception as exc:
            print(f"⚠ Could not create Bedrock client: {exc}", file=sys.stderr)
            print("  Run with --no-bedrock to skip description generation.", file=sys.stderr)
            sys.exit(1)

        print(f"\nGenerating descriptions via Bedrock ({args.model}, {args.workers} workers)...")
        products = generate_descriptions_bedrock(bedrock, products, model_id=args.model, workers=args.workers)
    else:
        for p in products:
            p["short_description"] = ""
            p["long_description"] = ""

    # 3. Write outputs
    print(f"\nWriting outputs...")
    write_outputs(products, Path(args.output), args.count)
    print("\nDone.")


if __name__ == "__main__":
    main()
