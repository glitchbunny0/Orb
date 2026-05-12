# Implementation Plan: Internet Character Browse

## Overview

Add an **Internet** button to the character browser modal alongside the existing Grid/List toggle. Clicking it replaces the local character list with an online search panel — initially targeting CharacterHub (chub.ai). The panel has a source dropdown (extensible), a search input, and a paginated results grid with per-card Import buttons.

---

## Current Architecture Baseline

| Concern | Location |
|---|---|
| Modal entry point | `frontend/library.js:1127` — `showCharacterBrowserModal()` |
| View toggle HTML | `library.js:1154–1157` — `.view-toggle#char-browser-view-toggle` |
| View switch handler | `library.js:1180` — `setCharBrowserView(mode)` |
| Items renderer | `library.js:1321` — `renderCharBrowserItems()` |
| View mode state | `_browserViewMode` / `S.characterBrowserView` |
| File import flow | `library.js:493` → `POST /api/characters/import` (PNG upload) |
| API proxy | `frontend/api.js` — `api.get/post/put/del/upload` |

The view mode is persisted to settings via `api.put("/settings", { character_library_view: mode })`.

---

## Changes Required

### 1. Frontend state (`library.js` — top of file, near line 28)

Add three new module-level variables:

```js
let _internetSource = "characterhub";   // selected dropdown source
let _internetQuery  = "";               // current search text
let _internetPage   = 1;               // current results page
let _internetResults = [];             // last fetched page of results
let _internetLoading = false;
let _internetHasMore = false;          // whether a next page exists
```

---

### 2. "Internet" button in modal HTML (`library.js:1155–1156`)

Add a third button to the existing view-toggle group:

```html
<button class="view-toggle-btn${_browserViewMode === "internet" ? " active" : ""}"
        data-view="internet"
        onclick="setCharBrowserView('internet')">🌐 Internet</button>
```

The `.view-toggle` CSS already handles any number of flex children, so no CSS change is needed for the button itself.

---

### 3. `setCharBrowserView` — handle internet mode (`library.js:1180`)

When `mode === "internet"`:
- Skip the min-height measurement block (it only applies to local characters).
- Hide the local search/sort row and tags row.
- Render the internet panel instead of `renderCharBrowserItems()`.

When switching *away* from internet mode:
- Unhide the local search/sort and tags rows.
- Re-render local items.

Implementation sketch:
```js
export function setCharBrowserView(mode) {
  _browserViewMode = mode;
  S.characterBrowserView = mode;
  api.put("/settings", { character_library_view: mode }).catch(...);

  document.querySelectorAll("#char-browser-view-toggle .view-toggle-btn")
    .forEach(btn => btn.classList.toggle("active", btn.dataset.view === mode));

  const isInternet = mode === "internet";
  const searchRow = document.querySelector(".char-browser-search-row");
  const tagsRow   = document.querySelector(".char-browser-tags-row");
  if (searchRow) searchRow.style.display = isInternet ? "none" : "";
  if (tagsRow)   tagsRow.style.display   = isInternet ? "none" : "";

  if (isInternet) {
    renderInternetPanel();
  } else {
    const container = $("char-browser-content");
    if (container) container.style.minHeight = "";
    // existing min-height measurement + render
    ...
  }
}
```

---

### 4. Internet panel renderer (`library.js` — new function)

`renderInternetPanel()` writes a self-contained sub-UI into `#char-browser-content`:

```html
<div class="char-browser-internet">
  <div class="internet-controls">
    <select id="internet-source" onchange="setInternetSource(this.value)">
      <option value="characterhub">CharacterHub</option>
    </select>
    <input  id="internet-search-input" type="text"
            placeholder="Search characters…"
            value="${esc(_internetQuery)}"
            onkeydown="if(event.key==='Enter')searchInternet()">
    <button onclick="searchInternet()">Search</button>
  </div>
  <div id="internet-results">
    ${_internetLoading
      ? `<div class="internet-loading">Loading…</div>`
      : renderInternetResults()}
  </div>
</div>
```

`renderInternetResults()` maps `_internetResults` to cards (see §6) and appends a "Load More" button when `_internetHasMore`.

