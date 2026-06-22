#!/usr/bin/env python3
"""
Meridian Outdoor Co. — Policy document generation script.

Generates 40 policy/guidance documents using Amazon Bedrock (Nova Lite).
Each document is written in UK English in a professional retail tone with
clear headings and bullet points.

Output:
    policies_40.parquet   — structured records
    policies_40.json      — human-readable JSON
    policies/POL-001.txt  — one plain-text file per document

Usage:
    python generate_policies.py --output ../../data/

Requirements:
    pip install boto3 pandas pyarrow
    AWS profile 'ridge-course-dev' with Bedrock access in eu-west-1
    Bedrock model enabled: eu.amazon.nova-2-lite-v1:0
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import boto3
import pandas as pd
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AWS_PROFILE = "ridge-course-dev"
AWS_REGION = "eu-west-1"
BEDROCK_MODEL = "eu.amazon.nova-2-lite-v1:0"

POLICIES: list[dict[str, Any]] = [
    {"doc_id": "POL-001", "title": "Standard Returns Policy", "doc_type": "returns", "tags": ["returns", "refund", "exchange"], "applies_to": "all_products"},
    {"doc_id": "POL-002", "title": "Online Order Returns", "doc_type": "returns", "tags": ["online", "returns", "postage"], "applies_to": "online_orders"},
    {"doc_id": "POL-003", "title": "In-Store Returns & Exchanges", "doc_type": "returns", "tags": ["in-store", "returns", "exchange"], "applies_to": "in_store"},
    {"doc_id": "POL-004", "title": "Product Warranty Terms", "doc_type": "warranty", "tags": ["warranty", "defects", "guarantee"], "applies_to": "all_products"},
    {"doc_id": "POL-005", "title": "Extended Warranty Programme", "doc_type": "warranty", "tags": ["warranty", "extended", "protection"], "applies_to": "selected_products"},
    {"doc_id": "POL-006", "title": "Footwear Sizing Guide", "doc_type": "sizing_guide", "tags": ["footwear", "sizing", "fit", "boots"], "applies_to": "footwear"},
    {"doc_id": "POL-007", "title": "Jacket & Outerwear Sizing Guide", "doc_type": "sizing_guide", "tags": ["jackets", "sizing", "fit", "outerwear"], "applies_to": "jackets"},
    {"doc_id": "POL-008", "title": "Backpack Sizing & Fit Guide", "doc_type": "sizing_guide", "tags": ["backpack", "sizing", "torso", "fit"], "applies_to": "backpacks"},
    {"doc_id": "POL-009", "title": "Sleeping Bag Temperature Ratings Explained", "doc_type": "sizing_guide", "tags": ["sleeping_bag", "temperature", "comfort", "EN13537"], "applies_to": "sleeping_bags"},
    {"doc_id": "POL-010", "title": "Tent Capacity & Sizing Guide", "doc_type": "sizing_guide", "tags": ["tent", "capacity", "footprint", "vestibule"], "applies_to": "tents"},
    {"doc_id": "POL-011", "title": "Down Product Care Instructions", "doc_type": "care_guide", "tags": ["down", "care", "washing", "storage"], "applies_to": "down_products"},
    {"doc_id": "POL-012", "title": "Waterproof Garment Care & Reproofing", "doc_type": "care_guide", "tags": ["waterproof", "care", "reproof", "DWR"], "applies_to": "waterproof_garments"},
    {"doc_id": "POL-013", "title": "Merino Wool Care Guide", "doc_type": "care_guide", "tags": ["merino", "wool", "care", "washing"], "applies_to": "merino_products"},
    {"doc_id": "POL-014", "title": "Footwear Care & Waterproofing", "doc_type": "care_guide", "tags": ["footwear", "care", "waterproofing", "cleaning"], "applies_to": "footwear"},
    {"doc_id": "POL-015", "title": "Sleeping Bag Care & Storage", "doc_type": "care_guide", "tags": ["sleeping_bag", "care", "storage", "compression"], "applies_to": "sleeping_bags"},
    {"doc_id": "POL-016", "title": "Tent Maintenance & Care", "doc_type": "care_guide", "tags": ["tent", "care", "seam_sealing", "poles"], "applies_to": "tents"},
    {"doc_id": "POL-017", "title": "Standard UK Delivery", "doc_type": "shipping", "tags": ["delivery", "shipping", "standard", "timescales"], "applies_to": "all_orders"},
    {"doc_id": "POL-018", "title": "Express & Next Day Delivery", "doc_type": "shipping", "tags": ["express", "next_day", "delivery", "cut_off"], "applies_to": "all_orders"},
    {"doc_id": "POL-019", "title": "Click & Collect", "doc_type": "shipping", "tags": ["click_collect", "in_store", "pickup", "collection"], "applies_to": "in_store"},
    {"doc_id": "POL-020", "title": "International Shipping", "doc_type": "shipping", "tags": ["international", "shipping", "EU", "overseas"], "applies_to": "international_orders"},
    {"doc_id": "POL-021", "title": "FAQs: Orders & Delivery", "doc_type": "faq", "tags": ["faq", "orders", "delivery", "tracking"], "applies_to": "all_orders"},
    {"doc_id": "POL-022", "title": "FAQs: Returns & Exchanges", "doc_type": "faq", "tags": ["faq", "returns", "exchanges", "refunds"], "applies_to": "all_products"},
    {"doc_id": "POL-023", "title": "FAQs: Product Care", "doc_type": "faq", "tags": ["faq", "care", "maintenance", "washing"], "applies_to": "all_products"},
    {"doc_id": "POL-024", "title": "FAQs: Loyalty Programme", "doc_type": "faq", "tags": ["faq", "loyalty", "points", "rewards"], "applies_to": "loyalty_members"},
    {"doc_id": "POL-025", "title": "FAQs: Sizing & Fit", "doc_type": "faq", "tags": ["faq", "sizing", "fit", "measurement"], "applies_to": "all_products"},
    {"doc_id": "POL-026", "title": "Meridian Loyalty Programme Terms", "doc_type": "loyalty", "tags": ["loyalty", "points", "tiers", "gold_silver_bronze"], "applies_to": "loyalty_members"},
    {"doc_id": "POL-027", "title": "Gift Cards Terms & Conditions", "doc_type": "terms", "tags": ["gift_card", "terms", "balance", "expiry"], "applies_to": "gift_cards"},
    {"doc_id": "POL-028", "title": "Corporate & Group Orders", "doc_type": "commercial", "tags": ["corporate", "bulk", "group", "trade_discount"], "applies_to": "corporate_customers"},
    {"doc_id": "POL-029", "title": "Ethical Sourcing & Supply Chain", "doc_type": "sustainability", "tags": ["ethical", "sourcing", "supply_chain", "fair_trade"], "applies_to": "company_wide"},
    {"doc_id": "POL-030", "title": "Environmental Commitment", "doc_type": "sustainability", "tags": ["environment", "sustainability", "carbon", "packaging"], "applies_to": "company_wide"},
    {"doc_id": "POL-031", "title": "Product Recall Procedure", "doc_type": "safety", "tags": ["recall", "safety", "defect", "procedure"], "applies_to": "all_products"},
    {"doc_id": "POL-032", "title": "Helmets & Safety Equipment Policy", "doc_type": "safety", "tags": ["helmets", "safety", "EN_standards", "certification"], "applies_to": "safety_equipment"},
    {"doc_id": "POL-033", "title": "Price Match Guarantee", "doc_type": "commercial", "tags": ["price_match", "guarantee", "competitor", "best_price"], "applies_to": "all_products"},
    {"doc_id": "POL-034", "title": "Sale & Clearance Terms", "doc_type": "commercial", "tags": ["sale", "clearance", "discount", "final_sale"], "applies_to": "sale_items"},
    {"doc_id": "POL-035", "title": "Accessibility Statement", "doc_type": "legal", "tags": ["accessibility", "WCAG", "inclusive_design"], "applies_to": "website"},
    {"doc_id": "POL-036", "title": "Privacy Policy Summary", "doc_type": "legal", "tags": ["privacy", "GDPR", "personal_data", "rights"], "applies_to": "all_customers"},
    {"doc_id": "POL-037", "title": "Cookie Policy", "doc_type": "legal", "tags": ["cookies", "tracking", "consent", "analytics"], "applies_to": "website"},
    {"doc_id": "POL-038", "title": "Complaints Procedure", "doc_type": "customer_service", "tags": ["complaints", "escalation", "resolution", "ombudsman"], "applies_to": "all_customers"},
    {"doc_id": "POL-039", "title": "Highland & Island Delivery Surcharges", "doc_type": "shipping", "tags": ["highland", "island", "surcharge", "remote_areas"], "applies_to": "remote_deliveries"},
    {"doc_id": "POL-040", "title": "Expedition & Specialist Equipment Advice", "doc_type": "advice", "tags": ["expedition", "specialist", "consultation", "technical_advice"], "applies_to": "specialist_customers"},
]

# ---------------------------------------------------------------------------
# Bedrock generation
# ---------------------------------------------------------------------------


def _build_prompt(title: str) -> str:
    return (
        f'Write the "{title}" document for Meridian Outdoor Co., a UK outdoor equipment '
        f"and clothing retailer with 12 stores across Scotland and Northern England. "
        f"UK English. Professional retail tone. 300-500 words. Use clear headings and "
        f"bullet points where appropriate. Start directly with content, no preamble."
    )


def _generate_one(
    bedrock_runtime: Any,
    policy: dict[str, Any],
    model_id: str,
    index: int,
    total: int,
) -> dict[str, Any]:
    """Generate content for a single policy document. Returns the completed record."""
    title = policy["title"]
    print(f"[{index}/{total}] Generating: {title} ...", flush=True)

    prompt = _build_prompt(title)
    body = json.dumps({
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"max_new_tokens": 700, "temperature": 0.7},
    })

    text = ""
    for attempt in range(4):
        try:
            resp = bedrock_runtime.invoke_model(
                modelId=model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(resp["body"].read())
            text = result["output"]["message"]["content"][0]["text"].strip()
            break
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "ThrottlingException" and attempt < 3:
                wait = 2 ** attempt * 2
                print(f"  ThrottlingException — retrying in {wait}s (attempt {attempt + 1}/4)...",
                      file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  Bedrock error on '{title}': {code}", file=sys.stderr)
            break

    return {
        "doc_id": policy["doc_id"],
        "title": policy["title"],
        "doc_type": policy["doc_type"],
        "tags": policy["tags"],
        "applies_to": policy["applies_to"],
        "content": text,
        "word_count": len(text.split()),
        "version": "1.0",
        "last_updated": "2026-01-15",
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def write_outputs(documents: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    count = len(documents)
    stem = f"policies_{count}"

    # Individual .txt files
    txt_dir = output_dir / "policies"
    txt_dir.mkdir(parents=True, exist_ok=True)
    for doc in documents:
        txt_path = txt_dir / f"{doc['doc_id']}.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(doc["content"])

    # JSON
    json_path = output_dir / f"{stem}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(documents, f, indent=2, default=str, ensure_ascii=False)
    print(f"  Wrote {json_path} ({count} documents)")

    # Parquet — flatten list fields
    flat: list[dict[str, Any]] = []
    for doc in documents:
        row = {k: v for k, v in doc.items() if k != "tags"}
        row["tags"] = json.dumps(doc["tags"])
        flat.append(row)

    df = pd.DataFrame(flat)
    parquet_path = output_dir / f"{stem}.parquet"
    df.to_parquet(parquet_path, index=False)
    print(f"  Wrote {parquet_path} ({df.shape[0]} rows x {df.shape[1]} columns)")
    print(f"  Wrote {count} .txt files to {txt_dir}/")

    # Summary
    print(f"\nDocument type breakdown:")
    for doc_type, grp in df.groupby("doc_type"):
        avg_words = grp["word_count"].mean()
        print(f"  {doc_type:<20} {len(grp):>3} docs   avg {avg_words:.0f} words")

    total_words = df["word_count"].sum()
    avg_words_all = df["word_count"].mean()
    empty = (df["word_count"] == 0).sum()
    print(f"\nTotal words: {total_words:,}   Average: {avg_words_all:.0f}   Empty: {empty}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate Meridian Outdoor Co. policy documents via Amazon Bedrock",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--output", type=str, default="../../data/",
                   help="Output directory (default: ../../data/)")
    p.add_argument("--profile", type=str, default=AWS_PROFILE,
                   help=f"AWS profile name (default: {AWS_PROFILE})")
    p.add_argument("--region", type=str, default=AWS_REGION,
                   help=f"AWS region (default: {AWS_REGION})")
    p.add_argument("--model", type=str, default=BEDROCK_MODEL,
                   help=f"Bedrock model ID (default: {BEDROCK_MODEL})")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    print(f"Meridian policy generation — {len(POLICIES)} documents")
    print(f"Output: {Path(args.output).resolve()}")
    print(f"Bedrock: {args.model} in {args.region} (profile: {args.profile})")
    print()

    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        bedrock_runtime = session.client("bedrock-runtime")
    except Exception as exc:
        print(f"Could not create Bedrock client: {exc}", file=sys.stderr)
        sys.exit(1)

    total = len(POLICIES)
    documents: list[dict[str, Any]] = []
    for i, policy in enumerate(POLICIES, start=1):
        doc = _generate_one(bedrock_runtime, policy, args.model, i, total)
        documents.append(doc)

    print(f"\nWriting outputs...")
    write_outputs(documents, Path(args.output))
    print("\nDone.")


if __name__ == "__main__":
    main()
