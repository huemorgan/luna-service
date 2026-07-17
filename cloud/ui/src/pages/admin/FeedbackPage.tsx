import { useCallback, useEffect, useState } from 'react';
import { MessageSquareWarning, RefreshCw, Loader2, X, Send, User, Bot, Shield } from 'lucide-react';

interface TicketRow {
  id: string;
  title: string;
  category: string;
  origin: string;
  severity: string;
  status: string;
  created_at: string | null;
  updated_at: string | null;
  last_admin_reply_at: string | null;
  last_client_reply_at: string | null;
  unread_by_us: boolean;
  agent_name: string | null;
  agent_slug: string | null;
  account_slug: string | null;
}

interface Message {
  id: string;
  author: string;
  admin_user_id: string | null;
  body: string;
  meta: Record<string, any> | null;
  created_at: string | null;
}

interface Detail {
  ticket: TicketRow & { context: Record<string, any> | null };
  messages: Message[];
}

const CATEGORY_LABEL: Record<string, string> = {
  cost: 'Pricing', bug: 'Bug', frustration: 'Frustration', feature: 'Idea', praise: 'Praise', other: 'General',
};
const STATUS_COLOR: Record<string, string> = {
  open: '#eab308', answered: '#22c55e', closed: 'var(--text-dim)',
};
const AUTHOR_LABEL: Record<string, string> = { user: 'Owner', agent: 'Their Luna', admin: 'Luna team' };
const AUTHOR_ICON: Record<string, any> = { user: User, agent: Bot, admin: Shield };

const cardStyle = { background: 'var(--surface)', borderColor: 'var(--ink-lighter)' } as const;
const dimText = { color: 'var(--text-dim)' } as const;

