"""
Meridian Outdoor Co. — API Lambda handler.

Single function with path-based routing via API Gateway.
Uses RDS Data API (Aurora PostgreSQL), DynamoDB, and S3.
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone

import boto3

# --- Config ---
CLUSTER_ARN = os.environ.get("AURORA_CLUSTER_ARN", "")
SECRET_ARN = os.environ.get("AURORA_SECRET_ARN", "")
DATABASE = os.environ.get("DATABASE_NAME", "meridian")
CONVERSATIONS_TABLE = os.environ.get("CONVERSATIONS_TABLE", "meridian-conversations")
POLICIES_BUCKET = os.environ.get("POLICIES_BUCKET", "")

rds = boto3.client("rds-data")
dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")


def handler(event, context):
    """Lambda entry point. Routes by HTTP method + path."""
    method = event.get("httpMethod", "GET")
    path = event.get("path", "/")
    qs = event.get("queryStringParameters") or {}
    body = event.get("body")

    # Path routing
    if path == "/products" and method == "GET":
        return get_products(qs)
    if re.match(r"^/products/[\w\-]+$", path) and method == "GET":
        sku = path.split("/")[-1]
        return get_product(sku)
    if path == "/customers" and method == "GET":
        return get_customers(qs)
    if re.match(r"^/customers/[\w\-]+$", path) and method == "GET":
        customer_id = path.split("/")[-1]
        return get_customer(customer_id)
    if path == "/conversations" and method == "GET":
        return get_conversations(qs)
    if path == "/conversations" and method == "POST":
        return post_conversation(body)
    if path == "/policies" and method == "GET":
        return get_policies()
    if re.match(r"^/policies/[\w\-]+$", path) and method == "GET":
        doc_id = path.split("/")[-1]
        return get_policy(doc_id)
    if re.match(r"^/reviews/[\w\-]+$", path) and method == "GET":
        sku = path.split("/")[-1]
        return get_reviews(sku)

    return response(404, {"error": "Not found"})


# --- Products ---

def get_products(qs):
    search = qs.get("search", "")
    category = qs.get("l1", "")
    colour = qs.get("colour", "")
    price_min = qs.get("price_min", "")
    price_max = qs.get("price_max", "")
    gender = qs.get("gender", "")
    limit = min(int(qs.get("limit", "40")), 100)
    offset = int(qs.get("offset", "0"))

    sql = "SELECT sku, name, brand, l1, price_gbp, short_description, stock_total FROM products WHERE in_stock = true"
    params = []

    if search:
        sql += " AND (name ILIKE :search OR brand ILIKE :search OR short_description ILIKE :search)"
        params.append({"name": "search", "value": {"stringValue": f"%{search}%"}})
    if category:
        sql += " AND l1 = :category"
        params.append({"name": "category", "value": {"stringValue": category}})
    if colour:
        # ponytail: exact JSONB array contains — intentionally brittle.
        # "red" won't match "fiery_red" in the array. This is the teaching point:
        # traditional structured search fails when supplier data is inconsistent.
        sql += " AND attributes->'colours' @> :colour::jsonb"
        params.append({"name": "colour", "value": {"stringValue": json.dumps([colour])}})
    if price_min:
        sql += " AND price_gbp >= :price_min"
        params.append({"name": "price_min", "value": {"doubleValue": float(price_min)}})
    if price_max:
        sql += " AND price_gbp <= :price_max"
        params.append({"name": "price_max", "value": {"doubleValue": float(price_max)}})
    if gender:
        # ponytail: exact match on gender column — won't find "unisex" if stored as "Unisex"
        sql += " AND LOWER(gender) = :gender"
        params.append({"name": "gender", "value": {"stringValue": gender.lower()}})

    sql += " ORDER BY name LIMIT :lim OFFSET :off"
    params.append({"name": "lim", "value": {"longValue": limit}})
    params.append({"name": "off", "value": {"longValue": offset}})

    rows = execute_sql(sql, params)
    products = [row_to_dict(r, ["sku", "name", "brand", "l1", "price_gbp", "short_description", "stock_total"]) for r in rows]
    return response(200, products)


def get_product(sku):
    sql = "SELECT * FROM products WHERE sku = :sku"
    params = [{"name": "sku", "value": {"stringValue": sku}}]
    rows = execute_sql(sql, params)
    if not rows:
        return response(404, {"error": "Product not found"})
    # ponytail: full row as dict; column names come from columnMetadata
    product = full_row_to_dict(sql, params)
    return response(200, product)


# --- Customers ---

def get_customers(qs):
    search = qs.get("search", "")
    limit = min(int(qs.get("limit", "20")), 50)

    if not search:
        return response(400, {"error": "search parameter required"})

    sql = """SELECT customer_id, first_name, last_name, email, loyalty_tier, segment, lifetime_value_gbp
             FROM customers
             WHERE customer_id ILIKE :search
                OR first_name ILIKE :search
                OR last_name ILIKE :search
                OR email ILIKE :search
             LIMIT :lim"""
    params = [
        {"name": "search", "value": {"stringValue": f"%{search}%"}},
        {"name": "lim", "value": {"longValue": limit}},
    ]
    rows = execute_sql(sql, params)
    customers = [row_to_dict(r, ["customer_id", "first_name", "last_name", "email", "loyalty_tier", "segment", "lifetime_value_gbp"]) for r in rows]
    return response(200, customers)


def get_customer(customer_id):
    sql = """SELECT customer_id, first_name, last_name, email, phone, postcode, country,
                    registration_date, segment, loyalty_tier, lifetime_value_gbp,
                    order_count, avg_order_value_gbp, last_purchase_date,
                    favourite_categories, preferred_store, marketing_opt_in
             FROM customers WHERE customer_id = :id"""
    params = [{"name": "id", "value": {"stringValue": customer_id}}]
    rows = execute_sql(sql, params)
    if not rows:
        return response(404, {"error": "Customer not found"})

    customer = row_to_dict(rows[0], [
        "customer_id", "first_name", "last_name", "email", "phone", "postcode", "country",
        "registration_date", "segment", "loyalty_tier", "lifetime_value_gbp",
        "order_count", "avg_order_value_gbp", "last_purchase_date",
        "favourite_categories", "preferred_store", "marketing_opt_in"
    ])

    # Fetch recent conversations from DynamoDB
    try:
        table = dynamodb.Table(CONVERSATIONS_TABLE)
        conv_resp = table.query(
            IndexName="customer-index",
            KeyConditionExpression=boto3.dynamodb.conditions.Key("customer_id").eq(customer_id),
            ScanIndexForward=False,
            Limit=10,
        )
        customer["conversations"] = conv_resp.get("Items", [])
    except Exception:
        customer["conversations"] = []

    return response(200, customer)


# --- Conversations ---

def get_conversations(qs):
    """List recent conversations awaiting response."""
    try:
        table = dynamodb.Table(CONVERSATIONS_TABLE)
        # ponytail: scan with limit; upgrade path is GSI on status + created_at
        resp = table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr("status").eq("pending"),
            Limit=50,
        )
        items = resp.get("Items", [])
        # Sort by created_at descending
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return response(200, items)
    except Exception as e:
        return response(500, {"error": str(e)})


def post_conversation(body):
    """Submit a new chat question from Ridge Assist."""
    try:
        data = json.loads(body) if isinstance(body, str) else (body or {})
    except (json.JSONDecodeError, TypeError):
        return response(400, {"error": "Invalid JSON body"})

    message = data.get("message", "").strip()
    if not message:
        return response(400, {"error": "message is required"})

    item = {
        "conversation_id": f"CONV-{uuid.uuid4().hex[:8].upper()}",
        "customer_id": data.get("customer_id", "ANONYMOUS"),
        "channel": data.get("channel", "web_chat"),
        "message": message,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        table = dynamodb.Table(CONVERSATIONS_TABLE)
        table.put_item(Item=item)
        return response(201, {"conversation_id": item["conversation_id"]})
    except Exception as e:
        return response(500, {"error": str(e)})


# --- Policies ---

def get_policies():
    """List policy documents from Aurora metadata."""
    sql = "SELECT doc_id, title, doc_type, applies_to FROM policy_documents ORDER BY doc_id"
    rows = execute_sql(sql)
    docs = [row_to_dict(r, ["doc_id", "title", "doc_type", "applies_to"]) for r in rows]
    return response(200, docs)


def get_policy(doc_id):
    """Fetch a single policy document from S3."""
    key = f"documents/{doc_id}.txt"
    try:
        obj = s3.get_object(Bucket=POLICIES_BUCKET, Key=key)
        content = obj["Body"].read().decode("utf-8")
        return response(200, {"doc_id": doc_id, "title": doc_id, "content": content})
    except s3.exceptions.NoSuchKey:
        return response(404, {"error": "Policy not found"})
    except Exception as e:
        return response(500, {"error": str(e)})


# --- Reviews ---

def get_reviews(sku):
    sql = """SELECT review_id, customer_id, rating, title, body, created_at
             FROM reviews WHERE product_sku = :sku ORDER BY created_at DESC LIMIT 20"""
    params = [{"name": "sku", "value": {"stringValue": sku}}]
    rows = execute_sql(sql, params)
    reviews = [row_to_dict(r, ["review_id", "customer_id", "rating", "title", "body", "created_at"]) for r in rows]
    return response(200, reviews)


# --- Helpers ---

def execute_sql(sql, params=None):
    """Execute SQL via RDS Data API, return records. Retries on Aurora resume."""
    import time
    from botocore.exceptions import ClientError
    kwargs = {
        "resourceArn": CLUSTER_ARN,
        "secretArn": SECRET_ARN,
        "database": DATABASE,
        "sql": sql,
        "includeResultMetadata": True,
    }
    if params:
        kwargs["parameters"] = params
    for attempt in range(4):
        try:
            resp = rds.execute_statement(**kwargs)
            return resp.get("records", [])
        except ClientError as exc:
            if "DatabaseResumingException" in str(exc) and attempt < 3:
                time.sleep(3 * (attempt + 1))
                continue
            raise


def full_row_to_dict(sql, params):
    """Execute and return full row as dict using column metadata."""
    import time
    from botocore.exceptions import ClientError
    kwargs = {
        "resourceArn": CLUSTER_ARN,
        "secretArn": SECRET_ARN,
        "database": DATABASE,
        "sql": sql,
        "includeResultMetadata": True,
        "parameters": params,
    }
    for attempt in range(4):
        try:
            resp = rds.execute_statement(**kwargs)
            break
        except ClientError as exc:
            if "DatabaseResumingException" in str(exc) and attempt < 3:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    records = resp.get("records", [])
    if not records:
        return {}
    columns = [col["name"] for col in resp.get("columnMetadata", [])]
    row = records[0]
    return {columns[i]: extract_value(row[i]) for i in range(len(columns))}


def row_to_dict(row, columns):
    """Map a Data API row (list of field dicts) to a dict."""
    result = {}
    for i, col in enumerate(columns):
        if i < len(row):
            result[col] = extract_value(row[i])
        else:
            result[col] = None
    return result


def extract_value(field):
    """Extract the actual value from an RDS Data API field dict."""
    if "isNull" in field and field["isNull"]:
        return None
    if "stringValue" in field:
        return field["stringValue"]
    if "longValue" in field:
        return field["longValue"]
    if "doubleValue" in field:
        return field["doubleValue"]
    if "booleanValue" in field:
        return field["booleanValue"]
    if "arrayValue" in field:
        return field["arrayValue"]
    return None


def response(status_code, body):
    """Build API Gateway proxy response with CORS headers."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body, default=str),
    }
