#!/usr/bin/env python3
"""Check one Axion call against the transparency log and its anchors.

    python verify.py AXN-2026-09-01-00344
    python verify.py AXN-2026-09-01-00344 --offline
    python verify.py --self-test

Run inside a clone it reads the files on disk, anywhere else it fetches them
from GitHub. The hashes and the chain need nothing but the files. Rekor and a
Bitcoin block explorer are asked over HTTPS unless --offline is given.
Standard library only. spec.md says what each check means.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO = "kutpat/axion-transparency"
RAW = "https://raw.githubusercontent.com/" + REPO + "/main/"
API = "https://api.github.com/repos/" + REPO + "/contents/"
REKOR = "https://rekor.sigstore.dev/api/v1/"
EXPLORERS = ("https://blockstream.info/api/", "https://mempool.space/api/")
SCHEMA = "axion-attestation/1"
SIGNAL_ID = re.compile(r"^AXN-\d{4}-\d{2}-\d{2}-\d{5,}$")


# --- files -------------------------------------------------------------------


def fetch(url):
    """GET a URL. None on 404, so a missing file reads like a missing file."""
    request = Request(url, headers={"User-Agent": "axion-transparency-verify"})
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


class Files:
    """The repository's files, from a clone on disk or straight from GitHub."""

    def __init__(self, root):
        self.root = root

    def read(self, path):
        if self.root is None:
            return fetch(RAW + path)
        full = os.path.join(self.root, *path.split("/"))
        if not os.path.isfile(full):
            return None
        with open(full, "rb") as handle:
            return handle.read()

    def log_days(self):
        if self.root is None:
            listing = fetch(API + "log") or b"[]"
            names = [entry["name"] for entry in json.loads(listing)]
        else:
            folder = os.path.join(self.root, "log")
            names = os.listdir(folder) if os.path.isdir(folder) else []
        return sorted((name for name in names if name.endswith(".jsonl")), reverse=True)


def canonical(document):
    """The bytes that are hashed: sorted keys, no whitespace, ASCII only."""
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def when(unix_time):
    return datetime.fromtimestamp(unix_time, timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


# --- ECDSA P-256, just enough to check a signature ---------------------------

P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
G = (
    0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
    0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5,
)
# SubjectPublicKeyInfo header of an uncompressed P-256 point, as OpenSSL writes it.
P256_HEADER = bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d030107034200")


def _add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0]:
        if (p[1] + q[1]) % P == 0:
            return None
        slope = (3 * p[0] * p[0] - 3) * pow(2 * p[1], P - 2, P)
    else:
        slope = (q[1] - p[1]) * pow(q[0] - p[0], P - 2, P)
    x = (slope * slope - p[0] - q[0]) % P
    return (x, (slope * (p[0] - x) - p[1]) % P)


def _multiply(k, point):
    result = None
    while k:
        if k & 1:
            result = _add(result, point)
        point = _add(point, point)
        k >>= 1
    return result


def key_der(pem):
    return base64.b64decode("".join(line for line in pem.decode().splitlines() if "-----" not in line))


def public_key(pem):
    der = key_der(pem)
    if len(der) != 91 or not der.startswith(P256_HEADER) or der[26] != 4:
        raise ValueError("not an uncompressed P-256 public key")
    x = int.from_bytes(der[27:59], "big")
    y = int.from_bytes(der[59:91], "big")
    if (y * y - x * x * x + 3 * x - B) % P:
        raise ValueError("point is not on P-256")
    return (x, y)


def der_signature(der):
    """SEQUENCE { INTEGER r, INTEGER s }."""
    if der[0] != 0x30:
        raise ValueError("not a DER signature")
    at = 2 + (der[1] - 0x80 if der[1] & 0x80 else 0)
    numbers = []
    for _ in range(2):
        if der[at] != 0x02:
            raise ValueError("not a DER signature")
        length = der[at + 1]
        numbers.append(int.from_bytes(der[at + 2 : at + 2 + length], "big"))
        at += 2 + length
    return numbers[0], numbers[1]


