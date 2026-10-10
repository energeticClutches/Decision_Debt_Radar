---
name: Decision Debt Radar
colors:
  surface: '#f8f9ff'
  surface-dim: '#cbdbf5'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eff4ff'
  surface-container: '#e5eeff'
  surface-container-high: '#dce9ff'
  surface-container-highest: '#d3e4fe'
  on-surface: '#0b1c30'
  on-surface-variant: '#434655'
  inverse-surface: '#213145'
  inverse-on-surface: '#eaf1ff'
  outline: '#737686'
  outline-variant: '#c3c6d7'
  surface-tint: '#0053db'
  primary: '#004ac6'
  on-primary: '#ffffff'
  primary-container: '#2563eb'
  on-primary-container: '#eeefff'
  inverse-primary: '#b4c5ff'
  secondary: '#4b41e1'
  on-secondary: '#ffffff'
  secondary-container: '#645efb'
  on-secondary-container: '#fffbff'
  tertiary: '#005a89'
  on-tertiary: '#ffffff'
  tertiary-container: '#0073ae'
  on-tertiary-container: '#e7f2ff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dbe1ff'
  primary-fixed-dim: '#b4c5ff'
  on-primary-fixed: '#00174b'
  on-primary-fixed-variant: '#003ea8'
  secondary-fixed: '#e2dfff'
  secondary-fixed-dim: '#c3c0ff'
  on-secondary-fixed: '#0f0069'
  on-secondary-fixed-variant: '#3323cc'
  tertiary-fixed: '#cce5ff'
  tertiary-fixed-dim: '#93ccff'
  on-tertiary-fixed: '#001d31'
  on-tertiary-fixed-variant: '#004b73'
  background: '#f8f9ff'
  on-background: '#0b1c30'
  surface-variant: '#d3e4fe'
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 2rem
    fontWeight: '600'
    lineHeight: 2.5rem
    letterSpacing: -0.025em
  headline-xl-mobile:
    fontFamily: Inter
    fontSize: 1.5rem
    fontWeight: '600'
    lineHeight: 2rem
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 1.5rem
    fontWeight: '600'
    lineHeight: 2rem
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 1.25rem
    fontWeight: '600'
    lineHeight: 1.75rem
    letterSpacing: -0.015em
  headline-sm:
    fontFamily: Inter
    fontSize: 1rem
    fontWeight: '600'
    lineHeight: 1.5rem
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Inter
    fontSize: 1rem
    fontWeight: '400'
    lineHeight: 1.5rem
    letterSpacing: -0.005em
  body-md:
    fontFamily: Inter
    fontSize: 0.875rem
    fontWeight: '400'
    lineHeight: 1.25rem
    letterSpacing: 0em
  body-sm:
    fontFamily: Inter
    fontSize: 0.75rem
    fontWeight: '400'
    lineHeight: 1rem
    letterSpacing: 0em
  label-md:
    fontFamily: Inter
    fontSize: 0.8125rem
    fontWeight: '500'
    lineHeight: 1.125rem
    letterSpacing: 0em
  label-sm:
    fontFamily: Inter
    fontSize: 0.6875rem
    fontWeight: '600'
    lineHeight: 0.875rem
    letterSpacing: 0.06em
  mono-metric-lg:
    fontFamily: Inter
    fontSize: 1.75rem
    fontWeight: '600'
    lineHeight: 2rem
    letterSpacing: -0.02em
  mono-metric-md:
    fontFamily: Inter
    fontSize: 0.875rem
    fontWeight: '500'
    lineHeight: 1.25rem
    letterSpacing: -0.01em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-desktop: 1.5rem
  margin: 1rem
  margin-desktop: 2rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2rem
---

## Brand & Style

The design system embodies analytical precision, calm authority, and high-velocity clarity. Built for executive operators, engineering leaders, and risk architects, the interface eschews superficial flash in favor of an engineered workspace inspired by high-leverage tools like Linear, Datadog, and the Stripe Dashboard.

The visual ethos blends **Corporate Modernism** with **Analytical Precision**:
- **Clarity over Clutter:** High-density data matrices live alongside generous structural margins, preventing cognitive fatigue during critical operational reviews.
- **De-escalated Color Hierarchy:** Debt scores and backlog velocity eschew alarming, visceral red/green gamification. Instead, debt severity scales across an architectural slate-to-indigo progression, reserving alert states strictly for system interrupts and acute operational blockers.
- **Mechanical Craft:** Every element aligns to a deterministic grid with crisp hairline borders, sub-pixel rendering considerations, and subtle single-tier depth.

## Colors

The palette is engineered for prolonged data analysis with rigorous WCAG AAA compliance across foundational text elements and AA compliance for active accents.

