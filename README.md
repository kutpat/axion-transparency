# Axion transparency log

Every call an Axion analyst posts gets a permanent id, like `AXN-2026-08-20-00345`, and a record for the opening and for each later change: a stop move, a partial, a target reached, the close, the result. Each record is hashed, and the hash is published here the minute Core has it.

While a call is open only the hash and a short envelope are public. The record carries a random salt, so the hash cannot be guessed back into the levels. When the call closes the full record is published in `records/`, and anyone can recompute every hash and the chain from one record to the next.

Each hash is also written to the Sigstore Rekor log and committed to a Bitcoin block through OpenTimestamps. The proofs are in `proofs/`. The key that signs the Rekor entries is in `keys/`. The format and how to check each anchor are in `schema.md`.

Commits here are made by Core's publisher. A commit named after a record carries that record; `reveal AXN-...` publishes a closed call; one word means a batch.