def verify_ecdsa(key, message, der):
    r, s = der_signature(der)
    if not (0 < r < N and 0 < s < N):
        return False
    e = int.from_bytes(hashlib.sha256(message).digest(), "big")
    w = pow(s, N - 2, N)
    point = _add(_multiply(e * w % N, G), _multiply(r * w % N, key))
    return point is not None and point[0] % N == r


# --- Rekor -------------------------------------------------------------------


def merkle_root(leaf, index, size, hashes):
    """Walk an RFC 6962 inclusion proof the way Rekor's tree hashes it."""
    inner = (index ^ (size - 1)).bit_length()
    node = leaf
    for level, sibling in enumerate(hashes[:inner]):
        if (index >> level) & 1:
            node = hashlib.sha256(b"\x01" + sibling + node).digest()
        else:
            node = hashlib.sha256(b"\x01" + node + sibling).digest()
    for sibling in hashes[inner:]:
        node = hashlib.sha256(b"\x01" + sibling + node).digest()
    return node


def parse_checkpoint(text):
    """A signed note: origin, tree size, root hash, a blank line, signatures."""
    note, _, signatures = text.partition("\n\n")
    lines = note.split("\n")
    size = int(lines[1])
    root = base64.b64decode(lines[2]).hex()
    signed = []
    for line in signatures.splitlines():
        if line.strip():
            blob = base64.b64decode(line.split(" ")[-1])
            signed.append(((note + "\n").encode(), blob[4:]))  # four bytes of key hint first
    return size, root, signed


def entry_timestamp_message(entry):
    """What Rekor signs as the entry timestamp: four fields, canonical JSON."""
    fields = {key: entry[key] for key in ("body", "integratedTime", "logID", "logIndex")}
    return json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()


_rekor_key = {}


def rekor_key():
    if "pem" not in _rekor_key:
        _rekor_key["pem"] = fetch(REKOR + "log/publicKey")
    return _rekor_key["pem"]


def check_rekor(files, signal_id, number, raw, digest, online, report):
    reference = files.read("proofs/%s/%d.rekor.json" % (signal_id, number))
    if reference is None:
        report.line("rekor", "pending", "no entry reference published yet")
        return
    ref = json.loads(reference)
    key_pem = files.read("keys/%s.pub.pem" % ref["key_id"])
    if key_pem is None:
        report.line("rekor", "FAIL", "key %s is not in keys/" % ref["key_id"])
        return
    problems = []
    if online:
        answer = fetch(REKOR + "log/entries?logIndex=%d" % ref["log_index"])
        if answer is None:
            report.line("rekor", "FAIL", "Rekor has no entry at index %d" % ref["log_index"])
            return
        uuid, entry = next(iter(json.loads(answer).items()))
        if uuid != ref["entry_uuid"]:
            problems.append("entry uuid differs from the reference file")
        source = "entry %d fetched from Rekor" % ref["log_index"]
    else:
        uuid = ref["entry_uuid"]
        entry = {
            "body": ref["body"],
            "integratedTime": ref["integrated_time"],
            "logID": ref["log_id"],
            "logIndex": ref["log_index"],
            "verification": ref["verification"],
        }
        source = "entry %d as copied into the reference file" % ref["log_index"]

    body_bytes = base64.b64decode(entry["body"])
    body = json.loads(body_bytes)
    spec = body.get("spec", {})
    if body.get("kind") != "hashedrekord":
        problems.append("entry is not a hashedrekord")
    if spec.get("data", {}).get("hash", {}).get("value") != digest:
        problems.append("entry hash is not the record hash")
    entry_key = base64.b64decode(spec["signature"]["publicKey"]["content"])
    if key_der(entry_key) != key_der(key_pem):
        problems.append("entry key is not keys/%s.pub.pem" % ref["key_id"])
    signature = base64.b64decode(spec["signature"]["content"])
    if raw is None:
        signed = "record bytes not public yet so the signature is not checked"
    elif verify_ecdsa(public_key(key_pem), raw, signature):
        signed = "signature over the record bytes ok"
    else:
        signed = ""
        problems.append("signature does not verify over the record bytes")

    proof = entry["verification"]["inclusionProof"]
    leaf = hashlib.sha256(b"\x00" + body_bytes).digest()
    siblings = [bytes.fromhex(item) for item in proof["hashes"]]
    if merkle_root(leaf, proof["logIndex"], proof["treeSize"], siblings).hex() != proof["rootHash"]:
        problems.append("inclusion proof does not reach the root hash")
    if uuid[-64:] != leaf.hex():
        problems.append("entry uuid is not the leaf hash")
    size, checkpoint_root, signed_notes = parse_checkpoint(proof["checkpoint"])
    if size != proof["treeSize"] or checkpoint_root != proof["rootHash"]:
        problems.append("checkpoint does not describe the same tree as the inclusion proof")

    rekor_note = ""
    if online:
        pem = rekor_key()
        if sha256(key_der(pem)) != entry["logID"]:
            problems.append("log id is not the hash of Rekor's key")
        key = public_key(pem)
        stamp = base64.b64decode(entry["verification"]["signedEntryTimestamp"])
        if not verify_ecdsa(key, entry_timestamp_message(entry), stamp):
            problems.append("Rekor's signed entry timestamp does not verify")
        if not any(verify_ecdsa(key, note, sig) for note, sig in signed_notes):
            problems.append("Rekor's checkpoint signature does not verify")
        rekor_note = ", Rekor's own signatures ok"

    if problems:
        report.line("rekor", "FAIL", "; ".join(problems))
    else:
        report.line(
            "rekor",
            "ok",
            "%s, signed by %s, %s, inclusion proof ok%s, integrated %s"
            % (source, ref["key_id"], signed, rekor_note, when(entry["integratedTime"])),
        )


