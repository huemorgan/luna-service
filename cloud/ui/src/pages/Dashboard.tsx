import { useEffect, useRef, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  Moon, LogOut, Bot, Loader2, Plus, ExternalLink,
  RotateCcw, Square, Play, AlertTriangle, Shield, ChevronDown,
  Settings, ArrowUpCircle, ChevronRight, CheckCircle2, Sparkles,
} from 'lucide-react';

interface UserInfo {
  user: { id: string; email: string; name: string | null; avatar_url: string | null; is_admin?: boolean };
  account: { id: string; slug: string; name: string; plan: string } | null;
}

interface AgentInfo {
  id: string;
  name: string;
  slug: string;
  status: string;
  runtime_kind: string | null;
  internal_url: string | null;
  image_version: string | null;
  latest_version: string | null;
  upgrade_available: boolean;
  error_message: string | null;
  error_at: string | null;
  created_at: string;
  last_active_at: string | null;
}

interface AgentIdentity {
  name: string | null;
  emoji: string | null;
  avatar_url: string | null;
}

interface PluginStatus {
  name: string;
  installed_version?: string | null;
  status: string;
  upgrade_to?: string | null;
  reason?: string | null;
}

interface UpgradeCheck {
  upgradable: boolean;
  reason?: string;
  current_version?: string | null;
  target_version?: string;
  release_notes?: string | null;
  compat?: 'ok' | 'unavailable';
  verdict?: string;
  summary?: Record<string, number>;
  plugins?: PluginStatus[];
}

