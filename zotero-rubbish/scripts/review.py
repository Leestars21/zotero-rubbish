#!/usr/bin/env python3
"""Local screening files only. This module never connects to or writes to Zotero."""

import argparse
import copy
import csv
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

VERSION = 1
KEY_PATTERN = re.compile(r"^[A-Z0-9]{8}$")
RUN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
DECISIONS = {"pending", "keep", "defer", "rubbish"}
PROFILE_FIELDS = (
    "research_direction", "current_question", "stage",
    "method_background", "desired_help",
)
STATUS_LABELS = {
    "verified": "已核实", "partial": "部分完成", "not_applied": "未发生移动",
    "conflict": "状态冲突，需人工处理", "unverified": "已尝试，尚未核实",
    "planned": "已记录操作意图",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def positive_id(value, label):
    require(type(value) is int and value > 0, f"{label} must be a positive integer")
    return value


def item_key(value):
    require(isinstance(value, str) and KEY_PATTERN.fullmatch(value), "Invalid item_key")
    return value


def identity(row):
    return positive_id(row.get("library_id"), "library_id"), item_key(row.get("item_key"))


def now():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_text(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json(path, data):
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def fingerprint(data):
    value = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def collections(rows):
    require(isinstance(rows, list), "collections must be a list")
    result = {}
    for row in rows:
        require(isinstance(row, dict), "Invalid collection row")
        collection_id = positive_id(row.get("id"), "collection id")
        require(isinstance(row.get("path"), str) and row["path"].strip(),
                "Collection full path is required")
        normalized = {"id": collection_id, "path": row["path"]}
        if row.get("key"):
            normalized["key"] = item_key(row["key"])
        if collection_id in result:
            require(result[collection_id] == normalized, "Conflicting collection identities")
        result[collection_id] = normalized
    return sorted(result.values(), key=lambda row: row["id"])


def keys(values):
    require(isinstance(values, list), "Child keys must be a list")
    return sorted({item_key(value) for value in values})


def validate_context(data):
    profile = data.get("profile", {})
    require(isinstance(profile, dict), "profile must be an object")
    for field in PROFILE_FIELDS:
        require(isinstance(profile.get(field), str) and profile[field].strip(),
                f"Ask the user for profile.{field} before scoring")
    scope = data.get("scope", {})
    require(isinstance(scope, dict), "scope must be an object")
    positive_id(scope.get("library_id"), "scope.library_id")
    require(scope.get("mode") in {"library", "collection"}, "Choose library or collection scope")
    require(scope.get("library_type") in {"user", "group"}, "Specify library_type")
    if scope["library_type"] == "group":
        positive_id(scope.get("group_id"), "group_id (not local library_id)")
    require(type(scope.get("include_subcollections")) is bool, "Specify include_subcollections")
    for field in ("collection_ids", "excluded_collection_ids"):
        require(isinstance(scope.get(field), list), f"Specify scope.{field}")
        for value in scope[field]:
            positive_id(value, field)
    if scope["mode"] == "collection":
        require(scope["collection_ids"], "A selected collection is required")
    coverage = data.get("coverage", {})
    require(type(coverage.get("enumeration_complete")) is bool,
            "coverage.enumeration_complete must reflect real pagination")
    return copy.deepcopy(profile), copy.deepcopy(scope), copy.deepcopy(coverage)


def normalize_input(data, previous=None):
    profile, scope, coverage = validate_context(data)
    require(isinstance(data.get("items"), list), "items must be a list")
    if previous:
        require(profile == previous["profile"] and scope == previous["scope"],
                "Changed profile or scope requires a new run")
    excluded = set(scope["excluded_collection_ids"])
    selected = set(scope["collection_ids"])
    result, skipped = {}, []
    for raw in data["items"]:
        require(isinstance(raw, dict), "Invalid item")
        row = copy.deepcopy(raw)
        row.setdefault("library_id", scope["library_id"])
        ident = identity(row)
        require(ident[0] == scope["library_id"], "Cross-library item rejected")
        current_collections = collections(row.get("collections", []))
        memberships = {value["id"] for value in current_collections}
        skip = None
        if row.get("deleted"):
            skip = "trash"
        elif row.get("item_type") in {"attachment", "note"}:
            skip = "child-item; enumerate its parent separately"
        elif memberships & excluded:
            skip = "!Rubbish/excluded collection"
        elif scope["mode"] == "collection" and not memberships & selected:
            skip = "outside selected collection tree"
        if skip:
            skipped.append({"item_key": ident[1], "reason": skip})
            continue
        score = row.get("score")
        require(score is None or type(score) is int and 0 <= score <= 5, "Score must be 0–5 or null")
        evidence = row.get("evidence", "insufficient")
        require(evidence in {"title", "abstract", "full_text", "insufficient"}, "Invalid evidence level")
        require(evidence != "insufficient" or score is None, "Insufficient evidence cannot score zero")
        status = row.get("score_status", "scored" if score is not None else
                         "insufficient" if evidence == "insufficient" else "pending")
        require(status in {"scored", "insufficient", "pending"}, "Invalid score_status")
        require((status == "scored") == (score is not None), "Score and score_status disagree")
        require(status != "insufficient" or evidence == "insufficient", "Mark insufficient evidence explicitly")
        reason = row.get("reason", "")
        require(isinstance(reason, str), "reason must be text")
        require(status == "pending" or reason.strip(), "Explain the score or missing evidence")
        normalized = {
            "library_id": ident[0], "item_key": ident[1],
            "item_id": positive_id(row.get("item_id"), "item_id"),
            "title": str(row.get("title") or "（无题名）"),
            "authors": str(row.get("authors", "")), "year": str(row.get("year", "")),
            "collections": current_collections,
            "attachment_keys": keys(row.get("attachment_keys", [])),
            "note_keys": keys(row.get("note_keys", [])),
            "score": score, "score_status": status, "reason": reason,
            "evidence": evidence, "evidence_locator": str(row.get("evidence_locator", "")),
        }
        if row.get("pdf_key"):
            normalized["pdf_key"] = item_key(row["pdf_key"])
        if ident in result:
            old = result[ident]
            require(old["item_id"] == normalized["item_id"], "Same key has conflicting item IDs")
            if old["score"] is not None and normalized["score"] is not None:
                require(old["score"] == normalized["score"], "Resolve conflicting duplicate scores")
            chosen = normalized if old["score_status"] == "pending" or (
                old["score"] is None and normalized["score"] is not None) else old
            chosen["collections"] = collections(old["collections"] + normalized["collections"])
            for field in ("attachment_keys", "note_keys"):
                chosen[field] = keys(old[field] + normalized[field])
            result[ident] = chosen
        else:
            result[ident] = normalized
    existing = {identity(row): row["record_id"] for row in previous["items"]} if previous else {}
    require(not previous or set(existing) <= set(result), "Update must retain previous items")
    next_number = max((int(value[1:]) for value in existing.values()), default=0) + 1
    items = []
    for ident, row in sorted(result.items()):
        if ident not in existing:
            existing[ident] = f"R{next_number:04d}"
            next_number += 1
        row["record_id"] = existing[ident]
        items.append(row)
    coverage.update({
        "received_rows": len(data["items"]), "unique_items": len(items), "skipped": skipped,
        "pending_scores": sum(row["score_status"] == "pending" for row in items),
    })
    complete = coverage["enumeration_complete"] and not coverage["pending_scores"]
    return {
        "schema_version": VERSION, "profile": profile, "profile_hash": fingerprint(profile),
        "scope": scope, "coverage": coverage, "items": items,
        "status": "waiting_review" if complete else "scoring_incomplete",
    }


def read_session(path):
    session = load_json(path)
    require(session.get("schema_version") == VERSION, "Unsupported session version")
    require(RUN_PATTERN.fullmatch(session.get("run_id", "")), "Invalid run_id")
    require(session["profile_hash"] == fingerprint(session["profile"]), "Profile fingerprint changed")
    identities = [identity(row) for row in session["items"]]
    require(len(set(identities)) == len(identities), "Duplicate session identities")
    return session


def create_run(data, project, run_id=None):
    session = normalize_input(data)
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6]
    require(isinstance(run_id, str) and RUN_PATTERN.fullmatch(run_id), "Invalid run_id")
    require(run_id.split(".")[0].upper() not in
            {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)}, *{f"LPT{i}" for i in range(1, 10)}},
            "Reserved Windows name")
    project = Path(project).resolve()
    require(project.is_dir(), "Project directory must exist")
    archive = project / ".zotero-rubbish"
    folder = archive / "runs" / run_id
    require(folder.resolve().is_relative_to(project), "Output escapes project")
    folder.mkdir(parents=True, exist_ok=False)
    # The local ignore applies even when the caller's project has its own Git repository.
    if not (archive / ".gitignore").exists():
        write_text(archive / ".gitignore", "*\n")
    session.update(run_id=run_id, created_at=now(), updated_at=now())
    path = folder / "session.json"
    write_json(path, session)
    render(path)
    return path


