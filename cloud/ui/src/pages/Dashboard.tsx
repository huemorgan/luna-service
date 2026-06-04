import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  Moon, LogOut, Bot, Loader2, Plus, ExternalLink,
  RotateCcw, Square, Play, Trash2, AlertTriangle,
} from 'lucide-react';

interface UserInfo {
  user: { id: string; email: string; name: string | null; avatar_url: string | null };
  account: { id: string; slug: string; name: string; plan: string } | null;
}

interface AgentInfo {
  id: string;
  name: string;
  slug: string;
  status: string;
  runtime_kind: string | null;
  internal_url: string | null;
  error_message: string | null;
  error_at: string | null;
  created_at: string;
  last_active_at: string | null;
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

  const handleAction = async (agentId: string, action: 'start' | 'stop' | 'retry' | 'delete') => {
    setActionLoading(agentId);
    try {
      if (action === 'delete') {
        const res = await fetch(`/api/agents/${agentId}`, { method: 'DELETE' });
        if (res.ok) setAgents(prev => prev.filter(a => a.id !== agentId));
      } else {
        const res = await fetch(`/api/agents/${agentId}/${action}`, { method: 'POST' });
        if (res.ok) {
          const updated = await res.json();
          setAgents(prev => prev.map(a => a.id === agentId ? updated : a));
        }
      }
    } finally {
      setActionLoading(null);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--ink)' }}>
        <Loader2 className="animate-spin" size={32} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  if (!data) return null;
  const { user, account } = data;

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
        <div className="flex items-center gap-4">
          {account && (
            <span className="text-sm px-3 py-1 rounded-full" style={{ background: 'var(--ink-light)', color: 'var(--text-dim)' }}>
              {account.name}
            </span>
          )}
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
          <a
            href="/auth/logout"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors hover:opacity-80"
            style={{ color: 'var(--text-dim)' }}
          >
            <LogOut size={14} />
            Sign out
          </a>
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
                isLoading={actionLoading === agent.id}
                onAction={handleAction}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

function AgentCard({
  agent, isLoading, onAction,
}: {
  agent: AgentInfo;
  isLoading: boolean;
  onAction: (id: string, action: 'start' | 'stop' | 'retry' | 'delete') => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const dotColor = STATUS_DOT[agent.status] || '#94a3b8';

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
              className="font-semibold hover:underline"
              style={{ color: 'var(--text)' }}
              title="View agent details"
            >
              {agent.name}
            </Link>
            <div className="flex items-center gap-3 mt-1">
              <span className="text-xs capitalize" style={{ color: 'var(--text-dim)' }}>
                {agent.status === 'provisioning' && (
                  <span className="inline-flex items-center gap-1">
                    <Loader2 className="animate-spin" size={10} />
                    Setting up...
                  </span>
                )}
                {agent.status !== 'provisioning' && agent.status}
              </span>
              {agent.created_at && (
                <span className="text-xs" style={{ color: 'var(--text-dim)', opacity: 0.6 }}>
                  Created {timeAgo(agent.created_at)}
                </span>
              )}
            </div>
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
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs transition-colors hover:opacity-80 disabled:opacity-50"
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
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs transition-colors hover:opacity-80 disabled:opacity-50"
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
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium transition-colors hover:opacity-80 disabled:opacity-50"
              style={{ color: '#facc15', border: '1px solid rgba(250,204,21,0.3)' }}
              title="Retry provisioning"
            >
              <RotateCcw size={12} />
              Retry
            </button>
          )}

          {agent.status !== 'provisioning' && (
            confirmDelete ? (
              <div className="flex items-center gap-1">
                <button
                  onClick={() => { onAction(agent.id, 'delete'); setConfirmDelete(false); }}
                  disabled={isLoading}
                  className="px-3 py-2 rounded-lg text-xs font-medium disabled:opacity-50"
                  style={{ background: '#ef4444', color: 'white' }}
                >
                  Confirm
                </button>
                <button
                  onClick={() => setConfirmDelete(false)}
                  className="px-3 py-2 rounded-lg text-xs"
                  style={{ color: 'var(--text-dim)' }}
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={() => setConfirmDelete(true)}
                disabled={isLoading}
                className="flex items-center gap-1 px-2 py-2 rounded-lg text-xs transition-colors hover:opacity-80 disabled:opacity-50"
                style={{ color: 'var(--text-dim)' }}
                title="Delete agent"
              >
                <Trash2 size={12} />
              </button>
            )
          )}
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
    </div>
  );
}
