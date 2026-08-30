#!/usr/bin/env python3
"""
Builds data/mods.json (and data/mods.js, which is what the page loads)
from real sources:

  - every public repo in the Elduin-Labs GitHub org
  - each mod's own fabric.mod.json / stonecutter.properties.toml, for its
    display name, description and Minecraft version
  - the latest GitHub release and its .jar, if there is one
  - the Modrinth projects published by ItsElduin, matched up by slug

data/overrides.json supplies the hand-drawn 8x8 icon, the category and a couple
of tags for each mod. A repo that isn't in there still shows up on the site,
with a guessed icon, so publishing a new mod is enough to put it on the site.

Run:  python3 tools/build_mods.py
GITHUB_TOKEN in the environment is optional locally, and set for us in Actions.
Nothing outside the standard library is needed.
"""
import json, os, re, sys, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

ORG = "Elduin-Labs"
MODRINTH_USER = "ItsElduin"
ROOT = Path(__file__).resolve().parent.parent
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
UA = "elduin-mod-lab (github.com/Elduin-Labs)"


def get(url, headers=None, tolerate=(404,)):
    req = urllib.request.Request(url, headers={"user-agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code in tolerate:
            return None
        raise


def gh(path):
    h = {"accept": "application/vnd.github+json"}
    if TOKEN:
        h["authorization"] = "Bearer " + TOKEN
    body = get("https://api.github.com" + path, h)
    return json.loads(body) if body else None


def raw(repo, path):
    url = f"https://raw.githubusercontent.com/{ORG}/{repo['name']}/{repo['default_branch']}/{path}"
    return get(url) or ""


def modrinth(path):
    try:
        body = get("https://api.modrinth.com/v2" + path)
        return json.loads(body) if body else None
    except Exception:
        return None


overrides = json.loads((ROOT / "data/overrides.json").read_text())
SKIP = set(overrides.get("_skip", []))

GUESS = [
    (r"mob|villager|zombie|cow|pig|chicken|turtle|baby|npc|bot|creature|spawn", "mobs"),
    (r"block|piston|door|furnitur|terminal|dispenser|jukebox", "blocks"),
    (r"item|tool|weapon|sword|armour|armor|wear|boots", "tools"),
]
GUESS_ART = {
    "mobs":   ["........", ".gggggg.", "gggggggg", "gkkggkkg", "gggggggg", "gkkkkkkg", ".gggggg.", "..g..g.."],
    "blocks": ["dddddddd", "dtttttdd", "dttttttd", "dttttttd", "dttttttd", "dttttttd", "ddtttttd", "dddddddd"],
    "tools":  ["......ll", ".....lll", "....lll.", "y..lll..", ".y.ll...", "..yl....", ".d.y....", "d......."],
    "world":  ["iiiiiiii", "gggggggg", "dddddddd", "dddddddd", "uuuuuuuu", "uukuuuuu", "uuuuuuuu", "uuuuukuu"],
}


def guess_cat(repo):
    hay = f"{repo['name']} {repo.get('description') or ''}"
    for pattern, cat in GUESS:
        if re.search(pattern, hay, re.I):
            return cat
    return "world"


def read_manifest(repo):
    """Everything the mod says about itself, read out of its own source."""
    out = {}
    tree = gh(f"/repos/{ORG}/{repo['name']}/git/trees/{repo['default_branch']}?recursive=1")
    if not tree or "tree" not in tree:
        return out
    paths = [t["path"] for t in tree["tree"] if t["type"] == "blob"]

    fabric = next((p for p in paths if p.endswith("src/main/resources/fabric.mod.json")), None) \
        or next((p for p in paths if p.endswith("fabric.mod.json") and "/build/" not in p), None)
    if fabric:
        try:
            j = json.loads(re.sub(r"\$\{[^}]*\}", "0", raw(repo, fabric)))
            out["id"] = j.get("id")
            out["title"] = j.get("name")
            out["desc"] = j.get("description")
            out["env"] = j.get("environment")
            mc = (j.get("depends") or {}).get("minecraft")
            if isinstance(mc, list):
                mc = mc[0] if mc else None
            if mc:
                out["mc"] = re.sub(r"[~^>=<\s]", "", str(mc))
        except Exception:
            pass  # a manifest full of build-time placeholders; not a problem

    if "stonecutter.properties.toml" in paths:
        txt = raw(repo, "stonecutter.properties.toml")
        def grab(key):
            m = re.search(rf'^\s*{key}\s*=\s*"([^"]*)"', txt, re.M)
            return m.group(1) if m else None
        out.setdefault("id", grab("id"))
        out["title"] = out.get("title") or grab("name")
        out["desc"] = out.get("desc") or grab("description")
        m = re.search(r"^\s*versions\s*=\s*\[([^\]]*)\]", txt, re.M)
        if m:
            out["versions"] = [v.replace("-fabric", "") for v in re.findall(r'"([^"]+)"', m.group(1))]

    if not out.get("mc") and "gradle.properties" in paths:
        m = re.search(r"^\s*minecraft_version\s*=\s*(.+)$", raw(repo, "gradle.properties"), re.M)
        if m:
            out["mc"] = m.group(1).strip()

    if not out.get("versions") and out.get("mc"):
        out["versions"] = [out["mc"]]
    return out


def blurb(text):
    t = (text or "").strip()
    if len(t) <= 180:
        return t
    cut = t[:180]
    stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if stop > 90:
        return cut[:stop + 1]
    return re.sub(r"[\s,;-]+\S*$", "", cut) + "…"


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def title_from_repo(name):
    base = re.sub(r"-mod$", "", name)
    return " ".join(w.capitalize() for w in base.split("-"))


def main():
    repos, page = [], 1
    while True:
        batch = gh(f"/orgs/{ORG}/repos?type=public&per_page=100&page={page}")
        if not batch:
            break
        repos += batch
        if len(batch) < 100:
            break
        page += 1

    mr_projects = modrinth(f"/user/{MODRINTH_USER}/projects") or []

    live = sorted(
        (r for r in repos if not r["private"] and not r["archived"] and not r["fork"] and r["name"] not in SKIP),
        key=lambda r: r["name"],
    )

    mods = []
    for repo in live:
        ov = overrides["mods"].get(repo["name"], {})
        man = read_manifest(repo)
        rel = gh(f"/repos/{ORG}/{repo['name']}/releases/latest")
        jar = next((a for a in (rel or {}).get("assets", []) if a["name"].endswith(".jar")), None)

        mr = next(
            (p for p in mr_projects
             if norm(p.get("slug")) in {norm(re.sub(r"-mod$", "", repo["name"])), norm(repo["name"]), norm(man.get("id"))}
             or norm(p.get("title")) == norm(man.get("title"))),
            None,
        )

        cat = ov.get("cat") or guess_cat(repo)
        gh_desc = repo.get("description") or ""
        man_desc = man.get("desc") or ""
        desc = ov.get("desc") or blurb(man_desc if len(man_desc) > len(gh_desc) else gh_desc or man_desc)

        # the buttons on the card already say where to get it, so tags only
        # carry things the buttons don't
        tags = list(ov.get("tags", []))
        if man.get("env") == "client":
            tags.append("Client only")

        mods.append({
            "repo": repo["name"],
            "title": ov.get("title") or man.get("title") or title_from_repo(repo["name"]),
            "cat": cat,
            "kind": ov.get("kind", "Fabric mod"),
            "desc": desc,
            "art": ov.get("art") or GUESS_ART[cat],
            "versions": man.get("versions", []),
            "tags": tags,
            "github": repo["html_url"],
            "stars": repo["stargazers_count"],
            "release": {"tag": rel["tag_name"], "url": rel["html_url"], "published": rel["published_at"]} if rel else None,
            "jar": {"url": jar["browser_download_url"], "downloads": jar["download_count"], "name": jar["name"]} if jar else None,
            "modrinth": {"slug": mr["slug"], "url": f"https://modrinth.com/mod/{mr['slug']}", "downloads": mr.get("downloads", 0)} if mr else None,
        })

    # things people can actually install come first, then everything else, A-Z
    mods.sort(key=lambda m: (0 if m["modrinth"] else 1 if m["jar"] else 2, m["title"].lower()))

    out = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "org": ORG,
        "modrinth_user": MODRINTH_USER,
        "count": len(mods),
        "mods": mods,
    }
    (ROOT / "data/mods.json").write_text(json.dumps(out, indent=1) + "\n")
    # the page loads this one with a <script> tag, so mod.com also works
    # straight off the disk, with no local web server in the way
    (ROOT / "data/mods.js").write_text("window.MOD_DATA = " + json.dumps(out, indent=1) + ";\n")

    with_jar = sum(1 for m in mods if m["jar"])
    on_mr = sum(1 for m in mods if m["modrinth"])
    print(f"wrote data/mods.json + data/mods.js - {len(mods)} mods, {with_jar} with a jar, {on_mr} on Modrinth")
    missing = [m["repo"] for m in mods if m["repo"] not in overrides["mods"]]
    if missing:
        print("no hand-drawn icon yet for: " + ", ".join(missing))


if __name__ == "__main__":
    sys.exit(main())
