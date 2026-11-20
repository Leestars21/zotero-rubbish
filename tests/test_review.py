"""Observable local workflow invariants; all Zotero state below is fictitious."""

import copy
import csv
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("review", ROOT / "zotero-rubbish" / "scripts" / "review.py")
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


def sample():
    return json.loads((ROOT / "tests" / "fixtures" / "sample-inventory.json").read_text(encoding="utf-8"))


class FakeZotero:
    def __init__(self, session):
        self.items = {row["item_key"]: copy.deepcopy(row) for row in session["items"]}
        self.calls = []

    def read(self, key):
        return copy.deepcopy(self.items[key])

    def move(self, key, target=99, partial=False, timeout=False):
        self.calls.append(("move", key))
        row = self.items[key]
        originals = row["collections"]
        row["collections"] = ([originals[-1]] if partial and originals else []) + [{"id": target, "path": "!Rubbish"}]
        if timeout:
            raise TimeoutError("simulated response lost after write")
        return {"action_id": "fictional-action-" + str(len(self.calls))}

    def restore(self, key, plan):
        self.calls.append(("restore", key))
        row = self.items[key]
        memberships = {value["id"]: value for value in row["collections"]}
        for original in plan["original_collections"]:
            memberships[original["id"]] = original
        if plan["remove_rubbish"]:
            memberships.pop(plan["rubbish_collection_id"], None)
        row["collections"] = list(memberships.values())

    def snapshot(self, session, keys=None):
        return {
            "library_id": session["scope"]["library_id"],
            "target_collection": {"library_id": 1, "id": 99, "path": "!Rubbish", "parent_id": None},
            "available_collection_ids": [10, 11, 12, 99, 100, 77],
            "items": [self.read(key) for key in (keys or self.items)],
        }


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.path = review.create_run(sample(), self.project, "fictional-test")
        self.session = review.read_session(self.path)
        self.fake = FakeZotero(self.session)

    def tearDown(self):
        self.temp.cleanup()

    def decisions(self, choices=None, confirmed=True):
        choices = choices or {"ABCD2345": "rubbish", "CDEF2345": "defer"}
        return {
            "schema_version": 1, "run_id": self.session["run_id"],
            "profile_hash": self.session["profile_hash"], "review_confirmed": confirmed,
            "decisions": [{
                "library_id": row["library_id"], "item_key": row["item_key"], "record_id": row["record_id"],
                "planned_read": row["item_key"] in choices, "read_confirmed": confirmed and choices.get(row["item_key"]) == "rubbish",
                "decision": choices.get(row["item_key"], "pending"), "reason": "虚构测试：方法不适用"
            } for row in self.session["items"]],
        }

    def imported(self, decisions=None):
        file = self.path.parent / "decisions-fictional-test.json"
        review.write_json(file, decisions or self.decisions())
        review.import_decisions(self.path, file)
        return review.load_json(self.path.parent / "decisions.json")

    def plan(self):
        return review.prepare_move(self.session, self.imported(), self.fake.snapshot(self.session))

    def intent(self, row, attempt="attempt-1", operation="move"):
        return dict(row, operation=operation, phase="intent", attempt_id=attempt,
                    authorization_text="虚构测试用户：按该批次已阅读确认的决定执行")

    def verification(self, intent):
        return {
            "library_id": intent["library_id"], "item_key": intent["item_key"],
            "operation": intent["operation"], "phase": "verification",
            "attempt_id": intent["attempt_id"], "after": self.fake.read(intent["item_key"]),
        }

    def perform(self, partial=False, timeout=False, attempt="attempt-1"):
        row = self.plan()["items"][0]
        intent = self.intent(row, attempt)
        review.record_event(self.path, intent)
        try:
            receipt = self.fake.move(row["item_key"], partial=partial, timeout=timeout)
        except TimeoutError:
            receipt = {"error": "timeout", "outcome": "unknown"}
        review.record_event(self.path, {
            "library_id": row["library_id"], "item_key": row["item_key"],
            "operation": "move", "phase": "result", "attempt_id": attempt, "receipt": receipt,
        })
        return intent, review.record_event(self.path, self.verification(intent))

    def test_profile_is_required_before_creating_scores(self):
        data = sample()
        del data["profile"]["method_background"]
        with self.assertRaisesRegex(ValueError, "Ask the user"):
            review.normalize_input(data)

    def test_scope_is_not_silently_whole_library(self):
        data = sample()
        del data["scope"]["mode"]
        with self.assertRaises(ValueError):
            review.normalize_input(data)

    def test_parent_deduplication_and_rubbish_exclusion(self):
        self.assertEqual(len(self.session["items"]), 4)
        self.assertEqual(self.session["coverage"]["received_rows"], 6)
        self.assertEqual(self.session["coverage"]["skipped"][0]["reason"], "!Rubbish/excluded collection")
        self.assertEqual(self.session["status"], "waiting_review")
        self.assertEqual(self.fake.calls, [])

    def test_trash_and_child_items_do_not_become_papers(self):
        data = sample()
        data["items"] += [
            dict(data["items"][0], item_key="FGHI2345", item_id=201, deleted=True),
            dict(data["items"][0], item_key="GHIJ2345", item_id=202, item_type="attachment"),
        ]
        result = review.normalize_input(data)
        self.assertEqual(len(result["items"]), 4)
        self.assertEqual(len(result["coverage"]["skipped"]), 3)

    def test_absent_abstract_is_null_and_not_zero(self):
        row = next(row for row in self.session["items"] if row["item_key"] == "CDEF2345")
        self.assertIsNone(row["score"])
        data = sample()
        data["items"][2]["score"] = 0
        with self.assertRaises(ValueError):
            review.normalize_input(data)

    def test_incomplete_pagination_cannot_plan_a_move(self):
        data = sample()
        data["coverage"]["enumeration_complete"] = False
        session = review.normalize_input(data) | {"run_id": "fictional-test"}
        self.assertEqual(session["status"], "scoring_incomplete")
        with self.assertRaisesRegex(ValueError, "Complete"):
            review.prepare_move(session, self.decisions(), self.fake.snapshot(self.session))
        self.assertEqual(self.fake.calls, [])

    def test_pending_scores_cannot_plan_a_move(self):
        session = copy.deepcopy(self.session)
        session["coverage"]["pending_scores"] = 1
        with self.assertRaises(ValueError):
            review.prepare_move(session, self.decisions(), self.fake.snapshot(self.session))

    def test_importing_decisions_does_not_move_anything(self):
        self.imported()
        self.assertEqual(review.read_session(self.path)["status"], "waiting_authorization")
        self.assertEqual(self.fake.calls, [])
        self.assertFalse((self.path.parent / "operations.jsonl").exists())

    def test_unread_rejections_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Read the paper"):
            review.validate_decisions(self.decisions(confirmed=False), self.session)

    def test_wrong_run_profile_number_and_unknown_item_are_rejected(self):
        for field, value in (("run_id", "another-run"), ("profile_hash", "wrong")):
            data = self.decisions()
            data[field] = value
            with self.assertRaises(ValueError):
                review.validate_decisions(data, self.session)
        for field, value in (("record_id", "R9999"), ("item_key", "ZZZZ2345"), ("library_id", 2)):
            data = self.decisions()
            data["decisions"][0][field] = value
            with self.assertRaises(ValueError):
                review.validate_decisions(data, self.session)

    def test_newest_downloaded_copy_is_used_and_not_an_old_decision(self):
        downloads = self.project / "downloads"
        downloads.mkdir()
        old = downloads / "decisions-fictional-test.json"
        new = downloads / "decisions-fictional-test (1).json"
        review.write_json(old, self.decisions())
        review.write_json(new, self.decisions({"BCDE2345": "keep"}))
        import os
        os.utime(new, ns=(old.stat().st_atime_ns, old.stat().st_mtime_ns + 2_000_000))
        result = review.import_decisions(self.path, downloads=downloads)
        self.assertTrue(any(row["item_key"] == "BCDE2345" and row["decision"] == "keep" for row in result["decisions"]))
        self.assertEqual(self.fake.calls, [])

    def test_missing_decisions_requests_only_saved_location(self):
        with self.assertRaisesRegex(ValueError, "saved location"):
            review.locate_decisions(self.path, self.session, self.project / "empty")

    def test_equally_recent_different_exports_require_a_file_choice(self):
        import os
        folder = self.project / "tied-downloads"
        folder.mkdir()
        first = folder / "decisions-fictional-test.json"
        second = folder / "decisions-fictional-test (1).json"
        review.write_json(first, self.decisions())
        review.write_json(second, self.decisions({"ABCD2345": "keep"}))
        timestamp = first.stat().st_mtime_ns
        os.utime(second, ns=(timestamp, timestamp))
        with self.assertRaisesRegex(ValueError, "saved file location"):
            review.import_decisions(self.path, downloads=folder)
        self.assertFalse((self.path.parent / "decisions.json").exists())

    def test_missing_membership_field_is_not_treated_as_unfiled(self):
        snapshot = self.fake.snapshot(self.session)
        del snapshot["items"][0]["collections"]
        with self.assertRaisesRegex(ValueError, "missing is not unfiled"):
            review.prepare_move(self.session, self.decisions(), snapshot)
        self.assertEqual(self.fake.calls, [])
        self.assertFalse((self.path.parent / "operations.jsonl").exists())

    def test_verification_requires_an_explicit_membership_list(self):
        intent, _ = self.perform()
        event = self.verification(intent)
        del event["after"]["collections"]
        with self.assertRaisesRegex(ValueError, "complete memberships"):
            review.record_event(self.path, event)

    def test_execution_stage_updates_after_move_and_restoration(self):
        self.perform()
        self.assertEqual(review.read_session(self.path)["status"], "moves_complete")
        restore = review.prepare_restore(self.session, review.read_journal(self.path),
                                         self.fake.snapshot(self.session), ["R0001"])["items"][0]
        intent = self.intent(restore, "phase-restore", "restore")
        review.record_event(self.path, intent)
        self.assertEqual(review.read_session(self.path)["status"], "execution_in_progress")
        self.fake.restore("ABCD2345", restore)
        review.record_event(self.path, self.verification(intent))
        self.assertEqual(review.read_session(self.path)["status"], "restored")
        self.imported()
        self.assertEqual(review.read_session(self.path)["status"], "restored")

    def test_default_preview_removes_all_original_categories(self):
        row = self.plan()["items"][0]
        self.assertEqual(row["remove_collection_ids"], [10, 12])
        self.assertEqual(row["expected_collection_ids"], [99])
        self.assertTrue(self.plan()["authorization_required"])
        self.assertEqual(self.fake.calls, [])

    def test_changed_library_or_target_is_rejected(self):
        for target in (
            {"library_id": 2, "id": 99, "path": "!Rubbish", "parent_id": None},
            {"library_id": 1, "id": 99, "path": "Topic/!Rubbish", "parent_id": 10},
        ):
            snapshot = self.fake.snapshot(self.session)
            snapshot["target_collection"] = target
            with self.assertRaises(ValueError):
                review.prepare_move(self.session, self.decisions(), snapshot)

    def test_write_intent_requires_imported_human_decision_and_auth(self):
        plan = review.prepare_move(self.session, self.decisions(), self.fake.snapshot(self.session))
        intent = self.intent(plan["items"][0])
        with self.assertRaisesRegex(ValueError, "Import human"):
            review.record_event(self.path, intent)
        self.imported()
        del intent["authorization_text"]
        with self.assertRaisesRegex(ValueError, "real execution"):
            review.record_event(self.path, intent)
        self.assertEqual(self.fake.calls, [])

    def test_verified_move_keeps_children_and_original_snapshot(self):
        before = self.fake.read("ABCD2345")
        intent, verified = self.perform()
        after = self.fake.read("ABCD2345")
        self.assertEqual(verified["status"], "verified")
        self.assertEqual(after["attachment_keys"], before["attachment_keys"])
        self.assertEqual(after["note_keys"], before["note_keys"])
        self.assertEqual(after["title"], before["title"])
        self.assertEqual({row["id"] for row in intent["before_collections"]}, {10, 12})
        self.assertTrue((self.path.parent / "Rubbish" / "操作记录.md").exists())

    def test_lost_write_response_is_verified_by_read_without_retry(self):
        _, verification = self.perform(timeout=True)
        self.assertEqual(verification["status"], "verified")
        self.assertEqual(len(self.fake.calls), 1)
        journal = review.read_journal(self.path)
        self.assertEqual(journal[1]["status"], "unverified")
        self.assertEqual(journal[-1]["status"], "verified")

    def test_partial_completion_has_distinct_status(self):
        _, verification = self.perform(partial=True)
        self.assertEqual(verification["status"], "partial")

    def test_restoration_retains_later_added_memberships(self):
        self.perform()
        self.fake.items["ABCD2345"]["collections"].append({"id": 77, "path": "用户后来加入"})
        plan = review.prepare_restore(self.session, review.read_journal(self.path),
                                      self.fake.snapshot(self.session), ["R0001"])
        row = plan["items"][0]
        self.assertEqual(row["add_collection_ids"], [10, 12])
        self.assertEqual(set(row["expected_collection_ids"]), {10, 12, 77})
        intent = self.intent(row, "restore-1", "restore")
        review.record_event(self.path, intent)
        self.fake.restore(row["item_key"], row)
        verification = review.record_event(self.path, self.verification(intent))
        self.assertEqual(verification["status"], "verified")

    def test_partial_then_retry_retains_the_first_complete_source_snapshot(self):
        self.perform(partial=True, attempt="partial-1")
        self.perform(attempt="retry-2")
        plan = review.prepare_restore(self.session, review.read_journal(self.path),
                                      self.fake.snapshot(self.session), ["R0001"])
        self.assertEqual(set(plan["items"][0]["add_collection_ids"]), {10, 12})
        self.assertTrue(plan["items"][0]["remove_rubbish"])

    def test_partial_move_can_be_restored(self):
        self.perform(partial=True)
        plan = review.prepare_restore(self.session, review.read_journal(self.path),
                                      self.fake.snapshot(self.session), ["R0001"])
        self.assertEqual(len(plan["items"]), 1)
        self.assertEqual(set(plan["items"][0]["expected_collection_ids"]), {10, 12})

    def test_missing_original_collection_blocks_restore(self):
        self.perform()
        snapshot = self.fake.snapshot(self.session)
        snapshot["available_collection_ids"].remove(12)
        with self.assertRaisesRegex(ValueError, "collection"):
            review.prepare_restore(self.session, review.read_journal(self.path), snapshot, ["R0001"])

    def test_restore_of_originally_unfiled_item_can_leave_no_membership(self):
        data = sample()
        data["scope"].update(mode="library", collection_ids=[])
        data["items"][0]["collections"] = []
        path = review.create_run(data, self.project, "unfiled-test")
        session = review.read_session(path)
        fake = FakeZotero(session)
        decisions = self.decisions()
        decisions["run_id"] = session["run_id"]
        review.write_json(path.parent / "decisions.json", decisions)
        plan = review.prepare_move(session, decisions, fake.snapshot(session))
        intent = self.intent(plan["items"][0], "unfiled-move")
        review.record_event(path, intent)
        fake.move("ABCD2345")
        review.record_event(path, dict(library_id=1, item_key="ABCD2345", operation="move",
                                     phase="verification", attempt_id="unfiled-move", after=fake.read("ABCD2345")))
        restore = review.prepare_restore(session, review.read_journal(path), fake.snapshot(session), ["R0001"])["items"][0]
        self.assertEqual(restore["expected_collection_ids"], [])
        review.record_event(path, self.intent(restore, "unfiled-restore", "restore"))

    def test_association_conflict_is_not_reported_as_success(self):
        intent, _ = self.perform()
        self.fake.items["ABCD2345"]["note_keys"] = []
        verification = review.record_event(self.path, self.verification(intent))
        self.assertEqual(verification["status"], "conflict")

    def test_verification_rejects_other_library(self):
        intent, _ = self.perform()
        event = self.verification(intent)
        event["after"]["library_id"] = 2
        with self.assertRaises(ValueError):
            review.record_event(self.path, event)

    def test_update_keeps_stable_numbers_and_rejects_profile_change(self):
        data = sample()
        data["items"].reverse()
        updated = review.normalize_input(data, self.session)
        self.assertEqual({row["item_key"]: row["record_id"] for row in updated["items"]},
                         {row["item_key"]: row["record_id"] for row in self.session["items"]})
        data["profile"]["research_direction"] = "另一个方向"
        with self.assertRaisesRegex(ValueError, "new run"):
            review.normalize_input(data, self.session)

    def test_page_escapes_special_titles_and_csv_formula_cells(self):
        session = copy.deepcopy(self.session)
        session["items"][0]["title"] = '</script><script>window.unwanted=true</script>中文'
        session["items"][1]["title"] = "=2+2"
        review.write_json(self.path, session)
        review.render(self.path)
        html = (self.path.parent / "review.html").read_text(encoding="utf-8")
        self.assertNotIn("</script><script>window.unwanted", html)
        with (self.path.parent / "scores.csv").open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.reader(file))
        self.assertEqual(rows[2][1], "'=2+2")

    def test_run_id_cannot_escape_project_or_overwrite_existing_run(self):
        with self.assertRaises(ValueError):
            review.create_run(sample(), self.project, "../escape")
        with self.assertRaises(FileExistsError):
            review.create_run(sample(), self.project, "fictional-test")

    def test_private_results_are_ignored_in_calling_git_project(self):
        try:
            subprocess.run(["git", "init", "-q", str(self.project)], check=True, capture_output=True)
        except FileNotFoundError:
            self.skipTest("Git not installed")
        result = subprocess.run(["git", "-C", str(self.project), "check-ignore", str(self.path)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
