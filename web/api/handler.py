"""
Meridian Outdoor Co. — API Lambda handler.

Single function with path-based routing via API Gateway.
Uses RDS Data API (Aurora PostgreSQL), OpenSearch (keyword search),
DynamoDB, and S3.

Search architecture:
- Product BROWSING/SEARCH goes through OpenSearch (BM25 keyword search)
- Product DETAIL goes through Aurora (source of truth)
- This intentionally creates drift: products may exist in one but not the other.
  Zero-ETL integration resolves this in a later module.
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
SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "meridian-sessions-dev")
OPENSEARCH_ENDPOINT = os.environ.get("OPENSEARCH_ENDPOINT", "")
OPENSEARCH_INDEX = os.environ.get("OPENSEARCH_INDEX", "products")
AWS_REGION = os.environ.get("AWS_REGION", "eu-west-1")

rds = boto3.client("rds-data")
dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")
session = boto3.Session()


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

    # --- Chat routes ---
    if path == "/chat/start" and method == "POST":
        return chat_start(body)
    if path == "/chat/message" and method == "POST":
        return chat_message(body)
    if path == "/chat" and method == "GET":
        return chat_list()
    if re.match(r"^/chat/[\w\-]+$", path) and method == "GET":
        session_id = path.split("/")[-1]
        return chat_get(session_id)

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

    # Use OpenSearch for browsing/search if configured
    if OPENSEARCH_ENDPOINT:
        return get_products_opensearch(search, category, colour, price_min, price_max, gender, limit, offset)

    # Fallback: Aurora SQL (used before OpenSearch is seeded)
    return get_products_aurora(search, category, colour, price_min, price_max, gender, limit, offset)


def get_products_opensearch(search, category, colour, price_min, price_max, gender, limit, offset):
    """Search products via OpenSearch BM25 keyword search."""
    must = []
    filter_clauses = []

    if search:
        must.append({"multi_match": {
            "query": search,
            "fields": ["name^3", "brand^2", "short_description", "long_description"],
            "type": "best_fields"
        }})
    else:
        must.append({"match_all": {}})

    if category:
        filter_clauses.append({"term": {"l1": category}})
    if colour:
        # ponytail: exact match on colour keyword — intentionally brittle
        filter_clauses.append({"term": {"colours": colour}})
    if price_min:
        filter_clauses.append({"range": {"price_gbp": {"gte": float(price_min)}}})
    if price_max:
        filter_clauses.append({"range": {"price_gbp": {"lte": float(price_max)}}})
    if gender:
        filter_clauses.append({"term": {"gender": gender.lower()}})

    query = {"bool": {"must": must}}
    if filter_clauses:
        query["bool"]["filter"] = filter_clauses

    body = {
        "query": query,
        "size": limit,
        "from": offset,
        "_source": ["sku", "name", "brand", "l1", "price_gbp", "short_description", "stock_total", "in_stock"],
    }

    try:
        result = opensearch_request("POST", f"/{OPENSEARCH_INDEX}/_search", body)
        hits = result.get("hits", {}).get("hits", [])
        products = [h["_source"] for h in hits]
        return response(200, products)
    except Exception as e:
        import traceback
        print(f"OpenSearch error: {e}")
        print(f"Query body: {json.dumps(body)}")
        print(traceback.format_exc())
        # Fallback to Aurora on OpenSearch error
        return get_products_aurora(search, category, colour, price_min, price_max, gender, limit, offset)


def get_products_aurora(search, category, colour, price_min, price_max, gender, limit, offset):
    """Fallback: search products via Aurora SQL LIKE."""
    sql = "SELECT sku, name, brand, l1, price_gbp, short_description, stock_total FROM products WHERE in_stock = true"
    params = []

    if search:
        sql += " AND (name ILIKE :search OR brand ILIKE :search OR short_description ILIKE :search)"
        params.append({"name": "search", "value": {"stringValue": f"%{search}%"}})
    if category:
        sql += " AND l1 = :category"
        params.append({"name": "category", "value": {"stringValue": category}})
    if colour:
        sql += " AND attributes->'colours' @> :colour::jsonb"
        params.append({"name": "colour", "value": {"stringValue": json.dumps([colour])}})
    if price_min:
        sql += " AND price_gbp >= :price_min"
        params.append({"name": "price_min", "value": {"doubleValue": float(price_min)}})
    if price_max:
        sql += " AND price_gbp <= :price_max"
        params.append({"name": "price_max", "value": {"doubleValue": float(price_max)}})
    if gender:
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
    """List recent conversations awaiting response (submitted via chat widget)."""
    try:
        table = dynamodb.Table(CONVERSATIONS_TABLE)
        # Chat submissions use customer_id=ANONYMOUS; query directly
        resp = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("customer_id").eq("ANONYMOUS"),
            ScanIndexForward=False,
            Limit=50,
        )
        items = resp.get("Items", [])
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


# --- Chat ---

def chat_start(body):
    """Create a new live chat session."""
    try:
        data = json.loads(body) if isinstance(body, str) else (body or {})
    except (json.JSONDecodeError, TypeError):
        return response(400, {"error": "Invalid JSON body"})

    email = data.get("email", "").strip()
    if not email:
        return response(400, {"error": "email is required"})

    session_id = f"CHAT-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc).isoformat()

    item = {
        "session_id": session_id,
        "email": email,
        "status": "active",
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }

    try:
        table = dynamodb.Table(SESSIONS_TABLE)
        table.put_item(Item=item)
        return response(201, {"session_id": session_id})
    except Exception as e:
        return response(500, {"error": str(e)})


def chat_message(body):
    """Append a message to an existing chat session."""
    try:
        data = json.loads(body) if isinstance(body, str) else (body or {})
    except (json.JSONDecodeError, TypeError):
        return response(400, {"error": "Invalid JSON body"})

    session_id = data.get("session_id", "").strip()
    message = data.get("message", "").strip()
    role = data.get("role", "").strip()

    if not session_id or not message or role not in ("customer", "staff"):
        return response(400, {"error": "session_id, message, and role (customer|staff) are required"})

    now = datetime.now(timezone.utc).isoformat()
    msg_obj = {"role": role, "text": message, "ts": now}

    try:
        table = dynamodb.Table(SESSIONS_TABLE)
        table.update_item(
            Key={"session_id": session_id},
            UpdateExpression="SET messages = list_append(messages, :msg), updated_at = :now",
            ExpressionAttributeValues={":msg": [msg_obj], ":now": now},
        )
        return response(200, {"status": "ok"})
    except Exception as e:
        return response(500, {"error": str(e)})


def chat_get(session_id):
    """Return full chat session with all messages."""
    try:
        table = dynamodb.Table(SESSIONS_TABLE)
        resp = table.get_item(Key={"session_id": session_id})
        item = resp.get("Item")
        if not item:
            return response(404, {"error": "Session not found"})
        return response(200, item)
    except Exception as e:
        return response(500, {"error": str(e)})


def chat_list():
    """List all active chat sessions."""
    try:
        table = dynamodb.Table(SESSIONS_TABLE)
        # ponytail: full scan is fine — table only holds live chat sessions
        resp = table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr("status").eq("active")
        )
        items = resp.get("Items", [])
        # Return summary: email, last message preview, created_at
        result = []
        for item in items:
            msgs = item.get("messages", [])
            last_msg = msgs[-1]["text"][:80] if msgs else ""
            result.append({
                "session_id": item["session_id"],
                "email": item.get("email", ""),
                "last_message": last_msg,
                "created_at": item.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
            })
        result.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return response(200, result)
    except Exception as e:
        return response(500, {"error": str(e)})


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


# --- OpenSearch Serverless helper ---

def opensearch_request(method, path, body=None):
    """Make a signed request to OpenSearch Serverless (AOSS)."""
    import hashlib
    import urllib.request as urllib_request
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    url = f"{OPENSEARCH_ENDPOINT}{path}"
    data = json.dumps(body).encode() if body else b""

    # AOSS requires x-amz-content-sha256 header
    content_hash = hashlib.sha256(data).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "x-amz-content-sha256": content_hash,
    }

    fresh_session = boto3.Session()
    credentials = fresh_session.get_credentials().get_frozen_credentials()

    request = AWSRequest(method=method, url=url, data=data, headers=headers)
    SigV4Auth(credentials, "aoss", AWS_REGION).add_auth(request)

    req = urllib_request.Request(
        url=request.url,
        data=data,
        headers=dict(request.headers),
        method=method,
    )
    with urllib_request.urlopen(req) as resp:
        return json.loads(resp.read())