---

### 5. Search action + pagination (`library.js` — new functions)

```js
export async function searchInternet(nextPage = false) {
  if (_internetLoading) return;
  const input = $("internet-search-input");
  if (input) _internetQuery = input.value.trim();

  if (!nextPage) _internetPage = 1;

  _internetLoading = true;
  refreshInternetResults();   // show spinner

  try {
    const data = await api.get(
      `/characters/browse?source=${_internetSource}&q=${encodeURIComponent(_internetQuery)}&page=${_internetPage}`
    );
    if (!nextPage) _internetResults = data.results;
    else           _internetResults = [..._internetResults, ...data.results];
    _internetHasMore = data.has_more;
  } catch (e) {
    toast("Search failed: " + e.message, true);
  } finally {
    _internetLoading = false;
    refreshInternetResults();
  }
}

export function loadMoreInternet() {
  _internetPage++;
  searchInternet(true);
}

export function setInternetSource(val) {
  _internetSource = val;
  _internetQuery  = "";
  _internetResults = [];
  _internetPage   = 1;
  _internetHasMore = false;
  renderInternetPanel();
}
```

`refreshInternetResults()` just updates `#internet-results` innerHTML without re-rendering the controls row.

---

### 6. Internet result card (`library.js` — new function)

Mirrors `renderCharBrowserCard` but for external data:

```js
function renderInternetResultCard(item) {
  const av = item.avatar_url
    ? `<img src="${esc(item.avatar_url)}" onerror="this.parentElement.textContent='👤'">`
    : "👤";
  return `
    <div class="char-browser-card internet-result-card">
      <div class="char-browser-avatar">${av}</div>
      <div class="char-browser-card-name">${esc(item.name)}</div>
      <div class="internet-result-meta">${esc(item.tagline || "")}</div>
      <button class="internet-import-btn"
              onclick="importInternetChar('${esc(item.full_path)}')">Import</button>
    </div>`;
}
```

Fields expected from backend: `name`, `avatar_url`, `tagline`, `full_path` (opaque identifier passed back on import).

---

### 7. Import action (`library.js` — new function)

Reuses the existing `showCharEditModal` flow so the user can review the card before saving:

```js
export async function importInternetChar(fullPath) {
  try {
    toast("Fetching card…");
    const r = await api.post("/characters/import-url", { source: _internetSource, full_path: fullPath });
    showCharEditModal(r);   // same pre-save review modal as file import
  } catch (e) {
    toast("Import failed: " + e.message, true);
  }
}
```

---

### 8. Backend — browse proxy (`backend/main.py`)

New endpoint that proxies CharacterHub search so the frontend never makes cross-origin requests directly:

```python
@app.get("/api/characters/browse")
async def api_browse_characters(source: str = "characterhub", q: str = "", page: int = 1):
    if source == "characterhub":
        return await _browse_characterhub(q, page)
    raise HTTPException(400, f"Unknown source: {source}")

async def _browse_characterhub(q: str, page: int):
    import httpx
    url = "https://api.chub.ai/api/characters/search"
    params = {
        "search": q, "page": page, "sort": "dl",
        "limit": 24, "nsfw": "false",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
    data = resp.json()
    nodes = data.get("data", {}).get("nodes", [])
    results = [
        {
            "name":       n.get("name", ""),
            "tagline":    n.get("tagline", ""),
            "avatar_url": f"https://avatars.chub.ai/avatars/{n['fullPath']}/avatar.jpg"
                          if n.get("fullPath") else None,
            "full_path":  n.get("fullPath", ""),
        }
        for n in nodes
    ]
    has_more = len(nodes) == 24
    return {"results": results, "has_more": has_more}
```

> **Dependency note:** `httpx` is already present in many FastAPI projects; confirm it is in `requirements.txt` / `pyproject.toml`. If not, add it.

---

### 9. Backend — import from URL (`backend/main.py`)

Downloads the card as a PNG from CharacterHub and feeds it through the existing import pipeline:

```python
class ImportUrlRequest(BaseModel):
    source: str
    full_path: str

@app.post("/api/characters/import-url")
async def api_import_character_url(req: ImportUrlRequest):
    if req.source == "characterhub":
        content = await _download_characterhub_card(req.full_path)
    else:
        raise HTTPException(400, f"Unknown source: {req.source}")

    # Reuse exact same logic as /api/characters/import
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        orb_id  = tavern_cards.read_orb_id(tmp_path)
        card    = tavern_cards.parse(tmp_path)
        card_dict = tavern_cards.card_to_dict(card)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    finally:
        os.unlink(tmp_path)

    card_id = orb_id or str(uuid.UUID(bytes=hashlib.sha256(content).digest()[:16], version=5))
    card_dict["id"]          = card_id
    card_dict["avatar_b64"]  = base64.b64encode(content).decode("ascii")
    card_dict["avatar_mime"] = "image/png"
    return card_dict   # same shape returned by /api/characters/import

async def _download_characterhub_card(full_path: str) -> bytes:
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.chub.ai/api/characters/download",
            json={"fullPath": full_path, "format": "tavern"},
        )
        resp.raise_for_status()
    return resp.content
```

---

### 10. CSS (`frontend/style.css`)

```css
/* Internet panel layout */
.char-browser-internet {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.internet-controls {
  display: flex;
  gap: 8px;
  align-items: center;
}

.internet-controls select {
  flex: 0 0 auto;
}

.internet-controls input {
  flex: 1 1 auto;
}

/* Result cards reuse .char-browser-card; extras below */
.internet-result-card {
  cursor: default;   /* not clickable as a whole — only the Import button */
}

.internet-result-meta {
  font-size: 11px;
  color: var(--text-muted);
  text-align: center;
  margin: 4px 0;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.internet-import-btn {
  width: 100%;
  margin-top: 6px;
  padding: 4px 0;
  font-size: 12px;
  border-radius: 4px;
  background: var(--accent);
  color: var(--on-accent, #fff);
  border: none;
  cursor: pointer;
}

.internet-import-btn:hover {
  opacity: 0.85;
}

.internet-loading {
  text-align: center;
  padding: 32px;
  color: var(--text-muted);
}

.internet-load-more {
  display: block;
  margin: 12px auto 0;
  padding: 6px 24px;
}
```

---

### 11. `app.js` — expose new globals

Any function called by inline `onclick` handlers must be on `window`. Add to the window assignment block:

```js
window.searchInternet       = searchInternet;
window.loadMoreInternet     = loadMoreInternet;
window.setInternetSource    = setInternetSource;
window.importInternetChar   = importInternetChar;
```

---

## File Manifest

| File | Change |
|---|---|
| `frontend/library.js` | New state vars, 3rd view-toggle button, `setCharBrowserView` update, 5 new functions |
| `frontend/style.css` | ~45 lines of new CSS |
| `frontend/app.js` | 4 new `window.*` assignments |
| `backend/main.py` | 2 new endpoints + 2 helper async functions |
| `requirements.txt` / `pyproject.toml` | Confirm/add `httpx` |

No new files required.

---

## UX Flow

```
User opens Character Library modal
  → clicks "🌐 Internet"
  → local search/sort/tags rows hidden
  → internet panel appears: [CharacterHub ▼] [search input] [Search]
  → user types query, presses Enter or clicks Search
  → spinner shown, backend proxies chub.ai API
  → results render as card grid (same .char-browser-card style)
  → user clicks "Import" on a card
  → backend downloads PNG, parses tavern card
  → showCharEditModal opens pre-filled (same review flow as file import)
  → user saves → character added to local library
```

---

## Open Questions / Risks

| # | Question | Suggested Default |
|---|---|---|
| 1 | Should NSFW content be shown? | Default `nsfw=false`; expose a toggle later |
| 2 | Rate limits on chub.ai API? | Respect `Retry-After` headers; 429 → toast |
| 3 | Avatar proxy? Chub avatar URLs are public CDN — load directly in `<img>` | Direct load (no proxy needed) |
| 4 | Saving chosen `_internetSource` to settings? | Not needed for v1; resets to "characterhub" each open |
| 5 | Result grid vs list? | Always grid in internet mode for v1; local view toggle is irrelevant |