function fmtAgo(iso: string | null): string {
  if (!iso) return '—';
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function StatusPill({ status }: { status: string }) {
  const c = STATUS_COLOR[status] || 'var(--text-dim)';
  return (
    <span className="text-xs px-2 py-0.5 rounded-full font-medium capitalize"
      style={{ color: c, background: `${c}22` }}>{status}</span>
  );
}

function OriginBadge({ origin }: { origin: string }) {
  const agent = origin === 'agent';
  return (
    <span className="text-xs px-2 py-0.5 rounded-full font-medium inline-flex items-center gap-1"
      style={agent
        ? { color: 'var(--moon)', background: 'rgba(201,184,255,0.15)' }
        : { color: 'var(--text-dim)', background: 'var(--ink-light)' }}>
      {agent ? <Bot size={11} /> : <User size={11} />}
      {agent ? 'agent-filed' : 'owner'}
    </span>
  );
}

export default function FeedbackPage() {
  const [tickets, setTickets] = useState<TicketRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusF, setStatusF] = useState('');
  const [categoryF, setCategoryF] = useState('');
  const [originF, setOriginF] = useState('');
  const [q, setQ] = useState('');
  const [selected, setSelected] = useState<string | null>(null);

  const fetchList = useCallback(async () => {
    const params = new URLSearchParams();
    if (statusF) params.set('status', statusF);
    if (categoryF) params.set('category', categoryF);
    if (originF) params.set('origin', originF);
    if (q) params.set('q', q);
    try {
      const res = await fetch(`/api/admin/feedback/tickets?${params}`);
      if (res.ok) setTickets((await res.json()).tickets || []);
    } catch { /* offline; keep prior list */ }
    setLoading(false);
  }, [statusF, categoryF, originF, q]);

  useEffect(() => { fetchList(); }, [fetchList]);

  return (
    <div className="max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          <MessageSquareWarning size={20} style={{ color: 'var(--moon)' }} />
          Feedback
        </h2>
        <button onClick={fetchList}
          className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition-all hover:scale-105"
          style={{ border: '1px solid var(--ink-lighter)', color: 'var(--text-dim)' }}>
          <RefreshCw size={14} />
        </button>
      </div>

      {/* filters */}
      <div className="flex flex-wrap gap-2 mb-4 items-center">
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search title…"
          className="px-3 py-1.5 rounded-lg text-sm border bg-transparent"
          style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text)' }} />
        <Select value={statusF} onChange={setStatusF} options={[['', 'All statuses'], ['open', 'Open'], ['answered', 'Answered'], ['closed', 'Closed']]} />
        <Select value={categoryF} onChange={setCategoryF} options={[['', 'All categories'], ...Object.entries(CATEGORY_LABEL)]} />
        <Select value={originF} onChange={setOriginF} options={[['', 'All origins'], ['user', 'Owner'], ['agent', 'Agent-filed']]} />
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
        </div>
      ) : (
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--ink-lighter)' }}>
          <table className="w-full">
            <thead>
              <tr style={{ background: 'var(--surface)', borderBottom: '1px solid var(--ink-lighter)' }}>
                {['', 'Title', 'Category', 'Origin', 'Agent', 'Updated', 'Status'].map((h, i) => (
                  <th key={i} className="text-left text-xs font-medium px-4 py-3" style={dimText}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tickets.length === 0 ? (
                <tr style={{ background: 'var(--surface)' }}>
                  <td colSpan={7} className="px-4 py-8 text-center text-sm" style={dimText}>
                    No feedback yet. Tickets arrive here when an owner writes in the Feedback pane
                    or their Luna files feedback on their behalf.
                  </td>
                </tr>
              ) : tickets.map(t => (
                <tr key={t.id} onClick={() => setSelected(t.id)}
                  className="border-t cursor-pointer hover:opacity-90"
                  style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}>
                  <td className="px-4 py-3">
                    {t.unread_by_us && <span className="inline-block w-2 h-2 rounded-full" style={{ background: '#eab308' }} title="Client replied — awaiting the team" />}
                  </td>
                  <td className="px-4 py-3 text-sm max-w-xs truncate" style={{ color: 'var(--text)' }}>{t.title}</td>
                  <td className="px-4 py-3 text-xs" style={dimText}>{CATEGORY_LABEL[t.category] || t.category}</td>
                  <td className="px-4 py-3"><OriginBadge origin={t.origin} /></td>
                  <td className="px-4 py-3 text-xs" style={dimText}>
                    {t.agent_name || '—'}{t.agent_slug && <span className="font-mono block opacity-70">{t.agent_slug}</span>}
                  </td>
                  <td className="px-4 py-3 text-xs" style={dimText}>{fmtAgo(t.updated_at)}</td>
                  <td className="px-4 py-3"><StatusPill status={t.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <TicketDrawer id={selected} onClose={() => setSelected(null)} onChanged={fetchList} />
      )}
    </div>
  );
}

function Select({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)}
      className="px-3 py-1.5 rounded-lg text-sm border bg-transparent"
      style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text)' }}>
      {options.map(([v, label]) => (
        <option key={v} value={v} style={{ background: 'var(--surface)', color: 'var(--text)' }}>{label}</option>
      ))}
    </select>
  );
}