def validate_decisions(data, session):
    require(isinstance(data, dict) and data.get("schema_version") == VERSION, "Unsupported decision file")
    require(data.get("run_id") == session["run_id"], "Decision file belongs to a different run")
    require(data.get("profile_hash") == session["profile_hash"], "Decision profile mismatch")
    require(type(data.get("review_confirmed")) is bool, "Explicit reading confirmation is required")
    require(isinstance(data.get("decisions"), list), "decisions must be a list")
    inventory = {identity(row): row for row in session["items"]}
    seen, result = set(), []
    for row in data["decisions"]:
        ident = identity(row)
        require(ident in inventory, "Unknown or cross-library decision item")
        require(ident not in seen, "Duplicate decision item")
        seen.add(ident)
        require(row.get("record_id") == inventory[ident]["record_id"], "Stable number mismatch")
        require(row.get("decision") in DECISIONS, "Invalid human decision")
        require(type(row.get("planned_read")) is bool and type(row.get("read_confirmed")) is bool,
                "Reading flags must be booleans")
        reason = row.get("reason", "")
        require(isinstance(reason, str), "Decision reason must be text")
        if row["decision"] == "rubbish":
            require(data["review_confirmed"] and row["read_confirmed"],
                    "Read the paper and explicitly confirm before requesting a !Rubbish move")
        result.append({key: row[key] for key in
                       ("library_id", "item_key", "record_id", "planned_read", "read_confirmed", "decision")}
                      | {"reason": reason})
    return {
        "schema_version": VERSION, "run_id": session["run_id"],
        "profile_hash": session["profile_hash"], "review_confirmed": data["review_confirmed"],
        "exported_at": str(data.get("exported_at", "")), "decisions": result,
    }


