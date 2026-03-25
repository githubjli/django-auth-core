# Unified Content Layer: Smallest Safe Next Step (Design Only)

> Status note: the unified content layer is currently **internal-only** and is **not** a public frontend API contract yet.

## Decision Summary

**Recommendation: keep the unified content layer as an internal mapping layer for now** and defer a public `/api/content/` endpoint to the next phase.

This is the smallest safe step because:
1. We already introduced a shared representation (`video` + `live`) without API breakage.
2. Existing frontend flows already consume `/api/videos/*` and `/api/live/*`.
3. A mixed feed endpoint introduces ordering/ranking/pagination semantics that are product-level decisions, not just transport changes.
4. We can harden contract expectations and observability first, then expose a new endpoint with lower risk.

---

## Option Evaluation

## Option 1 — Internal mapping layer only (for now)

### Pros
- **Zero endpoint churn**: no client migration required.
- **Lowest regression risk**: current contracts stay intact.
- **Lets us validate representation quality** in backend tests and internal use before externalizing.
- **Avoids premature feed semantics** (cross-type sort strategy, weighting, freshness rules, cursor behavior).

### Cons
- Frontend still composes mixed feeds client-side from multiple APIs.
- Slight duplicate fetching work remains in frontend until a unified endpoint exists.

### Safe next actions under Option 1
- Keep mapping helpers as the single source of cross-content field definitions.
- Add/expand contract tests around mapping outputs.
- Add design doc for future `/api/content/` with explicit non-goals and migration path.

---

## Option 2 — Add read-only `/api/content/` now

This is feasible, but carries moderate behavior-definition risk for a “smallest safe step”.

If we choose it later, it should be **additive only** and coexist with existing APIs.

## Proposed endpoint (future)

### Route
- `GET /api/content/` (read-only)

### Query params
- `type` (optional): `video|live|all` (default: `all`)
- `visibility` (optional): default public-safe behavior for anonymous users; authenticated users may include own private where policy allows
- `category` (optional): category slug
- `search` (optional): title/description search
- `ordering` (optional): `-created_at` default, plus explicitly allowed values only
- `page`, `page_size` (optional): standard DRF pagination

### Response shape (paginated)
```json
{
  "count": 123,
  "next": "...",
  "previous": null,
  "results": [
    {
      "id": 42,
      "content_type": "video",
      "title": "...",
      "description": "...",
      "owner_id": 7,
      "owner_name": "...",
      "category_slug": "technology",
      "category_name": "Technology",
      "visibility": "public",
      "status": "active",
      "status_source": "django_control",
      "thumbnail_url": "...",
      "playback_url": "...",
      "created_at": "...",
      "is_live": false,
      "viewer_count": null,
      "view_count": 345,
      "like_count": 99,
      "comment_count": 12
    }
  ]
}
```

### Coexistence with existing endpoints
- `/api/videos/*` and `/api/live/*` remain unchanged and source-of-truth for domain-specific operations.
- `/api/content/` acts as a **read aggregation surface only**.
- No mutation operations through `/api/content/`.
- Frontend can adopt incrementally for mixed feeds while keeping detail pages on existing endpoints.

### Why add it later (recommended timing)
Add once these are agreed:
1. Cross-type ordering semantics (e.g., creation-time only vs weighted freshness).
2. Visibility policy for authenticated mixed feeds.
3. Pagination/cursor behavior for stable infinite scroll.
4. Performance budget and query strategy for mixed aggregation.

---

## Proposed smallest safe next step (actionable)

1. Keep unified mapping internal in this pass.
2. Publish this design decision and endpoint draft in docs.
3. Add one integration test plan (design only) for eventual `/api/content/`.
4. Revisit endpoint implementation after product-level feed ordering rules are confirmed.

This preserves current API stability while preparing a low-risk path to unified content delivery.
