# HealthDoc Frontend

Next.js App Router frontend for the HealthDoc Hospital Information Management System (HIMS).

## Stack

| Layer | Choice |
| --- | --- |
| Framework | Next.js 15 (App Router) + React 19 + TypeScript |
| UI | MUI v6 + Emotion |
| Utility CSS | Tailwind CSS v4 |
| Charts | Recharts |
| Auth (planned) | Keycloak JS |
| Desktop (optional) | Electron stub under `electron/` |

Path alias: `@/*` → `src/*` (see `tsconfig.json`).

---

## Top-level layout

```
frontend/
├── electron/              # Optional Electron shell (compiled separately)
├── lib/                   # Legacy/root helpers (api, auth) — prefer src/lib going forward
├── public/                # Static assets served as-is
├── src/                   # Application source (primary codebase)
├── Dockerfile
├── next.config.ts
├── postcss.config.mjs     # Tailwind v4 PostCSS plugin
├── package.json
├── tsconfig.json
├── yarn.lock / package-lock.json
└── README.md
```

---

## `src/` architecture

Code is split by **role**, not by technical layer alone:

| Folder | Responsibility |
| --- | --- |
| `app/` | Routes only — thin pages that compose features |
| `features/` | Module/domain UI and business screens (doctor, billing, lab, …) |
| `components/` | Shared, reusable UI used across features |
| `styles/` | Fonts, global CSS, Meridian tokens, MUI theme |
| `lib/` | Shared helpers, mocks, future API clients |

**Rule of thumb**

- Put a screen’s logic under `features/<module>/`.
- Put something used by **two or more** modules under `components/`.
- Keep `app/**/page.tsx` thin: import a feature component and render it.

```
src/
├── app/                   # Next.js routes (URL → page)
├── components/            # Shared UI
│   ├── ui/                # Primitives (cards, buttons, modal, toast, …)
│   ├── tables/            # DataTable, EMARTable
│   ├── BedGrid/           # IPD bed occupancy grid
│   ├── VitalsTimeline/    # Clinical vitals table
│   ├── forms/             # (reserved) shared form controls
│   ├── dashboards/        # (reserved) shared dashboard widgets
│   ├── fhir/              # (reserved) FHIR display helpers
│   └── providers.tsx      # App-wide MUI + toast providers
├── features/              # Domain modules (one folder per product area)
├── lib/                   # Utilities & mock data
└── styles/                # Design system wiring
```

---

## `src/app/` — routes

Next.js App Router: each folder with `page.tsx` is a URL.

| Route | Purpose |
| --- | --- |
| `/login` | Authentication |
| `/billing` | Billing (currently hosts temporary shared-UI gallery) |
| `/doctor/dashboard` | Doctor home |
| `/doctor/consultation` | Consultation workspace |
| `/doctor/orders` | Orders |
| `/doctor/prescriptions` | Prescriptions |
| `/receptionist/registration` | Patient registration |
| `/receptionist/queue` | Front-desk queue |
| `/receptionist/patient-search` | Patient search |
| `/nurse/ward-dashboard` | Ward overview |
| `/nurse/emar` | Electronic medication administration |
| `/pharmacy/prescription-queue` | Pharmacy queue |
| `/pharmacy/dispense` | Dispense workflow |
| `/lab` | Lab |
| `/radiology` | Radiology |
| `/ipd` | In-patient |
| `/emergency` | Emergency |
| `/inventory` | Inventory |
| `/admin/users` | User admin |
| `/admin/departments` | Departments |
| `/admin/abdm-sync` | ABDM sync |
| `/consent` | Consent |
| `/audit-viewer` | Audit trail |
| `/reports` | Reports |
| `/queue-display` | Public queue display |
| `/patient-portal` | Patient-facing portal |

Root layout (`src/app/layout.tsx`):

- Loads IBM Plex fonts (`@/styles/fonts`)
- Imports global CSS (`@/styles/globals.css`)
- Wraps the tree in `<Providers>` (MUI theme, CssBaseline, Toaster)

Most pages are still stubs; real UI should grow under matching `features/` folders.

---

## `src/features/` — domain modules

One folder per hospital product area. Feature code owns screens, local hooks, and module-specific components.

```
features/
├── admin/
├── audit-viewer/
├── billing/               # Has SharedUiPreview (temporary gallery)
├── consent/
├── doctor/
├── emergency/
├── inventory/
├── ipd/
├── lab/
├── login/
├── nurse/
├── patient-portal/
├── pharmacy/
├── queue-display/
├── radiology/
├── receptionist/
└── reports/
```

**Example (billing)**

- `features/billing/SharedUiPreview.tsx` — temporary showcase of shared components on `/billing`. Safe to delete later; remove its import from `app/billing/page.tsx` when done reviewing.

Empty modules keep a `.gitkeep` so the folder structure stays in git until real screens land.

---

## `src/components/` — shared UI

### `components/ui/` — design primitives

| File | Role |
| --- | --- |
| `MetricCard.tsx` | KPI tile (value, delta, icon, loading) |
| `ChartWrapper.tsx` | Recharts shell (title, loading/empty, `ResponsiveContainer`) |
| `ExportButton.tsx` | CSV / Excel / PDF export menu (`onExport` callback) |
| `Badge.tsx` | Generic tag/chip |
| `StatusChip.tsx` | Visit/order status → consistent color mapping |
| `Modal.tsx` | Shared dialog (title, body, actions) |
| `Toaster.tsx` + `toast.ts` | Global toast API (`toast.success()`, etc.) |
| `index.ts` | Barrel for MetricCard, ChartWrapper, ExportButton |

