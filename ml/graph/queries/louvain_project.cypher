// louvain_project.cypher — Project the SENT_TO subgraph into the GDS catalog.
//
// Creates a named in-memory graph projection for Louvain community detection.
// Must be dropped (louvain_drop.cypher) before re-running to avoid conflicts.
//
// Parameters:
//   $graph_name     string  name for the in-memory GDS graph (e.g. "fraud-ring-graph")
//   $since_ms       int     epoch ms — only include edges newer than this (rolling window)

CALL gds.graph.project(
  $graph_name,
  'Account',
  {
    SENT_TO: {
      properties: ['amount', 'timestamp'],
      orientation: 'NATURAL'
    }
  },
  {
    nodeProperties: ['account_id'],
    relationshipFilter: 'timestamp >= ' + toString($since_ms)
  }
)
YIELD graphName, nodeCount, relationshipCount, projectMillis
RETURN graphName, nodeCount, relationshipCount, projectMillis
