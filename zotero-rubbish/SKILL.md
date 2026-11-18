---
name: zotero-rubbish
description: Score Zotero literature against a research profile supplied for this invocation, guide human reading through a local review page, and move only explicitly approved items out of their original collections into a recoverable Rubbish collection. Use for research-fit screening and user-directed quarantine or restoration.
---

# Zotero Rubbish

Support a small human-in-the-loop workflow. Research-fit scores guide reading;
the human decides what belongs in Rubbish. Preserve the same Zotero parent item,
PDFs, notes, annotations, and reading records.

## Intake: before each invocation

Obtain the research direction, current research question, and the user's profile
(research stage, method background, and desired help from the papers).
Use information explicitly supplied in this invocation. For a resumed run,
show the saved profile and require the user to explicitly confirm using it.
Do not silently substitute memory, an old profile, or a previous run's scores.
If the user changes the profile or scope, create a new run.

Resolve the intended library and either all its literature or a named collection
by full path. Scope is mandatory; do not silently choose the whole library.
Include subcollections by default and say so. Save results under the calling
project, not beside installed skill source files. If no project is available,
ask for the output project. The user may explicitly choose this repository as
the output project; local run data stays ignored.

## Score and stop for human reading

1. Discover available Zotero interfaces and their current schemas. Prefer the
   existing llm-for-zotero MCP for supported reads and membership writes.
   Tool presence alone does not prove connectivity or write support.
2. Enumerate the complete requested scope with pagination and record coverage.
   Resolve attachments/notes to literature parents; deduplicate the same
   library ID + item key across collections. Do not merge different Zotero
   records just because their DOI or title matches.
3. Exclude trash and items belonging to top-level Rubbish or its descendants
   by default. Report skipped records. Explicit Rubbish restoration uses the
   restoration workflow, not ordinary screening.
4. Read metadata and abstracts first. Read targeted body passages when needed;
   do not claim to have read full texts from titles, abstracts, or old notes.
   Use a single integer 0–5 research-fit score with a brief rationale and an
   evidence locator. Judge direction fit, method applicability, and help for
   the user's current stage together; no extra weighted rubric is required.
   Mark genuinely insufficient evidence with null, not zero.
5. Read [references/local-workflow.md](references/local-workflow.md) to create
   the local session, CSV and offline reading page. Intermediate incomplete
   inventories may be checkpointed but must be labelled incomplete.
6. Present the result directory, coverage, score rationale, and page. Ask the
   user to choose and read papers, then export decisions. **End the turn here
   and wait for human input.** Do not schedule polling, keep waiting in a loop,
   create Rubbish, write notes/tags, or move papers because of low scores.

Score anchors: 0 clearly outside the requested research; 1 low fit; 2 potentially
limited help; 3 relevant and usable; 4 highly relevant; 5 directly advances the
current question. A score is a reading-priority judgment, not a measured quality
metric. Explain any title-only provisional judgment and its missing evidence.

## Resume after reading

Import the human's decision file from the run directory or Downloads. The
helper locates the exact batch filename and the newest matching browser copy;
if it is absent or ambiguous, ask only for the saved file location. The human
can also specify stable record numbers. Convert those to exact identities in
this session, record the actual human reading confirmation, and use the same
decision validation as an exported file.

Decisions are pending, keep, defer, or rubbish. Opening a link and AI reading
are not evidence that the human read the paper. The page requires a human
reading confirmation for rubbish decisions. If the reason is merely "I do not
understand it yet", propose defer and ask the human to resolve that judgment;
do not turn lack of understanding into rejection.

Importing or exporting decisions grants no execution authority. Read
[references/zotero-operations.md](references/zotero-operations.md) before
preparing any membership change. Show a concrete preview of the papers, their
current original collections, and target Rubbish.

- If the user has only saved/exported decisions, ask whether to execute this
  preview, then stop and wait.
- If the user has explicitly instructed you to move the identified papers
  using this run's decisions, and the removal rule is clear, the instruction
  is sufficient. Show the preview and continue without redundant confirmation.
- Default removal rule: remove **all original collection memberships**, even
  when the screening scope was a single collection. State this in the preview.
  An explicit user exception takes precedence and must be handled as a
  separately recorded plan; the bundled default preview is for all-source moves.

## Execute, verify, and restore

Only membership changes and, when required by the approved move, creation of a
same-library top-level Rubbish are in scope. Never delete/trash items, recreate
references, move PDF files, rename theme collections, modify notes or annotations,
or write Zotero's database directly.

Re-read identities, current memberships, and child associations immediately
before execution. Save the complete source snapshot and genuine user
authorization to the durable journal **before** invoking a write tool.
If the local journal cannot be saved, stop before writing to Zotero.
Execute the supported move, save actual receipts/action IDs, and independently
verify that only the intended memberships changed.

A timeout is an unknown outcome until re-read. Query before retrying; never
repeat an ambiguous write blindly. Report verified, partial, unverified and
conflicting states separately and checkpoint them for a later invocation.
If Zotero is unreachable, preserve local progress and name the missing
capability; do not launch Zotero or change plugin settings unasked.

For a human-requested restoration, use this run's journal, re-read current
state, preview the exact additions/removals and obtain applicable authorization.
Add back removed original memberships before removing Rubbish that this workflow
added. Preserve later user-added memberships and child associations. Missing
original collections require the user's decision; do not invent replacements.
Keep results and operation records locally; do not copy PDFs or publish library
inventories, profiles, decisions, or run outputs.
