# Brand-compliance document audit — methodology

**Package:** `agentic_bi` (part of the `agentic_bi_framework` project)
**Base materials:** the brand style guide (visual identity guide),
`agentic_bi/brand.py`

---

## 1. The task

You have created a presentation (or another document) and need to **quickly
locate places that deviate from the corporate style**: colors
(text/fill/line/background), fonts (family/weight) and brand-book rules
(mandatory accent, "2 of 3" elements).

The check is fully automated and works offline, without opening PowerPoint.

## 2. Architecture (3 layers)

```
brand_config.yaml   <-  audit config (rules, tolerances, severity)
        │
        ▼
brand.py            <-  machine-readable brand-book base (palette/fonts/rules)
        │
        ▼
brand/config.py     <-  merge config + base -> BrandConfig (effective)
        │
        ▼
brand/audit.py      <-  extract observations from the document + evaluate -> AuditReport
```

| Layer | File | Role |
|-------|------|------|
| Base | `brand.py` | brand-book defaults (source of truth) |
| Config | `brand_config.yaml` | project overrides: tolerances, severity, what to check |
| Loader | `brand/config.py` | `BrandConfig.load()` / `.default()`, `match()`, `severity_of()` |
| Engine | `brand/audit.py` | `audit_pptx()` / `audit_document()`, `ThemeResolver`, CLI |

**Principle:** the config contains **only differences** from `brand.py`. Anything
not set in the config falls back to the style-guide value. This avoids duplication
and divergence from the spec.

### 2.1 What the engine captures

| Area | Support |
|------|---------|
| Direct RGB colors | text, shape fill, line/outline |
| **Theme (scheme) colors** | resolved via `theme1.xml` (`ThemeResolver`): accent1-6, dk/lt, text/bg |
| **Groups** | nested shapes traversed recursively |
| **Tables** | cell → paragraph → run |
| Fonts | family, **weight** (by name), **size** (opt., step 2pt) |
| Background | slide background + text-to-background contrast |
| Rules | mandatory accent, "2 of 3", min 2 primary-range colors |

Neutral colors (white/grey/black) and brand colors are **not flagged** for
contrast (sanctioned by the style guide). Master-layout placeholders are by
default not checked for fill/line (inherited from the theme).

## 3. Configuration file

`agentic_bi/brand_config.yaml` — structure:

| Section | Sets | Keys |
|---------|------|------|
| `meta` | version/source | `source: assets/brand/brand-book.pdf` |
| `colors` | palette and tolerance | `primary`, `additional`, `allow_extra`, `tolerance_rgb` |
| `fonts` | families | `allowed`, `fallback`, `weights`, `check_size_step` |
| `background` | backgrounds and contrast | `preferred`, `allowed`, `min_contrast` |
| `rules` | brand-book thresholds | `red_mandatory`, `primary_color_min`, `base_elements_min`, `check_*` |
| `severity` | level per rule | `error / warning / info / off` |
| `audit` | what and how to scan | `check_text_color/fill/line/background/font_size`, `resolve_theme_colors`, `contrast_skip_brand`, `foundation_present`, `max_findings`, `ignore_fonts`, `ignore_layout_placeholders` |

### 3.1 Key settings

- **`tolerance_rgb`** (default 12) — the "almost brand" color tolerance. Export
  and themes distort RGB; a Euclidean distance within the tolerance counts as a
  match. Stricter — decrease (e.g. 4); looser — increase (e.g. 24).
- **`severity`** — overrides the level per rule. `off` fully disables a rule.
  Example: make the font finding blocking — `FONT-FAMILY-BRAND: error`.
- **`allow_extra`** — non-grey colors allowed outside the palette. Achromatic
  (white/grey/black) are always allowed.
- **`ignore_fonts`** — theme placeholders (`+mn-lt` etc.), common in exports.
- **`resolve_theme_colors`** (default `true`) — resolve theme colors via
  `theme1.xml`. Disable it for strict RGB-only control.
- **`contrast_skip_brand`** (default `true`) — do not flag contrast for brand
  colors (primary accent on white is sanctioned by the style guide).
- **`foundation_present`** — whether to assume the "foundation" is present (for
  the "2 of 3" rule) when it cannot be detected automatically.

### 3.2 Settings cascade

```
brand/palette.py + brand/fonts.py (true source)  ->  brand_config.yaml (project)  ->  BrandConfig(incode) ->  CLI --config
```
The further right, the higher the priority. For a one-off check `--config` is
enough; for a series of similar documents, commit the config to the project repo.

## 4. Workflow

### Step 1. Tune the config for the document type

- **Presentation (deck)**: `tolerance_rgb: 12`, `severity` as in the example,
  `check_background: true`.
- **Strict corporate template**: `tolerance_rgb: 4`,
  `severity.FONT-FAMILY-BRAND: error`.
- **Master-inherited template**: keep `ignore_layout_placeholders: true` to avoid
  flooding findings on default placeholders.

### Step 2. Run the audit

