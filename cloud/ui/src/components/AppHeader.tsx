// Shared customer-area header: sticky, logo links home, nav highlights the
// active area (Usage / Billing / Admin), profile dropdown with sign out.
// Used across Dashboard, Billing, Usage and Agent detail so the chrome stays
// identical everywhere. Self-fetches the current user when not given one.

import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Moon, BarChart3, CreditCard, Shield, LogOut, ChevronDown } from 'lucide-react';

export interface HeaderUser {
  id: string;
  email: string;
  name: string | null;
  avatar_url: string | null;
  is_admin?: boolean;
}

export default function AppHeader({ user: userProp }: { user?: HeaderUser | null }) {
  const [user, setUser] = useState<HeaderUser | null>(userProp ?? null);

  useEffect(() => {
    if (userProp) {
      setUser(userProp);
      return;
    }
    fetch('/api/auth/me')
      .then(r => (r.ok ? r.json() : null))
      .then(d => setUser(d?.user ?? null))
      .catch(() => {});
  }, [userProp]);

  const { pathname } = useLocation();
  const nav = [
    { to: '/dashboard/usage', label: 'Usage', icon: BarChart3 },
    { to: '/dashboard/billing', label: 'Billing', icon: CreditCard },
    ...(user?.is_admin ? [{ to: '/admin', label: 'Admin', icon: Shield }] : []),
  ];

  return (
    <header
      className="sticky top-0 z-40 flex items-center justify-between px-6 py-4 border-b"
      style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}
    >
      <Link to="/dashboard" className="flex items-center gap-3 transition-opacity hover:opacity-80">
        <Moon size={24} style={{ color: 'var(--moon)' }} />
        <span className="text-lg font-semibold" style={{ color: 'var(--text)' }}>Luna Service</span>
      </Link>
      <div className="flex items-center gap-2">
        {nav.map(({ to, label, icon: Icon }) => {
          const active = pathname === to || pathname.startsWith(to + '/');
          return (
            <Link
              key={to}
              to={to}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors hover:opacity-80"
              style={
                active
                  ? { background: 'var(--ink-light)', color: 'var(--text)' }
                  : { color: 'var(--text-dim)' }
              }
            >
              <Icon size={14} />
              {label}
            </Link>
          );
        })}
        {user ? (
          <ProfileMenu user={user} />
        ) : (
          <a
            href="/auth/logout"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors hover:opacity-80"
            style={{ color: 'var(--text-dim)' }}
          >
            <LogOut size={14} />
            Sign out
          </a>
        )}
      </div>
    </header>
  );
}

function ProfileMenu({ user }: { user: HeaderUser }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-2 py-1.5 rounded-lg transition-colors hover:opacity-80"
        style={{ color: 'var(--text-dim)' }}
      >
        {user.avatar_url ? (
          <img src={user.avatar_url} alt="" className="w-8 h-8 rounded-full" />
        ) : (
          <div
            className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold"
            style={{ background: 'var(--moon)', color: 'var(--ink)' }}
          >
            {(user.name || user.email)[0].toUpperCase()}
          </div>
        )}
        <span className="text-sm hidden sm:inline" style={{ color: 'var(--text-dim)' }}>
          {user.name || user.email}
        </span>
        <ChevronDown
          size={14}
          style={{ color: 'var(--text-dim)', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }}
        />
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-2 w-48 rounded-xl border py-1 shadow-lg z-50"
          style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}
        >
          <a
            href="/auth/logout"
            className="flex items-center gap-2.5 px-4 py-2.5 text-sm transition-colors hover:opacity-80"
            style={{ color: 'var(--text-dim)' }}
          >
            <LogOut size={14} />
            Sign out
          </a>
        </div>
      )}
    </div>
  );
}