const STATUS_DOT: Record<string, string> = {
  running: '#22c55e',
  provisioning: '#facc15',
  pending: '#94a3b8',
  stopped: '#94a3b8',
  error: '#ef4444',
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export default function Dashboard() {
  const [data, setData] = useState<UserInfo | null>(null);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('My Luna');
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [me, ag] = await Promise.all([
        fetch('/api/auth/me').then(r => r.ok ? r.json() : Promise.reject()),
        fetch('/api/agents').then(r => r.ok ? r.json() : []),
      ]);
      setData(me);
      setAgents(ag);
    } catch {
      window.location.href = '/';
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // The agent's self-chosen identity (name it gave itself, emoji/avatar) lives
  // on the machine — fetch it through the /a/{slug}/ proxy for running agents.
  const [identities, setIdentities] = useState<Record<string, AgentIdentity>>({});
  // Track *attempted* fetches, not resolved ones: a failed fetch (agent
  // unreachable) must not be retried on every agents/identities change —
  // that fan-out used to hammer dead agents with 35 s requests.
  const identityAttempted = useRef<Set<string>>(new Set());
  useEffect(() => {
    agents
      .filter(a => a.status === 'running' && a.slug && !identityAttempted.current.has(a.id))
      .forEach(a => {
        identityAttempted.current.add(a.id);
        fetch(`/a/${a.slug}/api/p/plugin-identity/`)
          .then(r => r.ok ? r.json() : null)
          .then(idn => {
            if (idn) setIdentities(prev => ({ ...prev, [a.id]: { name: idn.name || null, emoji: idn.emoji || null, avatar_url: idn.avatar_url || null } }));
          })
          .catch(() => { /* best-effort — card falls back to the machine name */ });
      });
  }, [agents]);

  // Poll for provisioning agents
  useEffect(() => {
    const hasProvisioning = agents.some(a => a.status === 'provisioning');
    if (!hasProvisioning) return;
    const interval = setInterval(() => {
      fetch('/api/agents').then(r => r.ok ? r.json() : []).then(setAgents);
    }, 3000);
    return () => clearInterval(interval);
  }, [agents]);

  const handleCreate = async () => {
    setCreating(true);
    try {
      const res = await fetch('/api/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName.trim() || 'My Luna' }),
      });
      if (res.ok) {
        const agent = await res.json();
        setAgents(prev => [...prev, agent]);
        setShowCreate(false);
        setNewName('My Luna');
      }
    } finally {
      setCreating(false);
    }
  };

  const handleAction = async (agentId: string, action: 'start' | 'stop' | 'retry') => {
    setActionLoading(agentId);
    try {
      const res = await fetch(`/api/agents/${agentId}/${action}`, { method: 'POST' });
      if (res.ok) {
        const updated = await res.json();
        setAgents(prev => prev.map(a => a.id === agentId ? updated : a));
      }
    } finally {
      setActionLoading(null);
    }
  };

  // Upgrade with an explicit mode (used by the upgrade tray). Returns an error
  // string on failure so the tray can surface it inline.
  const handleUpgrade = async (
    agentId: string,
    mode: 'upgrade_only' | 'update_plugins_then_upgrade',
  ): Promise<string | null> => {
    const res = await fetch(`/api/agents/${agentId}/upgrade`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    });
    if (res.ok) {
      const updated = await res.json();
      setAgents(prev => prev.map(a => a.id === agentId ? updated : a));
      return null;
    }
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    return err.detail || res.statusText || 'Upgrade failed';
  };

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
    <div className="min-h-screen" style={{ background: 'var(--ink)' }}>
      <header
        className="flex items-center justify-between px-6 py-4 border-b"
        style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}
      >
        <div className="flex items-center gap-3">
          <Moon size={24} style={{ color: 'var(--moon)' }} />
          <span className="text-lg font-semibold" style={{ color: 'var(--text)' }}>Luna Service</span>
        </div>
        <div className="flex items-center gap-3">
          {user.is_admin && (
            <Link
              to="/admin"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors hover:opacity-80"
              style={{ color: 'var(--moon)' }}
            >
              <Shield size={14} />
              Admin
            </Link>
          )}
          <ProfileMenu user={user} />
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-10">
        {/* Title bar */}
        <div className="flex items-center justify-between mb-8">
          <h2 className="text-2xl font-bold" style={{ color: 'var(--text)' }}>My Agents</h2>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all hover:scale-105"
            style={{ background: 'var(--moon)', color: 'var(--ink)' }}
          >
            <Plus size={18} />
            New Agent
          </button>
        </div>

        {/* Create dialog */}
        {showCreate && (
          <div
            className="rounded-2xl p-6 border mb-6"
            style={{ background: 'var(--surface)', borderColor: 'var(--moon)', boxShadow: '0 0 30px rgba(250, 204, 21, 0.08)' }}
          >
            <h3 className="text-lg font-semibold mb-4" style={{ color: 'var(--text)' }}>Create a new agent</h3>
            <div className="flex gap-3">
              <input
                type="text"
                value={newName}
                onChange={e => setNewName(e.target.value)}
                placeholder="Agent name"
                className="flex-1 px-4 py-2.5 rounded-xl text-sm outline-none"
                style={{ background: 'var(--ink)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' }}
                onKeyDown={e => e.key === 'Enter' && handleCreate()}
                autoFocus
              />
              <button
                onClick={handleCreate}
                disabled={creating}
                className="flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-semibold transition-all hover:scale-105 disabled:opacity-50"
                style={{ background: 'var(--moon)', color: 'var(--ink)' }}
              >
                {creating ? <Loader2 className="animate-spin" size={16} /> : <Plus size={16} />}
                Create
              </button>
              <button
                onClick={() => { setShowCreate(false); setNewName('My Luna'); }}
                className="px-4 py-2.5 rounded-xl text-sm transition-colors hover:opacity-80"
                style={{ color: 'var(--text-dim)' }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Empty state */}
        {agents.length === 0 && !showCreate && (
          <div
            className="rounded-2xl p-12 border text-center"
            style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}
          >
            <Bot size={56} className="mx-auto mb-4" style={{ color: 'var(--moon)', opacity: 0.5 }} />
            <h3 className="text-xl font-semibold mb-2" style={{ color: 'var(--text)' }}>No agents yet</h3>
            <p className="text-sm mb-6" style={{ color: 'var(--text-dim)' }}>
              Create your first Luna agent to get started. Each agent runs in its own isolated environment.
            </p>
            <button
              onClick={() => setShowCreate(true)}
              className="inline-flex items-center gap-2 px-8 py-3 rounded-xl text-sm font-semibold transition-all hover:scale-105"
              style={{ background: 'var(--moon)', color: 'var(--ink)' }}
            >
              <Plus size={18} />
              Create Agent
            </button>
          </div>
        )}

        {/* Agent list */}
        {agents.length > 0 && (
          <div className="space-y-3">
            {agents.map(agent => (
              <AgentCard
                key={agent.id}
                agent={agent}
                identity={identities[agent.id] || null}
                isLoading={actionLoading === agent.id}
                onAction={handleAction}
                onUpgrade={handleUpgrade}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

function AgentCard({
  agent, identity, isLoading, onAction, onUpgrade,
}: {
  agent: AgentInfo;
  identity: AgentIdentity | null;
  isLoading: boolean;
  onAction: (id: string, action: 'start' | 'stop' | 'retry') => void;
  onUpgrade: (id: string, mode: 'upgrade_only' | 'update_plugins_then_upgrade') => Promise<string | null>;
}) {
  const dotColor = STATUS_DOT[agent.status] || '#94a3b8';
  const stuckProvisioning = agent.status === 'provisioning' && agent.created_at
    && (Date.now() - new Date(agent.created_at).getTime()) > 5 * 60 * 1000;

  return (
    <div
      className="rounded-2xl p-5 border transition-all"
      style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="w-3 h-3 rounded-full flex-shrink-0" style={{ background: dotColor }} />
          <div>
            <Link
              to={`/dashboard/agents/${agent.id}`}
              className="group inline-flex items-center gap-1.5 font-semibold underline decoration-dotted underline-offset-4 hover:decoration-solid transition-colors"
              style={{ color: 'var(--moon)' }}
              title="Open settings & config"
            >
              {identity?.name || agent.name}
              {identity?.name && (
                identity.emoji
                  ? <span className="no-underline">{identity.emoji}</span>
                  : identity.avatar_url
                    ? <img src={`/a/${agent.slug}${identity.avatar_url}`} alt="" className="w-4 h-4 rounded-full" />
                    : null
              )}
              <Settings size={13} className="opacity-60 transition-opacity group-hover:opacity-100" />
            </Link>
            {identity?.name && identity.name !== agent.name && (
              <div className="text-xs" style={{ color: 'var(--text-dim)', opacity: 0.7 }}>
                {agent.name}
              </div>
            )}
            <div className="flex items-center gap-3 mt-1">
              <span className="text-xs capitalize" style={{ color: stuckProvisioning ? '#facc15' : 'var(--text-dim)' }}>
                {agent.status === 'provisioning' && !stuckProvisioning && (
                  <span className="inline-flex items-center gap-1">
                    <Loader2 className="animate-spin" size={10} />
                    Setting up...
                  </span>
                )}
                {stuckProvisioning && (
                  <span className="inline-flex items-center gap-1">
                    <AlertTriangle size={10} />
                    Setup failed
                  </span>
                )}
                {agent.status !== 'provisioning' && agent.status}
              </span>
              {agent.created_at && (
                <span className="text-xs" style={{ color: 'var(--text-dim)', opacity: 0.6 }}>
                  Created {timeAgo(agent.created_at)}
                </span>
              )}
              {agent.image_version && (
                <span className="text-xs font-mono" style={{ color: 'var(--text-dim)', opacity: 0.6 }}>
                  v{agent.image_version}
                </span>
              )}
            </div>
            {(agent.status === 'error' || stuckProvisioning) && agent.error_message && (
              <div
                className="flex items-start gap-2 mt-2 rounded-lg px-3 py-2 text-xs"
                style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.15)' }}
              >
                <AlertTriangle size={12} className="flex-shrink-0 mt-0.5" style={{ color: '#ef4444' }} />
                <span style={{ color: '#fca5a5' }}>{agent.error_message}</span>
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {isLoading && <Loader2 className="animate-spin" size={16} style={{ color: 'var(--moon)' }} />}

          {agent.status === 'running' && agent.slug && (
            <a
              href={`/a/${agent.slug}/`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all hover:scale-105"
              style={{ background: 'var(--moon)', color: 'var(--ink)' }}
            >
              <ExternalLink size={14} />
              Open
            </a>
          )}

          {agent.status === 'running' && (
            <button
              onClick={() => onAction(agent.id, 'stop')}
              disabled={isLoading}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs transition-all hover:bg-[var(--ink-light)] disabled:opacity-50"
              style={{ color: 'var(--text-dim)', border: '1px solid var(--ink-lighter)' }}
              title="Stop agent"
            >
              <Square size={12} />
              Stop
            </button>
          )}

          {agent.status === 'stopped' && (
            <button
              onClick={() => onAction(agent.id, 'start')}
              disabled={isLoading}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs transition-all hover:bg-[var(--ink-light)] disabled:opacity-50"
              style={{ color: 'var(--text-dim)', border: '1px solid var(--ink-lighter)' }}
              title="Start agent"
            >
              <Play size={12} />
              Start
            </button>
          )}

          {agent.status === 'error' && (
            <button
              onClick={() => onAction(agent.id, 'retry')}
              disabled={isLoading}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium transition-all hover:bg-[rgba(250,204,21,0.1)] disabled:opacity-50"
              style={{ color: '#facc15', border: '1px solid rgba(250,204,21,0.3)' }}
              title="Retry provisioning"
            >
              <RotateCcw size={12} />
              Retry
            </button>
          )}

          {stuckProvisioning && (
            <button
              onClick={() => onAction(agent.id, 'retry')}
              disabled={isLoading}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all hover:bg-[rgba(250,204,21,0.1)] disabled:opacity-50"
              style={{ color: '#facc15', border: '1px solid rgba(250,204,21,0.3)' }}
              title="Retry provisioning"
            >
              <RotateCcw size={12} />
              Retry
            </button>
          )}

          <Link
            to={`/dashboard/agents/${agent.id}`}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs transition-all hover:bg-[var(--ink-light)]"
            style={{ color: 'var(--text-dim)', border: '1px solid var(--ink-lighter)' }}
            title="Settings & config (rename, upgrade, delete)"
          >
            <Settings size={12} />
            Config
          </Link>
        </div>
      </div>

      {/* Error message */}
      {agent.status === 'error' && agent.error_message && (
        <div
          className="mt-3 flex items-start gap-2 px-4 py-3 rounded-xl text-xs"
          style={{ background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.2)' }}
        >
          <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" style={{ color: '#ef4444' }} />
          <span style={{ color: '#fca5a5' }}>{agent.error_message}</span>
        </div>
      )}

      {/* Upgrade tray — docked under the machine box when a newer image exists */}
      {agent.upgrade_available && <UpgradeTray agent={agent} onUpgrade={onUpgrade} />}
    </div>
  );
}

const VERDICT_STYLE: Record<string, { color: string; bg: string; label: string }> = {
  ok: { color: '#22c55e', bg: 'rgba(34,197,94,0.12)', label: 'Compatible' },
  upgrade_with_changes: { color: '#facc15', bg: 'rgba(250,204,21,0.12)', label: 'Updates needed' },
  blocked: { color: '#ef4444', bg: 'rgba(239,68,68,0.12)', label: 'Some plugins unsupported' },
};

const PLUGIN_STATUS_STYLE: Record<string, { color: string; label: (p: PluginStatus) => string }> = {
  compatible: { color: '#22c55e', label: () => 'compatible' },
  baked: { color: '#22c55e', label: () => 'built in' },
  needs_upgrade: { color: '#facc15', label: (p) => `update available${p.upgrade_to ? ` → v${p.upgrade_to}` : ''}` },
  unsupported: { color: '#ef4444', label: () => 'unsupported — will be disabled' },
  unknown: { color: '#94a3b8', label: () => 'unverified' },
};

function UpgradeTray({
  agent, onUpgrade,
}: {
  agent: AgentInfo;
  onUpgrade: (id: string, mode: 'upgrade_only' | 'update_plugins_then_upgrade') => Promise<string | null>;
}) {
  const [open, setOpen] = useState(false);
  const [check, setCheck] = useState<UpgradeCheck | null>(null);
  const [loadingCheck, setLoadingCheck] = useState(false);
  const [upgrading, setUpgrading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const targetLabel = agent.latest_version ? `v${agent.latest_version}` : 'a new version';

  const expand = async () => {
    const next = !open;
    setOpen(next);
    if (next && !check && !loadingCheck) {
      setLoadingCheck(true);
      try {
        const res = await fetch(`/api/agents/${agent.id}/upgrade-check`);
        setCheck(res.ok ? await res.json() : { upgradable: true, compat: 'unavailable', reason: 'Couldn’t load the compatibility report.' });
      } catch {
        setCheck({ upgradable: true, compat: 'unavailable', reason: 'Couldn’t load the compatibility report.' });
      } finally {
        setLoadingCheck(false);
      }
    }
  };

  const doUpgrade = async (mode: 'upgrade_only' | 'update_plugins_then_upgrade') => {
    setUpgrading(true);
    setError(null);
    const err = await onUpgrade(agent.id, mode);
    setUpgrading(false);
    if (err) setError(err);
  };

  const verdict = check?.verdict;
  const verdictStyle = verdict ? VERDICT_STYLE[verdict] : null;
  const notes = (check?.release_notes || '')
    .split('\n')
    .map(l => l.replace(/^[-*]\s*/, '').trim())
    .filter(Boolean);

  return (
    <div
      className="mt-4 -mx-5 -mb-5 rounded-b-2xl overflow-hidden"
      style={{ borderTop: '1px solid var(--ink-lighter)', background: 'rgba(201,184,255,0.05)' }}
    >
      {/* Collapsed bar */}
      <button
        onClick={expand}
        className="w-full flex items-center justify-between px-5 py-3 text-left transition-colors hover:bg-[rgba(201,184,255,0.06)]"
      >
        <span className="flex items-center gap-2 text-sm font-medium" style={{ color: 'var(--moon)' }}>
          <ArrowUpCircle size={15} />
          New version available — {targetLabel}
        </span>
        <span className="flex items-center gap-1 text-xs" style={{ color: 'var(--text-dim)' }}>
          Details
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
      </button>

      {/* Expanded drawer */}
      {open && (
        <div className="px-5 pb-5 pt-1 space-y-4">
          {/* What's new */}
          <div>
            <div className="flex items-center gap-1.5 mb-1.5 text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--text-dim)' }}>
              <Sparkles size={12} /> What's new in {targetLabel}
            </div>
            {loadingCheck && !check ? (
              <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-dim)' }}>
                <Loader2 className="animate-spin" size={12} /> Loading…
              </div>
            ) : notes.length > 0 ? (
              <ul className="space-y-0.5 text-xs" style={{ color: 'var(--text)' }}>
                {notes.slice(0, 8).map((n, i) => (
                  <li key={i} className="flex gap-1.5">
                    <span style={{ color: 'var(--moon)' }}>•</span>
                    <span>{n}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs" style={{ color: 'var(--text-dim)' }}>No release notes recorded for this version.</p>
            )}
          </div>

          {/* Compatibility */}
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide mb-1.5" style={{ color: 'var(--text-dim)' }}>
              Compatibility
            </div>
            {loadingCheck && !check ? (
              <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-dim)' }}>
                <Loader2 className="animate-spin" size={12} /> Checking your plugins…
              </div>
            ) : check?.compat === 'ok' ? (
              <div>
                {verdictStyle && (
                  <span
                    className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium mb-2"
                    style={{ background: verdictStyle.bg, color: verdictStyle.color }}
                  >
                    {verdict === 'ok' ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
                    {verdictStyle.label}
                  </span>
                )}
                {check.plugins && check.plugins.length > 0 ? (
                  <ul className="space-y-1 text-xs">
                    {check.plugins.map((p) => {
                      const s = PLUGIN_STATUS_STYLE[p.status] || PLUGIN_STATUS_STYLE.unknown;
                      return (
                        <li key={p.name} className="flex items-center justify-between gap-2">
                          <span style={{ color: 'var(--text)' }}>
                            {p.name}
                            {p.installed_version && (
                              <span className="font-mono ml-1.5" style={{ color: 'var(--text-dim)', opacity: 0.6 }}>v{p.installed_version}</span>
                            )}
                          </span>
                          <span style={{ color: s.color }}>{s.label(p)}</span>
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="text-xs" style={{ color: 'var(--text-dim)' }}>No installed plugins to check.</p>
                )}
                <p className="text-[10px] mt-2" style={{ color: 'var(--text-dim)', opacity: 0.7 }}>
                  Based on declared SDK compatibility — not a runtime guarantee.
                </p>
              </div>
            ) : (
              <p className="text-xs" style={{ color: 'var(--text-dim)' }}>
                {check?.reason || 'Compatibility couldn’t be verified for this machine.'}
              </p>
            )}
          </div>

          {error && (
            <div className="flex items-start gap-2 px-3 py-2 rounded-lg text-xs" style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.2)' }}>
              <AlertTriangle size={12} className="flex-shrink-0 mt-0.5" style={{ color: '#ef4444' }} />
              <span style={{ color: '#fca5a5' }}>{error}</span>
            </div>
          )}

          {/* Actions */}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {verdict === 'upgrade_with_changes' && (
              <button
                onClick={() => doUpgrade('update_plugins_then_upgrade')}
                disabled={upgrading}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold transition-all hover:scale-105 disabled:opacity-50"
                style={{ background: 'var(--moon)', color: 'var(--ink)' }}
              >
                {upgrading ? <Loader2 className="animate-spin" size={14} /> : <ArrowUpCircle size={14} />}
                Update plugins & upgrade
              </button>
            )}
            <button
              onClick={() => doUpgrade('upgrade_only')}
              disabled={upgrading}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium transition-all hover:scale-105 disabled:opacity-50"
              style={
                verdict === 'blocked'
                  ? { background: 'rgba(239,68,68,0.12)', color: '#fca5a5', border: '1px solid rgba(239,68,68,0.4)' }
                  : verdict === 'upgrade_with_changes'
                    ? { color: 'var(--text-dim)', border: '1px solid var(--ink-lighter)' }
                    : { background: 'var(--moon)', color: 'var(--ink)' }
              }
            >
              {upgrading ? <Loader2 className="animate-spin" size={14} /> : <ArrowUpCircle size={14} />}
              {verdict === 'ok' || !verdict ? 'Upgrade' : 'Upgrade anyway'}
            </button>
            <button
              onClick={() => setOpen(false)}
              disabled={upgrading}
              className="px-3 py-2 rounded-lg text-xs transition-colors hover:opacity-80 disabled:opacity-50"
              style={{ color: 'var(--text-dim)' }}
            >
              Cancel
            </button>
          </div>
          {verdict === 'blocked' && (
            <p className="text-[10px]" style={{ color: '#fca5a5', opacity: 0.85 }}>
              Unsupported plugins will come back disabled after the upgrade. You can update or remove them first.
            </p>
          )}
        </div>
      )}
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