def downloads_folder():
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                value, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
                return Path(os.path.expandvars(value))
        except OSError:
            pass
    return Path.home() / "Downloads"


def locate_decisions(path, session, downloads=None):
    pattern = re.compile(re.escape("decisions-" + session["run_id"]) + r"( \(\d+\))?\.json$")
    candidates = []
    for folder in (Path(path).parent, Path(downloads) if downloads else downloads_folder()):
        if folder.is_dir():
            candidates.extend(file for file in folder.iterdir() if file.is_file() and pattern.fullmatch(file.name))
    saved = Path(path).parent / "decisions.json"
    if saved.is_file():
        candidates.append(saved)
    require(candidates, "Decision file not found; ask only for its saved location")
    newest_time = max(file.stat().st_mtime_ns for file in candidates)
    newest = sorted({file for file in candidates if file.stat().st_mtime_ns == newest_time})
    if len(newest) > 1:
        require(len({fingerprint(load_json(file)) for file in newest}) == 1,
                "Decision files are equally recent and differ; ask only for the saved file location")
    return newest[0]


def import_decisions(path, file=None, downloads=None):
    session = read_session(path)
    source = Path(file) if file else locate_decisions(path, session, downloads)
    decisions = validate_decisions(load_json(source), session)
    write_json(Path(path).parent / "decisions.json", decisions)
    if session["status"] != "scoring_incomplete":
        session["status"] = "waiting_authorization" if any(
            row["decision"] == "rubbish" for row in decisions["decisions"]) else "waiting_review"
    session["updated_at"] = now()
    write_json(path, session)
    if read_journal(path):
        write_report(path)
    render(path)
    return decisions