function TicketDrawer({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [reply, setReply] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/admin/feedback/tickets/${id}`);
      if (res.ok) setDetail(await res.json());
      else setError(`${res.status} ${res.statusText}`);
    } catch (e: any) { setError(String(e)); }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const sendReply = async () => {
    if (!reply.trim()) return;
    setSending(true); setError(null);
    try {
      const res = await fetch(`/api/admin/feedback/tickets/${id}/reply`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body: reply.trim() }),
      });
      if (!res.ok) { setError((await res.json().catch(() => ({}))).detail || `${res.status}`); }
      else { setReply(''); await load(); onChanged(); }
    } catch (e: any) { setError(String(e)); }
    setSending(false);
  };

  const setStatus = async (status: string) => {
    await fetch(`/api/admin/feedback/tickets/${id}/status`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    });
    await load(); onChanged();
  };

  const t = detail?.ticket;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" style={{ background: 'rgba(0,0,0,0.4)' }} onClick={onClose}>
      <div className="w-full max-w-2xl h-full overflow-y-auto p-6 border-l"
        style={{ background: 'var(--ink)', borderColor: 'var(--ink-lighter)' }}
        onClick={e => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-4">
          <div>
            <div className="text-xs mb-1" style={dimText}>
              {t ? (CATEGORY_LABEL[t.category] || t.category).toUpperCase() : ''}
            </div>
            <h3 className="text-lg font-bold" style={{ color: 'var(--text)' }}>{t?.title || 'Loading…'}</h3>
            {t && (
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <StatusPill status={t.status} />
                <OriginBadge origin={t.origin} />
                <span className="text-xs" style={dimText}>
                  {t.agent_name} · <span className="font-mono">{t.agent_slug}</span>
                  {t.account_slug && <> · {t.account_slug}</>}
                </span>
              </div>
            )}
          </div>
          <button onClick={onClose} style={dimText}><X size={20} /></button>
        </div>

        {error && (
          <div className="rounded-lg px-3 py-2 mb-3 text-sm" style={{ color: '#ef4444', background: '#ef444411' }}>{error}</div>
        )}

        {/* thread */}
        <div className="space-y-3 mb-6">
          {(detail?.messages || []).map(m => {
            const Icon = AUTHOR_ICON[m.author] || User;
            const isAdmin = m.author === 'admin';
            return (
              <div key={m.id} className="rounded-xl border p-3" style={{
                ...cardStyle,
                borderColor: isAdmin ? 'var(--moon)' : 'var(--ink-lighter)',
              }}>
                <div className="flex items-center gap-2 mb-1">
                  <Icon size={13} style={{ color: isAdmin ? 'var(--moon)' : 'var(--text-dim)' }} />
                  <span className="text-xs font-semibold" style={{ color: 'var(--text)' }}>{AUTHOR_LABEL[m.author] || m.author}</span>
                  <span className="text-xs" style={dimText}>{fmtAgo(m.created_at)}</span>
                </div>
                <div className="text-sm whitespace-pre-wrap" style={{ color: 'var(--text)' }}>{m.body}</div>
                {m.meta?.technical && (
                  <pre className="mt-2 text-xs p-2 rounded overflow-x-auto" style={{ background: 'var(--ink-light)', color: 'var(--text-dim)' }}>
                    {JSON.stringify(m.meta.technical, null, 2)}
                  </pre>
                )}
                {m.meta?.conversation_excerpt && (
                  <details className="mt-2">
                    <summary className="text-xs cursor-pointer" style={dimText}>Conversation excerpt ({m.meta.conversation_excerpt.length})</summary>
                    <div className="mt-1 space-y-1">
                      {m.meta.conversation_excerpt.map((c: any, i: number) => (
                        <div key={i} className="text-xs" style={dimText}>
                          <span className="font-semibold">{c.role}:</span> {c.content}
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            );
          })}
        </div>

        {/* context */}
        {t?.context && (
          <details className="mb-6">
            <summary className="text-xs cursor-pointer font-semibold" style={dimText}>Context</summary>
            <pre className="mt-2 text-xs p-3 rounded-lg overflow-x-auto" style={{ background: 'var(--surface)', color: 'var(--text-dim)' }}>
              {JSON.stringify(t.context, null, 2)}
            </pre>
          </details>
        )}

        {/* reply box */}
        <div className="rounded-xl border p-3" style={cardStyle}>
          <textarea value={reply} onChange={e => setReply(e.target.value)} rows={3}
            placeholder="Reply to the owner…"
            className="w-full bg-transparent text-sm resize-none outline-none"
            style={{ color: 'var(--text)' }} />
          <div className="flex items-center justify-between mt-2">
            <div className="flex gap-2">
              {t?.status !== 'closed'
                ? <button onClick={() => setStatus('closed')} className="text-xs px-2 py-1 rounded" style={dimText}>Close ticket</button>
                : <button onClick={() => setStatus('open')} className="text-xs px-2 py-1 rounded" style={dimText}>Reopen</button>}
            </div>
            <button onClick={sendReply} disabled={sending || !reply.trim()}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium disabled:opacity-50"
              style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
              {sending ? <Loader2 className="animate-spin" size={14} /> : <Send size={14} />}
              Reply
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
