# Format

Schemas `axion-attestation/1` and `axion-attestation/2` for a call's records, and `axion-attestation-source/1` for a message's. How the bytes are hashed, what is public while a call is open, and how to check each anchor are in [spec.md](spec.md).

## Ids

A trade is `AXN-YYYY-MM-DD-NNNNN`: the UTC day the analyst posted the opening message, and one global running number over every trade Core has recorded, padded to at least five digits, never reused, never changed. Its records are numbered from 1: `AXN-2026-08-20-00345/2`. Every trade gets a number, including ones that never appear in a public list, so a number without a listing means the trade exists but is not shown, not that it is missing.

A message is `AXM-YYYY-MM-DD-NNNNN`: the UTC day it was posted, read off its own Discord snowflake, and one global running number over every message Core has anchored. Every message in a tracked channel is numbered whether or not a call came out of it, and its records are numbered from 1 as well: record 1 is the message as Core first read it, and a revision Core sees later is record 2 rather than a rewrite of record 1.

## Records

One record per canonical event of the trade (corrections included), one `result` when the official portfolio finalises it, one `withdrawal` when a trade is a re-post of an earlier one. Kinds: `opening`, `plan`, `restatement`, `entry_added`, `entry_filled`, `entry_missed`, `entry_cancelled`, `average_entry`, `stop_move`, `stop_deferred`, `targets_set`, `target_added`, `target_reached`, `size_increased`, `partial`, `close`, `stopped`, `cancel`, `leverage`, `retraction`, `note`, `correction`, `result`, `withdrawal`.

Every key is always present; an absent value is `null`.

| key | meaning |
| --- | --- |
| `schema` | `axion-attestation/1`, or `axion-attestation/2` on a record built since Core v1.13.0, which is the same document with `source_record` added |
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
| `source_record` | on `axion-attestation/2`: `record_id` and `record_hash` of record 1 of the message this record was built from; null where that message was posted before message anchoring, and on `result` and `withdrawal`. The key is absent under `axion-attestation/1` |
| `previous_record_hash` | the hash of record `n - 1` of the same trade; null on record 1 |
| `salt` | 32 random bytes as 64 hex characters |

Nothing the analyst typed is in a record. Entry and target ids are kept only when they match `^[A-Za-z0-9 _.:/-]{1,80}$`, otherwise they are `entry-N` or `target-N`.

## Message records

Schema `axion-attestation-source/1`, a record about the message a call was posted in rather than about a trade, which is why it is a name of its own and not a version of the one above: `schema`, `record_id`, `message_ref`, `record_number`, `kind` (`source_message` for the revision Core read first, `source_revision` for a later one), `source`, `posted_at` (the message's own snowflake time), `observed_at`, `previous_record_hash` and `salt`. `source` carries `system`, `guild_id`, `channel_id`, `message_id`, `analyst_id`, `analyst`, `revision`, AxionSignal's `content_hash` of the message, the `hash_recipe` that hash was taken under, and one `attachments` entry per file with its `attachment_id`, `size` and `sha256`.

There is no trade, no instrument and no side, because at arrival nothing has read the message, and no filename, which is the analyst's own text. The hash recipe is in Core's attestation contract, sections 3.5 to 3.7.
