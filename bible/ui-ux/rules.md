<!-- RULE START: UIUX-ASYNC-001 -->
## Rule UIUX-ASYNC-001

**Domain**: ui-ux
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When wiring a user-triggered action that performs network/DB work (submit, save, delete, generate, fetch-on-click).

### Statement
Every async action implements four states: idle → loading (spinner inside the triggering control, control disabled, `aria-busy`) → success (UI visibly reflects the new data; toast only when the change isn't on-screen) → error (message states what failed and what the user can do; action retryable). Content areas loading > 200ms show skeletons, never a blank region or a page-center spinner replacing existing content.

### Violation
```jsx
<button onClick={save}>Save</button>
// no pending state; double-clicks double-submit; failure logs to console only
```

### Pass
```jsx
<button onClick={save} disabled={saving} aria-busy={saving}>
  {saving ? <><Spinner/> Saving…</> : "Save"}
</button>
{error && <p class="error">Couldn't save — check connection and retry.</p>}
```

### Enforcement
Review checklist per mutation handler: pending flag, disabled control, error branch rendered in UI.

### Rationale
Missing loading/error states is the #1 perceived-quality gap in AI-built UIs: double submits, silent failures, frozen-feeling screens.

<!-- RULE END: UIUX-ASYNC-001 -->
---

<!-- RULE START: UIUX-CONTRAST-001 -->
## Rule UIUX-CONTRAST-001

**Domain**: ui-ux
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When choosing a text or icon color over any background — especially when using a brand or decorative accent color (lime, mint, yellow, pastel) for text, buttons, or status indication.

### Statement
Text/icon contrast is ≥ 4.5:1 against its background (≥ 3:1 for text ≥ 24px). Decorative highlight colors (`--highlight`; lime/mint/yellow class colors) are never used as text color and never carry meaning alone: they appear only as fills behind dark ink (`--highlight-ink`), and status meaning always pairs a status color with a text label or icon.

### Violation
```html
<p style="color: var(--highlight)">Success!</p>          <!-- lime text ~1.6:1 -->
<button style="background: var(--highlight); color: #fff">Save</button>
<span class="dot dot-green"></span>                       <!-- color = only signal -->
```

### Pass
```html
<span class="badge" style="background: var(--highlight); color: var(--highlight-ink)">New</span>
<span class="badge badge-ok">Active</span>                <!-- color + label -->
```

### Enforcement
Contrast check on new color pairs (WebAIM/Chrome devtools); review flags highlight-as-text.

### Rationale
Light candy colors fail WCAG hard as text (lime on white ≈ 1.6:1) — the references that look good with lime use it strictly as a fill under dark ink. Color-only status excludes colorblind users.

<!-- RULE END: UIUX-CONTRAST-001 -->
---

<!-- RULE START: UIUX-EMPTY-001 -->
## Rule UIUX-EMPTY-001

**Domain**: ui-ux
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When rendering a collection view (list, table, grid, feed, search results) whose data can be empty.

### Statement
The empty case renders a designed empty state — short title, one explanatory line, and the primary action that fills the view (or the reason none exists). A bare "No data", a blank region, or an empty table frame is a violation. First-run empty and filtered-to-empty get different copy ("no results match" + clear-filters action).

### Violation
```jsx
{items.length > 0 && <Table rows={items} />}   // empty → nothing renders
```

### Pass
```jsx
{items.length ? <Table rows={items}/> : (
  <EmptyState title="No reports yet"
    hint="Reports appear after your first campaign run."
    action={<Button>Create campaign</Button>}/>
)}
```

### Enforcement
Review: every `.map(` over fetched data has a sibling empty branch.

### Rationale
Every list is empty on day one — that's the first screen a new user judges. Blank regions read as broken.

<!-- RULE END: UIUX-EMPTY-001 -->
---

<!-- RULE START: UIUX-FOCUS-001 -->
## Rule UIUX-FOCUS-001

**Domain**: ui-ux
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When creating an interactive element, a custom control from divs, or writing `outline: none` / `focus:outline-none`.

### Statement
Every interactive element shows a visible focus indicator on `:focus-visible` (the shared `--focus-ring` construction). Removing the default outline without an equal-or-better replacement is forbidden. Custom clickable divs get `role`, `tabindex`, and key handlers — or become a real `<button>`. Esc closes the topmost layer (modal, popover); tab order follows visual order.

### Violation
```css
button:focus { outline: none; }
```
```html
<div onclick="submit()">Save</div>
```

### Pass
```css
:focus-visible { outline: none; box-shadow: var(--focus-ring); }
```
```html
<button type="button" onclick="submit()">Save</button>
```

### Enforcement
Grep `outline:\s*none` / `outline-none` for unpaired removals; review clickable divs.

### Rationale
Focus removal is the most common copy-pasted accessibility break; a shared ring token makes correct focus free.

<!-- RULE END: UIUX-FOCUS-001 -->
---

<!-- RULE START: UIUX-FORM-001 -->
## Rule UIUX-FORM-001

**Domain**: ui-ux
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When building a form field or its validation feedback.

### Statement
Every field has a permanently visible `<label>` — placeholder text is a format hint, never the label. Validation errors render inline directly under their field (message says how to fix, border matches), with `aria-invalid` + `aria-describedby`. Toasts/alerts are forbidden for field validation. Validate on blur or submit, not on every keystroke of an untouched field.

### Violation
```html
<input placeholder="Email">                <!-- label vanishes on input -->
<script>toast("Form invalid")</script>     <!-- which field? -->
```

### Pass
```html
<label for="email">Email</label>
<input id="email" placeholder="you@company.com"
       aria-invalid="true" aria-describedby="email-err">
<p id="email-err" class="error">Enter a valid email address.</p>
```

### Enforcement
Review: every `<input>`/`<select>`/`<textarea>` pairs with a `<label for>`; no toast on validation paths.

### Rationale
Placeholder-as-label loses context the moment the user types; toast validation forces users to hunt for the broken field.

<!-- RULE END: UIUX-FORM-001 -->
---

<!-- RULE START: UIUX-HIER-001 -->
## Rule UIUX-HIER-001

**Domain**: ui-ux
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When adding buttons to a view, toolbar, dialog, or form footer.

### Statement
Exactly one primary (filled accent) button per view/dialog; all other actions are secondary (outlined) or ghost. Destructive actions use the danger variant, get a confirmation naming the specific object ("Delete 'Q3 report'?"), and the confirm button carries the destructive verb — never "OK"/"Yes". Icon-only buttons have an accessible label.

### Violation
```html
<button class="btn-primary">Save</button>
<button class="btn-primary">Export</button>
<button class="btn-primary">Share</button>
<!-- delete flow: confirm("Are you sure?") → [OK] [Cancel] -->
```

### Pass
```html
<button class="btn-primary">Save</button>
<button class="btn-secondary">Export</button>
<button class="btn-ghost">Share</button>
<!-- modal: "Delete 'Q3 report'?" → [Cancel] [Delete report] -->
```

### Enforcement
Review: count primary-variant buttons per rendered view; check destructive confirms name object + verb.

### Rationale
Multiple primaries = no hierarchy = user reads every button. "OK" confirms teach users to click through — until one deletes real data.

<!-- RULE END: UIUX-HIER-001 -->
---

<!-- RULE START: UIUX-SCALE-001 -->
## Rule UIUX-SCALE-001

**Domain**: ui-ux
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When setting a margin, padding, gap, width of a control, or a font size in UI code.

### Statement
Spacing values come only from the 4px scale (`--sp-1`…`--sp-9`: 4, 8, 12, 16, 24, 32, 48, 64, 96) and font sizes only from the type scale (`--fs-xs`…`--fs-5xl`). Freehand values (`margin: 13px`, `font-size: 15.5px`, `p-[18px]`) are forbidden; if a step feels wrong, pick the adjacent step, don't invent one.

### Violation
```css
.toolbar { padding: 14px 18px; gap: 10px; }
.title { font-size: 23px; }
```

### Pass
```css
.toolbar { padding: var(--sp-3) var(--sp-4); gap: var(--sp-2); }
.title { font-size: var(--fs-xl); }
```

### Enforcement
Grep for arbitrary px values / Tailwind arbitrary `[..px]` utilities in review.

### Rationale
A fixed scale is what makes unrelated screens look like one product. Freehand pixels are the single biggest source of "why does this page feel off" time sink.

<!-- RULE END: UIUX-SCALE-001 -->
---

<!-- RULE START: UIUX-SLIDE-001 -->
## Rule UIUX-SLIDE-001

**Domain**: ui-ux
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When creating HTML slides or a presentation deck.

### Statement
Slides are fixed 1280×720 sections built from the ui-kit deck template with a single `data-brand` preset. Per slide: one idea stated as a full-sentence headline, body ≤ ~40 words, ≤ 3 bullet points, ≤ 2 decorative stickers. Key numbers get the stat treatment (giant numeral + short label + rule), never buried in sentences. Decks for an external brand use that brand's preset; everything else uses the `own` preset — brand identities are parameterized, not cloned into layouts.

### Violation
```html
<section class="slide">
  <h2>Update</h2>
  <p>We achieved 14 million users this year which is a great result and also
  onboarded 36,000 partners while keeping uptime at 99.98% and…</p> <!-- 3 ideas, buried numbers -->
</section>
```

### Pass
```html
<section class="slide">
  <h2 class="h-title">Numbers carry this slide</h2>
  <div class="stat"><span class="n">14M+</span><span class="l">monthly active users</span></div>
  <div class="stat"><span class="n">36k</span><span class="l">partners onboarded</span></div>
</section>
```

### Enforcement
Review: word count per slide body; stats rendered as stat rows; one headline idea.

### Rationale
Slides are read in ~6 seconds each; one idea + giant numerals is what makes reference-grade decks (fintech partner decks) land, and fixed geometry keeps export/print predictable.

<!-- RULE END: UIUX-SLIDE-001 -->
---

<!-- RULE START: UIUX-THEME-001 -->
## Rule UIUX-THEME-001

**Domain**: ui-ux
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When starting UI work in a project or adding a new surface (app screen, marketing page, slide deck) — before writing any styles.

### Statement
Pick one ui-kit theme per surface from the decision table (dense/creator app → `studio`; business app → `paper`+app mode; marketing/content → `paper`; neutral fallback → `clean`; slides → deck template) and set it once on the root (`data-theme`). Themes are never mixed within a surface, and a new brand/look is added as a theme block overriding semantic tokens — never by restyling components. Dark themes build elevation with lighter surfaces (`--surface`, `--surface-2`), not drop shadows, and reserve saturated color for focus/links/status.

### Violation
```html
<div data-theme="studio">
  <section style="background:#F6F2E9">…</section>  <!-- paper section inside studio -->
</div>
```
```css
[data-theme="studio"] .card { box-shadow: 0 12px 40px rgba(0,0,0,.6); }
```

### Pass
```html
<html data-theme="studio"> <!-- whole app surface -->
```
```css
[data-theme="studio"] .card { background: var(--surface); border: 1px solid var(--line); }
```

### Enforcement
Review: one `data-theme` per surface root; no hardcoded theme values inside another theme's tree.

### Rationale
Theme mixing is how products end up looking stitched together; heavy shadows on dark UI look muddy — layered surface lightness is how dark tools (Krea-class) read as slick.

<!-- RULE END: UIUX-THEME-001 -->
---

<!-- RULE START: UIUX-TOKEN-001 -->
## Rule UIUX-TOKEN-001

**Domain**: ui-ux
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When writing or editing any UI styling — CSS, Tailwind classes, inline styles, styled components — for a user-facing surface.

### Statement
Components reference only semantic design tokens (`--bg`, `--surface`, `--ink`, `--ink-muted`, `--line`, `--accent`, `--highlight`, or their Tailwind theme mappings like `bg-surface text-ink`) from the ui-kit token sheet. Raw hex/rgb/hsl literals in component code are forbidden. A color that has no token enters `tokens.css` as a theme token first, then gets used.

### Violation
```css
.card { background: #141416; border: 1px solid #2a2a2e; }
```
```html
<div class="bg-[#141416] text-[#f4f4f5]">…</div>
```

### Pass
```css
.card { background: var(--surface); border: 1px solid var(--line); }
```
```html
<div class="bg-surface text-ink">…</div>
```

### Enforcement
Grep for `#[0-9a-fA-F]{3,8}` and `bg-\[` / `text-\[` in component files during review.

### Rationale
Raw values fork the design system silently: theme switching breaks, dark mode breaks, and every screen drifts toward its own palette. Tokens keep one decision in one place.

<!-- RULE END: UIUX-TOKEN-001 -->
---

<!-- RULE START: UIUX-TYPE-001 -->
## Rule UIUX-TYPE-001

**Domain**: ui-ux
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When choosing a font family or styling headings for a surface.

### Statement
Max two font families per surface (display + body) plus mono for code/numerals. Serif/display faces appear only at large sizes (≥ `--fs-2xl`) on marketing pages and slides — never in app UI controls, tables, or headings below 20px. App surfaces are sans-only. Interactive/body text never renders below 13px (`--fs-sm`); 12px (`--fs-xs`) is reserved for meta/labels.

### Violation
```css
.table th { font-family: var(--font-display); font-size: 11px; }  /* serif table header */
.settings h3 { font-family: "Fraunces"; font-size: 16px; }
```

### Pass
```css
.hero h1 { font-family: var(--font-display); font-size: var(--fs-4xl); }  /* marketing */
.settings h3 { font-family: var(--font-body); font-size: var(--fs-md); font-weight: 600; }
```

### Enforcement
Review: display-font usage grep in app-mode surfaces; font-size < 13px on interactive text.

### Rationale
Serif display is a marketing voice — at small app sizes it scans badly and reads as a bug. Tiny text is the fastest way to make a UI feel cheap and unreadable.

<!-- RULE END: UIUX-TYPE-001 -->