# --- OpenTimestamps ----------------------------------------------------------

OTS_MAGIC = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94"
BITCOIN = bytes.fromhex("0588960d73d71901")
PENDING = bytes.fromhex("83dfe30d2ef90c8e")


class Reader:
    def __init__(self, data):
        self.data = data
        self.at = 0

    def byte(self):
        return self.take(1)[0]

    def take(self, count):
        piece = self.data[self.at : self.at + count]
        if len(piece) != count:
            raise ValueError("truncated")
        self.at += count
        return piece

    def varuint(self):
        value, shift = 0, 0
        while True:
            byte = self.byte()
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value
            shift += 7

    def varbytes(self):
        return self.take(self.varuint())


def parse_ots(data):
    """The proof's file digest and every attestation it ends in, with the
    message each one commits to; for Bitcoin that is the block's merkle root."""
    reader = Reader(data)
    if reader.take(len(OTS_MAGIC)) != OTS_MAGIC:
        raise ValueError("not an OpenTimestamps proof")
    if reader.varuint() != 1:
        raise ValueError("unknown proof version")
    if reader.byte() != 0x08:
        raise ValueError("file digest is not SHA-256")
    digest = reader.take(32)
    attestations = []
    _walk(reader, digest, attestations)
    return digest, attestations


def _walk(reader, message, out):
    tag = reader.byte()
    while tag == 0xFF:  # a fork: several paths continue from the same message
        _step(reader, reader.byte(), message, out)
        tag = reader.byte()
    _step(reader, tag, message, out)


def _step(reader, tag, message, out):
    if tag == 0x00:
        kind = reader.take(8)
        payload = Reader(reader.varbytes())
        if kind == BITCOIN:
            out.append(("bitcoin", payload.varuint(), message))
        elif kind == PENDING:
            out.append(("pending", payload.varbytes().decode("utf-8", "replace"), message))
        else:
            out.append(("unknown", kind.hex(), message))
        return
    if tag == 0xF0:
        message = message + reader.varbytes()
    elif tag == 0xF1:
        message = reader.varbytes() + message
    elif tag == 0xF2:
        message = message[::-1]
    elif tag == 0xF3:
        message = message.hex().encode()
    elif tag == 0x02:
        message = hashlib.sha1(message).digest()
    elif tag == 0x03:
        message = hashlib.new("ripemd160", message).digest()
    elif tag == 0x08:
        message = hashlib.sha256(message).digest()
    else:
        raise ValueError("unknown operation 0x%02x" % tag)
    _walk(reader, message, out)


