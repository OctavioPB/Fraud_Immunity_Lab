// louvain_drop.cypher — Drop the GDS in-memory graph projection.
// Call before re-projecting to avoid "already exists" errors.
//
// Parameters:
//   $graph_name   string  name of the projected GDS graph to drop

CALL gds.graph.drop($graph_name, false)
YIELD graphName
RETURN graphName