Import preferred shared exports:

```ts
import { MetricCard, ChartWrapper, ExportButton } from "@/components/ui";
```

`Toaster` is mounted once in `providers.tsx` — do not add another per page.

### `components/tables/`

| Component | Role |
| --- | --- |
| `DataTable.tsx` | Generic sortable/paginated list table (MUI) |
| `EMARTable/` | Medication administration table (name, dose, route, status) |

### Clinical / ward widgets

| Folder | Role |
| --- | --- |
| `BedGrid/` | Bed cards by status (Occupied, Vacant, Reserved, Cleaning) |
| `VitalsTimeline/` | Timestamped vitals rows (temp, pulse, BP, SpO₂, …) |

Folder pattern for multi-file widgets:

```
BedGrid/
├── BedGrid.tsx
├── BedGrid.types.ts
├── constants.ts
└── index.ts          # public export
```

### `components/providers.tsx`

App-wide providers:

1. `AppRouterCacheProvider` (`enableCssLayer: true`) — MUI + Next App Router
2. `GlobalStyles` — CSS layer order for Tailwind v4 + MUI
3. `ThemeProvider` + `CssBaseline` — Meridian MUI theme
4. `Toaster` — toast host

---

## `src/styles/` — design system

```
styles/
├── fonts.ts               # IBM Plex Sans + IBM Plex Mono (next/font)
├── globals.css            # Tailwind v4 + CSS variables + component classes
└── theme/
    ├── meridian.ts        # Color/token source of truth (TS)
    ├── mui-theme.ts       # createTheme(...) wired to Meridian
    └── index.ts           # Re-exports
```

### Meridian theme

Navy / light HIMS palette (`#001f54` primary). Use:

- `meridian` object in `sx` / TS for MUI components
- CSS variables in `globals.css` for Tailwind utilities (`bg-primary`, `text-muted-foreground`, `surface-card`, …)

### Tailwind v4 + MUI layers

`globals.css` starts with:

```css
@layer theme, base, mui, components, utilities;
@import "tailwindcss";
```

This order (also set in the MUI theme via `modularCssLayers`) keeps Tailwind preflight from zeroing MUI button/table padding. Do not remove the layer declaration without a replacement strategy.

---

## `src/lib/` and root `lib/`

| Location | Intent |
| --- | --- |
| `src/lib/` | Preferred home for shared TS helpers and `mock/` data |
| `frontend/lib/` | Older `api.ts` / `auth.ts` helpers at package root |

New shared utilities should go under `src/lib/` and be imported as `@/lib/...`.

---

## `electron/`

Optional desktop shell:

- `electron/main.ts` — Electron main process stub
- `electron/tsconfig.json` — separate compile target

`npm run electron:dev` compiles Electron TS then launches it. Electron is excluded from the Next `tsconfig` include set.

---

## Scripts

From `healthdoc/frontend`:

```bash
npm run dev          # Next.js on http://localhost:3000
npm run build        # Production build
npm run start        # Serve production build
npm run lint         # ESLint
npm run typecheck    # tsc --noEmit
npm run electron:dev # Compile + run Electron stub
```

Prefer one package manager for this package (`npm` or `yarn`). Both `package-lock.json` and `yarn.lock` exist today; mixing them causes merge noise.

---

## How to add a new screen

1. **Route** — add `src/app/<module>/.../page.tsx` (thin).
2. **Feature** — implement UI in `src/features/<module>/YourScreen.tsx`.
3. **Shared pieces** — if reused across modules, move to `src/components/...`.
4. **Tokens** — use `meridian` / CSS variables; avoid hard-coded one-off colors when a token exists.

Example page:

```tsx
// src/app/billing/invoices/page.tsx
import { InvoiceList } from "@/features/billing/InvoiceList";

export default function Page() {
  return <InvoiceList />;
}
```

---

## Import conventions

```ts
// Shared UI
import { MetricCard, ChartWrapper, ExportButton } from "@/components/ui";
import { DataTable } from "@/components/tables/DataTable";
import BedGrid from "@/components/BedGrid";

// Theme
import { meridian, muiTheme } from "@/styles/theme";

// Feature-local
import { SharedUiPreview } from "@/features/billing/SharedUiPreview";

// Toasts (Toaster already mounted in providers)
import { toast } from "@/components/ui/toast";
```

---

## Charts

Charts use **Recharts**. Pattern:

1. Wrap with `ChartWrapper` (header, loading, empty, height, actions slot).
2. Pass a Recharts chart as `children` (`AreaChart`, `BarChart`, etc.).
3. Put export UI in `actions` via `ExportButton` when needed.

`ChartWrapper` does not own data fetching or series config — the parent does.

---

## Temporary / delete-later notes

| Item | Note |
| --- | --- |
| `features/billing/SharedUiPreview.tsx` | Gallery of shared components for review |
| Import in `app/billing/page.tsx` | Remove when gallery is no longer needed |

Shared components under `components/` stay; only the gallery is temporary.

---

## Related monorepo paths

This package lives at `healthdoc/frontend` inside the HealthDoc monorepo. Backend and infra are siblings under `healthdoc/` and are out of scope for this README.
