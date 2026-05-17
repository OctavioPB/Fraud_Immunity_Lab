// cluster_signals.cypher — Compute risk signals for a candidate fraud ring cluster.
//
// Given a list of account_ids in the same Louvain community, returns:
//   - total_flow: sum of SENT_TO amounts within the cluster
//   - unidirectional_ratio: fraction of edges that flow only one way (laundering signal)
//   - shared_ip_count: distinct IPs shared by >= 2 accounts (collusion signal)
//   - shared_device_count: distinct devices shared by >= 2 accounts (collusion signal)
//   - synthetic_edge_count: number of SENT_TO edges tagged synthetic=true
//
// Parameters:
//   $account_ids    list<string>  tokenized account_ids in the candidate cluster
//   $since_ms       int           epoch ms — only edges newer than this

MATCH (a:Account)-[s:SENT_TO]->(b:Account)
WHERE a.account_id IN $account_ids
  AND b.account_id IN $account_ids
  AND s.timestamp >= $since_ms
WITH
  sum(s.amount) AS total_flow,
  count(s) AS edge_count,
  sum(CASE WHEN s.synthetic = true THEN 1 ELSE 0 END) AS synthetic_edge_count

// Unidirectional ratio: count pairs where A→B exists but B→A does not
MATCH (a2:Account)-[fwd:SENT_TO]->(b2:Account)
WHERE a2.account_id IN $account_ids
  AND b2.account_id IN $account_ids
  AND fwd.timestamp >= $since_ms
WITH total_flow, edge_count, synthetic_edge_count,
     a2, b2, fwd,
     EXISTS {
       MATCH (b2)-[:SENT_TO]->(a2)
     } AS has_reverse

WITH total_flow, edge_count, synthetic_edge_count,
     count(CASE WHEN NOT has_reverse THEN 1 END) AS one_way_edges,
     count(fwd) AS total_directed_edges

WITH total_flow, edge_count, synthetic_edge_count,
     CASE WHEN total_directed_edges > 0
          THEN toFloat(one_way_edges) / total_directed_edges
          ELSE 0.0
     END AS unidirectional_ratio

// Shared IPs
MATCH (ip:IPAddress)<-[:LOGGED_IN_FROM]-(acc:Account)
WHERE acc.account_id IN $account_ids
WITH total_flow, edge_count, synthetic_edge_count, unidirectional_ratio, ip,
     count(acc) AS accounts_per_ip

WITH total_flow, edge_count, synthetic_edge_count, unidirectional_ratio,
     count(CASE WHEN accounts_per_ip >= 2 THEN 1 END) AS shared_ip_count

// Shared devices
MATCH (d:Device)<-[:USED_DEVICE]-(acc2:Account)
WHERE acc2.account_id IN $account_ids
WITH total_flow, edge_count, synthetic_edge_count, unidirectional_ratio,
     shared_ip_count, d,
     count(acc2) AS accounts_per_device

WITH total_flow, edge_count, synthetic_edge_count, unidirectional_ratio,
     shared_ip_count,
     count(CASE WHEN accounts_per_device >= 2 THEN 1 END) AS shared_device_count

RETURN
  total_flow,
  edge_count,
  unidirectional_ratio,
  shared_ip_count,
  shared_device_count,
  synthetic_edge_count