def block_header(height):
    for base in EXPLORERS:
        try:
            block_hash = fetch(base + "block-height/%d" % height)
            if block_hash is None:
                continue
            block = json.loads(fetch(base + "block/" + block_hash.decode().strip()))
            return block["merkle_root"], block["timestamp"]
        except (URLError, OSError, ValueError, KeyError):
            continue
    return None


def check_bitcoin(files, signal_id, number, digest, online, report):
    proof = files.read("proofs/%s/%d.ots" % (signal_id, number))
    if proof is None:
        report.line("bitcoin", "pending", "no OpenTimestamps proof published yet")
        return
    try:
        file_digest, attestations = parse_ots(proof)
    except ValueError as error:
        report.line("bitcoin", "FAIL", "proof unreadable: %s" % error)
        return
    if file_digest.hex() != digest:
        report.line("bitcoin", "FAIL", "proof is for %s, not this record" % file_digest.hex())
        return
    blocks = sorted({(height, root) for kind, height, root in attestations if kind == "bitcoin"})
    if not blocks:
        calendars = sorted({uri for kind, uri, _ in attestations if kind == "pending"})
        report.line("bitcoin", "pending", "not in a block yet, waiting on " + ", ".join(calendars))
        return
    for height, root in blocks:
        expected = root[::-1].hex()  # explorers print the root byte reversed
        if not online:
            report.line("bitcoin", "skipped", "block %d must carry merkle root %s" % (height, expected))
            continue
        header = block_header(height)
        if header is None:
            report.line("bitcoin", "skipped", "no explorer answered for block %d, root %s" % (height, expected))
        elif header[0] == expected:
            report.line("bitcoin", "ok", "block %d, mined %s, merkle root matches" % (height, when(header[1])))
        else:
            report.line("bitcoin", "FAIL", "block %d carries %s, the proof says %s" % (height, header[0], expected))


# --- the log and the records -------------------------------------------------


def find_envelopes(files, signal_id):
    found = {}
    needle = '"signal_id":"%s"' % signal_id
    for day in files.log_days():
        data = files.read("log/" + day)
        if not data:
            continue
        for line_no, line in enumerate(data.decode("ascii", "replace").replace("\r", "").split("\n"), start=1):
            if needle in line:
                found[json.loads(line)["record_id"]] = (day, line_no, line)
    return found


def load_records(files, signal_id):
    records = {}
    number = 1
    while number < 10000:
        raw = files.read("records/%s/%d.json" % (signal_id, number))
        if raw is None:
            break
        records[number] = raw
        number += 1
    return records


class Report:
    def __init__(self):
        self.failed = 0

    def line(self, label, status, detail):
        if status == "FAIL":
            self.failed += 1
        print("  %-8s %-8s %s" % (label, status, detail))


def check_record(document, raw, signal_id, number, report):
    if document.get("schema") != SCHEMA:
        report.line("hash", "FAIL", "schema %r is not one this script knows" % document.get("schema"))
        return None
    problems = []
    ids = (document.get("record_id"), document.get("signal_id"), document.get("record_number"))
    if ids != ("%s/%d" % (signal_id, number), signal_id, str(number)):
        problems.append("the ids inside the record do not match its path")
    if canonical(document) != raw:
        problems.append("the file is not in canonical form (hashing the bytes as published)")
    digest = sha256(raw)
    report.line("hash", "FAIL" if problems else "ok", "; ".join(problems) if problems else digest)
    return digest


def check_chain(document, number, digests, report):
    previous = document.get("previous_record_hash")
    if number == 1:
        if previous is None:
            report.line("chain", "ok", "first record")
        else:
            report.line("chain", "FAIL", "record 1 names a previous record")
        return
    expected = digests.get(number - 1)
    if expected is None:
        report.line("chain", "skipped", "record %d is not published" % (number - 1))
    elif previous == expected:
        report.line("chain", "ok", "previous_record_hash is record %d" % (number - 1))
    else:
        report.line("chain", "FAIL", "previous_record_hash is not the hash of record %d" % (number - 1))


