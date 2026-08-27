import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { Moon, Shield, Package, Server, ScrollText, ArrowLeft, LogOut, Loader2, User, ChevronDown, ChevronRight, KeyRound, SlidersHorizontal, MessageCircle, Clock, Send, Blocks, Coins, LayoutDashboard, GitBranch, Cpu, Wallet, Activity, FlaskConical, Gauge, Menu, X, MessageSquareWarning, Bug, Webhook } from 'lucide-react';

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
  { to: '/admin/errors', label: 'Error Tracking', icon: Bug },
];

const SERVICE_ITEMS = [
  { to: '/admin/whatsapp', label: 'WhatsApp', icon: MessageCircle },
  { to: '/admin/telegram', label: 'Telegram', icon: Send },
  { to: '/admin/scheduler', label: 'Scheduler', icon: Clock },
  { to: '/admin/webhooks', label: 'Webhooks', icon: Webhook },
  { to: '/admin/feedback', label: 'Feedback', icon: MessageSquareWarning },
];

const PRICING_ITEMS = [
  { to: '/admin/pricing', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/admin/pricing/versions', label: 'Versions', icon: GitBranch },
  { to: '/admin/pricing/models', label: 'LLM & services', icon: Cpu },
  { to: '/admin/pricing/buckets', label: 'Credit buckets', icon: Wallet },
  { to: '/admin/pricing/ops', label: 'Operations', icon: Activity },
  { to: '/admin/pricing/simulations', label: 'Simulator', icon: FlaskConical },
  { to: '/admin/pricing/testing', label: 'Billing testing', icon: Gauge },
];

const NAV_BOTTOM = [
  { to: '/admin/changelog', label: 'Changelog', icon: ScrollText },
];

/** Fired by FeedbackPage after a ticket is opened/replied so the nav badge refreshes immediately. */
export const FEEDBACK_UNREAD_EVENT = 'luna:feedback-unread-changed';

function NavItem({ item, badge }: { item: { to: string; label: string; icon: typeof Shield; end?: boolean }; badge?: number }) {
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
      {!!badge && (
        <span
          className="ml-auto min-w-[18px] h-[18px] px-1 rounded-full text-[11px] font-bold leading-[18px] text-center"
          style={{ background: '#ef4444', color: '#fff' }}
          title={`${badge} unread`}
          aria-label={`${badge} unread`}
        >
          {badge > 99 ? '99+' : badge}
        </span>
      )}
    </NavLink>
  );
}

function useFeedbackUnread(): number {
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    const load = () => {
      fetch('/api/admin/feedback/unread-count')
        .then(r => (r.ok ? r.json() : null))
        .then(d => { if (alive && d) setN(d.unread || 0); })
        .catch(() => { /* keep last value */ });
    };
    load();
    const id = setInterval(load, 60_000);
    const onVis = () => { if (document.visibilityState === 'visible') load(); };
    window.addEventListener(FEEDBACK_UNREAD_EVENT, load);
    document.addEventListener('visibilitychange', onVis);
    return () => {
      alive = false;
      clearInterval(id);
      window.removeEventListener(FEEDBACK_UNREAD_EVENT, load);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, []);
  return n;
}

export default function AdminLayout() {
  const [data, setData] = useState<UserInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [servicesOpen, setServicesOpen] = useState(true);
  const [pricingOpen, setPricingOpen] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();
  const feedbackUnread = useFeedbackUnread();

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
          <button
            type="button"
            className="md:hidden"
            onClick={() => setMenuOpen(open => !open)}
            aria-label={menuOpen ? 'Close admin navigation' : 'Open admin navigation'}
            aria-expanded={menuOpen}
          >
            {menuOpen ? <X size={22} /> : <Menu size={22} />}
          </button>
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

      <div className="flex flex-1 min-w-0">
        <nav
          className={`${menuOpen ? 'flex' : 'hidden'} md:flex absolute md:static top-[77px] bottom-0 left-0 z-40 w-56 border-r p-4 flex-col gap-1 overflow-y-auto`}
          style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}
        >
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
              {SERVICE_ITEMS.map(item => (
                <NavItem key={item.to} item={item} badge={item.to === '/admin/feedback' ? feedbackUnread : undefined} />
              ))}
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

        <main className="flex-1 min-w-0 p-4 md:p-8 overflow-auto">
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
