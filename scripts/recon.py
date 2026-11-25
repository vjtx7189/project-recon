#!/usr/bin/env python3
"""project-recon helper: assemble the handbook, write the lock, self-check, diff.

Stdlib only. Run from anywhere; pass --repo for the target repository.

  recon.py build   --repo R --fragments DIR [--fresh] [--title T] [--subtitle S] [--no-gitignore]
  recon.py check   --repo R
  recon.py changed --repo R              # incremental: which chapters need regenerating
  recon.py render  --repo R              # re-render index.html from the lock only
  recon.py mark recon|generate|end --repo R [--at ISO]   # record phase boundaries for cost tracking
  recon.py cost    --repo R [--transcript F.jsonl]       # write project-recon/token-costs.md

Fragments directory layout (written by the model):
  DIR/chapters.json     [{"id": "ch-x", "title": "X", "sources": ["src/a.py", "src/pkg/*.py", ...]}, ...]
                        (order = reading order; sources may use globs)
  DIR/ch-x.html         one <section id="ch-x" class="chapter">…</section> per chapter (file name = section id)
  DIR/excluded.json     optional: ["glob", ...] files deliberately left out of the handbook
  DIR/dependencies.json optional: [{"name", "version", "origin"}, ...] stored in the lock

Chapter id "ch-az-index" is generated automatically from every id="sym-*" anchor; do not write it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL_DIR / "assets" / "template.html"
LOCK_NAME = "project-recon.lock"
OUT_DIR = "project-recon"
LOCK_VERSION = 1
SKILL_VERSION = "1.0.0"
AZ_ID = "ch-az-index"
GITIGNORE_BLOCK = "\n# project-recon handbook\nproject-recon/\nproject-recon.lock\n"


# ---------------------------------------------------------------- helpers
def git(repo: Path, *args: str) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def file_hash(repo: Path, rel: str) -> str | None:
    p = repo / rel
    if not p.is_file():
        return None
    h = git(repo, "hash-object", rel)
    return h or hashlib.sha256(p.read_bytes()).hexdigest()


class Outline(HTMLParser):
    """Collects h2/h3 with ids per section, all ids, all #hrefs, sym anchors."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.hrefs: list[str] = []
        self.sections: list[dict] = []
        self.syms: list[dict] = []
        self._cur: dict | None = None
        self._cap: dict | None = None
        self._depth = 0
        self._in_code = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "a" and (a.get("href") or "").startswith("#"):
            self.hrefs.append(a["href"][1:])
        if tag == "section" and a.get("id"):
            self._cur = {"id": a["id"], "title": "", "subs": []}
            self.sections.append(self._cur)
        if self._cap is not None:
            self._depth += 1
            if tag == "code" and self._cap["tag"] == "sym" and not self._cap["code"]:
                self._in_code = True
            return
        if tag in ("h2", "h3") and self._cur is not None:
            self._cap = {"tag": tag, "id": a.get("id"), "text": ""}
            self._depth = 1
        elif (a.get("id") or "").startswith("sym-"):
            self._cap = {"tag": "sym", "id": a["id"], "text": "", "code": "", "name": a.get("data-name", ""),
                         "kind": a.get("data-kind", ""), "chapter": self._cur["id"] if self._cur else ""}
            self._depth = 1

    def handle_endtag(self, tag):
        if self._cap is None:
            return
        if tag == "code":
            self._in_code = False
        self._depth -= 1
        if self._depth > 0:
            return
        c, self._cap = self._cap, None
        text = re.sub(r"\s+", " ", c["text"]).strip()
        if c["tag"] == "h2" and self._cur is not None and not self._cur["title"]:
            self._cur["title"] = text
        elif c["tag"] == "h3" and c["id"] and self._cur is not None:
            self._cur["subs"].append((c["id"], text))
        elif c["tag"] == "sym":
            c["text"] = text
            self.syms.append(c)

    def handle_data(self, data):
        if self._cap is not None and self._depth >= 1:
            self._cap["text"] += data
            if self._in_code:
                self._cap["code"] += data


