# Checking a record

Everything Axion publishes about a call can be checked without asking Axion. This page says how. The field by field format is in [schema.md](schema.md), and `python verify.py <signal id>` runs every check below for one call. `python verify.py <message id>` does the same for one analyst message.

## What is published

Every call has a permanent id, `AXN-YYYY-MM-DD-NNNNN`, and a chain of numbered records: the opening, each later change, the result. Each record is a small JSON document hashed with SHA-256, and the hash is anchored three times.

| Anchor | Where | What it shows |
| --- | --- | --- |
| GitHub | a line in `log/<day>.jsonl`, in a commit | the hash was in the repository when the commit was made. Readable, but the owner of a repository can rewrite history, so this is the index, not the proof |
| Sigstore Rekor | `proofs/<id>/<n>.rekor.json` names the entry | the hash, signed with the key in `keys/`, was accepted into a public append-only log at `integratedTime` |
| OpenTimestamps | `proofs/<id>/<n>.ots` | the hash was committed into a Bitcoin block at a given height |

An anchor dates the record, not the analyst's message. `committed_at` in the envelope is when Core built the record and `posted_at` inside the record is the Discord message time; both are published, so the gap can be read. For the history backfilled on 2026-09-05 the gap is weeks or months.

Every message in a tracked source channel has an id of its own, `AXM-YYYY-MM-DD-NNNNN`, and a chain of its own, hashed and anchored the same way within seconds of the message arriving, and the ones already stored when the chain started are part of that same backfill. A trade record built since Core v1.13.0 is schema `axion-attestation/2`, the same document with one key more, `source_record`, which names the message record the trade came from, so the chain runs from the raw message through to the close.

## Envelope now, record at close

While a call is open only the envelope is public: one line in `log/<UTC day of committed_at>.jsonl` carrying `schema`, `record_id`, `signal_id`, `record_number`, `kind`, `instrument`, `side`, `analyst`, `posted_at`, `committed_at` and `record_hash`. Lines are appended and never edited. The record carries a random 32-byte salt, so the levels cannot be guessed back from the hash.

A call is revealed when the official portfolio finalises it, when its status is terminal, when it is a re-post of a revealed call, or when its opening is more than 90 days old. The reveal publishes `records/<id>/<n>.json` for every record: the exact bytes that were hashed, salt included. A reveal is never undone, and a record built afterwards is published in full together with its log line.

A message record has no reveal condition. It holds no levels and no text, so it lands in `records/<message id>/<n>.json` in the same commit as its log line, salt included, and a member who can see the message can check it while the call is still open. Its line is a different shape, carrying `message_ref`, `channel_id` and `message_id` where a call's carries `signal_id`, `instrument` and `side`, and `schema` is what tells the two apart.

`source.content_hash` in a message record is AxionSignal's hash of the message itself, taken on arrival, and `source.hash_recipe` names the rule it was taken under, `axionsignal-msg/1` or `axionsignal-msg/2`, a null meaning the first. Recomputing it over a message you can see is what ties a record to that message; the recipe is in Core's attestation contract, sections 3.5 to 3.7, and AxionSignal's `docs/message-hash-recipe.md` is its authority.

## The bytes that are hashed

A record file is JSON in one fixed form:

1. keys sorted by code point, separators `,` and `:`, no whitespace, no trailing newline;
2. every string printable ASCII, so the only escapes that can occur are `\"` and `\`;
3. no JSON numbers: counts and ids are decimal strings, prices are shortest plain decimals (`116500`, `0.386`, `-1.5`, `0`);
4. timestamps `YYYY-MM-DDTHH:MM:SS.ffffffZ`;
5. booleans `true` and `false`, absent values `null`, every key of the schema present.

`record_hash` is the SHA-256 of those bytes as lowercase hex, and the file is those bytes, so

    sha256sum records/AXN-2026-09-01-00344/2.json

must print the `record_hash` in the log line and in the Rekor entry. Record `n` carries `previous_record_hash`, the hash of record `n - 1` of the same call, null on record 1. Checking a chain means checking every hash and every link. In Python, `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)` gives the same bytes back; `python verify.py --self-test` does that for the worked example in Core's contract, whose hash is `5a5387f6af5285a887e093b36cb6f4c9670d5d10c85ae16375c8377161b2640c`.

## GitHub

    grep -rn '"record_id":"AXN-2026-09-01-00344/2"' log/

The permalink form is `https://github.com/kutpat/axion-transparency/blob/<commit>/log/<day>.jsonl#L<line>`, and `git log --follow log/<day>.jsonl` shows the file was only ever appended to. The commit date is GitHub's record of when the line arrived. Commits are made by Trading Core's publisher.

## Rekor

`proofs/<id>/<n>.rekor.json` holds `log_index`, `entry_uuid`, `integrated_time`, `body` and Rekor's inclusion proof. Do not take the file's word for it; fetch the entry from Rekor by its index (or by `entry_uuid` at `log/entries/<uuid>`):

    curl -s "https://rekor.sigstore.dev/api/v1/log/entries?logIndex=<log_index>" > entry.json

`body` is a base64 `hashedrekord`. Decode it and check that `spec.data.hash.value` is the record hash and that `spec.signature.publicKey.content`, base64 decoded, is `keys/axion-2026-09.pub.pem`. `integratedTime` is the Unix time Rekor accepted the entry, and Rekor signs it. With `rekor-cli`:

    rekor-cli get --log-index <log_index> --format json
    rekor-cli verify --artifact records/<id>/<n>.json --signature sig.der --public-key keys/axion-2026-09.pub.pem

The signature is ECDSA P-256 over the SHA-256 of the record bytes, DER encoded. Once the call is revealed, OpenSSL alone checks it:

    jq -r '.[].body' entry.json | base64 -d | jq -r '.spec.signature.content' | base64 -d > sig.der
    openssl dgst -sha256 -verify keys/axion-2026-09.pub.pem -signature sig.der records/<id>/<n>.json

Before the reveal the bytes are not public, so the check stops at: the entry exists at that index, its hash is the envelope's `record_hash`, the key is Axion's, and `integratedTime` is the time bound. `verify.py` also recomputes the inclusion proof up to the checkpoint and checks Rekor's own signatures with the key Rekor publishes.

## OpenTimestamps

`proofs/<id>/<n>.ots` is a detached proof whose digest is the record hash. It is published only once the calendars have written it into Bitcoin, so the file always ends in a Bitcoin attestation; until then the trade page reports the proof as pending.

    pip install opentimestamps-client
    ots verify -d <record_hash> proofs/<id>/<n>.ots
    ots verify -f records/<id>/<n>.json proofs/<id>/<n>.ots
    ots info proofs/<id>/<n>.ots

The first form works while the call is open, the second after the reveal. `ots verify` needs a Bitcoin node and prints the block time, which is the time bound this anchor gives. Without a node, `ots info` prints the block height and the 32-byte merkle root the block header must carry; a block explorer shows it, byte reversed. `verify.py` makes that comparison against a public explorer.

## Versions

`schema` names the format. Any change to a key or a rule is a new string, and a verifier refuses one it does not know. There are three: `axion-attestation/1` and `axion-attestation/2` for a call's records, differing only by `source_record`, and `axion-attestation-source/1` for a message record. A chain can hold more than one of them, and every chain that predates message anchoring does. Records, hashes, salts and anchors are never rewritten; a mistake is a new record. A new signing key is a new file in `keys/` and a new `key_id` in the Rekor references.
