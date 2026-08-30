# Mod.com

Every Minecraft mod Elduin has made, on one page.

**Live:** https://elduin.org/mod-com/

## Nothing on the page is typed by hand

`tools/build_mods.py` reads the public repos in the `Elduin-Labs` org, each
mod's own `fabric.mod.json` / `stonecutter.properties.toml`, its GitHub
releases and the Modrinth projects of **ItsElduin**, and writes:

- `data/mods.json` — the plain data
- `data/mods.js` — the same data as `window.MOD_DATA`, which is what
  `index.html` loads. It's a `<script>` tag rather than a `fetch`, so the page
  also works when you just open the file, with no local web server.

`data/overrides.json` is the one file edited by hand: an 8x8 pixel icon, a
category, a kind label and a couple of tags per repo. A repo missing from it
still shows up, with a guessed icon.

A daily workflow rebuilds and commits both files, so **publishing a mod puts it
on the site by itself**. It also answers a `repository_dispatch`:

```
gh api repos/Elduin-Labs/mod-com/dispatches -f event_type=mod-released
```

## Building it locally

```
python3 tools/build_mods.py     # GITHUB_TOKEN in the environment avoids rate limits
open index.html
```
