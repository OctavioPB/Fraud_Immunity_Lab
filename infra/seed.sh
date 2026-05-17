#!/usr/bin/env bash
# ============================================================
# Seed script — run once after `make up` to initialize:
#   1. Kafka topics
#   2. Neo4j constraints + indexes
#   3. Pinecone indexes (if API key is set)
# ============================================================
set -euo pipefail

# Install minimal dependencies
pip install --quiet confluent-kafka neo4j requests

echo "==> [1/3] Creating Kafka topics..."

TOPICS=(
  "transactions"
  "logins"
  "devices"
  "detection_results"
  "alerts"
  "synthetic_audit"
)

for topic in "${TOPICS[@]}"; do
  python3 - <<PYEOF
from confluent_kafka.admin import AdminClient, NewTopic

client = AdminClient({"bootstrap.servers": "${KAFKA_BOOTSTRAP_SERVERS}"})
topic = NewTopic("${topic}", num_partitions=3, replication_factor=1)
futures = client.create_topics([topic])
for t, f in futures.items():
    try:
        f.result()
        print(f"  ✓ Created topic: {t}")
    except Exception as e:
        if "TOPIC_ALREADY_EXISTS" in str(e):
            print(f"  ~ Topic already exists: {t}")
        else:
            raise
PYEOF
done

echo ""
echo "==> [2/3] Creating Neo4j constraints and indexes..."

python3 - <<PYEOF
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    "${NEO4J_URI}",
    auth=("${NEO4J_USERNAME}", "${NEO4J_PASSWORD}"),
)

constraints = [
    ("Account", "account_id", "UNIQUE"),
    ("Transaction", "transaction_id", "UNIQUE"),
    ("Device", "device_id", "UNIQUE"),
    ("Merchant", "merchant_id", "UNIQUE"),
    ("IPAddress", "address", "UNIQUE"),
    ("FraudRing", "ring_id", "UNIQUE"),
]

with driver.session() as session:
    for label, prop, kind in constraints:
        try:
            cypher = (
                f"CREATE CONSTRAINT {label.lower()}_{prop}_unique "
                f"IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
            )
            session.run(cypher)
            print(f"  ✓ Constraint: {label}.{prop} UNIQUE")
        except Exception as e:
            print(f"  ~ {label}.{prop}: {e}")

    # Indexes for common query patterns
    indexes = [
        ("Account", "tenant_id"),
        ("Transaction", "timestamp"),
        ("Transaction", "synthetic"),
        ("Account", "label"),
    ]
    for label, prop in indexes:
        try:
            cypher = (
                f"CREATE INDEX {label.lower()}_{prop}_idx "
                f"IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"
            )
            session.run(cypher)
            print(f"  ✓ Index: {label}.{prop}")
        except Exception as e:
            print(f"  ~ {label}.{prop} index: {e}")

driver.close()
PYEOF

echo ""
echo "==> [3/3] Pinecone index check..."

if [ -z "${PINECONE_API_KEY:-}" ]; then
  echo "  ~ PINECONE_API_KEY not set — skipping Pinecone seed (OK for local dev)"
else
  python3 - <<PYEOF
import requests, os

api_key = os.environ["PINECONE_API_KEY"]
env = os.environ.get("PINECONE_ENVIRONMENT", "us-east-1")
headers = {"Api-Key": api_key, "Content-Type": "application/json"}

indexes = [
    {"name": "clean-profiles", "dimension": 3072, "metric": "cosine"},
    {"name": "suspicious-profiles", "dimension": 3072, "metric": "cosine"},
]

for idx in indexes:
    resp = requests.post(
        "https://api.pinecone.io/indexes",
        headers=headers,
        json={"name": idx["name"], "dimension": idx["dimension"],
              "metric": idx["metric"],
              "spec": {"serverless": {"cloud": "aws", "region": env}}},
    )
    if resp.status_code in (200, 201):
        print(f"  ✓ Created Pinecone index: {idx['name']}")
    elif resp.status_code == 409:
        print(f"  ~ Pinecone index already exists: {idx['name']}")
    else:
        print(f"  ! Pinecone error ({resp.status_code}): {resp.text}")
PYEOF
fi

echo ""
echo "==> Seed complete. Stack is ready."
