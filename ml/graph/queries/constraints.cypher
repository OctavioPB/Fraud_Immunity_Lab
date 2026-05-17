// constraints.cypher — Schema constraints and indexes
// Run once on database init (idempotent via IF NOT EXISTS).
// CLAUDE.md: Node labels PascalCase, relationship types SCREAMING_SNAKE_CASE.

CREATE CONSTRAINT account_id_unique IF NOT EXISTS
FOR (a:Account) REQUIRE a.account_id IS UNIQUE;

CREATE CONSTRAINT transaction_id_unique IF NOT EXISTS
FOR (t:Transaction) REQUIRE t.transaction_id IS UNIQUE;

CREATE CONSTRAINT device_id_unique IF NOT EXISTS
FOR (d:Device) REQUIRE d.device_id IS UNIQUE;

CREATE CONSTRAINT merchant_id_unique IF NOT EXISTS
FOR (m:Merchant) REQUIRE m.merchant_id IS UNIQUE;

CREATE CONSTRAINT ip_address_unique IF NOT EXISTS
FOR (ip:IPAddress) REQUIRE ip.address IS UNIQUE;

CREATE CONSTRAINT fraud_ring_id_unique IF NOT EXISTS
FOR (fr:FraudRing) REQUIRE fr.ring_id IS UNIQUE;

// Indexes for lookup-heavy query paths
CREATE INDEX account_segment_idx IF NOT EXISTS
FOR (a:Account) ON (a.segment);

CREATE INDEX transaction_timestamp_idx IF NOT EXISTS
FOR (t:Transaction) ON (t.timestamp);

CREATE INDEX transaction_synthetic_idx IF NOT EXISTS
FOR (t:Transaction) ON (t.synthetic);

CREATE INDEX fraud_ring_risk_score_idx IF NOT EXISTS
FOR (fr:FraudRing) ON (fr.risk_score);
