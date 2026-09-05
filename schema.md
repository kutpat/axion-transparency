# Format

Schema `axion-attestation/1`.

## Ids

A trade is `AXN-YYYY-MM-DD-NNNNN`: the UTC day the analyst posted the opening message, and one global running number over every trade Core has recorded, padded to at least five digits, never reused, never changed. Its records are numbered from 1: `AXN-2026-08-20-00345/2`. Every trade gets a number, including ones that never appear in a public list, so a number without a listing means the trade exists but is not shown, not that it is missing.

## Records

One record per canonical event of the trade (corrections included), one `result` when the official portfolio finalises it, one `withdrawal` when a trade is a re-post of an earlier one. Kinds: `opening`, `plan`, `restatement`, `entry_added`, `entry_filled`, `entry_missed`, `entry_cancelled`, `average_entry`, `stop_move`, `stop_deferred`, `targets_set`, `target_added`, `target_reached`, `size_increased`, `partial`, `close`, `stopped`, `cancel`, `leverage`, `retraction`, `note`, `correction`, `result`, `withdrawal`.

Every key is always present; an absent value is `null`.

| key | meaning |
| --- | --- |
| `schema` | `axion-attestation/1` |
| `record_id`, `signal_id`, `record_number` | `<signal_id>/<n>`, the trade id, `n` as a string |
| `kind` | one of the kinds above |
| `trade` | `provider`, `analyst` (`discord-<user id>`), `instrument` (as posted), `side` (`LONG`, `SHORT`) |
| `posted_at` | the Discord message time; null on `result` and `withdrawal` |
| `source` | `system`, `guild_id`, `channel_id`, `message_id`, `event_key`, `revision`, `analyst_id`, `content_hash`; null on `result` and `withdrawal` |
| `event` | `type`, `id`, `semantic`, `origin`, `effective_at`, `observed_at`, `recorded_at`; null on `result` and `withdrawal` |
| `levels` | `semantic_kind`, `entries[]` (`entry_id`, `type`, `price`, `price_low`, `price_high`, `allocation_pct`, `match_current_position_quantity`, `trigger_price_type`), `announced_dca_slots`, `stop` (`price`, `at_break_even`, `trigger_price_type`, `trigger_mode`, `candle_interval_minutes`, `condition_operator`), `stop_deferral` (`candle_count`), `targets[]` (`target_id`, `price`, `close_pct`, `quantity_basis`, `is_runner`, `trigger_price_type`), `leverage`, `quantity_pct`, `quantity_basis`, `reference_price`, `label`, `auto_sl_be_override` |
| `supersedes`, `corrected_kind` | on a `correction`: the record it corrects and the kind that record would have had |
| `restates` | `signal_id`, `kind` (`DUPLICATE`, `RE_ENTRY`), `exclusion_reason`; on the first record of a re-post and on a `withdrawal` |
| `result` | `portfolio`, `policy_key`, `policy_version`, `policy_hash`, `projector_version`, `calculation_version`, `outcome_state`, `closed_at`, `exit_reason`, `classification`, `entry_price`, `exit_price`, `exit_at`, `r`, `move_pct`, `evidence_label`, `evidence_identity`, `evidence_kind`, `venue`, `venue_symbol`, `strict_result_hash`, `optimistic_result_hash`, `result_key` |
| `previous_record_hash` | the hash of record `n - 1` of the same trade; null on record 1 |
| `salt` | 32 random bytes as 64 hex characters |

Nothing the analyst typed is in a record. Entry and target ids are kept only when they match `^[A-Za-z0-9 _.:/-]{1,80}$`, otherwise they are `entry-N` or `target-N`.

## Canonical form and hash

The hashed bytes are JSON with keys sorted by code point, separators `,` and `:`, no whitespace, no trailing newline. Every string is printable ASCII. There are no JSON numbers: counts and ids are decimal strings, prices are shortest plain decimals (`116500`, `0.386`, `-1.5`, `0`). Timestamps are `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Booleans are `true` and `false`.

`record_hash` is SHA-256 of those bytes, lowercase hex. A file in `records/` is exactly those bytes:

    sha256sum records/AXN-2026-08-20-00345/1.json

## Envelope

One line per record in `log/<UTC day>.jsonl`, appended in the order Core built the records: `schema`, `record_id`, `signal_id`, `record_number`, `kind`, `instrument`, `side`, `analyst`, `posted_at`, `committed_at`, `record_hash`. The line is the canonical form of that object. `committed_at` is when Core built the record; the anchors bound that time, not `posted_at`.

## Reveal

A trade's records are published to `records/<signal_id>/<n>.json` when the official portfolio finalises it, when its ledger status is terminal, when it is a re-post of a revealed trade, or when its opening is more than 90 days old. Reveal is never undone. A record built after the reveal is published in full together with its log line.

## Anchors

GitHub: the log line's commit. Readable, but the owner of a repository can rewrite history, so it is the index, not the proof.

Rekor: `proofs/<signal_id>/<n>.rekor.json` names the entry. Fetch it from Rekor by `log_index`, decode `body` (a `hashedrekord`), check `spec.data.hash.value` equals the record hash and `spec.signature.publicKey.content` decodes to the key in `keys/`. `integratedTime` is the time Rekor accepted it. The signature is ECDSA P-256 over SHA-256 of the record bytes, DER encoded:

    curl -s "https://rekor.sigstore.dev/api/v1/log/entries?logIndex=<log_index>" > entry.json
    jq -r '.[].body' entry.json | base64 -d | jq -r '.spec.signature.content' | base64 -d > sig.der
    openssl dgst -sha256 -verify keys/axion-2026-09.pub.pem -signature sig.der records/<signal_id>/<n>.json

OpenTimestamps: `proofs/<signal_id>/<n>.ots` is a detached proof of the record hash. It appears once the calendars have committed it to a Bitcoin block.

    ots verify -d <record_hash> proofs/<signal_id>/<n>.ots
    ots verify -f records/<signal_id>/<n>.json proofs/<signal_id>/<n>.ots
    ots info proofs/<signal_id>/<n>.ots

## Versions

A change to any key or rule is a new schema string. Records, hashes, salts and anchors are never rewritten; a mistake is a new record. A new signing key is a new file in `keys/` and a new `key_id` in the Rekor references.
