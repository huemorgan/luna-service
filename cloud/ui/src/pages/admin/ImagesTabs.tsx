import { NavLink } from 'react-router-dom';
import { Package, SlidersHorizontal } from 'lucide-react';

const TABS = [
  { to: '/admin/images', label: 'Images', icon: Package, end: true },
  { to: '/admin/images/defaults', label: 'Defaults', icon: SlidersHorizontal, end: false },
];

/** Tab bar for the Luna Images area (Plan 020): Images list vs image Defaults. */
export default function ImagesTabs() {
  return (
    <div
      className="flex items-center gap-1 mb-6 border-b"
      style={{ borderColor: 'var(--ink-lighter)' }}
    >
      {TABS.map(t => (
        <NavLink
          key={t.to}
          to={t.to}
          end={t.end}
          className="flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-colors"
          style={({ isActive }) => ({
            color: isActive ? 'var(--moon)' : 'var(--text-dim)',
            borderBottom: isActive ? '2px solid var(--moon)' : '2px solid transparent',
            marginBottom: -1,
          })}
        >
          <t.icon size={15} />
          {t.label}
        </NavLink>
      ))}
    </div>
  );
}