def check_envelope(envelope, document, digest, report):
    if envelope is None:
        report.line("log", "FAIL", "no line for this record in log/")
        return
    day, line_no, line = envelope
    env = json.loads(line)
    problems = []
    if canonical(env) != line.encode("ascii"):
        problems.append("the line is not in canonical form")
    if env.get("record_hash") != digest:
        problems.append("record_hash differs from the record")
    if document is not None:
        trade = document.get("trade") or {}
        expected = {
            "schema": document.get("schema"),
            "signal_id": document.get("signal_id"),
            "record_number": document.get("record_number"),
            "kind": document.get("kind"),
            "instrument": trade.get("instrument"),
            "side": trade.get("side"),
            "analyst": trade.get("analyst"),
            "posted_at": document.get("posted_at"),
        }
        different = sorted(key for key, value in expected.items() if env.get(key) != value)
        if different:
            problems.append("differs from the record in " + ", ".join(different))
    if problems:
        report.line("log", "FAIL", "log/%s line %d: %s" % (day, line_no, "; ".join(problems)))
    else:
        report.line("log", "ok", "log/%s line %d, committed %s" % (day, line_no, env.get("committed_at")))


def check_call(signal_id, files, online):
    report = Report()
    records = load_records(files, signal_id)
    envelopes = find_envelopes(files, signal_id)
    numbers = sorted(set(records) | {int(record_id.rsplit("/", 1)[1]) for record_id in envelopes})
    if not numbers:
        print("%s: nothing is published under this id" % signal_id)
        return 1
    print("%s: %d record%s, %d revealed" % (signal_id, len(numbers), "" if len(numbers) == 1 else "s", len(records)))
    digests = {}
    for number in numbers:
        record_id = "%s/%d" % (signal_id, number)
        raw = records.get(number)
        envelope = envelopes.get(record_id)
        document = None
        if raw is not None:
            try:
                document = json.loads(raw)
            except ValueError:
                print(record_id)
                report.line("hash", "FAIL", "the file is not JSON")
                continue
            print("%s  %s" % (record_id, document.get("kind")))
            digest = check_record(document, raw, signal_id, number, report)
            if digest is None:
                continue
            check_chain(document, number, digests, report)
        else:
            env = json.loads(envelope[2])
            digest = env["record_hash"]
            print("%s  %s" % (record_id, env.get("kind")))
            report.line("hash", "hidden", "not revealed yet, checking the envelope's %s" % digest)
        digests[number] = digest
        check_envelope(envelope, document, digest, report)
        try:
            check_rekor(files, signal_id, number, raw, digest, online, report)
        except (URLError, OSError) as error:
            report.line("rekor", "skipped", "network: %s" % error)
        try:
            check_bitcoin(files, signal_id, number, digest, online, report)
        except (URLError, OSError) as error:
            report.line("bitcoin", "skipped", "network: %s" % error)
    print("%d checks failed" % report.failed if report.failed else "no check failed")
    return 1 if report.failed else 0


# --- the worked example from Core's contract ---------------------------------