```bash
cd agentic_bi_framework
python -m agentic_bi.brand.audit "Presentation.pptx" \
    --config src/agentic_bi/brand_config.yaml \
    --json "output_files/audit.json" \
    --fail-on error
```

### Step 3. Read the report

- **Text report** — the location of every non-compliance:
  `slide 2 / shape 'TextBox 1' / p0r0 / font`.
- **JSON** — machine-readable: `summary` (counts by category) + `findings[]`.
- **Exit code** (`--fail-on`): `error` → 1 on blocking findings; `warning` → 1 on
  any; `never` (default) → always 0.

### Step 4. Fix and repeat

Edit the document by location and re-run until `OK`. For CI, use
`--fail-on error` as a quality gate.

## 5. Usage example ("created a presentation" scenario)

```python
from agentic_bi.brand.config import BrandConfig
from agentic_bi.brand.audit import audit_pptx

cfg = BrandConfig.load("src/agentic_bi/brand_config.yaml")
rep = audit_pptx("Presentation.pptx", cfg)

print(rep.format())  # what does not comply and where
print(rep.by_category())  # {'color': 3, 'font': 1, ...}
if not rep.ok():
    rep.to_json("audit.json")  # hand off to a developer/designer
```

Example output:

```
Audit: Presentation.pptx
  total: 4 (error=0, warning=4, info=0)
  by category: {'color': 3, 'font': 1}

  [WARNING] BRAND-PALETTE-MEMBERSHIP @ slide 2 / shape 'TextBox 1' / p0r0 / text
            Color #123456 is outside the brand palette.
  [WARNING] FONT-FAMILY-BRAND @ slide 2 / shape 'TextBox 1' / p0r0 / font
            Family 'Comic Sans MS' is not a brand one (Brand Sans/Text).
  [WARNING] BRAND-PALETTE-MEMBERSHIP @ slide 2 / shape 'Rectangle 2' / fill
            Color #ff00ff is outside the brand palette.
  [WARNING] BRAND-PRIMARY-COLORS-MIN @ document
            The palette is extended but only 1 primary-range color is used (minimum 2).
```

## 6. Rules and what they catch

| Rule | Category | Catches | Brand book |
|------|----------|---------|-----------|
| `BRAND-ACCENT-MANDATORY` | color | the red `#D32F2F` not found | pp. 49/51 |
| `BRAND-PALETTE-MEMBERSHIP` | color | a chromatic color outside the palette | pp. 49/51 |
| `BRAND-PRIMARY-COLORS-MIN` | color | extending the palette with < 2 primary colors | pp. 49/51 |
| `FONT-FAMILY-BRAND` | font | a family that is neither Brand Sans/Text nor fallback | pp. 58-61 |
| `FONT-WEIGHT-ALLOWED` | font | a disallowed Brand Sans weight | pp. 60-61 |
| `FONT-SIZE-STEP` | font | a size not a multiple of the step (opt., `check_font_size`) | — |
| `BG-ALLOWED` | background | a background outside the allowed set | pp. 14/49/51 |
| `BG-CONTRAST` | background | text-to-background contrast < 4.5:1 | p. 14 + WCAG AA |
| `ELEM-BASE-2OF3` | element | < 2 of 3 base elements | pp. 13/40/46 |

## 7. Limitations and roadmap

- **Formats:** currently `.pptx`; the `audit_document()` dispatcher is ready for
  `.docx`/`.xlsx` (by extension). `.docx` is easy to add (python-docx).
- **Theme colors** (`theme_color`): resolved via the master's `theme1.xml`. If the
  theme is unavailable, the observation is skipped (no false positives).
- **Font weight:** derived from the family name (`Brand Sans Semibold` →
  `semibold`); full weight from OTF tables is available via `fontTools`, but is
  not always stored in a pptx.
- **Background:** the explicitly set slide background; when inherited from the
  layout, white is used as the contrast base.
- **Images:** raster screenshots are not analyzed (only vector shape/text
  properties). If needed, a separate image color analysis (`Pillow`) can reuse
  the same `BrandConfig`.
- **Logo:** the "presence/safe zone" check requires image recognition and is out
  of scope for the current version (`ELEM-LOGO-SAFE-ZONE` is declared in `brand.py`).

## 7.1 Code quality

- The engine is split into small functions (`_eval_colors`, `_eval_font`,
  `_eval_contrast`, `_eval_background`, `_eval_document_rules`, `_eval_font_size`).
- Tests: `tests/test_brand_audit.py` — config, theme resolver, groups, tables,
  background, contrast, weights/sizes, severity, limits, serialization.

## 8. Related materials

- `agentic_bi/brand.py` — the brand base (palette/fonts/rules)
- `agentic_bi/brand_config.yaml` — the audit config
- `agentic_bi/brand/config.py` — config loading and merging
- `agentic_bi/brand/audit.py` — the audit engine + CLI
- `tests/test_brand_audit.py` — tests
- the brand style guide (visual identity guide) — the primary source
- the corporate font library (Brand Sans/Text)