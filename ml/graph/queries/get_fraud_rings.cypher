// get_fraud_rings.cypher — Retrieve fraud rings above a risk score threshold.
//
// Parameters:
//   $min_risk_score   float   minimum risk_score to include (e.g. 0.70)
//   $limit            int     max rings to return
//   $since_ms         int     only rings detected after this epoch ms

MATCH (ring:FraudRing)
WHERE ring.risk_score >= $min_risk_score
  AND ring.detected_at >= $since_ms
OPTIONAL MATCH (ring)-[:INCLUDES]->(member:Account)
WITH ring, collect(member.account_id) AS member_ids
RETURN
  ring.ring_id       AS ring_id,
  ring.community_id  AS community_id,
  ring.risk_score    AS risk_score,
  ring.signals       AS signals,
  ring.total_flow    AS total_flow,
  ring.member_count  AS member_count,
  ring.synthetic     AS synthetic,
  ring.detected_at   AS detected_at,
  member_ids
ORDER BY ring.risk_score DESC
LIMIT $limit
