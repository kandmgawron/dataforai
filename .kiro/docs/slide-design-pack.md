# Slide Design Pack

Standard design system for all course slide decks. Every module must follow this exactly.

---

## Technology

- Single HTML file per module at `slides/module-NN/index.html`
- Pure CSS, no external dependencies
- Vanilla JavaScript for navigation
- Self-contained (works offline, no CDN)

---

## Colour Palette

```css
:root {
  --bg: #0f1117;           /* Page background */
  --surface: #1a1d27;      /* Card/panel background */
  --surface2: #22263a;     /* Secondary surface (chips, etc.) */
  --border: #2e3350;       /* Borders, dividers */
  --accent: #4f8ef7;       /* Primary accent (blue) */
  --accent2: #7c5cbf;      /* Secondary accent (purple) */
  --green: #3ecf8e;        /* Success, positive */
  --orange: #f5a623;       /* Warning, highlight */
  --red: #e05c5c;          /* Error, problem */
  --text: #e8eaf0;         /* Primary text */
  --text-muted: #8b90a8;   /* Secondary text, body */
}
```

---

## Typography

```css
--mono: 'JetBrains Mono', 'Fira Code', monospace;
--sans: 'Inter', 'Segoe UI', system-ui, sans-serif;
```

| Element | Size | Weight | Font |
|---------|------|--------|------|
| h1 | 2.8rem | 700 | --sans |
| h2 | 2rem | 700 | --sans |
| h3 | 1.3rem | 600 | --sans |
| Body (p) | 1.05rem | 400 | --sans |
| Bullet list items | 1.05rem | 400 | --sans |
| Callout text | 1.05rem | 400 | --sans |
| Card body text | 1.05rem min | 400 | --sans |
| Card label | 0.85rem | 700, uppercase, 0.1em tracking | --sans |
| Label | 0.75rem | 600, uppercase, 0.12em tracking | --sans |
| Code/numbers | varies | varies | --mono |
| Stat numbers | 2.2rem | 800 | --mono |
| Stat labels | 0.85rem | 400 | --sans |
| Command block | 0.95rem | 400 | --mono |

---

## Layout

- Slides are 100vh, absolutely positioned
- Padding: 56px top/bottom, 72px left/right
- Max content width implied by padding (no explicit max-width on slide)
- Flexbox column, justify-content: center (default)

### Sizing Principles

- Content should fill the slide. Avoid small, cramped text surrounded by empty space.
- Body/card text minimum: 1.05rem. Never go below 0.95rem for any readable text.
- Card labels (uppercase headers inside cards): 0.85rem minimum.
- Callout text: 1.05rem.
- When using two-col with multiple boxes per column, use `align-items: stretch` (the default) so columns share the same height. Use flexbox inside columns with `flex: 1` on cards to divide space evenly.
- Stat numbers: 2.2rem. Stat labels: 0.85rem.
- Card padding: 28px 32px. Stat block padding: 24px.

---

## Components

### Title Slide
- Module label (uppercase, accent colour)
- h1 title
- h1 subtitle (text-muted, font-weight: 400)
- Accent line (48px wide gradient bar)
- Course name line
- Background: radial gradient with subtle accent glow

### Section Label
```html
<div class="label">Section label text</div>
```
Uppercase, accent colour, 0.75rem, always above the h2.

### Accent Line
```html
<div class="accent-line"></div>
```
48px × 4px gradient bar (accent → accent2). Goes between heading and content.

### Cards
```html
<div class="card">...</div>
<div class="card-grid card-grid-2">...</div>  <!-- 2 columns -->
<div class="card-grid card-grid-3">...</div>  <!-- 3 columns -->
```

Card padding: 28px 32px. Card label font-size: 0.85rem. Card body text: 1.05rem minimum.
Cards should fill their column width fully with no cramped margins.

### Tags / Pills
```html
<span class="tag tag-blue">Label</span>
<span class="tag tag-green">Label</span>
<span class="tag tag-purple">Label</span>
<span class="tag tag-orange">Label</span>
```

### AWS Service Chips
```html
<div class="aws-chip"><span class="dot"></span>Service Name</div>
<div class="aws-chip"><span class="dot new"></span>New Service</div>  <!-- green dot -->
```

### Step Reveals (click-to-appear)
```html
<div data-step="1">First to appear</div>
<div data-step="2">Second to appear</div>
```
Items start hidden; each click/arrow reveals the next step number.

### Two Column Layout
```html
<div class="two-col">
  <div>Left content</div>
  <div>Right content</div>
</div>
```

Use `align-items: stretch` when both columns contain multiple boxes that should share the same total height (tops and bottoms line up). Use flexbox inside each column (`display: flex; flex-direction: column; gap: 16px`) with `flex: 1` on child cards so they divide vertical space evenly. For the simpler case where columns have a single block each, `align-items: center` is fine.

### Bullet List
```html
<ul class="bullet-list">
  <li><strong>Bold part</strong> then description</li>
</ul>
```
Uses → arrow prefix, border-bottom separator. Font-size: 1.05rem, line-height: 1.6. Padding per item: 10px 0.

### Callout Box
```html
<div class="callout">Important note with <strong>bold</strong> emphasis.</div>
```
Blue-tinted background, left border accent. Padding: 20px 24px. Font-size: 1.05rem.

When a slide uses a two-col or grid layout, place callouts **below** the grid at full width, not nested inside one column. This keeps them visually anchored as a footer-level message spanning the whole slide.

### Stat Block
```html
<div class="stat-grid">
  <div class="stat-block">
    <div class="stat-num">40k</div>
    <div class="stat-label">Description</div>
  </div>
</div>
```

Stat block padding: 24px. stat-num: 2.2rem. stat-label: 0.85rem with 8px top margin. Use these sizes to fill the slide space rather than the smaller defaults.

### Problem Item (numbered list with badge)
```html
<div class="problem-item" data-step="1">
  <div class="num">01</div>
  <div class="content">
    <h3>Title</h3>
    <p>Description</p>
  </div>
  <div class="badge">→ Section N</div>
</div>
```

### Before/After Comparison
```html
<div class="before-after">
  <div class="side"><div class="side-label before-label">Before</div>...</div>
  <div class="side after"><div class="side-label after-label">After</div>...</div>
</div>
```

---

## Navigation

- Arrow keys (left/right) or click to navigate
- Space = next
- S toggles speaker notes panel
- Progress bar at bottom (gradient fill)
- Slide counter bottom-right (mono font)
- Nav hint bottom-left

---

## Speaker Notes

```html
<div class="notes">
  Notes text goes here. Not rendered on screen.
  Only visible when S is pressed.
</div>
```

Place inside each `.slide` div. Full sentences, conversational tone, written in Kate's voice.

---

## Slide Title Format

Each module's title slide follows:

```
Module NN · Section N: Section Name
[Title]
[Subtitle in muted colour]
```

---

## File Template

Each new module starts by copying the CSS and JS from module-01, then replacing only the slide content between `<div class="deck">` and `</div><!-- /deck -->`.

The full CSS block and JS navigation code are identical across all modules.
