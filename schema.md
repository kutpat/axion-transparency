# Format

Schema `axion-attestation/1`. How the bytes are hashed, what is public while a call is open, and how to check each anchor are in [spec.md](spec.md).

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
