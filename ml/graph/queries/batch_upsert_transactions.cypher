// batch_upsert_transactions.cypher — Bulk ingest a list of TransactionEvents.
// Used by the historical backfill loader (parallelized by account segment).
//
// Parameters:
//   $rows   list<map>   each map has keys matching upsert_transaction.cypher params:
//                       {transaction_id, sender_id, receiver_id, amount, currency,
//                        merchant_id, timestamp, channel, synthetic, origin, segment}

UNWIND $rows AS row
MERGE (sender:Account   {account_id: row.sender_id})
  ON CREATE SET sender.segment = row.segment, sender.created_at = timestamp()
MERGE (receiver:Account {account_id: row.receiver_id})
  ON CREATE SET receiver.segment = row.segment, receiver.created_at = timestamp()
MERGE (merchant:Merchant {merchant_id: row.merchant_id})
  ON CREATE SET merchant.created_at = timestamp()
CREATE (tx:Transaction {
  transaction_id: row.transaction_id,
  amount:         row.amount,
  currency:       row.currency,
  channel:        row.channel,
  timestamp:      row.timestamp,
  synthetic:      row.synthetic,
  origin:         row.origin
})
MERGE (sender)-[s:SENT_TO {transaction_id: row.transaction_id}]->(receiver)
  ON CREATE SET s.amount    = row.amount,
               s.timestamp  = row.timestamp,
               s.currency   = row.currency,
               s.synthetic  = row.synthetic
MERGE (sender)-[:TRANSACTED_AT]->(merchant)

RETURN count(*) AS rows_processed