def outline(fragment: str) -> Outline:
    o = Outline()
    o.feed(fragment)
    return o


def nav_for(fragment: str) -> str:
    o = outline(fragment)
    out = []
    for s in o.sections:
        subs = "".join(f'<li><a href="#{html.escape(i)}">{html.escape(t)}</a></li>' for i, t in s["subs"])
        out.append(f'<li><a href="#{html.escape(s["id"])}">{html.escape(s["title"])}</a>'
                   + (f"<ul>{subs}</ul>" if subs else "") + "</li>")
    return "\n".join(out)


def sym_label(s: dict) -> str:
    """data-name wins; else the first <code> in the anchor element, cut at '('; else its text."""
    if s.get("name"):
        return s["name"]
    text = re.sub(r"\s+", " ", s.get("code") or s["text"]).strip()
    return text.split("(")[0].strip() or text


def az_section(chapters: list[dict], titles: dict[str, str]) -> str:
    entries = []
    for ch in chapters:
        for s in outline(ch["content_html"]).syms:
            entries.append((sym_label(s), s["id"], s.get("kind", ""), ch["id"]))
    seen, uniq = set(), []
    for e in sorted(entries, key=lambda e: e[0].lower()):
        if e[1] not in seen:
            seen.add(e[1])
            uniq.append(e)
    groups: dict[str, list] = {}
    for e in uniq:
        k = e[0][:1].upper()
        groups.setdefault(k if k.isalpha() else "#", []).append(e)
    parts = [f'<section id="{AZ_ID}" class="chapter"><h2>A–Z index</h2>',
             f'<p>Every documented symbol, config key and command, alphabetically. {len(uniq)} entries.'
             f' <span class="src">generated from handbook anchors</span></p>']
    for letter in sorted(groups):
        lid = "az-" + ("sym" if letter == "#" else letter.lower())
        parts.append(f'<h4 class="az-letter" id="{lid}">{html.escape(letter)}</h4><ul class="az-list">')
        for name, sid, kind, cid in groups[letter]:
            k = f' <span class="kind">{html.escape(kind)}</span>' if kind else ""
            parts.append(f'<li><a href="#{sid}"><code>{html.escape(name)}</code></a>{k}'
                         f' <span class="kind">· <a href="#{cid}">{html.escape(titles.get(cid, cid))}</a></span></li>')
        parts.append("</ul>")
    parts.append("</section>")
    return "\n".join(parts)


def is_excluded(path: str, excluded: list[str]) -> bool:
    return (path.startswith(OUT_DIR + "/") or path in (LOCK_NAME, ".gitignore") or bool(OS_JUNK.search(path))
            or any(Path(path).match(e) or path == e or path.startswith(e.rstrip("*").rstrip("/") + "/") for e in excluded))


def tracked_files(repo: Path) -> list[str]:
    return (git(repo, "ls-files", "--cached", "--others", "--exclude-standard") or "").splitlines()


# ---------------------------------------------------------------- render
def render(repo: Path, lock: dict) -> Path:
    chapters = sorted(lock["chapters"], key=lambda c: c["order"])
    titles = {c["id"]: c["title"] for c in chapters}
    titles[AZ_ID] = "A–Z index"
    az = az_section(chapters, titles)
    body = "\n\n".join(c["content_html"] for c in chapters) + "\n\n" + az
    nav = "\n".join(c["nav_html"] for c in chapters) + "\n" + f'<li><a href="#{AZ_ID}">A–Z index</a></li>'
    tpl = re.sub(r"<!--.*?-->\s*", "", TEMPLATE.read_text(encoding="utf-8"), count=1, flags=re.S)  # drop doc comment
    commit = (lock.get("commit") or "n/a")[:10] + (" (dirty)" if lock.get("dirty") else "")
    page = (tpl.replace("{{TITLE}}", html.escape(lock["title"]))
               .replace("{{SUBTITLE}}", html.escape(lock.get("subtitle", "Developer handbook")))
               .replace("{{GENERATED_AT}}", lock["generated_at"][:16].replace("T", " "))
               .replace("{{COMMIT}}", html.escape(commit))
               .replace("{{NAV}}", nav)
               .replace("{{CONTENT}}", body))
    out = repo / OUT_DIR / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


