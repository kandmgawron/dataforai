#!/usr/bin/env python3
"""
Meridian Outdoor Co. — Product review generation script.

Generates 200,000 synthetic customer reviews using template-based text.
No Bedrock required — runs in minutes. All structural fields and review
body text are deterministically seeded from a large template corpus.

Usage:
    python generate_reviews.py --count 200000 --output ../../data/
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Review text template corpus
# ---------------------------------------------------------------------------

TEMPLATES = {
    "very_positive": [
        "Absolutely love this {product}. It's been a game-changer on every trip I've taken since buying it.",
        "Best {product} I've ever owned. The quality is outstanding and it's held up brilliantly.",
        "Genuinely impressed with this {product}. Exceeded every expectation I had.",
        "This {product} is exceptional. Worth every penny and then some.",
        "Can't fault this {product} at all. It's become my go-to piece of kit.",
        "I've owned a lot of {category} gear over the years and this is by far the best.",
        "Superb quality and performance. This {product} has earned a permanent spot in my pack.",
        "Phenomenal bit of kit. The {product} performed flawlessly in some genuinely awful conditions.",
        "Bought this {product} after reading rave reviews and they were all spot on.",
        "Five stars isn't enough. This {product} is genuinely brilliant.",
        "Outstanding performance in all conditions. My {product} has never let me down.",
        "This is what quality outdoor gear looks like. The {product} is built to last.",
        "Blown away by how good this {product} is. Recommending it to everyone in my walking club.",
        "Meridian have really nailed it with this {product}. Exceptional piece of kit.",
        "Wore my {product} on a week-long trip and it performed perfectly every single day.",
        "The {product} is worth every penny. Craftsmanship is superb.",
        "I've been using this {product} for three months now and it still feels brand new.",
        "If you're on the fence about this {product}, don't be. Just buy it.",
        "The best {category} I've ever used, full stop. Incredible piece of gear.",
        "Rarely do products live up to the hype but this {product} absolutely does.",
    ],
    "positive": [
        "Really happy with this {product}. Does exactly what it says on the tin.",
        "Good quality {product} that's served me well so far. Would recommend.",
        "Solid {product}. A few minor niggles but nothing that affects performance.",
        "Very pleased with my purchase. The {product} has been reliable and well made.",
        "Good value for money. The {product} performs well and feels durable.",
        "Happy with this {product} overall. It's done everything I've needed it to.",
        "The {product} is well designed and comfortable. No complaints from me.",
        "Decent {product} for the price. Has held up well to regular use.",
        "Would buy again. The {product} is practical, well made, and good value.",
        "Pleasantly surprised by the quality. The {product} is better than I expected.",
        "The {product} does its job well. Comfortable and seems durable.",
        "Good solid {category} kit. Nothing flashy but reliable and well made.",
        "Four stars from me. The {product} is genuinely good, just a couple of small things could be better.",
        "Really useful bit of kit. My {product} has become a staple on all my outings.",
        "Solid purchase. The {product} is comfortable, functional, and well priced.",
        "Good quality {product} from Meridian. Fits well and performs as described.",
        "Happy customer here. The {product} has been excellent on my last few trips.",
        "Good {product} that works as advertised. Delivery was fast too.",
        "The {product} is well thought out and practical. Does the job nicely.",
        "Recommended. Good {category} gear at a fair price.",
    ],
    "neutral": [
        "The {product} is fine. Does what it's meant to, nothing more nothing less.",
        "Decent enough {product}. A few things I'd change but it does the job.",
        "Mixed feelings about this {product}. Some bits are great, others less so.",
        "It's OK. The {product} performs adequately but I've used better.",
        "Average {product} for the price. Not bad, not brilliant.",
        "The {product} is functional but nothing special. Gets the job done.",
        "Three stars feels right. The {product} is solid but has some limitations.",
        "Reasonable {product}. Would have liked better quality at this price point.",
        "Not bad but not great either. The {product} is middle of the road.",
        "The {product} does what it says but I expected more for the money.",
        "Functional {product} that works as described. Nothing to get excited about.",
        "It's a serviceable {product}. Does the job on shorter trips at least.",
        "Acceptable performance. The {product} isn't going to blow anyone away but it's fine.",
        "The {product} is adequate. I'd probably look at other options before buying again.",
        "Fair product for the price. The {product} has some good points and some weak ones.",
        "Can't complain too much. The {product} is decent for casual use.",
        "The {product} works but feels a bit plasticky for the price.",
        "Neither great nor terrible. The {product} sits firmly in the middle ground.",
        "Some things I like, some things I don't. The {product} is a mixed bag overall.",
        "It does the job. Not the best {category} gear out there but perfectly usable.",
    ],
    "negative": [
        "Disappointed with this {product}. Expected better quality at this price.",
        "Not impressed. The {product} hasn't lived up to the description at all.",
        "Had issues with my {product} fairly quickly. Expected better from Meridian.",
        "The {product} let me down on a recent trip. Not what I was hoping for.",
        "Poor quality for the money. My {product} shows wear after only a few uses.",
        "Would not recommend. The {product} isn't fit for purpose in my experience.",
        "Regret buying this {product}. Should have read the reviews more carefully.",
        "The {product} is below par. There are better options at this price point.",
        "Struggled with my {product} from early on. Quality control seems poor.",
        "Not great. The {product} failed to perform when I needed it most.",
        "Had to return my {product} due to a fault. Process was fine but frustrating.",
        "The {product} looks good but doesn't perform. Form over function.",
        "Wouldn't buy again. The {product} has been unreliable and disappointing.",
        "The {product} started falling apart after a few weeks of normal use.",
        "Poor design on this {product}. Clearly not tested in real conditions.",
        "Overpriced for what you get. The {product} is flimsy and poorly finished.",
        "The {product} doesn't live up to the marketing. Misleading description.",
        "Uncomfortable and poorly made. My {product} was a waste of money.",
        "Two stars because it arrived on time. The {product} itself is poor quality.",
        "The stitching on my {product} came apart within a month. Very disappointing.",
    ],
    "very_negative": [
        "Terrible {product}. Sending it back immediately.",
        "Worst {category} gear I've ever bought. Complete waste of money.",
        "Absolutely awful. My {product} fell apart within days of first use.",
        "Do not buy this {product}. It's dangerous in real outdoor conditions.",
        "One star. The {product} is cheap, poorly made, and nothing like the description.",
        "Disgusted with the quality. My {product} is going straight back.",
        "A disaster. The {product} failed completely on its first proper outing.",
        "Save your money and avoid this {product} at all costs.",
        "The {product} is genuinely dangerous. Quality control must be non-existent.",
        "Shocking quality. My {product} looked like a different product to what was advertised.",
        "Never again. The {product} is the worst piece of kit I've ever bought.",
        "Useless. My {product} was unusable from day one. Complete rubbish.",
        "Avoid this {product}. I'm warning other buyers — it is not fit for purpose.",
        "This {product} is a safety hazard. Returning it and reporting to the retailer.",
        "The lowest quality {category} product I've ever encountered. Embarrassing.",
    ],
    "contradictory": [
        "Love the design of this {product} but the quality is really disappointing for the price.",
        "Great idea, poor execution. The {product} looks brilliant but doesn't perform.",
        "The {product} is comfortable enough but the waterproofing gave up after one wet day.",
        "Stylish {product} that unfortunately lets you down when it actually rains.",
        "The fit on this {product} is perfect but the material feels much cheaper than expected.",
        "Looks great and the features are impressive, but my {product} started showing wear quickly.",
        "Good concept but the {product} has real durability issues. Shame.",
        "The {product} is exactly what I wanted aesthetically but the performance is lacking.",
        "Half the zips on my {product} are excellent, the other half feel like they'll fail soon.",
        "Lovely looking {product} but after two trips I'm having doubts about the longevity.",
        "The {product} works brilliantly in dry conditions but wet weather exposed its weaknesses.",
        "Impressive spec sheet on this {product} but the reality doesn't quite match.",
        "The {product} is comfortable and well designed but the seams worry me long term.",
        "Great value when it works. My {product} has been brilliant but had one odd failure.",
        "Mixed experience overall. The {product} has real strengths but real weaknesses too.",
    ],
}

# Additional sentence fragments to add variety
FOLLOW_UPS = {
    "very_positive": [
        "Highly recommend to anyone who takes their outdoor kit seriously.",
        "This is now my first recommendation to anyone asking about {category} gear.",
        "Meridian have really outdone themselves with this one.",
        "Will definitely be buying from Meridian again.",
        "Fast delivery and the product is even better in person.",
    ],
    "positive": [
        "Would recommend to friends looking for reliable {category} kit.",
        "Good experience with Meridian overall.",
        "Delivery was prompt and packaging was solid.",
        "Will buy from Meridian again.",
        "Happy with the overall experience.",
    ],
    "neutral": [
        "Wouldn't put me off buying from Meridian again though.",
        "Delivery was fine and the returns process looks straightforward.",
        "It's fine for casual use.",
        "Would consider other options before repurchasing.",
        "Might upgrade to something better eventually.",
    ],
    "negative": [
        "Customer service was helpful but couldn't fix the underlying quality issue.",
        "Won't be buying this particular product again.",
        "Return process was easy at least.",
        "Meridian should review the quality control on this line.",
        "Gutted because I really wanted to love this.",
    ],
    "very_negative": [
        "Shocking experience. Expected far better from a brand like Meridian.",
        "Will not be shopping here again.",
        "Refund process was the only positive thing about this purchase.",
        "Dangerous product that should be reviewed urgently.",
        "Leaving this review to warn other buyers.",
    ],
    "contradictory": [
        "On balance, probably not worth the price given the issues.",
        "Will see how it holds up long term before deciding whether to recommend.",
        "Hoping it was just a quality control issue with my unit.",
        "I'd buy it again on sale but not at full price.",
        "A revised version with better materials would be a five-star product.",
    ],
}

# ---------------------------------------------------------------------------
# Structural constants
# ---------------------------------------------------------------------------

RATING_WEIGHTS = [8, 12, 15, 30, 35]   # 1★ to 5★
RATING_TO_SENTIMENT = {5: "very_positive", 4: "positive", 3: "neutral", 2: "negative", 1: "very_negative"}
CONTRADICTORY_RATE = 0.08

POPULAR_L2 = {
    "Waterproof Jackets", "Softshell Jackets", "Fleece Jackets",
    "Backpacks", "Hiking Packs", "Backpacking Tents", "Trail Running Shoes",
    "Hiking Boots", "Waterproof Trousers",
}


def _build_review_body(rng: random.Random, product_name: str, l2: str, sentiment: str) -> str:
    category = l2.lower()
    product = product_name

    template = rng.choice(TEMPLATES[sentiment])
    body = template.format(product=product, category=category)

    # 60% chance to append a follow-up sentence
    if rng.random() < 0.6:
        follow_up = rng.choice(FOLLOW_UPS[sentiment])
        body = body + " " + follow_up.format(product=product, category=category)

    return body


def _random_datetime(rng: random.Random, days_back: int = 1095) -> str:
    """Random datetime within the last N days."""
    delta = timedelta(
        days=rng.randint(0, days_back),
        hours=rng.randint(0, 23),
        minutes=rng.randint(0, 59),
    )
    dt = datetime.now(timezone.utc) - delta
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_reviews(
    products: list[dict],
    count: int = 200_000,
    seed: int = 42,
) -> list[dict]:
    rng = random.Random(seed)

    # Weight products: popular l2 categories get 2.5x; ~60% of SKUs appear at all
    weights = []
    for p in products:
        l2 = p.get("l2", "")
        w = 2.5 if l2 in POPULAR_L2 else 1.0
        w *= 1.0 if rng.random() < 0.6 else 0.0
        weights.append(w)

    # Fallback: if too many zero weights, just use all
    if sum(weights) == 0:
        weights = [1.0] * len(products)

    ratings = [1, 2, 3, 4, 5]
    reviews = []

    for i in tqdm(range(1, count + 1), desc="Building reviews", unit="review"):
        product = rng.choices(products, weights=weights, k=1)[0]
        rating = rng.choices(ratings, weights=RATING_WEIGHTS, k=1)[0]

        sentiment = RATING_TO_SENTIMENT[rating]
        # Override some to contradictory
        if rng.random() < CONTRADICTORY_RATE:
            sentiment = "contradictory"
            rating = rng.choice([3, 4])

        body = _build_review_body(rng, product["name"], product.get("l2", "gear"), sentiment)
        title = body.split(".")[0][:60].strip()

        helpful = 0
        r = rng.random()
        if r < 0.70:
            helpful = 0
        elif r < 0.90:
            helpful = rng.randint(1, 5)
        else:
            helpful = rng.randint(6, 45)

        reviews.append({
            "review_id": f"REV-{i:07d}",
            "product_sku": product["sku"],
            "product_name": product["name"],
            "product_l2": product.get("l2", ""),
            "customer_id": f"CUST-{rng.randint(1, 5000):05d}",
            "rating": rating,
            "sentiment": sentiment,
            "title": title,
            "body": body,
            "verified_purchase": rng.random() < 0.75,
            "helpful_votes": helpful,
            "total_votes": helpful + rng.randint(0, 3),
            "created_at": _random_datetime(rng),
            "source": rng.choices(["website", "app"], weights=[70, 30], k=1)[0],
        })

    return reviews


def write_outputs(records: list[dict], output_dir: Path, label: str) -> None:
    df = pd.DataFrame(records)
    parquet_path = output_dir / f"{label}.parquet"
    json_path = output_dir / f"{label}.json"
    df.to_parquet(parquet_path, index=False)
    json_path.write_text(
        json.dumps(records, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    size_mb = parquet_path.stat().st_size / 1024 / 1024
    print(f"  Written: {parquet_path.name} ({size_mb:.1f} MB)")
    print(f"  Written: {json_path.name} ({json_path.stat().st_size / 1024 / 1024:.1f} MB)")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate Meridian product reviews (template-based)")
    p.add_argument("--count", type=int, default=200_000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output", type=str, default="../../data/")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    products_path = output_dir / "products_full_40000.json"
    if not products_path.exists():
        print(f"ERROR: {products_path} not found. Run generate_products.py first.", file=sys.stderr)
        sys.exit(1)

    print(f"Meridian review generation — {args.count:,} reviews (seed={args.seed}, template-based)")
    print(f"Loading products from {products_path.name} ...")
    with open(products_path) as f:
        all_products = json.load(f)
    product_lookup = [{"sku": p["sku"], "name": p["name"], "l2": p.get("l2", p.get("category_l2", ""))} for p in all_products]
    print(f"  {len(product_lookup):,} products loaded")

    reviews = build_reviews(product_lookup, count=args.count, seed=args.seed)

    print(f"\nWriting outputs ...")
    write_outputs(reviews, output_dir, f"reviews_{args.count}")

    # Summary
    from collections import Counter
    rating_dist = Counter(r["rating"] for r in reviews)
    sentiment_dist = Counter(r["sentiment"] for r in reviews)
    skus_covered = len(set(r["product_sku"] for r in reviews))

    print(f"\nRating distribution:")
    for star in [5, 4, 3, 2, 1]:
        n = rating_dist[star]
        print(f"  {star}★  {n:>7,}  ({n/args.count*100:.1f}%)")
    print(f"\nSentiment distribution:")
    for s, n in sentiment_dist.most_common():
        print(f"  {s:<16} {n:>7,}  ({n/args.count*100:.1f}%)")
    print(f"\nProducts covered: {skus_covered:,} / {len(product_lookup):,} ({skus_covered/len(product_lookup)*100:.0f}%)")
    print("\nDone.")


if __name__ == "__main__":
    main()
