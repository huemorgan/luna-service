# Luna Service — Design Styleguide

Living document. Every UI component in the admin and dashboard should follow
these rules. When in doubt, match what's already here rather than inventing.

---

## Color tokens

All colors come from CSS variables in `cloud/ui/src/index.css`.

| Token           | Hex        | Usage                              |
|-----------------|------------|-------------------------------------|
| `--ink`         | `#0f0f14`  | Page background                     |
| `--ink-light`   | `#1a1a24`  | Card hover, subtle fill             |
| `--ink-lighter` | `#2a2a3a`  | Borders, dividers                   |
| `--moon`        | `#c9b8ff`  | Primary accent (buttons, links)     |
| `--moon-dim`    | `#a08cd0`  | Secondary accent                    |
| `--surface`     | `#16161e`  | Card/panel background               |
| `--text`        | `#e4e4ef`  | Primary text                        |
| `--text-dim`    | `#8888a0`  | Secondary/muted text                |

Semantic colors (used inline, not tokens yet):

| Color     | Hex        | Usage                              |
|-----------|------------|-------------------------------------|
| Green     | `#22c55e`  | Success, active, "on"               |
| Red       | `#ef4444`  | Error, destructive                  |
| Yellow    | `#facc15`  | Warning, pending                    |
| Dim gray  | `#6b7280`  | Inactive, "off"                     |

---

## On/Off Toggle Pill

The standard control for boolean settings. **Never use a native checkbox,
a sliding track toggle, or a colored badge/tag** to represent on/off state.

### Anatomy

```
┌─────────────────────────────────────┐
│ [●] Label          description text │
└─────────────────────────────────────┘
```

- **Pill button**: rounded-lg, `px-3 py-1.5`, `text-xs font-medium`
- **On state**: `background: rgba(34,197,94,0.12)`, `color: #22c55e`, dot `●` filled green
- **Off state**: `background: var(--ink)`, `color: var(--text-dim)`, dot `●` filled `#6b7280`
- **Dot**: `w-2 h-2 rounded-full` inline before the label
- **Description**: dim text (`var(--text-dim)`) after the label, separated by ` — `
- **Click target**: the entire pill is clickable

### React reference implementation

```tsx
function OnOffPill({ label, description, value, onChange }: {
  label: string;
  description?: string;
  value: boolean;
  onChange: () => void;
}) {
  return (
    <button
      onClick={onChange}
      className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
      style={{
        background: value ? 'rgba(34,197,94,0.12)' : 'var(--ink)',
        color: value ? '#22c55e' : 'var(--text-dim)',
      }}
    >
      <span
        className="w-2 h-2 rounded-full flex-shrink-0"
        style={{ background: value ? '#22c55e' : '#6b7280' }}
      />
      {label}
      {description && (
        <span style={{ color: 'var(--text-dim)', fontWeight: 400 }}>— {description}</span>
      )}
    </button>
  );
}
```

### Rules

1. **No redundant badges.** If there's an on/off pill, don't also show a
   "disabled" or "provisioned" tag in the header. The pill IS the indicator.
2. **Always include a description** when the label alone is ambiguous
   (e.g. "Provision by default — auto-add key for new agents").
3. **Immediate effect.** Clicking the pill fires the API call and toggles
   state. No separate "Save" button.
4. **No confirmation dialog** for non-destructive toggles.

---

## Cards

- `rounded-xl border` with `background: var(--surface)`, `borderColor: var(--ink-lighter)`
- Active/highlighted cards: `borderColor: var(--moon)`, subtle box-shadow
- Padding: `px-5 py-4` for content areas
- Expandable cards: chevron left of title, full-width click target

## Buttons

- **Primary**: `background: var(--moon)`, `color: var(--ink)`, `rounded-xl`, `text-sm font-semibold`
- **Ghost/secondary**: `border: 1px solid var(--ink-lighter)`, `color: var(--moon)`, `rounded-lg`
- **Destructive**: `color: #ef4444`, ghost style
- **Hover**: `hover:scale-105` for primary, `hover:bg-[var(--ink-light)]` for ghost
- **Disabled**: `opacity-50`, `cursor-not-allowed`

## Status dots

- `w-2.5 h-2.5 rounded-full` for card-level status
- `w-2 h-2 rounded-full` for inline status (inside rows)
- Colors: green=running/active, yellow=pending, gray=stopped/cold, red=error

## Typography

- Page titles: `text-xl font-bold`
- Card titles: `text-sm font-semibold`
- Body: `text-sm`
- Meta/labels: `text-xs`, `color: var(--text-dim)`
- Monospace values: `font-mono text-xs`

## Spacing

- Page max width: `max-w-5xl` (dashboard), `max-w-4xl` (admin)
- Section gap: `gap-4` or `space-y-4`
- Inline element gap: `gap-2` or `gap-3`