# ---------------------------------------------------------------- check
def check(repo: Path) -> int:
    page = (repo / OUT_DIR / "index.html").read_text(encoding="utf-8")
    o = outline(page)
    problems = []
    dup = {i for i in o.ids if o.ids.count(i) > 1}
    if dup:
        problems.append(f"duplicate ids: {sorted(dup)[:20]}")
    missing = sorted({h for h in o.hrefs if h and h not in set(o.ids)})
    if missing:
        problems.append(f"broken #anchors ({len(missing)}): {missing[:20]}")
    if re.search(r'<script[^>]+src=|<link[^>]+href=["\']https?:|<img[^>]+src=["\']https?:|@import', page):
        problems.append("external resource reference found")
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    if any("<script" in sc for sc in scripts):
        problems.append("inline script contains a '<script' sequence; it would break the page")
    if re.search(r"\{\{[A-Z_]+\}\}", page):
        problems.append("unreplaced {{PLACEHOLDER}}")
    # every GML graph must parse, reference existing nodes, and link to existing anchors
    for n_g, gml in enumerate(re.findall(r'<script type="text/x-gml"[^>]*>(.*?)</script>', page, re.S), 1):
        toks = re.findall(r'"(?:[^"\\]|\\.)*"|\[|\]|[^\s\[\]"]+', gml)
        if toks.count("[") != toks.count("]") or not gml.strip().startswith("graph"):
            problems.append(f"graph #{n_g}: malformed GML (bracket mismatch or no 'graph [')")
            continue
        node_ids = set(re.findall(r"node\s*\[[^\]]*?\bid\s+(\"[^\"]*\"|\S+)", gml))
        for s_, t_ in re.findall(r"edge\s*\[[^\]]*?\bsource\s+(\"[^\"]*\"|\S+)[^\]]*?\btarget\s+(\"[^\"]*\"|\S+)", gml):
            if s_ not in node_ids or t_ not in node_ids:
                problems.append(f"graph #{n_g}: edge {s_}->{t_} references a missing node")
                break
        for u in re.findall(r'\burl\s+"#([^"]+)"', gml):
            if u not in set(o.ids):
                problems.append(f"graph #{n_g}: url #{u} has no matching id")
    # citations: any element with class "src". Each cited file must exist and each line range must fit the file.
    # (This proves the citation is plausible, not that the lines say what the prose claims.)
    bad: list[str] = []
    line_counts: dict[str, int] = {}

    def valid_citations(fragment: str) -> int:
        good = 0
        for _tag, cite in re.findall(r'<(\w+)[^>]*\bclass="src"[^>]*>(.*?)</\1>', fragment, re.S):
            for path, a, b in re.findall(r"([\w./\-]+\.[\w]+|[\w./\-]+/[\w.\-]+)(?::(\d+)(?:-(\d+))?)?",
                                         re.sub(r"<[^>]+>", "", html.unescape(cite))):
                f = repo / path
                if "/" not in path and not f.exists():
                    continue  # plain words in prose
                if f.is_dir():
                    good += 1  # directory or glob citation such as .github/workflows/*.yml
                    continue
                if not f.is_file():
                    bad.append(path)
                    continue
                if a:
                    if path not in line_counts:
                        line_counts[path] = sum(1 for _ in f.open(encoding="utf-8", errors="replace"))
                    if int(b or a) > line_counts[path] or (b and int(b) < int(a)):
                        bad.append(f"{path}:{a}{'-' + b if b else ''} (file has {line_counts[path]} lines)")
                        continue
                good += 1
        return good

    for s in o.sections:
        if s["id"] == AZ_ID:
            continue
        m = re.search(rf'<section id="{re.escape(s["id"])}".*?</section>', page, re.S)
        if m and not valid_citations(m.group(0)):
            problems.append(f"chapter without a valid source citation: {s['id']}")
    if bad:
        problems.append(f"invalid citations ({len(set(bad))}): {sorted(set(bad))[:25]}")
    # repo changes: only new ones count (baseline taken at `mark recon`); OS clutter like .DS_Store is ignored
    baseline = set(load_run(repo).get("baseline_status", []))
    status = (git(repo, "status", "--porcelain") or "").splitlines()
    stray = [ln for ln in status if ln not in baseline and not OS_JUNK.search(ln[3:].strip())
             and not re.search(r"(project-recon/|project-recon\.lock|\.gitignore)$", ln.strip())]
    if stray:
        problems.append(f"repo changed outside the outputs during this run: {stray[:10]}")
    pre = [ln for ln in status if ln in baseline and not OS_JUNK.search(ln[3:].strip())
           and not re.search(r"(project-recon/|project-recon\.lock|\.gitignore)$", ln.strip())]
    if pre:
        print(f"note: changes that existed before the run (ignored): {pre[:10]}")
    print(f"sections={len(o.sections)} ids={len(o.ids)} links={len(o.hrefs)} symbols={len(o.syms)}")
    for p in problems:
        print("FAIL:", p)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


