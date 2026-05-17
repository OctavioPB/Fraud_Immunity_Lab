// louvain_run.cypher — Execute Louvain community detection and stream results.
//
// Parameters:
//   $graph_name         string  name of the projected GDS graph
//   $max_iterations     int     max Louvain iterations (default 10)
//   $max_levels         int     max hierarchy levels (default 10)
//   $tolerance          float   convergence tolerance (default 0.0001)

CALL gds.louvain.stream(
  $graph_name,
  {
    maxIterations: $max_iterations,
    maxLevels:     $max_levels,
    tolerance:     $tolerance,
    includeIntermediateCommunities: false
  }
)
YIELD nodeId, communityId
WITH gds.util.asNode(nodeId) AS account, communityId
RETURN
  communityId                    AS community_id,
  collect(account.account_id)   AS member_account_ids,
  count(account)                 AS member_count
ORDER BY member_count DESC
