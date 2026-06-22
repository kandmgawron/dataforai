#!/usr/bin/env python3
"""
Meridian Outdoor Co. — Customer record generation script.

Generates 5,000 synthetic UK customer records with realistic segments,
purchase history, loyalty tiers, and preferences. Pure Python — no Bedrock.

Usage:
    python generate_customers.py --count 5000 --output ../../data/

Requirements:
    pip install pandas pyarrow
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

# ---------------------------------------------------------------------------
# Import STORES from generate_products.py (same directory)
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).parent))
from generate_products import STORES  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TODAY = date(2026, 5, 20)

FIRST_NAMES = [
    "James", "Oliver", "Harry", "Jack", "George", "Noah", "Charlie", "Jacob",
    "Alfie", "Freddie", "Oscar", "William", "Thomas", "Joshua", "Henry",
    "Ethan", "Daniel", "Samuel", "Archie", "Leo", "Muhammad", "Alexander",
    "Max", "Lucas", "Mason", "Amelia", "Olivia", "Isla", "Emily", "Ava",
    "Isabella", "Mia", "Poppy", "Ella", "Lily", "Sophie", "Grace", "Evie",
    "Freya", "Charlotte", "Jessica", "Hannah", "Chloe", "Lucy", "Millie",
    "Ellie", "Phoebe", "Daisy", "Alice", "Imogen", "Rosie", "Ruby",
    "Georgia", "Abigail", "Zoe", "Niamh", "Eva", "Lola", "Katie", "Molly",
]

LAST_NAMES = [
    "Smith", "Jones", "Williams", "Taylor", "Brown", "Davies", "Evans",
    "Wilson", "Thomas", "Roberts", "Johnson", "Walker", "Wright", "Robinson",
    "Thompson", "White", "Hughes", "Edwards", "Green", "Hall", "Lewis",
    "Harris", "Clarke", "Patel", "Jackson", "Wood", "Turner", "Martin",
    "Cooper", "Hill", "Ward", "Morris", "Moore", "Clark", "Lee", "King",
    "Baker", "Harrison", "Morgan", "Allen", "James", "Scott", "Phillips",
    "Watson", "Davis", "Parker", "Price", "Bennett", "Young", "Griffin",
]

EMAIL_DOMAINS = [
    "gmail.com",
    "outlook.com",
    "hotmail.co.uk",
    "yahoo.co.uk",
    "icloud.com",
    "btinternet.com",
]

FAVOURITE_CATEGORIES = [
    "Waterproof Jackets",
    "Fleece Jackets",
    "Base Layers",
    "Softshell Jackets",
    "Backpacks",
    "Sleeping Bags",
    "Tents",
    "Footwear",
    "Headwear",
    "Gloves & Mittens",
    "Trekking Poles",
    "Navigation",
    "Lighting",
]

# Segment config: (weight, ltv_range, order_range, loyalty_tier)
SEGMENT_CONFIG: dict[str, dict[str, Any]] = {
    "heavy_buyer":  {"weight": 0.15, "ltv": (500, 5000),  "orders": (20, 60),  "tier": "gold"},
    "regular":      {"weight": 0.30, "ltv": (150, 800),   "orders": (6, 20),   "tier": "silver"},
    "occasional":   {"weight": 0.25, "ltv": (50, 300),    "orders": (2, 6),    "tier": "bronze"},
    "one_time":     {"weight": 0.15, "ltv": (20, 150),    "orders": (1, 1),    "tier": "bronze"},
    "dormant":      {"weight": 0.15, "ltv": (30, 600),    "orders": (2, 15),   "tier": "bronze"},
}

# UK postcode area codes (first 1-2 letters)
POSTCODE_AREAS = [
    "AB", "AL", "B", "BA", "BB", "BD", "BH", "BL", "BN", "BR",
    "BS", "CA", "CB", "CF", "CH", "CM", "CO", "CR", "CT", "CV",
    "CW", "DA", "DD", "DE", "DG", "DH", "DL", "DN", "DT", "DY",
    "E", "EC", "EH", "EN", "EX", "FK", "FY", "G", "GL", "GU",
    "HA", "HD", "HG", "HP", "HR", "HS", "HU", "HX", "IG", "IP",
    "IV", "KA", "KT", "KW", "KY", "L", "LA", "LD", "LE", "LL",
    "LN", "LS", "LU", "M", "ME", "MK", "ML", "N", "NE", "NG",
    "NN", "NP", "NR", "NW", "OL", "OX", "PA", "PE", "PH", "PL",
    "PO", "PR", "RG", "RH", "RM", "S", "SA", "SE", "SG", "SK",
    "SL", "SM", "SN", "SO", "SP", "SR", "SS", "ST", "SW", "SY",
    "TA", "TD", "TF", "TN", "TQ", "TR", "TS", "TW", "UB", "W",
    "WA", "WC", "WD", "WF", "WN", "WR", "WS", "WV", "YO", "ZE",
]

POSTCODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _postcode(rng: random.Random) -> str:
    """Generate a realistic UK postcode, e.g. EH1 2AB or G42 9XZ."""
    area = rng.choice(POSTCODE_AREAS)
    district = rng.randint(1, 99)
    inward_digit = rng.randint(0, 9)
    inward_letters = rng.choice(POSTCODE_LETTERS) + rng.choice(POSTCODE_LETTERS)
    return f"{area}{district} {inward_digit}{inward_letters}"


def _phone(rng: random.Random) -> str:
    """Generate a UK mobile number in the format 07700 123456."""
    prefix = rng.choice(["07700", "07711", "07722", "07733", "07800", "07900", "07500", "07600"])
    number = rng.randint(100000, 999999)
    return f"{prefix} {number}"


def _reg_date(rng: random.Random) -> date:
    """Random registration date between 2018-01-01 and 2025-12-31."""
    start = date(2018, 1, 1)
    end = date(2025, 12, 31)
    delta = (end - start).days
    return start + timedelta(days=rng.randint(0, delta))


def _last_purchase_date(rng: random.Random, segment: str, reg_date: date) -> date:
    """
    Generate last_purchase_date based on segment rules:
    - dormant: 12–36 months ago
    - one_time: 1–60 days after reg_date
    - others: 1–90 days ago
    Never before reg_date, never after TODAY.
    """
    if segment == "dormant":
        days_ago = rng.randint(365, 1095)
        candidate = TODAY - timedelta(days=days_ago)
    elif segment == "one_time":
        days_after_reg = rng.randint(1, 60)
        candidate = reg_date + timedelta(days=days_after_reg)
    else:
        days_ago = rng.randint(1, 90)
        candidate = TODAY - timedelta(days=days_ago)

    # Clamp: must be on or after reg_date, on or before TODAY
    if candidate < reg_date:
        candidate = reg_date
    if candidate > TODAY:
        candidate = TODAY
    return candidate


def _email(rng: random.Random, first: str, last: str, existing: set[str]) -> str:
    """Generate a unique email address."""
    domain = rng.choice(EMAIL_DOMAINS)
    base = f"{first.lower()}.{last.lower()}"
    # Strip non-ascii just in case
    base = "".join(c for c in base if c.isalpha() or c == ".")
    addr = f"{base}@{domain}"
    if addr in existing:
        suffix = rng.randint(1, 9999)
        addr = f"{base}{suffix}@{domain}"
    existing.add(addr)
    return addr


def _pick_segment(rng: random.Random) -> str:
    """Pick a segment weighted by the defined proportions."""
    r = rng.random()
    cumulative = 0.0
    for seg, cfg in SEGMENT_CONFIG.items():
        cumulative += cfg["weight"]
        if r < cumulative:
            return seg
    return "dormant"


# ---------------------------------------------------------------------------
# Customer assembly
# ---------------------------------------------------------------------------


def build_customers(count: int = 5000, seed: int = 42) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    customers: list[dict[str, Any]] = []
    used_emails: set[str] = set()

    for i in range(1, count + 1):
        customer_id = f"CUST-{i:05d}"
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        email = _email(rng, first, last, used_emails)
        phone = _phone(rng)
        postcode = _postcode(rng)
        country = "GB"
        reg_date = _reg_date(rng)
        segment = _pick_segment(rng)
        cfg = SEGMENT_CONFIG[segment]

        loyalty_tier = cfg["tier"]
        ltv_min, ltv_max = cfg["ltv"]
        ord_min, ord_max = cfg["orders"]

        lifetime_value = round(rng.uniform(ltv_min, ltv_max), 2)

        if segment == "one_time":
            order_count = 1
        else:
            order_count = rng.randint(ord_min, ord_max)

        avg_order_value = round(lifetime_value / order_count, 2)
        last_purchase = _last_purchase_date(rng, segment, reg_date)
        days_since = (TODAY - last_purchase).days

        # 1–3 favourite categories
        n_cats = rng.randint(1, 3)
        favourite_categories = rng.sample(FAVOURITE_CATEGORIES, k=n_cats)

        # 60% chance of a preferred store
        preferred_store = rng.choice(STORES) if rng.random() < 0.60 else None

        marketing_opt_in = rng.random() < 0.65

        customers.append({
            "customer_id": customer_id,
            "first_name": first,
            "last_name": last,
            "email": email,
            "phone": phone,
            "postcode": postcode,
            "country": country,
            "registration_date": reg_date.isoformat(),
            "segment": segment,
            "loyalty_tier": loyalty_tier,
            "lifetime_value_gbp": lifetime_value,
            "order_count": order_count,
            "avg_order_value_gbp": avg_order_value,
            "last_purchase_date": last_purchase.isoformat(),
            "days_since_purchase": days_since,
            "favourite_categories": favourite_categories,
            "preferred_store": preferred_store,
            "marketing_opt_in": marketing_opt_in,
        })

    return customers


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def write_outputs(customers: list[dict[str, Any]], output_dir: Path, count: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"customers_{count}"

    # JSON
    json_path = output_dir / f"{stem}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(customers, f, indent=2, default=str, ensure_ascii=False)
    print(f"  Wrote {json_path} ({len(customers)} customers)")

    # Parquet — flatten list fields
    flat: list[dict[str, Any]] = []
    for c in customers:
        row = {k: v for k, v in c.items() if k != "favourite_categories"}
        row["favourite_categories"] = json.dumps(c["favourite_categories"])
        flat.append(row)

    df = pd.DataFrame(flat)
    parquet_path = output_dir / f"{stem}.parquet"
    df.to_parquet(parquet_path, index=False)
    print(f"  Wrote {parquet_path} ({df.shape[0]} rows x {df.shape[1]} columns)")

    # Segment summary
    print(f"\nSegment summary:")
    print(f"  {'Segment':<16} {'Count':>6}  {'Share':>6}  {'Avg LTV':>10}  {'Avg Orders':>11}  {'Tier'}")
    print(f"  {'-'*16} {'-'*6}  {'-'*6}  {'-'*10}  {'-'*11}  {'-'*10}")
    for seg in SEGMENT_CONFIG:
        seg_df = df[df["segment"] == seg]
        n = len(seg_df)
        share = 100 * n / len(df)
        avg_ltv = seg_df["lifetime_value_gbp"].mean()
        avg_orders = seg_df["order_count"].mean()
        tier = SEGMENT_CONFIG[seg]["tier"]
        print(f"  {seg:<16} {n:>6}  {share:>5.1f}%  £{avg_ltv:>9.2f}  {avg_orders:>10.1f}x  {tier}")

    print(f"\nMarketing opt-in: {df['marketing_opt_in'].sum()} / {len(df)} "
          f"({100 * df['marketing_opt_in'].mean():.1f}%)")
    print(f"With preferred store: {df['preferred_store'].notna().sum()} / {len(df)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate synthetic Meridian Outdoor Co. customer records",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--count", type=int, default=5000,
                   help="Number of customers to generate (default: 5000)")
    p.add_argument("--seed", type=int, default=42,
                   help="Random seed (default: 42)")
    p.add_argument("--output", type=str, default="../../data/",
                   help="Output directory (default: ../../data/)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    print(f"Meridian customer generation — {args.count} customers (seed={args.seed})")
    print(f"Output: {Path(args.output).resolve()}")
    print(f"Reference date (today): {TODAY.isoformat()}")
    print()

    print("Building customer records...")
    customers = build_customers(count=args.count, seed=args.seed)
    print(f"  {len(customers)} records built")

    print("\nWriting outputs...")
    write_outputs(customers, Path(args.output), args.count)
    print("\nDone.")


if __name__ == "__main__":
    main()
