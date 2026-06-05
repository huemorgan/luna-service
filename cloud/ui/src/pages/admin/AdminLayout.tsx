import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { Moon, Shield, Package, Server, ArrowLeft, LogOut, Loader2 } from 'lucide-react';

interface UserInfo {
  user: { id: string; email: string; name: string | null; avatar_url: string | null; is_admin: boolean };
  account: { id: string; slug: string; name: string; plan: string } | null;
}

const NAV_ITEMS = [
  { to: '/admin/admins', label: 'Admins', icon: Shield },
  { to: '/admin/images', label: 'Luna Images', icon: Package },
  { to: '/admin/machines', label: 'Machines', icon: Server },
];

export default function AdminLayout() {
  const [data, setData] = useState<UserInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    fetch('/api/auth/me')
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(me => {
        if (!me.user.is_admin) {
          navigate('/dashboard');
          return;
        }
        setData(me);
      })
      .catch(() => { window.location.href = '/'; })
      .finally(() => setLoading(false));
  }, [navigate]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--ink)' }}>
        <Loader2 className="animate-spin" size={32} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  if (!data) return null;
  const { user } = data;

  return (
    <div className="min-h-screen flex flex-col" style={{ background: 'var(--ink)' }}>
      <header
        className="flex items-center justify-between px-6 py-4 border-b"
        style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}
      >
        <div className="flex items-center gap-3">
          <Moon size={24} style={{ color: 'var(--moon)' }} />
          <span className="text-lg font-semibold" style={{ color: 'var(--text)' }}>Luna Service</span>
          <span
            className="text-xs px-2 py-0.5 rounded-full font-medium"
            style={{ background: 'rgba(201,184,255,0.15)', color: 'var(--moon)' }}
          >
            Admin
          </span>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            {user.avatar_url ? (
              <img src={user.avatar_url} alt="" className="w-8 h-8 rounded-full" />
            ) : (
              <div className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold" style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
                {(user.name || user.email)[0].toUpperCase()}
              </div>
            )}
            <span className="text-sm hidden sm:inline" style={{ color: 'var(--text-dim)' }}>{user.name || user.email}</span>
          </div>
          <a href="/auth/logout" className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors hover:opacity-80" style={{ color: 'var(--text-dim)' }}>
            <LogOut size={14} />
          </a>
        </div>
      </header>

      <div className="flex flex-1">
        <nav className="w-56 border-r p-4 flex flex-col gap-1" style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}>
          <Link
            to="/dashboard"
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm mb-3 transition-colors hover:opacity-80"
            style={{ color: 'var(--text-dim)' }}
          >
            <ArrowLeft size={14} />
            Dashboard
          </Link>

          {NAV_ITEMS.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors"
              style={({ isActive }) => ({
                background: isActive ? 'var(--ink-light)' : 'transparent',
                color: isActive ? 'var(--moon)' : 'var(--text-dim)',
              })}
            >
              <item.icon size={16} />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <main className="flex-1 p-8 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
