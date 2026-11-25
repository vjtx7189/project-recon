---
name: project-recon
description: Reads a repository's code and documentation and builds a single-file HTML handbook (an A–Z guide) that teaches developers how to use the framework or boilerplate it contains. Use when the user asks to document, onboard onto, map, explain, or create a handbook/guide for a codebase, framework, template, or boilerplate — or to regenerate/update an existing project-recon handbook.
---

# Project Recon

Build a developer handbook for the repository you are standing in. The handbook is a single, offline HTML page with a left sidebar and chapter content, structured by the project's own architecture, with examples taken from the real code.

Audience: **humans** (developers onboarding onto the framework/boilerplate). Keep it readable for agents too: semantic HTML, stable IDs, plain text in code blocks.

Supporting files (read each when you reach the step that needs it):
- `scripts/recon.py` — stdlib-only helper: `mark`, `build`, `check`, `changed`, `render`, `cost`. Run with `python3 <skill-dir>/scripts/recon.py <cmd> --repo <target>`.
- `assets/template.html` — the page shell. `recon.py build` fills it; never redesign it per run.
- `references/chapter-guide.md` — how to pick chapters and write them, HTML conventions.
- `references/lock-format.md` — lock file schema and the incremental algorithm.
- `references/pricing.json` — model prices used for the cost report.

## Outputs (in the target repository)

| Path | What |
|---|---|
| `project-recon/index.html` | The handbook |
| `project-recon/token-costs.md` | Tokens and API-equivalent cost of the run, split into reconnaissance and generation |
| `project-recon.lock` (repo root) | State for cheap regeneration |
| `.gitignore` | Gets `project-recon/` and `project-recon.lock` appended, unless the user said otherwise |

Nothing else in the repository may be created, modified, or deleted — not even temporarily (use a scratch clone to experiment). Chapter fragments and notes go in a scratch directory outside the repo.

## Pick the mode first

1. **No `project-recon.lock`** → full run.
2. **Lock exists, user asks to regenerate/update** → incremental run (below).
3. **Lock exists, user only wants layout/template changes** → `recon.py render`. No code reading.
4. User explicitly asks for a fresh/full rebuild → full run with `build --fresh`, which ignores the old lock completely. Do not read the old handbook or lock for content.

## Full run

### 0. Start cost tracking
`recon.py mark recon --repo <target>` — before the first inventory command. It prints a run id (e.g. `recon-1a2b3c4d5e6f`); `cost` later finds this session's transcript by that id. It also records the current `git status`, so changes that existed before the run never fail `check`.