### Core Canvas & Structure
- **App Canvas Base:** `#f8fafc` (Cool slate canvas background providing contrast against content surfaces)
- **Primary Surface:** `#ffffff` (Pure white containers, cards, tables, and overlays)
- **Sub-surface / Table Headers:** `#f1f5f9` (Neutral slate tint for column headers, toolbars, and inactive track rails)
- **Hairline Borders:** `#e2e8f0` (Default structure rule) and `#cbd5e1` (Interactive or active division rule)

### Accent & Primary Drivers
- **Primary Brand / Action:** `#2563eb` (Interactive blue for primary actions, focused tabs, active selections)
- **Primary Pressed / Hover:** `#1d4ed8` (Deepened cobalt state)
- **Subtle Action Tint:** `#eff6ff` (Light cobalt flood for selection states, active navigation pills, and hover wells)

### Decision Debt Severity Spectrum (Non-Gamified Banding)
Debt metrics rely entirely on a cool-to-deep continuum rather than traffic-light red/green conventions:
- **Band 0 (Negligible):** `#94a3b8` (Slate 400 fill, `#f8fafc` background)
- **Band 1 (Nominal):** `#64748b` (Slate 500 fill, `#f1f5f9` background)
- **Band 2 (Accumulating):** `#6366f1` (Indigo 500 fill, `#eef2ff` background)
- **Band 3 (Severe / Critical Debt):** `#4338ca` (Indigo 700 fill, `#e0e7ff` background)

### Operational Alerts & Indicators
Used selectively for status badges, system health, and callout callouts (featuring structural 3px left borders):
- **Warning / Divergence:** `#f59e0b` (Amber accent, `#fffbeb` surface, `#b45309` text)
- **Critical Failure / Blocker:** `#e11d48` (Rose accent, `#fff1f2` surface, `#be123c` text)
- **Informational / Telemetry:** `#0284c7` (Sky accent, `#f0f9ff` surface, `#0369a1` text)
- **Resolved / Steady:** `#059669` (Emerald accent, `#ecfdf5` surface, `#047857` text)

## Typography

The typography strategy leverages **Inter** throughout all tiers to guarantee seamless weight transitions and maximum rendering crispness across diverse pixel densities.

### Rules & Formatting
- **Tabular Figures (`tabular-nums`):** All timestamps, debt scores, metric deltas, currency, and data table columns must mandate `font-variant-numeric: tabular-nums`. This prevents layout shifts across dynamic dashboard refreshes.
- **Micro-Labels & Kicker Tracking:** Section sub-headers, table column metadata, and card category pills utilize `label-sm` with a strict `+0.06em` letter-spacing and uppercase transform for high-density scanning.
- **Contrast Ratios:** Primary typography maps to `#0f172a` (Slate 900), secondary context strings to `#475569` (Slate 600), and tertiary/inactive labels to `#94a3b8` (Slate 400).

## Layout & Spacing

The layout structure implements an uncompromising **8px base grid** (with a secondary 4px half-step for micro-alignments, chip insets, and icon locks).

### Grid Infrastructure
- **Desktop (>= 1280px):** 12-column responsive fluid grid with fixed side utility panel (260px or 64px collapsed). Canvas outer margin defaults to `margin-desktop` (32px / `2rem`), with column gutters fixed at `gutter-desktop` (24px / `1.5rem`).
- **Tablet (768px - 1279px):** 8-column layout with 16px gutters and margins. Navigation collapses to top bar with slide-out overlay.
- **Mobile (< 768px):** 4-column single-stack arrangement, 16px margins, vertical card stacking.

### Spacing Application Standards
- **Component Insets (`space-sm` / `space-md`):** Buttons, inputs, and list cells leverage vertical `0.5rem` (`space-sm`) and horizontal `0.75rem` or `1rem` (`space-md`).
- **Container Architecture (`space-lg` / `space-xl`):** Card inner padding maintains uniform `1.25rem` (20px) or `1.5rem` (`space-lg`). Card-to-card stack spacing maintains `1rem` (`space-md`) on analytics views.

## Elevation & Depth

Visual separation relies on sharp boundary lines rather than heavy artificial shadows. The elevation hierarchy is quiet and restrained.