# ---------------------------------------------------------------- build
def build(args) -> int:
    repo = Path(args.repo).resolve()
    frag = Path(args.fragments).resolve()
    manifest = json.loads((frag / "chapters.json").read_text(encoding="utf-8"))
    import fnmatch
    lock_path = repo / LOCK_NAME
    old = {} if args.fresh or not lock_path.exists() else json.loads(lock_path.read_text(encoding="utf-8"))
    old_ch = {c["id"]: c for c in old.get("chapters", [])}
    files = tracked_files(repo)
    reused: list[str] = []

    chapters = []
    for order, ch in enumerate(manifest):
        if not re.fullmatch(r"ch-[a-z0-9-]+", ch["id"]):
            print(f"chapter id {ch['id']!r} must look like ch-<slug> (it is also the <section id> and the fragment name)",
                  file=sys.stderr)
            return 2
        f = frag / f"{ch['id']}.html"
        if f.exists():
            content = f.read_text(encoding="utf-8").strip()
            if f'<section id="{ch["id"]}"' not in content:
                print(f"{f.name}: must contain <section id=\"{ch['id']}\" class=\"chapter\">", file=sys.stderr)
                return 2
        elif ch["id"] in old_ch:  # incremental: reuse cached chapter
            content = old_ch[ch["id"]]["content_html"]
            reused.append(ch["id"])
        else:
            print(f"missing fragment {f}" + ("" if args.fresh else " and no cached copy in the lock"), file=sys.stderr)
            return 2
        paths: list[str] = []
        for src in ch.get("sources", []):  # globs allowed
            if any(c in src for c in "*?["):
                hits = [x for x in files if fnmatch.fnmatchcase(x, src)]
                if not hits:
                    print(f"warning: {ch['id']}: source glob {src!r} matches no file", file=sys.stderr)
                paths += hits
            else:
                paths.append(src)
        sources = {s: file_hash(repo, s) for s in dict.fromkeys(paths)}
        gone = [s for s, h in sources.items() if h is None]
        if gone:
            print(f"warning: {ch['id']} lists missing files: {gone}", file=sys.stderr)
        chapters.append({
            "id": ch["id"], "title": ch["title"], "order": order,
            "sources": {s: h for s, h in sources.items() if h},
            "symbols": [s["id"] for s in outline(content).syms],
            "nav_html": nav_for(content),
            "content_html": content,
        })

    lock = {
        "lock_version": LOCK_VERSION,
        "skill_version": SKILL_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "commit": git(repo, "rev-parse", "HEAD"),
        "dirty": bool(git(repo, "status", "--porcelain", "--untracked-files=no")),
        "title": args.title or old.get("title") or repo.name,
        "subtitle": args.subtitle or old.get("subtitle") or "Developer handbook",
        "excluded_paths": manifest_excluded(frag, old),
        "chapters": chapters,
        "dependencies": json.loads((frag / "dependencies.json").read_text()) if (frag / "dependencies.json").exists() else old.get("dependencies", []),
        "options": {"gitignore": not args.no_gitignore},
    }
    if reused:
        print(f"note: reused cached HTML from the previous lock for: {reused}")
    for key, given in (("title", args.title), ("excluded_paths", (frag / "excluded.json").exists()),
                       ("dependencies", (frag / "dependencies.json").exists())):
        if not given and old.get(key):
            print(f"note: {key} taken from the previous lock")
    covered = {s for c in chapters for s in c["sources"]}
    unmapped = [x for x in files if x not in covered and not is_excluded(x, lock["excluded_paths"])]
    if unmapped:
        print(f"warning: {len(unmapped)} file(s) are in no chapter's sources and not excluded: {unmapped[:30]}")
    out = render(repo, lock)
    lock_path.write_text(json.dumps(lock, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if not args.no_gitignore:
        gi = repo / ".gitignore"
        cur = gi.read_text(encoding="utf-8") if gi.exists() else ""
        if not re.search(r"^/?project-recon/?$", cur, re.M):
            gi.write_text(cur.rstrip("\n") + "\n" + GITIGNORE_BLOCK if cur else GITIGNORE_BLOCK.lstrip(), encoding="utf-8")
    print(f"wrote {out} and {lock_path}")
    return check(repo)


def manifest_excluded(frag: Path, old: dict) -> list:
    p = frag / "excluded.json"
    return json.loads(p.read_text()) if p.exists() else old.get("excluded_paths", [])


# ---------------------------------------------------------------- changed
def changed(repo: Path) -> int:
    lock = json.loads((repo / LOCK_NAME).read_text(encoding="utf-8"))
    if lock.get("lock_version") != LOCK_VERSION or lock.get("skill_version", "0").split(".")[0] != SKILL_VERSION.split(".")[0]:
        print("FULL_RUN: lock/skill version mismatch")
        return 0
    known: set[str] = set()
    affected: dict[str, list[str]] = {}
    for ch in lock["chapters"]:
        for src, h in ch["sources"].items():
            known.add(src)
            now = file_hash(repo, src)
            if now != h:
                affected.setdefault(ch["id"], []).append(f"{src} ({'deleted' if now is None else 'changed'})")
    excluded = lock.get("excluded_paths", [])
    new = sorted(p for p in tracked_files(repo) if p not in known and not is_excluded(p, excluded))
    print(json.dumps({"commit_in_lock": lock.get("commit"), "commit_now": git(repo, "rev-parse", "HEAD"),
                      "affected_chapters": affected, "new_unmapped_files": new}, indent=1))
    return 0


# ---------------------------------------------------------------- token costs
PHASES_FILE = ".recon-phases.json"
PHASE_LABELS = {"recon": "Reconnaissance (inventory + deep read)",
                "generate": "Handbook generation (chapters, render, lock, checks)"}


OS_JUNK = re.compile(r"(^|/)(\.DS_Store|Thumbs\.db|desktop\.ini|\._[^/]*)$")


def load_run(repo: Path) -> dict:
    p = repo / OUT_DIR / PHASES_FILE
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    return {"marks": data} if isinstance(data, list) else data  # list = older format


def mark(repo: Path, phase: str, at: str | None) -> int:
    import secrets
    out = repo / OUT_DIR
    out.mkdir(exist_ok=True)
    run = load_run(repo)
    if phase == "recon" or not run.get("run_id"):  # a new run starts: forget earlier runs
        run = {"run_id": "recon-" + secrets.token_hex(6),
               # changes that already exist are not the skill's doing; check ignores them
               "baseline_status": (git(repo, "status", "--porcelain") or "").splitlines(),
               "marks": []}
    ts = at or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    run["marks"].append({"phase": phase, "at": ts})
    (out / PHASES_FILE).write_text(json.dumps(run, indent=1) + "\n")
    # printing the run id puts it into this session's transcript; `cost` finds the session by it
    print(f"marked {phase} at {ts} · project-recon run id: {run['run_id']}")
    return 0


def _parse_ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def _all_transcripts(since: dt.datetime | None) -> list[Path]:
    import glob
    import os
    roots = [os.environ["CLAUDE_CONFIG_DIR"]] if os.environ.get("CLAUDE_CONFIG_DIR") else []
    roots += glob.glob(os.path.expanduser("~/.claude*"))
    pats = [os.path.join(r, "projects", "*", "*.jsonl") for r in roots]
    pats += [os.path.join(r, "projects", "*", "*", "subagents", "*.jsonl") for r in roots]
    files = {Path(f).resolve() for pat in pats for f in glob.glob(pat)}
    cutoff = since.timestamp() - 60 if since else 0
    return [f for f in files if f.stat().st_mtime >= cutoff]


def _contains(path: Path, needle: str) -> bool:
    with path.open(encoding="utf-8", errors="replace") as fh:
        return any(needle in line for line in fh)


def session_files(runner: Path) -> list[tuple[Path, str]]:
    """The agent that ran the skill plus every subagent it (transitively) started."""
    runner = runner.resolve()
    if runner.parent.name == "subagents":
        sub_dir = runner.parent
    else:
        sub_dir = runner.with_suffix("") / "subagents"
    children = {}
    if sub_dir.is_dir():
        for f in sub_dir.glob("*.jsonl"):
            meta = f.with_suffix(".meta.json")
            try:
                tool_id = json.loads(meta.read_text()).get("toolUseId") if meta.exists() else None
            except (OSError, json.JSONDecodeError):
                tool_id = None
            if tool_id:
                children[f.resolve()] = tool_id
    included = [runner]
    frontier = [runner]
    while frontier:
        cur = frontier.pop()
        text = cur.read_text(encoding="utf-8", errors="replace")
        for f, tool_id in children.items():
            if f not in included and tool_id in text:
                included.append(f)
                frontier.append(f)
    return [(f, "runner" if f == runner else f"subagent:{f.stem}") for f in included]


def find_session(repo: Path, explicit: str | None, run: dict, marks: list) -> tuple[list[tuple[Path, str]], str]:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            raise SystemExit(f"transcript {p} does not exist")
        return session_files(p), f"{p} (given with --transcript)"
    run_id = run.get("run_id")
    if not run_id:
        raise SystemExit("this run has no run id (marks written by an older version); pass --transcript <session .jsonl>")
    since = marks[0]["at"] if marks else None
    hits = [f for f in _all_transcripts(since) if _contains(f, run_id)]
    if not hits:
        raise SystemExit(f"no Claude Code transcript mentions run id {run_id}; pass --transcript <session .jsonl>")
    # the skill ran in a subagent if a subagent transcript holds the id (a parent sees at most a summary);
    # with several candidates, the one that recorded it earliest is the runner
    def first_seen(f: Path) -> str:
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if run_id in line:
                    try:
                        return json.loads(line).get("timestamp", "")
                    except json.JSONDecodeError:
                        return ""
        return ""
    subs = [f for f in hits if f.parent.name == "subagents"]
    runner = min(subs or hits, key=first_seen)
    return session_files(runner), f"{runner} (found by run id {run_id})"


def usage_records(files: list[tuple[Path, str]]):
    """Yield (timestamp, model, usage, source) for each API request in the given transcripts, deduplicated."""
    seen: set[str] = set()
    for f, source in files:
        for line in f.open(encoding="utf-8"):
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = o.get("message") or {}
            if o.get("type") != "assistant" or not isinstance(msg, dict) or "usage" not in msg:
                continue
            key = msg.get("id") or o.get("requestId") or o.get("uuid")
            if key in seen:
                continue
            seen.add(key)
            yield _parse_ts(o["timestamp"]), msg.get("model", "unknown"), msg["usage"], source


def cost(repo: Path, transcript_arg: str | None) -> int:
    out = repo / OUT_DIR
    run = load_run(repo)
    if not run.get("marks"):
        print("no phase marks — run `recon.py mark recon` at the start and `mark generate` before writing", file=sys.stderr)
        return 2
    marks = sorted(({"phase": m["phase"], "at": _parse_ts(m["at"])} for m in run["marks"]), key=lambda m: m["at"])
    now = dt.datetime.now(dt.timezone.utc)
    # each mark opens a span that runs to the next mark ("end" only closes); several spans of one phase add up
    spans = [(m["phase"], m["at"], nxt["at"] if nxt else now)
             for m, nxt in zip(marks, marks[1:] + [None]) if m["phase"] != "end"]
    try:
        files, how = find_session(repo, transcript_arg, run, marks)
    except SystemExit as e:
        print(f"cost: {e}", file=sys.stderr)
        return 2
    print(f"cost: transcript {how}; counting {len(files)} agent transcript(s)")
    pricing = json.loads((SKILL_DIR / "references" / "pricing.json").read_text())
    wm, fast_m = pricing["cache_write_multiplier"], pricing.get("fast_mode_multiplier", 1.0)

    keys = ("requests", "input", "cache_write", "cache_read", "output")
    agg: dict = {}  # (phase, model) -> counters
    first_seen: dict[str, dt.datetime] = {}
    for ts, model, u, source in usage_records(files):
        # subagents started during reconnaissance (deep readers) count fully as reconnaissance even if they
        # outlive the phase mark; any other session/subagent usage is attributed by its own timestamp
        start = first_seen.setdefault(source, ts)
        start_phase = next((p for p, a, b in spans if a <= start < b), None) if source != "runner" else None
        phase = "recon" if start_phase == "recon" else next((p for p, a, b in spans if a <= ts < b), None)
        if phase is None:
            continue
        c = agg.setdefault((phase, model), {**{k: 0 for k in keys}, "usd": 0.0, "priced": True, "subagent_requests": 0})
        cw = u.get("cache_creation") or {}
        w5 = cw.get("ephemeral_5m_input_tokens", 0)
        w1 = cw.get("ephemeral_1h_input_tokens", 0)
        if not cw:
            w5 = u.get("cache_creation_input_tokens", 0)
        c["requests"] += 1
        c["subagent_requests"] += source != "runner"
        c["input"] += u.get("input_tokens", 0)
        c["cache_write"] += w5 + w1
        c["cache_read"] += u.get("cache_read_input_tokens", 0)
        c["output"] += u.get("output_tokens", 0)
        price = pricing["models"].get(model)
        if not price:
            c["priced"] = False
            continue
        usd = (u.get("input_tokens", 0) * price["input"] + w5 * price["input"] * wm["5m"]
               + w1 * price["input"] * wm["1h"] + u.get("cache_read_input_tokens", 0) * price["cache_read"]
               + u.get("output_tokens", 0) * price["output"]) / 1e6
        c["usd"] += usd * (fast_m if u.get("speed") == "fast" else 1.0)

    def fmt(n: int) -> str:
        return f"{n:,}".replace(",", " ")

    lines = ["# project-recon — token costs", "",
             f"Repository: `{repo.name}` · commit `{(git(repo, 'rev-parse', '--short', 'HEAD') or 'n/a')}` · "
             f"generated {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC", "",
             "Token counts come from the Claude Code session transcript (main session + subagents), "
             "split by the phase marks the skill recorded. Dollar amounts are **API list-price equivalents** "
             f"(prices as of {pricing['as_of']}, `references/pricing.json`); on a subscription plan "
             "you are not billed per token.", ""]
    totals = {k: 0 for k in keys} | {"usd": 0.0}
    for phase in dict.fromkeys(p for p, _, _ in spans):
        rows = [(m, c) for (p, m), c in agg.items() if p == phase]
        mine = [(a, b) for p, a, b in spans if p == phase]
        dur = int(sum((b - a).total_seconds() for a, b in mine) // 60)
        when = ", ".join(f"{a.strftime('%H:%M')}–{b.strftime('%H:%M')}" for a, b in mine)
        lines += [f"## {PHASE_LABELS.get(phase, phase)}", "",
                  f"{when} UTC ({dur} min)", "",
                  "| Model | Requests (subagent) | Input | Cache write | Cache read | Output | Cost (USD) |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        sub = {k: 0 for k in keys} | {"usd": 0.0}
        for m, c in sorted(rows):
            usd = f"{c['usd']:.2f}" if c["priced"] else "n/a (no price)"
            lines.append(f"| `{m}` | {c['requests']} ({c['subagent_requests']}) | {fmt(c['input'])} | {fmt(c['cache_write'])} | "
                         f"{fmt(c['cache_read'])} | {fmt(c['output'])} | {usd} |")
            for k in keys:
                sub[k] += c[k]
            sub["usd"] += c["usd"]
        lines += [f"| **Phase total** | {sub['requests']} | {fmt(sub['input'])} | {fmt(sub['cache_write'])} | "
                  f"{fmt(sub['cache_read'])} | {fmt(sub['output'])} | **{sub['usd']:.2f}** |", ""]
        for k in totals:
            totals[k] += sub[k]
    lines += ["## Total", "",
              f"- Requests: {totals['requests']}",
              f"- Tokens: input {fmt(totals['input'])} · cache write {fmt(totals['cache_write'])} · "
              f"cache read {fmt(totals['cache_read'])} · output {fmt(totals['output'])}",
              f"- **Cost: ${totals['usd']:.2f}** (API list-price equivalent)", ""]
    empty = [ph for ph in dict.fromkeys(p for p, _, _ in spans) if not any(p == ph for (p, _m) in agg)]
    if empty:
        print(f"warning: no requests found for phase(s) {empty} — check the transcript used", file=sys.stderr)
    if totals["requests"] == 0:
        print("cost: 0 requests matched the phase windows; not writing a report", file=sys.stderr)
        return 2
    target = out / "token-costs.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {target} (total ${totals['usd']:.2f})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--repo", default="."); b.add_argument("--fragments", required=True)
    b.add_argument("--title"); b.add_argument("--subtitle"); b.add_argument("--no-gitignore", action="store_true")
    b.add_argument("--fresh", action="store_true", help="ignore the previous lock entirely (full rebuild)")
    for name in ("check", "changed", "render"):
        s = sub.add_parser(name); s.add_argument("--repo", default=".")
    m = sub.add_parser("mark"); m.add_argument("phase", choices=["recon", "generate", "end"])
    m.add_argument("--repo", default="."); m.add_argument("--at", help="ISO timestamp (default: now)")
    c = sub.add_parser("cost"); c.add_argument("--repo", default="."); c.add_argument("--transcript")
    a = ap.parse_args()
    if a.cmd == "build":
        return build(a)
    repo = Path(a.repo).resolve()
    if a.cmd == "mark":
        return mark(repo, a.phase, a.at)
    if a.cmd == "cost":
        return cost(repo, a.transcript)
    if a.cmd == "check":
        return check(repo)
    if a.cmd == "changed":
        return changed(repo)
    lock = json.loads((repo / LOCK_NAME).read_text(encoding="utf-8"))
    print("wrote", render(repo, lock))
    return check(repo)


if __name__ == "__main__":
    sys.exit(main())