### 1. Inventory
- Record `git rev-parse HEAD` and whether the tree is dirty.
- Detect the stack from manifests (`pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, `composer.json`, `pom.xml`/`build.gradle`, `Gemfile`, …) and framework/deploy config (`Dockerfile`, CI under `.github/`, IaC, …).
- List files with `git ls-files`. Exclude dependency lockfiles, vendored and generated code, build output, binaries, large data/fixture blobs, and anything matching `.env*`, `*secret*`, `*.pem`, `*.key`.
- Measure size: `wc -l` over the included non-test source files (tests are read for examples, not counted).
- Read the existing docs first (`README*`, `docs/`, `CONTRIBUTING*`, entry-point docstrings). They give the authors' mental model; the code gives the truth. When they disagree, document the code and record the mismatch.

### 2. Plan chapters
Follow `references/chapter-guide.md`. Write the chapter list (id, title, source files) down before writing prose. Every included file should map to at least one chapter (test files → the Testing chapter). Files you deliberately leave out go to `excluded.json`, and you mention them in the final report. `build` warns about every file that is in neither.

### 3. Deep read
- **≲ 3 000 lines of included non-test source**: read it yourself.
- **Larger**: launch read-only subagents in parallel (2–4, grouped by related chapters; Explore with "very thorough", or general-purpose), each with its exact file list. Tell each to read every file in full with the Read tool (not excerpts or grep hits) and return, per module:
  - purpose;
  - public API with signatures and `path:line`;
  - configuration keys and env var names;
  - extension points with exact steps;
  - verbatim usage snippets with `path:start-end` (prefer tests);
  - gotchas and doc/code mismatches.

  Subagents return notes, not HTML. A very long report may come back as a path to a saved file — Read that file in full.
- **Their line numbers can be wrong.** `check` only catches ranges that do not exist in the file, not ranges that point at the wrong code — spot-check the citations you use (open the file at that line) before writing them.

### 4. Write chapters
`recon.py mark generate --repo <target>` right before you write the first chapter — even if deep-read subagents are still running (they are still billed to reconnaissance, because a subagent counts in the phase it was started in).
- Chapter ids look like `ch-<slug>` (`ch-routing`). Write one fragment per chapter to `<scratch>/<chapter-id>.html` (e.g. `ch-routing.html`), containing a single `<section id="<chapter-id>" class="chapter">`. Follow the template and HTML conventions in `references/chapter-guide.md`.
- **Every non-trivial claim cites its source** as `<span class="src">path:line</span>` (any element with `class="src"` is checked). Every code block has `<div class="src">from path:a-b</div>` or `derived from path`. Paths are relative to the repo root.
- **Examples come from the code.** Use quoted excerpts, or minimal usage built only from APIs that exist. Never invent functions, flags, or config keys. Tests are the best source of examples.
- When something cannot be determined from the source, say so (`<div class="callout unknown">`) instead of guessing. Put doc/code mismatches in `<div class="callout warn">`.
- Redact credentials, tokens, private hostnames/IDs and personal data (`&lt;redacted&gt;`).
- Do not write the A–Z index. `recon.py` generates it from every `id="sym-…"` anchor.
- Diagrams are **GML** inside `<figure class="graph">` (see "Graphs (GML)" in `references/chapter-guide.md`) — no ASCII art. The Architecture chapter needs at least a data-flow diagram and a components diagram.

### 5. Third-party dependencies (a chapter)
- List direct dependencies from the manifest, with versions pinned by the lockfile. Mention notable undeclared-but-imported ones (runtime-provided, transitive).
- For each one give:
  - its origin as a link (registry page such as `https://pypi.org/project/<name>/` or `https://www.npmjs.com/package/<name>`, or the homepage/repo);
  - a one-line purpose;
  - where this project uses it (`path:line`, found by grepping imports).
- Use your own knowledge first, and web search/fetch only for public library docs. **Never send repository code or contents to an external service.**
- For vendored code, state its origin when a header, license, or comment reveals it.

### 6. Cross-link
- Give every documented symbol (class, function, config key, env var, CLI command, job parameter) an anchor `id="sym-<slug>"` where it is defined. Add `data-kind="class|function|config key|env var|…"`, and add `data-name="…"` when the visible text is not a clean name. These feed the A–Z index.
- Inside code blocks, wrap the first occurrence of each anchored identifier: `<a href="#sym-…">Name</a>`. Escape all other code as HTML text.
- Link chapter and symbol mentions in prose the same way.

### 7. Build
Write into the scratch dir:
- `chapters.json`: `[{"id": "ch-…", "title": "…", "sources": ["path", "dir/*.py", …]}]` in reading order. `sources` are repo-relative paths; globs are expanded against tracked files.
- `excluded.json` (optional): `["glob", …]` for files deliberately left out.
- `dependencies.json` (optional): `[{"name", "version", "origin"}]` — stored in the lock for the record.

Then:
```
python3 <skill>/scripts/recon.py build --repo <target> --fragments <scratch> --title "<Project>" --subtitle "Developer handbook" [--fresh]
```
`build` does the following:
- renders `project-recon/index.html` with the nav and the A–Z index;
- writes `project-recon.lock` (hashes from `git hash-object`);
- updates `.gitignore` (`--no-gitignore` if the user opted out);
- prints notes when it reuses anything from the previous lock (chapters without a fragment, title, exclusions) — with `--fresh` it reuses nothing and fails on a missing fragment;
- warns about files that are in no chapter and not excluded;
- runs `check`.

### 8. Fix until `check` passes
`check` verifies:
- every `#anchor` resolves and ids are unique;
- every GML graph parses, its edges reference existing nodes, and its `url`s resolve;
- every chapter has at least one citation to an existing file;
- every cited file exists and every cited line range lies inside the file (it cannot tell whether the lines are the *right* ones);
- there are no external resources and no leftover placeholders;
- `git status` shows no changes outside the outputs that appeared since `mark recon` (OS clutter like `.DS_Store` is ignored).

Fix the fragments, never the generated HTML, and rebuild.

### 9. Costs and report
```
python3 <skill>/scripts/recon.py mark end --repo <target>
python3 <skill>/scripts/recon.py cost --repo <target>     # writes project-recon/token-costs.md
```
`cost` finds the transcript of the agent that printed the run id (main session or a subagent), adds the subagents that agent started, and prices their usage with `references/pricing.json`. A subagent counts in the phase it was started in; everything else counts by timestamp. It prints which transcript it used. If it cannot find the run id or matches no requests, it stops without writing a report — then pass `--transcript <path to the session .jsonl>` (a subagent's own transcript lives under `<session>/subagents/`). When the skill runs in the main session, other subagents of that session that run at the same time are counted too; say so in the report if that happened.

Report to the user:
- the output paths and the chapter list;
- the total cost;
- anything marked "Not determined from source";
- the doc/code mismatches you found;
- any files deliberately left out;
- that committing the lock (and/or the handbook) instead of gitignoring it lets teammates regenerate incrementally. It's their call.

## Incremental run
1. `recon.py mark recon`, then `recon.py changed --repo <target>`. This prints the affected chapters (with the changed or deleted sources) and new unmapped files. It prints `FULL_RUN` when the lock or skill version is incompatible.
2. Nothing changed → tell the user and stop.
3. Re-read only the affected sources. Decide where new files belong: an existing chapter (add them to its `sources`), a new chapter, or the exclusion list.
4. `recon.py mark generate`. Write fragments **only** for affected or new chapters, into a fresh scratch dir that holds the full `chapters.json` (and `excluded.json` if exclusions changed). `build` (without `--fresh`) reuses the cached HTML from the lock for every chapter without a fragment and lists them.
5. If a regenerated chapter dropped a `sym-…` anchor that other chapters link to, `check` reports it. Restore the anchor or regenerate the linking chapters too.
6. Continue with steps 8–9. Report which chapters were regenerated and why.

## Guardrails
- Stay inside the repository. Read outside it only the skill's own files and public library docs.
- Read-only toward project code. The only writes are the outputs above.
- Never read or quote `.env` files, secrets, keys, or credentials.
- Prefer accuracy over coverage: a shorter, correct handbook beats a long, speculative one.
