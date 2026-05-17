// upsert_fraud_ring.cypher — Persist a detected FraudRing node and link to members.
//
// Parameters:
//   $ring_id          string        UUID for this fraud ring
//   $community_id     int           Louvain community ID
//   $member_ids       list<string>  tokenized account_ids in the ring
//   $risk_score       float         composite risk score 0.0–1.0
//   $signals          list<string>  risk signals that fired (e.g. ["unidirectional_flow","shared_ip"])
//   $total_flow       float         total money flow within the ring
//   $synthetic        bool          true if members are from a red-team injection
//   $detected_at_ms   int           epoch ms when this ring was detected
//   $dag_run_id       string        Airflow DAG run ID for traceability

MERGE (ring:FraudRing {ring_id: $ring_id})
  ON CREATE SET
    ring.community_id  = $community_id,
    ring.risk_score    = $risk_score,
    ring.signals       = $signals,
    ring.total_flow    = $total_flow,
    ring.member_count  = size($member_ids),
    ring.synthetic     = $synthetic,
    ring.detected_at   = $detected_at_ms,
    ring.dag_run_id    = $dag_run_id
  ON MATCH SET
    ring.risk_score    = $risk_score,
    ring.signals       = $signals,
    ring.total_flow    = $total_flow,
    ring.member_count  = size($member_ids),
    ring.updated_at    = $detected_at_ms

WITH ring
UNWIND $member_ids AS member_id
  MATCH (a:Account {account_id: member_id})
  MERGE (ring)-[:INCLUDES]->(a)

RETURN ring.ring_id AS ring_id, ring.risk_score AS risk_score