WORKED_EXAMPLE = """
{
  "corrected_kind": null,
  "event": {
    "effective_at": "2026-08-20T10:52:29.000000Z",
    "id": "asv2:3f2a9c8b7d6e5f4a3b2c1d0e9f8a7b6c5d4e3f2a",
    "observed_at": "2026-08-20T10:53:04.000000Z",
    "origin": "ANALYST_REPORTED",
    "recorded_at": "2026-08-20T10:53:04.118406Z",
    "semantic": "INSTRUCTION",
    "type": "TRADE_OPENED"
  },
  "kind": "opening",
  "levels": {
    "announced_dca_slots": "0",
    "auto_sl_be_override": null,
    "entries": [
      {
        "allocation_pct": "50",
        "entry_id": "CMP",
        "match_current_position_quantity": false,
        "price": null,
        "price_high": null,
        "price_low": null,
        "trigger_price_type": "LAST",
        "type": "MARKET"
      },
      {
        "allocation_pct": "50",
        "entry_id": "DCA 1",
        "match_current_position_quantity": false,
        "price": "116500",
        "price_high": null,
        "price_low": null,
        "trigger_price_type": "LAST",
        "type": "DCA"
      }
    ],
    "label": null,
    "leverage": "10",
    "quantity_basis": null,
    "quantity_pct": null,
    "reference_price": null,
    "semantic_kind": "INSTRUCTION",
    "stop": {
      "at_break_even": false,
      "candle_interval_minutes": null,
      "condition_operator": null,
      "price": "118200",
      "trigger_mode": "PRICE_TOUCH",
      "trigger_price_type": "LAST"
    },
    "stop_deferral": null,
    "targets": [
      {
        "close_pct": "50",
        "is_runner": false,
        "price": "114000",
        "quantity_basis": "ORIGINAL",
        "target_id": "TP1",
        "trigger_price_type": "LAST"
      },
      {
        "close_pct": "50",
        "is_runner": false,
        "price": "112000",
        "quantity_basis": "ORIGINAL",
        "target_id": "TP2",
        "trigger_price_type": "LAST"
      }
    ]
  },
  "posted_at": "2026-08-20T10:52:29.000000Z",
  "previous_record_hash": null,
  "record_id": "AXN-2026-08-20-00345/1",
  "record_number": "1",
  "restates": null,
  "result": null,
  "salt": "5f1b9c6e2d3a4b7c8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d",
  "schema": "axion-attestation/1",
  "signal_id": "AXN-2026-08-20-00345",
  "source": {
    "analyst_id": "947954207493853214",
    "channel_id": "1076832098452770876",
    "content_hash": null,
    "event_key": "1539950246463803445:11a0e6b9dd6e:0",
    "guild_id": "1076832098452770876",
    "message_id": "1539950246463803445",
    "revision": "0",
    "system": "AXIONSIGNAL_V2"
  },
  "supersedes": null,
  "trade": {
    "analyst": "discord-947954207493853214",
    "instrument": "BTCUSDT",
    "provider": "axion",
    "side": "SHORT"
  }
}
"""
WORKED_EXAMPLE_HASH = "5a5387f6af5285a887e093b36cb6f4c9670d5d10c85ae16375c8377161b2640c"


def self_test():
    document = json.loads(WORKED_EXAMPLE)
    data = canonical(document)
    digest = sha256(data)
    print("AXN-2026-08-20-00345/1, the worked example in Core's attestation contract")
    print("  %d canonical bytes, sha256 %s" % (len(data), digest))
    if digest == WORKED_EXAMPLE_HASH:
        print("  matches the hash the contract gives")
        return 0
    print("  DOES NOT MATCH %s" % WORKED_EXAMPLE_HASH)
    return 1


def main():
    parser = argparse.ArgumentParser(description="Check one Axion call against the log and its anchors.")
    parser.add_argument("signal_id", nargs="?", help="for example AXN-2026-09-01-00344")
    parser.add_argument(
        "--repo", help="a clone to read instead of GitHub (default: this script's directory when it holds records/)"
    )
    parser.add_argument("--offline", action="store_true", help="no network at all; anchors are read from the proof files")
    parser.add_argument("--self-test", action="store_true", help="recompute the worked example's hash")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.signal_id or not SIGNAL_ID.match(args.signal_id):
        parser.error("give a signal id like AXN-2026-09-01-00344")
    here = os.path.dirname(os.path.abspath(__file__))
    root = args.repo or (here if os.path.isdir(os.path.join(here, "records")) else None)
    if root is None and args.offline:
        parser.error("--offline needs a clone; pass --repo or run from inside one")
    try:
        return check_call(args.signal_id, Files(root), online=not args.offline)
    except (URLError, OSError) as error:
        print("could not reach the network: %s" % error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
