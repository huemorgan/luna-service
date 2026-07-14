import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { Moon, Shield, Package, Server, ScrollText, ArrowLeft, LogOut, Loader2, User, ChevronDown, ChevronRight, KeyRound, SlidersHorizontal, MessageCircle, Clock, Blocks, Coins, LayoutDashboard, GitBranch, Cpu, Wallet, Activity, FlaskConical } from 'lucide-react';

interface UserInfo {
  user: { id: string; email: string; name: string | null; avatar_url: string | null; is_admin: boolean };
  account: { id: string; slug: string; name: string; plan: string } | null;
}

const NAV_TOP = [
  { to: '/admin/admins', label: 'Admins', icon: Shield },
  { to: '/admin/images', label: 'Luna Images', icon: Package },
  { to: '/admin/defaults', label: 'Defaults', icon: SlidersHorizontal },
  { to: '/admin/machines', label: 'Machines', icon: Server },
  { to: '/admin/services', label: 'Key Registry', icon: KeyRound },
];

const SERVICE_ITEMS = [
  { to: '/admin/whatsapp', label: 'WhatsApp', icon: MessageCircle },
  { to: '/admin/scheduler', label: 'Scheduler', icon: Clock },
];

const PRICING_ITEMS = [
  { to: '/admin/pricing', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/admin/pricing/versions', label: 'Versions', icon: GitBranch },
  { to: '/admin/pricing/models', label: 'LLM & services', icon: Cpu },
  { to: '/admin/pricing/buckets', label: 'Credit buckets', icon: Wallet },
  { to: '/admin/pricing/ops', label: 'Operations', icon: Activity },
  { to: '/admin/pricing/simulations', label: 'Simulator', icon: FlaskConical },
];

const NAV_BOTTOM = [
  { to: '/admin/changelog', label: 'Changelog', icon: ScrollText },
];

function NavItem({ item }: { item: { to: string; label: string; icon: typeof Shield; end?: boolean } }) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors"
      style={({ isActive }) => ({
        background: isActive ? 'var(--ink-light)' : 'transparent',
        color: isActive ? 'var(--moon)' : 'var(--text-dim)',
      })}
    >
      <item.icon size={16} />
      {item.label}
    </NavLink>
  );
}

export default function AdminLayout() {
  const [data, setData] = useState<UserInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [servicesOpen, setServicesOpen] = useState(true);
  const [pricingOpen, setPricingOpen] = useState(true);
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
        <ProfileMenu user={user} />
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

          {NAV_TOP.map(item => <NavItem key={item.to} item={item} />)}

          <button
            onClick={() => setServicesOpen(o => !o)}
            className="flex items-center justify-between px-3 py-2.5 rounded-lg text-sm font-medium transition-colors hover:opacity-80"
            style={{ color: 'var(--text-dim)' }}
          >
            <span className="flex items-center gap-2.5">
              <Blocks size={16} />
              Services
            </span>
            {servicesOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
          {servicesOpen && (
            <div className="flex flex-col gap-1 pl-4">
              {SERVICE_ITEMS.map(item => <NavItem key={item.to} item={item} />)}
            </div>
          )}

          <button
            onClick={() => setPricingOpen(o => !o)}
            className="flex items-center justify-between px-3 py-2.5 rounded-lg text-sm font-medium transition-colors hover:opacity-80"
            style={{ color: 'var(--text-dim)' }}
          >
            <span className="flex items-center gap-2.5">
              <Coins size={16} />
              Pricing
            </span>
            {pricingOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
          {pricingOpen && (
            <div className="flex flex-col gap-1 pl-4">
              {PRICING_ITEMS.map(item => <NavItem key={item.to} item={item} />)}
            </div>
          )}

          {NAV_BOTTOM.map(item => <NavItem key={item.to} item={item} />)}
        </nav>

        <main className="flex-1 p-8 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function ProfileMenu({ user }: { user: UserInfo['user'] }) {
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
          <div className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold" style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
            {(user.name || user.email)[0].toUpperCase()}
          </div>
        )}
        <span className="text-sm hidden sm:inline" style={{ color: 'var(--text-dim)' }}>{user.name || user.email}</span>
        <ChevronDown size={14} style={{ color: 'var(--text-dim)', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }} />
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-2 w-48 rounded-xl border py-1 shadow-lg z-50"
          style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}
        >
          <a
            href="/dashboard"
            className="flex items-center gap-2.5 px-4 py-2.5 text-sm transition-colors hover:opacity-80"
            style={{ color: 'var(--text)' }}
          >
            <User size={14} style={{ color: 'var(--moon)' }} />
            Personal Account
          </a>
          <div style={{ borderTop: '1px solid var(--ink-lighter)', margin: '2px 0' }} />
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