### Tiered Elevation Model
- **Level 0 (Canvas Base):** Surface `#f8fafc`. Flush, structural foundation.
- **Level 1 (Default Surface / Data Cards):** Background `#ffffff`, structural hairline border `1px solid #e2e8f0`, finished with an ultra-subtle directional ground shadow: `0 1px 3px 0 rgba(0, 0, 0, 0.05), 0 1px 2px -1px rgba(0, 0, 0, 0.05)`.
- **Level 2 (Hovered Surface / Dropdown Menus):** Background `#ffffff`, border `1px solid #cbd5e1`, elevated shadow: `0 4px 6px -1px rgba(0, 0, 0, 0.07), 0 2px 4px -2px rgba(0, 0, 0, 0.05)`.
- **Level 3 (Modals / Floating Command Bars / Slide-outs):** Background `#ffffff`, border `1px solid #cbd5e1`, deep focus shadow: `0 10px 15px -3px rgba(0, 0, 0, 0.08), 0 4px 6px -4px rgba(0, 0, 0, 0.03)`. Backdropped by `rgba(15, 23, 42, 0.4)` with an optional `backdrop-filter: blur(4px)`.

## Shapes

The design system employs a calibrated corner language to maintain an architectural, technical aesthetic:

- **Cards & Primary Modules:** Standardized to `0.625rem - 0.75rem` (10px–12px) border radius (`rounded-lg` token), striking the exact balance between modern enterprise SaaS interfaces and structured density.
- **Controls, Input Fields & Buttons:** Standardized to `0.375rem` (6px) or `0.5rem` (8px). This creates structural harmony within larger parent cards.
- **Badges, Status Chips & Metric Tags:** Configured as `0.25rem` (4px) micro-rectangles or fully rounded pill tags (`9999px`) depending on context: categorical labels use micro-rectangles; user presence and state badges use pills.

## Components

### Buttons
- **Primary:** Background `#2563eb`, text `#ffffff`, border `1px solid #1d4ed8`, radius `6px`, height `36px` (`32px` in compact tables). Hover: `#1d4ed8`. Active: scale 0.99.
- **Secondary / Default:** Background `#ffffff`, text `#0f172a`, border `1px solid #e2e8f0`, shadow `0 1px 2px 0 rgba(0,0,0,0.04)`. Hover: background `#f8fafc`, border `#cbd5e1`.
- **Ghost:** Background transparent, text `#475569`. Hover: background `#f1f5f9`, text `#0f172a`.
- **Destructive:** Background `#ffffff`, text `#e11d48`, border `1px solid #fecdd3`. Hover: background `#fff1f2`.

### Chips & Badges
- **Structure:** Inset padding `2px 8px`, typography `label-sm` (uppercase, tracked), height `20px` or `24px`.
- **Debt Band Badges:** 
  - Band 0 (Minimal): `#f8fafc` fill, `#64748b` text, `#e2e8f0` border.
  - Band 1 (Nominal): `#f1f5f9` fill, `#334155` text, `#cbd5e1` border.
  - Band 2 (Accumulating): `#eef2ff` fill, `#4338ca` text, `#c7d2fe` border.
  - Band 3 (Critical): `#312e81` fill, `#ffffff` text, border none.
- **Dot Indicators:** Circular `6px` inline status indicator on the leading edge with `space-xs` (4px) right margin.

### Data Tables
- **Header:** Height `36px`, background `#f8fafc`, typography `label-sm`, bottom border `1px solid #e2e8f0`, text `#64748b`.
- **Row:** Height `48px`, background `#ffffff`, border-bottom `1px solid #f1f5f9`. Hover: background `#f8fafc` transition `120ms ease`.
- **Numeric Cells:** Right-aligned, `mono-metric-md` token with tabular numbers enabled.

### Alert Banners & Callouts
- **Structure:** Pure white `#ffffff` or matched soft tint surface, subtle hairline stroke on right, top, bottom (`#e2e8f0`).
- **Accent Spine:** A defined, solid `3px` left border:
  - Error: `#e11d48` spine with `#fff1f2` background or white background with `#be123c` icon.
  - Warning: `#f59e0b` spine with `#fffbeb` background.
  - Info: `#0284c7` spine with `#f0f9ff` background.

### Input Fields & Controls
- **Text Inputs:** Height `36px`, background `#ffffff`, border `1px solid #e2e8f0`, radius `6px`, text `body-md` (`#0f172a`), placeholder `#94a3b8`. Focus state: border `#2563eb`, outline `2px solid rgba(37, 99, 235, 0.15)`.
- **Checkboxes & Radios:** `16px x 16px`, border `1px solid #cbd5e1`, radius `4px` (checkbox) / `50%` (radio). Checked state: `#2563eb` fill with white checkmark glyph.

### Stepper & Decision Progression Bar
- **Track Rail:** `2px` horizontal or vertical hairline `#e2e8f0`.
- **Completed Node:** `#2563eb` solid circle (`20px`) with white checkmark icon.
- **Active Node:** White circle (`20px`) with `#2563eb` outer ring (`2px`) and `#2563eb` center dot (`6px`).
- **Pending Node:** `#f1f5f9` circle with `#cbd5e1` border and `#94a3b8` index text.