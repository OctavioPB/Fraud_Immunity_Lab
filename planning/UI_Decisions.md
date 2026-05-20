# UI Decisions — OPB Design System

> This document captures every design and engineering decision for the **OPB design system**
> (Octavio Pérez Bravo). It is the authoritative reference for maintaining any OPB-branded
> dashboard and the migration guide for applying the system to new applications.

---

## Table of Contents

1. [Philosophy](#1-philosophy)
2. [Technology Choices](#2-technology-choices)
3. [Design Tokens](#3-design-tokens)
4. [Typography System](#4-typography-system)
5. [Color Palette](#5-color-palette)
6. [Spacing and Layout Scale](#6-spacing-and-layout-scale)
7. [Navigation](#7-navigation)
8. [Page Structure Pattern](#8-page-structure-pattern)
9. [Component Catalogue](#9-component-catalogue)
10. [Dark Mode](#10-dark-mode)
11. [State Management](#11-state-management)
12. [API Layer](#12-api-layer)
13. [Inline Styles vs CSS Modules vs Tailwind](#13-inline-styles-vs-css-modules-vs-tailwind)
14. [Migration Guide](#14-migration-guide)

---

## 1. Philosophy

The visual identity is **OPB** — Octavio Pérez Bravo, Data & AI Strategy Architect. The design
goal is:

> "Corporate authority without excess decoration. Technical precision + executive clarity."

This translates into three practical rules applied everywhere:

**Restraint over decoration.** No gradients on fills, no shadows heavier than `0 1px 6px`,
no rounded corners above `14px`. Every decorative element — the gold eyebrow line, the grid
texture on hero sections, the ghosted large numerals — serves a structural purpose rather than
adding visual noise.

**Typography does the hierarchy work.** Two font families carry the entire visual weight.
Fraunces (a variable serif) handles titles and display text. Plus Jakarta Sans handles all
interface copy, labels, and data. Weight and size variation within these two fonts eliminates
the need for colour-based hierarchy beyond a handful of defined tokens.

**Colour signals meaning, not style.** The primary navy (`#003366`) and gold (`#c8982a`) are
brand colours. All other colours in the system are semantic — green for success, orange for
warning, red for error. Using a colour outside this system requires explicit justification.

**Navy is dominant; gold is the only structural accent.** Navy fills backgrounds, hero sections,
table headers, and primary text. Gold marks structural accent lines (card `borderTop`, stat
card `borderLeft`), eyebrows, active states, and the primary action button. Status colours
(green, orange, red) are reserved exclusively for KPI values that communicate a risk or
performance signal — they are **never** applied to structural elements like card borders,
eyebrow bars, or categorical labels. The hierarchy is: navy first, gold second, status colours
only when the data demands them.

---

## 2. Technology Choices

### React + TypeScript

React is used because concurrent rendering and the hooks model support real-time update
patterns (WebSocket streams, live dashboards) without class component lifecycle management.
Functional components only — no class components exist anywhere in the codebase.

TypeScript strict mode (`"strict": true`) is required. Every API response, store slice, and
component prop is statically typed. A field mismatch between an interface and the actual API
response shape produces `undefined` at runtime but passes TypeScript's type checker — strict
typing and exact interface matching catch this class of bug at compile time.

### Next.js (App Router) — or Vite for SPAs

For server-rendered apps use **Next.js 15+** (App Router). For pure client-side SPAs use
**Vite 5**. The proxy configuration forwards `/api/*` and `/ws/*` to the backend:

```ts
// vite.config.ts — proxy section (SPA only)
proxy: {
  '/api': { target: 'http://localhost:8000', changeOrigin: true, rewrite: (path) => path.replace(/^\/api/, '') },
  '/ws':  { target: 'ws://localhost:8000',  ws: true },
}
```

For Next.js, server-side fetches use the internal Docker/service URL (`http://service:port`);
client-side fetches use `NEXT_PUBLIC_API_URL` (the public-facing URL).

### Zustand (state management)

Redux is over-engineered for typical dashboard scope. Zustand has no Provider wrapping, no
action creators, and no reducers. Standard stores to create per project:

- `authStore` — holds the JWT token, user object (`email`, `role`), and `clearAuth()`
- Any domain-specific form or wizard store for multi-step flows

All other state is local to the component via `useState`. Data fetching is done directly with
`useEffect` + the `api` service layer unless the project's data volume and update frequency
warrant a caching library like React Query.

### No external UI library

No Shadcn, no MUI, no Ant Design. All components are written from scratch using inline styles
and the design token system. This maintains full design fidelity to the OPB brand system
without fighting against a third-party component library's opinions on spacing, colour, or
typography.

---

## 3. Design Tokens

All values live in `src/styles/globals.css` (or `tokens.css`) as CSS custom properties.
**No value is ever hardcoded anywhere else in the application.** Using a raw hex colour in
a component is a bug.

```css
:root {
  /* Colour — brand */
  --primary:    #003366;   /* Navy — primary brand + nav background */
  --primary-80: #1a4d80;   /* Navy 80% — hover states, secondary headers */
  --primary-60: #336699;   /* Navy 60% — links, mid-weight accents */
  --primary-30: #99bbdd;   /* Navy 30% — decorative accents, diagram arrows */
  --primary-10: #e0eaf4;   /* Navy 10% — card backgrounds, table stripes */
  --gold:       #c8982a;   /* Brand gold — eyebrows, accent bars, borders */
  --gold-light: #e8c46a;   /* Gold light — active nav links, hero italic text */
  --dark:       #1c1c2e;   /* Near-black — primary body text */
  --mid:        #6b7280;   /* Grey — secondary text, captions, metadata */
  --light:      #f4f6f9;   /* Off-white — page background, card backgrounds */
  --white:      #ffffff;   /* Pure white — card surfaces */

  /* Colour — semantic status */
  --status-green:  #27b97c;   /* Completed, positive, on-track */
  --status-red:    #e03448;   /* Error, alert, critical */
  --status-orange: #f07020;   /* Warning, pending, at-risk */
  --status-purple: #7c4dbd;   /* Analytics, projections, AI */
  --status-blue:   #003366;   /* Primary, corporate default */

  /* Typography */
  --fd: 'Fraunces', Georgia, serif;       /* Display / titles */
  --fb: 'Plus Jakarta Sans', sans-serif;  /* Interface / body */

  /* Spacing (8-point grid) */
  --space-4:  4px;  --space-8:  8px;  --space-12: 12px;
  --space-16: 16px; --space-24: 24px; --space-32: 32px;
  --space-40: 40px; --space-48: 48px; --space-64: 64px;

  /* Border radius */
  --radius-sm:   6px;
  --radius-md:   12px;
  --radius-lg:   14px;
  --radius-pill: 20px;

  /* Shadows */
  --shadow-card: 0 1px 4px rgba(0, 51, 102, 0.08);
  --shadow-soft: 0 1px 6px rgba(0, 51, 102, 0.09);

  /* Layout */
  --max-width-content:   1200px;   /* Reading-oriented pages */
  --max-width-dashboard: 1300px;   /* Data-heavy dashboard pages */
  --nav-height: 52px;
}
```

### Semantic status colour variants

Each status colour has a `*-bg` (light background) and `*-text` (readable text on white)
variant for use in badges and pills. These are not CSS custom properties — they are hardcoded
in badge style objects because they are always used as matched pairs:

| Signal | Dot / bar | Badge bg | Badge text |
|---|---|---|---|
| Success / healthy | `#27b97c` | `#E0F7EF` | `#0D5C3A` |
| Warning / pending | `#f07020` | `#FEF0E6` | `#7A3800` |
| Error / critical  | `#e03448` | `#FDEAEA` | `#7A1020` |
| Running / info    | `#003366` | `#E0EAF4` | `#001F4D` |

---

## 4. Typography System

Two fonts are loaded via a single Google Fonts `<link>` in the document `<head>`:

```html
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;1,300&family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,400;0,9..144,600;1,9..144,300;1,9..144,400&display=swap" rel="stylesheet">
```

### Fraunces — display font (`var(--fd)`)

Used exclusively for titles, hero headings, and large decorative numerals. Never used for body
copy or interface labels.

| Context | Size | Weight | Notes |
|---|---|---|---|
| Hero / page titles | 36–48px | 300 | Key word in italic + `var(--gold-light)` |
| Section titles (H2) | 22px | 300 | Italic on emphasis word when needed |
| Widget / card headers | 16–20px | 300–400 | |
| KPI callout values | 28–34px | 300 | `var(--dark)` on cards, `var(--gold-light)` on dark backgrounds |
| Decorative numerals | 44px | 300 | `var(--primary-30)` — ghosted watermark, not content |

**Critical rule:** Never bold Fraunces. Use weight 300 or 400. The optical size axis (`opsz`)
adjusts automatically; combined with italic for emphasis, it renders at sufficient weight
without needing 600+.

### Plus Jakarta Sans — interface font (`var(--fb)`)

Used for everything else: body copy, labels, buttons, captions, table cells, form inputs.

| Context | Size | Weight | Style |
|---|---|---|---|
| Body text | 13–15px | 400 | `line-height: 1.7`, `color: var(--dark)` or `#475569` |
| Section captions | 13–14px | 400 | `color: var(--mid)` |
| Labels / eyebrows | 9–11px | 500–700 | UPPERCASE, `letter-spacing: 2–4px` |
| Button text | 9–11px | 700 | UPPERCASE, `letter-spacing: 1.5px` |
| Table headers | 10px | 600 | UPPERCASE, `letter-spacing: 2px` |
| Metadata / timestamps | 10–12px | 400 | `color: var(--mid)` |
| Code / endpoints | Courier New, 12–13px | 400 | Not Plus Jakarta — inline code uses `Courier New` |

**Letter spacing rule:** Any text rendered at ≤11px uppercase **must** have `letterSpacing`
of at least `2px`. Below 11px, zero letter spacing makes uppercase text illegible.

### Italic as a signature mark

The italic Fraunces variant is used in one specific pattern: the key word or phrase in a hero
title is wrapped in `<em>` with `fontStyle: 'italic'` and `color: 'var(--gold-light)'`. This
is the single most identifiable visual element of the OPB brand system.

```jsx
// Hero title
<h1>Build before you <em style={{ fontStyle: 'italic', color: 'var(--gold-light)' }}>ship.</em></h1>

// Section sub-title
<h2>Data <em style={{ fontStyle: 'italic', color: 'var(--gold-light)' }}>insights</em></h2>
```

---

## 5. Color Palette

### How to use primary colours

| Token | Where |
|---|---|
| `var(--primary)` | Nav background, hero backgrounds, table `<thead>` background |
| `var(--primary-80)` | Hover on dark surfaces |
| `var(--primary-60)` | Links, mid-weight code labels, stack table accents |
| `var(--primary-30)` | Diagram arrows, decorative borders, ghosted elements |
| `var(--primary-10)` | Card background alternate, table row stripes, divider lines |

### How to use gold

| Token | Where |
|---|---|
| `var(--gold)` | Eyebrow lines and text, `borderLeft` on hero stat cards (always 2–3px), `borderTop` on KPI/score cards (always 3px), accent bars, left-border callouts |
| `var(--gold-light)` | Active nav links, hero italic words, stat values on dark backgrounds |

Gold is never used as a button background except for primary action buttons, where it signals
the highest-priority action on the page.

**`borderLeft` rule:** Every stat card rendered inside a hero section uses
`borderLeft: '2px solid var(--gold)'` — no exceptions. Status colours are never used for
this structural accent, regardless of the metric's risk level.

**`borderTop` rule:** Every KPI card and score card in the body uses
`borderTop: '3px solid var(--gold)'` — no exceptions. If the metric value represents a
critical risk, the *value text* colour may contextually use a status colour. The border
itself always stays gold.

### Data visualisation series

When multiple data series need distinct colours in charts, use the navy gradient sequence,
with gold reserved for the highest-impact or highlight series:

1. `#003366` — navy (primary, dominant)
2. `#1a4d80` — navy 80%
3. `#336699` — navy 60%
4. `#4d7099` — navy muted
5. `#99bbdd` — navy 30% (lightest)
6. `#c8982a` — gold (highlight / top bucket / emphasis only)

**Do not use green, purple, orange, or pink for categorical chart series.** Those are semantic
status colours — their presence in a chart implies a specific meaning (success, analytics,
warning, error). Using them as arbitrary data series creates false associations. The navy
gradient provides sufficient visual distinction for 3–5 series; gold marks the one series
that deserves emphasis.

For SVG charts specifically: `fill=""` and `stroke=""` attributes cannot use CSS custom
properties. Use the raw hex values from the series above. Any hex value not in this list is
a bug.

### Color hierarchy and restriction rules

Three tiers, strict priority:

| Tier | Colours | Purpose |
|---|---|---|
| **1 — Navy (dominant)** | `--primary`, `--primary-80`, `--primary-60`, `--primary-30`, `--primary-10` | Structural mass: hero backgrounds, nav, table headers, body text, decorative accents |
| **2 — Gold (structural accent)** | `--gold`, `--gold-light` | Accent-only: eyebrow bars, `borderLeft` on stat cards, `borderTop` on KPI cards, active states, primary action button |
| **3 — Status colours (data signals only)** | `--status-green`, `--status-red`, `--status-orange`, `--status-purple` | KPI value text and status badges when the value communicates a specific risk or performance signal |

**Never apply a Tier 3 status colour to a structural element.** Card `borderTop`,
card `borderLeft`, eyebrow bars, section dividers, and categorical chart labels are
structural — they must use Tier 1 or Tier 2 colours only. Status colours may appear in:
value text, progress bars, risk indicators, and status badges.

**Permitted and prohibited use matrix:**

| Element | Permitted | Prohibited |
|---|---|---|
| Hero stat card `borderLeft` | `var(--gold)` only | Any status colour, any navy variant |
| KPI / score card `borderTop` | `var(--gold)` only | Any status colour, any navy variant |
| KPI value text | `var(--gold-light)` on dark; `var(--dark)` on light; status colour if critical KPI | Purple, orange, pink as decoration |
| Categorical chart series | Navy gradient + gold highlight | Green, purple, orange, pink |
| Status badge dot + label | Status colours matched to semantic meaning | Gold or navy as badge colour |
| Section eyebrow bar | `var(--gold)` / `var(--gold-light)` | Any status colour |
| Nav active state | `var(--gold-light)` | Green, red, purple |

---

## 6. Spacing and Layout Scale

### Spacing tokens

The spacing scale is an 8-point grid: `4 / 8 / 12 / 16 / 24 / 32 / 40 / 48 / 64 / 96px`.
Use `var(--space-N)` for margins and paddings in CSS. In inline styles, use the raw pixel
value but always from this scale — no `7px`, `11px`, or arbitrary values.

### Content width constraints

Every page body wraps its content with a `maxWidth` constraint and `margin: 0 auto`:

- `var(--max-width-dashboard)` — 1300px for data-heavy pages
- `var(--max-width-content)` — 1200px for reading-oriented pages

### Grid patterns

| Columns | Use case |
|---|---|
| 2-col `1fr 1fr` | Side-by-side charts, compare panels |
| 3-col `repeat(3, 1fr)` | Value pillar cards, feature descriptions |
| 4-col `repeat(4, 1fr)` | KPI stat rows |
| `300px 1fr` | Selection list + detail / chart panels |
| `repeat(auto-fill, minmax(280px, 1fr))` | Responsive card grids |

### Standard card padding

Cards use `28px` padding. Hero sections and information pages use `32px` card padding.
Never less than `20px` for interactive cards; never more than `40px`.

---

## 7. Navigation

### Structure

The navigation bar is sticky at the top, `52px` tall (`var(--nav-height)`), on a navy
background with a 12px backdrop blur and a subtle bottom border:

```
[OPB monogram] ············ [App title] ······ [Nav links] [User info] [Logout] [Theme]
left                         centre-ish                                          right
```

**Left:** OPB monogram rendered in Fraunces — `O` in `var(--white)` weight 300, `PB` in
italic `var(--gold-light)` weight 300. Always inline styles, never Tailwind or className.
The monogram is purely decorative (no click handler).

**Centre:** App title in 9px uppercase Plus Jakarta, `letter-spacing: 3px`,
`rgba(255,255,255,0.4)`.

**Right cluster:** Nav page links → user metadata → Logout button → Theme toggle.

### Nav links — inline style pattern

Nav links are `<button>` elements. Active state is applied via a ternary spread — never via
a className or CSS class toggle:

```tsx
const navLinkBase: React.CSSProperties = {
  background: 'none',
  backgroundColor: 'transparent',   // explicit — prevents browser default white bg on re-render
  border: 'none',
  color: 'rgba(255,255,255,0.45)',
  cursor: 'pointer',
  fontFamily: 'var(--fb)',
  fontSize: 9,
  letterSpacing: '2px',
  textTransform: 'uppercase',
  padding: '5px 8px',
  borderRadius: 6,
  transition: 'color 0.15s, background-color 0.15s',
}

const navLinkActive: React.CSSProperties = {
  color: 'var(--gold-light)',
  backgroundColor: 'rgba(201,168,76,0.12)',
}

// Usage
<button style={currentPage === id ? { ...navLinkBase, ...navLinkActive } : navLinkBase}>
  {label}
</button>
```

**Why `backgroundColor: 'transparent'` in base?** Without it, browsers apply their default
button background (white in light mode) when the component re-renders from active to inactive.
The explicit transparent value prevents the white flash.

### Page routing

For SPAs, manage navigation with a single `useState<Page>` in `App.tsx`. The `Page` union
type lists every valid route. For Next.js, use the App Router file system. The nav link
active state is determined by comparing the current route to the link's target.

Adding a new page (SPA pattern) requires:

1. Adding the string literal to the `Page` union
2. Adding a `case` to the `renderPage()` switch
3. Adding the entry to the `pages` array in `Nav`

---

## 8. Page Structure Pattern

Every page follows the same vertical structure:

```
┌──────────────────────────────────┐
│  HERO SECTION (dark navy)        │  ← always dark, grid texture
│  Eyebrow (light variant)         │
│  H1 with italic gold keyword     │
│  Subtitle in rgba white          │
│  [Optional: stat row / tab bar]  │
├──────────────────────────────────┤
│  BODY (var(--light) background)  │
│                                  │
│  [KPI row if applicable]         │
│                                  │
│  SECTION                         │
│    Eyebrow (dark variant)        │
│    H2 section title              │
│    Body content                  │
│                                  │
│  SECTION                         │
│    ...                           │
│                                  │
└──────────────────────────────────┘
│  FOOTER (dark navy)              │
└──────────────────────────────────┘
```

### Hero section

```tsx
const heroStyle: React.CSSProperties = {
  backgroundColor: 'var(--primary)',
  backgroundImage: `
    linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)
  `,
  backgroundSize: '48px 48px',
  padding: '56px 48px',   // use '48px 48px 0' when a tab bar attaches at the bottom
}
```

The `backgroundImage` grid texture is the same across every hero on every page. The grid
lines are `rgba(255,255,255,0.025)` — barely visible, but they give the navy a woven
structure at high brightness.

**`padding-bottom: 0`** when the hero has a tab bar at its bottom edge. The tab bar's
`marginBottom: -1` on the active tab merges its bottom border with the section divider,
creating a visual connection between the hero and the body. Otherwise use `padding: '56px 48px'`.

### Body section

The body sits on `var(--light)`. Each section uses:

```tsx
const section: React.CSSProperties = {
  maxWidth: 'var(--max-width-dashboard)',
  margin: '0 auto',
  padding: '40px 48px',   // up to 56px for spacious sections
}
```

### Eyebrow placement rule

- On dark (hero) backgrounds → `<Eyebrow light>Label</Eyebrow>` — renders in `var(--gold-light)`
- On light (`var(--light)` or `var(--white)`) backgrounds → `<Eyebrow>Label</Eyebrow>` — renders in `var(--gold)`

**Never** use the dark variant on a light background or the light variant on a dark background.
The contrast ratios are designed for their respective contexts.

### Tab bar pattern

When a page has multiple content tabs, the tab bar sits at the bottom of the hero, visually
bridging it to the body:

```tsx
<button style={{
  // ...base styles
  borderBottom: `2px solid ${active === id ? 'var(--gold-light)' : 'transparent'}`,
  marginBottom: -1,   // merges with hero's bottom edge
  color: active === id ? 'var(--gold-light)' : 'rgba(255,255,255,0.4)',
}}>
```

---

## 9. Component Catalogue

### `Eyebrow`

Renders a gold horizontal rule + uppercase label. Props: `children`, `light?: boolean`.

```tsx
function Eyebrow({ children, light }: { children: React.ReactNode; light?: boolean }) {
  return (
    <div style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 8,
      fontSize: 9,
      fontFamily: 'var(--fb)',
      fontWeight: 500,
      letterSpacing: '4px',
      textTransform: 'uppercase',
      color: light ? 'var(--gold-light)' : 'var(--gold)',
      marginBottom: 10,
    }}>
      <div style={{ width: 24, height: 1, flexShrink: 0,
                    backgroundColor: light ? 'var(--gold-light)' : 'var(--gold)' }} />
      {children}
    </div>
  )
}
```

Eyebrow labels are max 4 words. No leading numbers (not "01 · Metrics" — just "Metrics").

### Card

No shared `Card` component exists — cards are inline style objects defined per-file as
`const card: React.CSSProperties`. The standard values are:

```tsx
const card: React.CSSProperties = {
  backgroundColor: 'var(--white)',
  borderRadius: 'var(--radius-md)',   // 12px
  padding: '28px',
  boxShadow: 'var(--shadow-card)',    // 0 1px 4px rgba(0,51,102,0.08)
  border: '1px solid var(--primary-10)',
}
```

Danger zone cards add `border: '1px solid rgba(176,53,53,0.18)'` and a reddish background
tint. Callout / note cards add `borderLeft: '3px solid var(--gold)'`.

### KPI stat card (body variant)

Used in the body area — white card with gold top accent bar. The accent is structural, not
semantic:

```tsx
function KpiCard({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'stretch', gap: 16, ...card }}>
      <div style={{ width: 3, backgroundColor: 'var(--gold)', borderRadius: 2, flexShrink: 0 }} />
      <div>
        <div style={{ fontFamily: 'var(--fd)', fontSize: 30, fontWeight: 300,
                      color: valueColor ?? 'var(--dark)' }}>{value}</div>
        <div style={{ fontFamily: 'var(--fb)', fontSize: 10, textTransform: 'uppercase',
                      letterSpacing: '3px', color: 'var(--mid)', marginTop: 5 }}>{label}</div>
      </div>
    </div>
  )
}
```

The left accent bar always uses `var(--gold)`. Do not use per-KPI status colours for the
structural accent bar, regardless of what the metric represents. If a KPI value represents
a critical risk, express it in the value text colour (`valueColor` prop) — not the bar colour.

Alternatively, implement the accent as `borderTop: '3px solid var(--gold)'` on the card
container itself — both approaches are valid.

### KPI stat (hero / banner variant)

Used inside dark hero sections — no card wrapper:

```tsx
<div style={{ borderLeft: '2px solid var(--gold)', paddingLeft: 18 }}>
  <div style={{ fontFamily: 'var(--fd)', fontSize: 34, fontWeight: 300,
                color: 'var(--gold-light)', lineHeight: 1, marginBottom: 8 }}>
    {value}
  </div>
  <div style={{ fontFamily: 'var(--fb)', fontSize: 12, color: 'rgba(255,255,255,0.5)' }}>
    {label}
  </div>
</div>
```

The `borderLeft` is always `2px solid var(--gold)`. Every hero stat card across every page
uses the same accent — do not vary by metric type, severity, or department. The value text
uses `var(--gold-light)` uniformly on dark backgrounds.

### Status badge / sentiment pill

Pill-shaped indicator with a dot + label:

```tsx
<div style={{ display: 'inline-flex', alignItems: 'center', gap: 6,
              backgroundColor: bg, borderRadius: 'var(--radius-pill)',
              padding: '3px 10px' }}>
  <div style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: dot }} />
  <span style={{ fontFamily: 'var(--fb)', fontSize: 10, fontWeight: 500,
                 color: text }}>{label}</span>
</div>
```

The `bg`, `dot`, and `text` values come from the semantic status colour system (see the
variant table in §3). Never use arbitrary values.

### Tables

All data tables follow the same pattern:

- `<thead>`: `backgroundColor: 'var(--primary)'`, `color: 'var(--white)'`, `10px uppercase`,
  `letterSpacing: '2px'`, `padding: '12px 16px'`
- `<tbody>` rows: alternating `var(--white)` / `var(--primary-10)` via `i % 2 === 0`
- Cell padding: `12px 16px`
- Sort buttons are `<th>` elements with `onClick` — the sort indicator is a plain `▾` or `▴`
  character appended to the label string

### Toast / feedback message

```tsx
function Toast({ msg, ok }: { msg: string; ok: boolean }) {
  return (
    <div style={{
      fontFamily: 'var(--fb)', fontSize: 12,
      color:           ok ? '#22943a' : '#b03535',
      backgroundColor: ok ? 'rgba(34,148,58,0.07)' : 'rgba(176,53,53,0.07)',
      border:          `1px solid ${ok ? 'rgba(34,148,58,0.2)' : 'rgba(176,53,53,0.2)'}`,
      borderRadius: 8, padding: '10px 16px', marginTop: 16,
    }}>
      {msg}
    </div>
  )
}
```

### Confirm modal

Destructive actions (delete, clear) open a confirmation modal rather than executing
immediately. The modal uses a fixed-position overlay at `zIndex: 200`:

```tsx
// Overlay
position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.45)',
display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200

// Modal panel
backgroundColor: 'var(--white)', borderRadius: 14, padding: '32px 36px',
maxWidth: 400, width: '90%', boxShadow: '0 20px 60px rgba(0,0,0,0.2)'
```

The modal has a Cancel (ghost) button and a destructive action button (red background `#b03535`).

### Decorative section numerals

Used on cards that have a numbered sequence:

```tsx
<div style={{
  fontFamily: 'var(--fd)', fontSize: 44, fontWeight: 300,
  color: 'var(--primary-30)',   // navy-tinted, not grey
  lineHeight: 1, marginBottom: 2, userSelect: 'none',
}}>
  {num}
</div>
<div style={{ width: 36, height: 3, backgroundColor: 'var(--gold)', borderRadius: 2, margin: '6px 0 12px' }} />
```

The number is decorative — it identifies the card's position without being the focal point.
`userSelect: 'none'` prevents accidental selection on click. The 3px gold accent bar sits
between the number and the title.

---

## 10. Dark Mode

### Implementation

Theme is stored in `localStorage` under the key `opb-theme`. It is read once on mount in
`useTheme.ts` and applied by setting `data-theme` on `document.documentElement`:

```ts
type Theme = 'light' | 'dark'

function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute('data-theme', theme)
  localStorage.setItem('opb-theme', theme)
}

function getInitialTheme(): Theme {
  return (localStorage.getItem('opb-theme') as Theme) ?? 'light'
}
```

CSS overrides are then applied via the attribute selector in the global stylesheet:

```css
html[data-theme="dark"] {
  --light:      #0f1117;                    /* Page background darkens */
  --white:      #1a1d27;                    /* Card surfaces darken */
  --dark:       #e2e8f0;                    /* Text lightens */
  --mid:        #8b9099;                    /* Secondary text lightens */
  --primary-10: rgba(255, 255, 255, 0.07);  /* Subtle light tint replaces navy tint */
  --shadow-card: 0 1px 4px rgba(0, 0, 0, 0.35);
  --shadow-soft: 0 1px 6px rgba(0, 0, 0, 0.3);
}
```

The primary navy, gold, and status colours are **not** overridden in dark mode — they remain
the same. The nav, heroes, and footers use the navy background in both modes; dark mode only
affects body (`--light`) and card (`--white`) surfaces.

### Default theme

The application defaults to **light mode**. `getInitialTheme()` returns `'light'` when no
stored preference exists — the OS `prefers-color-scheme` media query is ignored. The user
toggles with the `◑ Dark` / `☀ Light` button in the nav bar.

### What components need to do to support dark mode

Because all colours use `var(--token)` references, most components get dark mode for free.
The only patterns to watch:

- **Hardcoded `#ffffff`**: Use `var(--white)` — surfaces that use literal `#ffffff` will
  not darken in dark mode.
- **Hardcoded `#f4f6f9`**: Use `var(--light)` instead.
- **Hardcoded `rgba(0,51,102,0.XX)`**: For subtle navy tints, use `var(--primary-10)`. In
  dark mode, `--primary-10` is overridden to a light white tint that achieves the same
  visual effect on dark surfaces.

---

## 11. State Management

### Auth store

```ts
interface AuthState {
  token: string | null
  user: { email: string; role: string } | null
  setAuth: (token: string, user: { email: string; role: string }) => void
  clearAuth: () => void
}
```

The token is persisted to `localStorage` under an app-specific key (e.g., `opb_auth_token`).
`clearAuth()` removes both the store state and the `localStorage` entry. The `user` object
is populated from the JWT payload on login.

The root layout or `App.tsx` reads `token` to decide whether to render the login page or
the main app.

### Domain stores

Create one Zustand store per multi-step flow or complex form (e.g., a wizard, a campaign
launcher, a configuration builder). Reset the store when the user exits the flow. Keep
stores flat — nested objects create unnecessarily verbose update functions.

### No server state library by default

Each component fetches directly from the `api` service on mount via `useEffect`. Add React
Query or SWR only when the project has frequent background updates, pagination, or cache
invalidation requirements that make manual `useEffect` fetching unwieldy.

---

## 12. API Layer

All HTTP calls go through a dedicated `api` service module. **No component imports `fetch`
directly.** This is enforced by convention, not tooling.

### Structure

```ts
// src/lib/api.ts (or src/services/api.ts)
export const api = {
  health: () => request<HealthResponse>('/health'),

  things: {
    list:   ()     => request<{ items: Thing[] }>('/things?size=100').then((r) => r.items),
    get:    (id)   => request<Thing>(`/things/${id}`),
    create: (body) => request<Thing>('/things', { method: 'POST', body }),
    delete: (id)   => request<void>(`/things/${id}`, { method: 'DELETE' }),
  },
}
```

### Pagination unwrapping

All list endpoints on the backend return `{ items: T[], total, page, size }`. The `api` layer
unwraps this transparently — calling code receives `T[]` directly. This avoids `.items`
access being scattered across every component.

### Auth headers

The `request()` function reads the auth token from `localStorage` (key `opb_auth_token`)
and adds `Authorization: Bearer <token>` to every request. Skip the header when no token
exists (unauthenticated routes).

### Interface discipline

TypeScript interfaces in `api.ts` must exactly match the backend response models. A field
that exists in the interface but not in the API response will be `undefined` at runtime
and typed as its declared type — TypeScript will not catch this. Before adding a field to
an interface, verify it in the actual API response JSON.

---

## 13. Inline Styles vs CSS Modules vs Tailwind

The OPB design system uses **inline styles exclusively**. No Tailwind, no CSS Modules,
no styled-components.

### Rationale

1. **Design token enforcement**: Inline styles that reference `var(--token)` names make it
   immediately visible when a hardcoded value is used instead. In a Tailwind class like
   `text-blue-800`, the actual hex value is invisible and cannot be audited.

2. **No CSS specificity battles**: Every style is scoped to the exact element it is applied
   to. There is no class specificity cascade to debug.

3. **TypeScript coverage**: `React.CSSProperties` catches misspelled property names and
   invalid values at compile time. `className` strings have no type safety.

4. **Design fidelity**: The OPB system uses precise values (e.g., `rgba(201,168,76,0.12)`
   for active nav backgrounds) that have no Tailwind equivalent. Approximating them with
   utility classes breaks the visual system.

### Style object pattern

Styles are defined as `const` objects at the top of each file, outside the component
function. This prevents recreation on every render:

```tsx
// Define outside component
const card: React.CSSProperties = {
  backgroundColor: 'var(--white)',
  borderRadius: 'var(--radius-md)',
  padding: '28px',
  boxShadow: 'var(--shadow-card)',
}

// Use in component
<div style={card}>...</div>

// Extend for variants
<div style={{ ...card, borderLeft: '3px solid var(--gold)' }}>...</div>
```

---

## 14. Migration Guide

How to apply the OPB design system to a new or existing React application.

### Step 1 — Fonts

Add to `<head>` in the document root (`index.html`, `layout.tsx`, etc.):

```html
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;1,300&family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,400;0,9..144,600;1,9..144,300;1,9..144,400&display=swap" rel="stylesheet">
```

### Step 2 — Tokens

Copy the CSS custom properties block from §3 into your global stylesheet and import it once
at the root of the application. Do not modify the token values — they are the brand.

### Step 3 — Base reset

Add to the global stylesheet after the token block:

```css
*, *::before, *::after { box-sizing: border-box; }

body {
  margin: 0;
  padding: 0;
  background-color: var(--light);
  font-family: var(--fb);
  font-size: 15px;
  line-height: 1.7;
  color: var(--dark);
  -webkit-font-smoothing: antialiased;
}
```

### Step 4 — Copy the Eyebrow component

Implement the `Eyebrow` component (pattern in §9). It has no dependencies beyond React. Use
it as the section label on every content section.

### Step 5 — Build the Nav

Follow the Nav pattern from §7:

```tsx
// Minimum required nav structure
<nav style={navStyle}>                               {/* sticky, dark navy, 52px */}
  <span>
    <span style={{ fontFamily: 'var(--fd)', fontSize: 20, fontWeight: 300,
                   color: 'var(--white)' }}>O</span>
    <em style={{ fontFamily: 'var(--fd)', fontSize: 20, fontWeight: 300,
                 fontStyle: 'italic', color: 'var(--gold-light)' }}>PB</em>
  </span>
  <span style={{ fontFamily: 'var(--fb)', fontSize: 9, letterSpacing: '3px',
                 textTransform: 'uppercase', color: 'rgba(255,255,255,0.4)' }}>
    App Name
  </span>
  <div style={{ display: 'flex', gap: 4 }}>
    {pages.map(({ id, label }) => (
      <button key={id}
              style={currentPage === id ? { ...navLinkBase, ...navLinkActive } : navLinkBase}
              onClick={() => navigate(id)}>
        {label}
      </button>
    ))}
    {/* Theme toggle, logout, user info as needed */}
  </div>
</nav>
```

**Critical:** Include `backgroundColor: 'transparent'` in `navLinkBase`. Without it,
inactive nav buttons show a white background in light mode when transitioning from active
state.

### Step 6 — Build a page

Every page follows this template:

```tsx
export default function MyPage() {
  return (
    <div>
      {/* 1. Hero */}
      <div style={heroStyle}>
        <div style={{ maxWidth: 'var(--max-width-dashboard)', margin: '0 auto' }}>
          <Eyebrow light>Section eyebrow</Eyebrow>
          <h1 style={{ fontFamily: 'var(--fd)', fontSize: 36, fontWeight: 300,
                       color: 'var(--white)' }}>
            Title with <em style={{ fontStyle: 'italic', color: 'var(--gold-light)' }}>italic</em>
          </h1>
          <p style={{ fontFamily: 'var(--fb)', fontSize: 14,
                      color: 'rgba(255,255,255,0.55)' }}>
            Subtitle text.
          </p>
        </div>
      </div>

      {/* 2. Body */}
      <div style={{ backgroundColor: 'var(--light)', minHeight: '70vh' }}>
        <div style={{ maxWidth: 'var(--max-width-dashboard)', margin: '0 auto',
                      padding: '40px 48px' }}>
          <div style={card}>
            <Eyebrow>Section label</Eyebrow>
            <h2 style={{ fontFamily: 'var(--fd)', fontSize: 22, fontWeight: 300,
                         color: 'var(--dark)' }}>
              Section title
            </h2>
            <p style={{ fontFamily: 'var(--fb)', fontSize: 14,
                        color: '#475569', lineHeight: 1.75 }}>
              Body text.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
```

### Step 7 — Wire routing

For SPAs using `useState`-based routing in `App.tsx`:

```tsx
export type Page = 'home' | 'detail' | 'login'

export default function App() {
  const [page, setPage] = useState<Page>('home')

  const renderPage = () => {
    switch (page) {
      case 'home':   return <HomePage />
      case 'detail': return <DetailPage />
      case 'login':  return <LoginPage />
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Nav currentPage={page} onNavigate={setPage} />
      <main style={{ flex: 1 }}>{renderPage()}</main>
    </div>
  )
}
```

For Next.js, use `usePathname()` from `next/navigation` to determine the active nav link.

### Step 8 — API service

Create `src/lib/api.ts` (or `src/services/api.ts`):

1. A base `request<T>(path, options?)` function that handles auth headers, JSON
   serialisation, and error throwing
2. Domain-grouped methods: `api.things.list()`, `api.things.create(body)`, etc.
3. Pagination unwrapping done inside `api.ts` — components receive `T[]`, not `{ items: T[] }`
4. TypeScript interfaces that exactly match the backend response shapes

### Step 9 — Dark mode

Implement `useTheme.ts`:

```ts
import { useState, useEffect } from 'react'

type Theme = 'light' | 'dark'

export function useTheme() {
  const [theme, setTheme] = useState<Theme>('light')

  useEffect(() => {
    const stored = localStorage.getItem('opb-theme') as Theme | null
    const initial = stored ?? 'light'
    setTheme(initial)
    document.documentElement.setAttribute('data-theme', initial)
  }, [])

  function toggle() {
    const next: Theme = theme === 'light' ? 'dark' : 'light'
    setTheme(next)
    document.documentElement.setAttribute('data-theme', next)
    localStorage.setItem('opb-theme', next)
  }

  return { theme, toggle }
}
```

Add the theme toggle button to the Nav right cluster. The dark mode CSS block in the global
stylesheet (§10) handles the rest automatically.
