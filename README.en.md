# Zotero Rubbish Literature Screening

[中文](README.md) | English

Project website: [Leestars21/zotero-rubbish](https://github.com/Leestars21/zotero-rubbish)

Score Zotero literature against the research direction and profile you supply for
this invocation, then make your reading decisions in a local page. After your
explicit execution instruction, the AI moves approved papers out of all original
collections into **!Rubbish**, preserving the original items, PDFs, notes,
annotations, and reading records.

## When to use it

- Screen an entire library or a topic collection, including its subcollections
  by default.
- Prioritize reading for your current question, methodological background, and
  research stage.
- Quarantine papers you have read and found unsuitable, record reasons, and
  restore them later.

A simple 0–5 research-fit score includes a rationale and actual evidence.
Check existing MinerU data before scoring. **Prefer usable parsed content
matched to the paper's live identities**, reading its original abstract and
relevant body passages. A missing Zotero abstract does not prevent scoring
from a MinerU abstract or body evidence. Record abstract and body reading
separately, with source files and section or line locators.

Without usable MinerU data, fall back to the Zotero abstract and other readable
body sources. Mark insufficient evidence only when the available material
cannot support a judgment. Reuse existing parses without running MinerU or
backfilling abstracts. Low scores do not automatically move papers. Papers
you do not understand yet can be deferred.

## The reading page

No new plugin or permanent service is needed. Open the generated `review.html`:

1. Search, sort, and select papers to read; record numbers remain stable.
2. Follow links to Zotero items or their PDFs.
3. Mark keep, defer, or move to !Rubbish, individually or in a batch, with optional reasons.
4. Confirm you have read proposed rejections and export the decisions together.
5. Return to the AI for a concrete preview. Collection changes require your
   explicit execution instruction.

One exported file submits the decisions without copying paper titles repeatedly.
For separate reading sessions, export progress and import it next time. Save
before closing; the page does not rely on automatic saving.

**Removal rule:** even when screening one collection, the default removes all
original memberships from approved papers, leaving only !Rubbish. The preview
lists those memberships. Explicitly request any memberships you want to retain
before execution. PDFs and notes stay in Zotero; they are not copied into the
results directory.

## Dependencies

- Codex or another AI client that can load `SKILL.md` and work with local files.
- Zotero Desktop and an existing integration that can read papers and
  memberships, create collections, and change memberships. llm-for-zotero MCP
  is preferred; a read-only connection cannot perform moves.
- Python 3.10+. Local page and record utilities use only the standard library.
- A modern browser supporting local HTML and file download/upload.

Live library moves have not been tested. Initial validation covers synthetic
library workflows, local records, and browser interactions. Actual runs
recheck connectivity, capabilities, and item state. When the connection is
unavailable, progress is retained and unfinished steps are identified.

## Installation

### Ask Codex to install

Give Codex this prompt:

    Install zotero-rubbish from https://github.com/Leestars21/zotero-rubbish into my Codex skills directory, preserve existing content, and verify the installation.

### Install manually

Download or clone the repository and copy its inner `zotero-rubbish/` folder
into `$HOME/.codex/skills/`, or `%USERPROFILE%\.codex\skills\` on Windows.
The installed folder should contain `SKILL.md` directly.

Windows PowerShell example, when the same skill is not already installed:

    git clone https://github.com/Leestars21/zotero-rubbish
    Copy-Item -Recurse .\zotero-rubbish\zotero-rubbish "$env:USERPROFILE\.codex\skills\zotero-rubbish"

Start a new Codex session to check that `$zotero-rubbish` is available.
For local development, a directory junction may point to the inner skill folder
so edits reach the installed entry. Handle its target before moving the repository.

## Usage examples

Supply the direction and profile for the first screening:

    Use $zotero-rubbish.
    My direction is heat conduction in heterogeneous materials. I want to learn
    reproducible numerical methods. I am a graduate student starting this topic,
    with basic differential equations and numerical computing knowledge.
    I want clear derivations and reproducible examples.
    Screen the "Heat Conduction" collection including subcollections, and save
    results in this project. Wait for me to choose and read papers after scoring.

Resume the same batch:

    Continue batch <run ID>. I explicitly confirm using its saved research profile.
    I have exported my decisions. Please check them and show the move preview.

Execute after checking:

    Execute this batch's read-confirmed decisions. Move approved papers out of
    all original collections into !Rubbish.

Restore later:

    Use $zotero-rubbish for batch <run ID>, using its saved profile as I confirm.
    Restore R0001 to its recorded original collections, keeping later memberships.

## Local results and restoration

Results live in the calling project's `.zotero-rubbish/runs/<run ID>/`:
profile, scores, reading page, decisions, previews, and recoverable membership
records. Operations produce `Rubbish/操作记录.md`, with partial and unverified
states shown separately.

All original memberships are saved before a move and checked afterward.
Timeouts trigger verification before resuming. Restoration adds back original
memberships before removing !Rubbish that this workflow added, preserving later
user-added memberships. If an original collection was deleted, you choose the
restoration target.

Local results carry Git ignore rules and are not public repository content.
Do not submit real profiles, inventories, decisions, full PDFs, or Zotero
databases in public feedback.

## Validation and feedback

Run the local workflow tests with fictional data:

    python -m unittest discover -s tests -v

If Codex skill-creator is installed, its `quick_validate.py` can check the
inner `zotero-rubbish/` skill folder. Browser checks cover searching, stable
numbers after sorting, batch decisions, reading confirmation, export/reimport,
and desktop and narrow-screen layouts.
Regression tests also cover accepting MinerU abstract/body scores without a
Zotero abstract and preserving source locators in sessions and reading pages.
The AI matches and reads caches through existing interfaces.

Report problems or suggestions through
[Issues](https://github.com/Leestars21/zotero-rubbish/issues), or submit a PR.
Include your operating system, AI client, Zotero integration, workflow stage,
error, and expected behavior. Use fictional or anonymized examples; do not
include secrets, private libraries, or complete paper attachments.

## License

MIT License. See `LICENSE`.