def csv_text(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def render(path):
    session = read_session(path)
    decisions_path = Path(path).parent / "decisions.json"
    decisions = validate_decisions(load_json(decisions_path), session) if decisions_path.exists() else None
    payload = json.dumps({"session": session, "decisions": decisions}, ensure_ascii=False)
    for character, escaped in (("<", r"\u003c"), (">", r"\u003e"), ("&", r"\u0026"),
                               ("\u2028", r"\u2028"), ("\u2029", r"\u2029")):
        payload = payload.replace(character, escaped)
    template = (Path(__file__).resolve().parent.parent / "assets" / "review.html").read_text(encoding="utf-8")
    require(template.count("__BATCH_DATA__") == 1, "Invalid page template")
    write_text(Path(path).parent / "review.html", template.replace("__BATCH_DATA__", payload))
    with (Path(path).parent / "scores.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["编号", "题目", "作者", "年份", "适配分", "读取依据", "理由", "文库ID", "条目key"])
        for row in session["items"]:
            writer.writerow([row["record_id"], csv_text(row["title"]), csv_text(row["authors"]),
                             csv_text(row["year"]), row["score"] if row["score"] is not None else "待补证据",
                             row["evidence"], csv_text(row["reason"]), row["library_id"], row["item_key"]])
    return Path(path).parent / "review.html"


def snapshot_items(snapshot, session):
    require(snapshot.get("library_id") == session["scope"]["library_id"], "Snapshot library mismatch")
    inventory = {identity(row): row for row in session["items"]}
    result = {}
    for raw in snapshot.get("items", []):
        row = copy.deepcopy(raw)
        row.setdefault("library_id", snapshot["library_id"])
        ident = identity(row)
        require(ident in inventory and ident not in result, "Unknown or duplicate snapshot item")
        require(row.get("item_id") == inventory[ident]["item_id"], "Re-resolve item ID drift before moving")
        require(not row.get("deleted"), "Item is now in trash")
        require("collections" in row, "Read the complete collections field; missing is not unfiled")
        require("attachment_keys" in row and "note_keys" in row, "Read child associations before moving")
        row["collections"] = collections(row.get("collections", []))
        row["attachment_keys"], row["note_keys"] = keys(row["attachment_keys"]), keys(row["note_keys"])
        result[ident] = row
    return result


def prepare_move(session, decisions, snapshot):
    require(session["coverage"]["enumeration_complete"] and not session["coverage"]["pending_scores"],
            "Complete the requested enumeration and scores before move planning")
    decisions = validate_decisions(decisions, session)
    target = snapshot.get("target_collection", {})
    require(target.get("library_id") == session["scope"]["library_id"], "Target must be in the same library")
    require(target.get("path") == "!Rubbish" and target.get("parent_id") is None,
            "Resolve the top-level !Rubbish collection")
    target_id = target.get("id")
    if target_id is not None:
        positive_id(target_id, "!Rubbish collection ID")
    current = snapshot_items(snapshot, session)
    inventory = {identity(row): row for row in session["items"]}
    result = []
    for decision in decisions["decisions"]:
        if decision["decision"] != "rubbish":
            continue
        ident = identity(decision)
        require(ident in current, "Read fresh memberships for every proposed move")
        before = current[ident]
        remove = [row["id"] for row in before["collections"] if row["id"] != target_id]
        result.append({
            "library_id": ident[0], "item_key": ident[1], "item_id": before["item_id"],
            "record_id": inventory[ident]["record_id"], "title": inventory[ident]["title"],
            "reason": decision["reason"] or "用户阅读后确认不适合当前研究方向",
            "before_collections": before["collections"],
            "attachment_keys": before["attachment_keys"], "note_keys": before["note_keys"],
            "rubbish_collection_id": target_id,
            "rubbish_added": target_id is None or target_id not in {row["id"] for row in before["collections"]},
            "remove_collection_ids": remove,
            "expected_collection_ids": [target_id] if target_id is not None else [],
        })
    return {
        "schema_version": VERSION, "run_id": session["run_id"], "profile_hash": session["profile_hash"],
        "generated_at": now(), "authorization_required": True, "operation": "move",
        "target_collection": target, "items": result,
    }


def read_journal(path):
    file = Path(path).parent / "operations.jsonl"
    return [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()] if file.exists() else []


def assess(intent, after):
    require(after.get("item_id") == intent["item_id"] and after.get("item_key") == intent["item_key"],
            "Verification identity mismatch")
    if after.get("deleted"):
        return "conflict"
    actual = {row["id"] for row in collections(after.get("collections", []))}
    expected = set(intent["expected_collection_ids"])
    if keys(after.get("attachment_keys", [])) != intent["attachment_keys"] or \
            keys(after.get("note_keys", [])) != intent["note_keys"]:
        return "conflict"
    if actual == expected:
        return "verified"
    before = {row["id"] for row in intent["before_collections"]}
    if actual == before:
        return "not_applied"
    allowed = before | expected
    if actual <= allowed and actual & expected:
        return "partial"
    return "conflict"


def record_event(path, raw):
    session = read_session(path)
    event = copy.deepcopy(raw)
    ident = identity(event)
    inventory = {identity(row): row for row in session["items"]}
    require(ident in inventory, "Unknown journal item")
    require(event.get("operation") in {"move", "restore"}, "Invalid operation")
    require(event.get("phase") in {"intent", "result", "verification"}, "Invalid journal phase")
    require(isinstance(event.get("attempt_id"), str) and event["attempt_id"].strip(), "attempt_id is required")
    journal = read_journal(path)
    attempts = [row for row in journal if row["attempt_id"] == event["attempt_id"]]
    if event["phase"] == "intent":
        require(not attempts, "Use a new attempt ID; inspect the old attempt before retrying")
        require(isinstance(event.get("authorization_text"), str) and event["authorization_text"].strip(),
                "Record the user's real execution instruction; never invent authorization")
        require(event.get("item_id") == inventory[ident]["item_id"], "Intent item ID mismatch")
        require("before_collections" in event, "Save the complete source snapshot before writing")
        event["before_collections"] = collections(event["before_collections"])
        event["attachment_keys"], event["note_keys"] = keys(event["attachment_keys"]), keys(event["note_keys"])
        require(isinstance(event.get("expected_collection_ids"), list), "Expected collection IDs must be a list")
        for value in event["expected_collection_ids"]:
            positive_id(value, "expected collection ID")
        if event["operation"] == "move":
            require(session["coverage"]["enumeration_complete"] and not session["coverage"]["pending_scores"],
                    "Complete enumeration and scores before recording a move")
            file = Path(path).parent / "decisions.json"
            require(file.exists(), "Import human decisions first")
            decisions = validate_decisions(load_json(file), session)
            require(any(identity(row) == ident and row["decision"] == "rubbish" for row in decisions["decisions"]),
                    "This item was not selected by a confirmed human decision")
            require(set(event["expected_collection_ids"]) == {event.get("rubbish_collection_id")},
                    "A move must leave only the verified !Rubbish membership")
        event["status"] = "planned"
    else:
        require(attempts and attempts[0]["phase"] == "intent", "Save intent before calling a write tool")
        intent = attempts[0]
        require(identity(intent) == ident and intent["operation"] == event["operation"], "Attempt identity mismatch")
        if event["phase"] == "verification":
            after = event.get("after", {})
            require(after.get("library_id", ident[0]) == ident[0], "Verification library mismatch")
            require("collections" in after, "Read complete memberships for verification")
            require("attachment_keys" in after and "note_keys" in after, "Verify child associations")
            event["status"] = assess(intent, after)
        else:
            event["status"] = "unverified"
    event["logged_at"] = now()
    event["event_id"] = uuid.uuid4().hex
    with (Path(path).parent / "operations.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    write_report(path)
    return event


def prepare_restore(session, journal, snapshot, record_ids=None):
    current = snapshot_items(snapshot, session)
    requested = set(record_ids) if record_ids is not None else None
    inventory = {identity(row): row for row in session["items"]}
    require(requested is None or requested <= {row["record_id"] for row in session["items"]}, "Unknown stable number")
    require(isinstance(snapshot.get("available_collection_ids"), list),
            "Read available collection IDs before restoring")
    available = {positive_id(value, "available collection ID") for value in snapshot["available_collection_ids"]}
    baselines, active, intents, conflicts = {}, set(), {}, set()
    for event in journal:
        ident = identity(event)
        if event["phase"] == "intent":
            intents[event["attempt_id"]] = event
            if event["operation"] == "move":
                if ident not in baselines:
                    baselines[ident] = copy.deepcopy(event)
                else:
                    baseline = baselines[ident]
                    require(baseline["rubbish_collection_id"] == event["rubbish_collection_id"],
                            "!Rubbish target changed between attempts")
                    additional = [row for row in event["before_collections"]
                                  if not baseline["rubbish_added"] or row["id"] != baseline["rubbish_collection_id"]]
                    baseline["before_collections"] = collections(baseline["before_collections"] + additional)
        elif event["phase"] == "verification":
            if event["operation"] == "restore" and event["status"] == "verified":
                active.discard(ident)
                baselines.pop(ident, None)
                conflicts.discard(ident)
            elif event["operation"] == "move":
                if event["status"] in {"verified", "partial"}:
                    active.add(ident)
                    conflicts.discard(ident)
                elif event["status"] == "not_applied" and ident not in active:
                    baselines.pop(ident, None)
                elif event["status"] == "conflict":
                    conflicts.add(ident)
    result = []
    for ident in sorted(active):
        if requested is not None and inventory[ident]["record_id"] not in requested:
            continue
        require(ident not in conflicts, "Resolve the conflicting move before restoration")
        require(ident in current, "Read fresh memberships before restoring")
        move = baselines[ident]
        before = current[ident]
        original = {row["id"] for row in move["before_collections"]}
        require(original <= available, "Original collection no longer exists; ask the user for a target")
        current_ids = {row["id"] for row in before["collections"]}
        remove_rubbish = bool(move["rubbish_added"]) and move["rubbish_collection_id"] in current_ids
        expected = current_ids | original
        if remove_rubbish:
            expected.discard(move["rubbish_collection_id"])
        result.append({
            "library_id": ident[0], "item_key": ident[1], "item_id": before["item_id"],
            "record_id": inventory[ident]["record_id"], "title": inventory[ident]["title"],
            "before_collections": before["collections"], "original_collections": move["before_collections"],
            "add_collection_ids": sorted(original - current_ids),
            "remove_rubbish": remove_rubbish, "rubbish_collection_id": move["rubbish_collection_id"],
            "attachment_keys": before["attachment_keys"], "note_keys": before["note_keys"],
            "expected_collection_ids": sorted(expected),
        })
    return {
        "schema_version": VERSION, "run_id": session["run_id"], "profile_hash": session["profile_hash"],
        "generated_at": now(), "authorization_required": True, "operation": "restore", "items": result,
    }


def markdown_text(value):
    return str(value).replace("\n", " ").replace("|", r"\|")


def execution_status(session, journal, decisions):
    latest = {}
    for event in journal:
        latest[identity(event)] = event
    if not latest:
        return session["status"]
    statuses = {event["status"] for event in latest.values()}
    for status, stage in (
        ("conflict", "execution_conflict"), ("unverified", "execution_unverified"),
        ("partial", "execution_partial"), ("planned", "execution_in_progress"),
    ):
        if status in statuses:
            return stage
    restored = {ident for ident, event in latest.items()
                if event["operation"] == "restore" and event["status"] == "verified"}
    moved = {ident for ident, event in latest.items()
             if event["operation"] == "move" and event["status"] == "verified"}
    if restored:
        return "restored" if len(restored) == len(latest) else "partially_restored"
    approved = {identity(row) for row in decisions.get("decisions", []) if row["decision"] == "rubbish"}
    if moved:
        return "moves_complete" if approved <= moved else "moves_partial"
    return "waiting_authorization"


def write_report(path):
    session = read_session(path)
    journal = read_journal(path)
    attempts = {}
    for event in journal:
        attempts.setdefault(event["attempt_id"], {"intent": event})
        attempts[event["attempt_id"]]["latest"] = event
    decision_file = Path(path).parent / "decisions.json"
    decisions = load_json(decision_file) if decision_file.exists() else {}
    session["status"] = execution_status(session, journal, decisions)
    session["updated_at"] = now()
    write_json(path, session)
    stage_labels = {
        "execution_conflict": "状态冲突，等待处理", "execution_unverified": "已尝试，等待核实",
        "execution_partial": "部分完成，可核查后续办", "execution_in_progress": "正在执行",
        "restored": "已恢复", "partially_restored": "已恢复部分文献",
        "moves_complete": "本次移入已完成并核实", "moves_partial": "部分文献已移入",
        "waiting_authorization": "等待执行指令",
    }
    lines = [
        "# !Rubbish 操作记录", "", f"批次：{session['run_id']}", "",
        f"当前阶段：{stage_labels.get(session['status'], session['status'])}", "",
        "下面只汇总已记录的尝试；操作回执不等于核实成功。原分类和恢复依据保存在 operations.jsonl。", "",
        "| 编号 | 文献 | 操作 | 状态 | 原分类 |", "| --- | --- | --- | --- | --- |",
    ]
    for attempt in attempts.values():
        intent, latest = attempt["intent"], attempt["latest"]
        paths = "；".join(row["path"] for row in intent["before_collections"]) or "无分类"
        label = STATUS_LABELS[latest["status"]]
        lines.append("| " + " | ".join(markdown_text(value) for value in (
            intent.get("record_id", intent["item_key"]), intent.get("title", intent["item_key"]),
            "移入" if intent["operation"] == "move" else "恢复", label, paths)) + " |")
    write_text(Path(path).parent / "Rubbish" / "操作记录.md", "\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--input", required=True)
    create.add_argument("--project", required=True)
    create.add_argument("--run-id")
    for command in ("update", "render", "import-decisions", "preview", "record", "restore-preview"):
        sub = commands.add_parser(command)
        sub.add_argument("--session", required=True)
        if command == "update":
            sub.add_argument("--input", required=True)
        elif command == "import-decisions":
            sub.add_argument("--file")
        elif command in {"preview", "restore-preview"}:
            sub.add_argument("--snapshot", required=True)
            if command == "restore-preview":
                sub.add_argument("--records", nargs="+")
        elif command == "record":
            sub.add_argument("--event", required=True)
    args = parser.parse_args()
    try:
        if args.command == "create":
            print(create_run(load_json(args.input), args.project, args.run_id))
        elif args.command == "render":
            print(render(args.session))
        elif args.command == "update":
            require(not read_journal(args.session), "Do not rewrite scoring evidence after execution starts")
            previous = read_session(args.session)
            updated = normalize_input(load_json(args.input), previous)
            updated.update(run_id=previous["run_id"], created_at=previous["created_at"], updated_at=now())
            write_json(args.session, updated)
            print(render(args.session))
        elif args.command == "import-decisions":
            result = import_decisions(args.session, args.file)
            print(json.dumps({"imported": len(result["decisions"]), "authorization_granted": False}))
        elif args.command in {"preview", "restore-preview"}:
            session = read_session(args.session)
            snapshot = load_json(args.snapshot)
            if args.command == "preview":
                decisions = load_json(Path(args.session).parent / "decisions.json")
                result = prepare_move(session, decisions, snapshot)
                output = Path(args.session).parent / "move-preview.json"
            else:
                result = prepare_restore(session, read_journal(args.session), snapshot, args.records)
                output = Path(args.session).parent / "restore-preview.json"
            write_json(output, result)
            print(output)
        elif args.command == "record":
            event = record_event(args.session, load_json(args.event))
            print(json.dumps({"event_id": event["event_id"], "status": event["status"]}))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
