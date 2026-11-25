# project-recon.lock

JSON file in the target repository root. It lets the skill regenerate the handbook without re-reading the whole project.

## Schema

```json
{
  "lock_version": 1,
  "skill_version": "1.0.0",
  "generated_at": "2026-11-25T17:00:00Z",
  "commit": "a1b2c3d…",           // git HEAD at generation, or null
  "dirty": false,                  // working tree had uncommitted changes
  "title": "Acme API Boilerplate",
  "subtitle": "Developer handbook",
  "excluded_paths": ["package-lock.json", "tmp/**"],
  "chapters": [
    {
      "id": "ch-routing",
      "title": "Routing",
      "order": 4,
      "sources": {                 // every file this chapter was written from → content hash
        "src/router/index.ts": "<git blob sha or sha256>"
      },
      "symbols": ["sym-router", "sym-route-decorator"],   // anchors this chapter defines
      "nav_html": "<li>…</li>",
      "content_html": "<section id=\"ch-routing\" class=\"chapter\">…</section>"
    }
  ],
  "dependencies": [
    { "name": "express", "version": "4.19.2", "origin": "https://www.npmjs.com/package/express" }
  ],
  "options": { "gitignore": true }
}
```

(Comments above are explanatory only — the real file must be valid JSON.)

Hashes: use `git hash-object <file>` when in a git repo (works for uncommitted changes too), otherwise sha256 of the file contents.

## How it is used

`recon.py build` writes the lock; `recon.py changed` compares it with the working tree and prints the affected chapters and new unmapped files; `build` with fragments for only some chapters reuses `content_html` of the others; `recon.py render` rebuilds `index.html` from the lock alone. The step-by-step incremental procedure is in `SKILL.md` → "Incremental run".

Version rule: if `lock_version` differs or the major part of `skill_version` differs, `changed` prints `FULL_RUN` — do a full run.

The A–Z index is not stored; it is regenerated from the chapters' `sym-…` anchors on every build.
