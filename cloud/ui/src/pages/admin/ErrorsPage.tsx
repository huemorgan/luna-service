import { useCallback, useEffect, useState } from 'react';
import { Bug, RefreshCw, Loader2, X, Globe, Bot, Server } from 'lucide-react';

interface Group {
  fingerprint: string;
  count: number;
  first_seen: string | null;
  last_seen: string | null;
  agent_count: number;
  severity: string;
  kind: string;
  source: string;
  sample_message: string;
  status: string;
  note: string | null;
  resolved_at: string | null;
  resolved_by_email: string | null;
}

interface GroupStatus {
  status: string;
  note: string | null;
  resolved_at: string | null;
  resolved_by_email: string | null;
}

interface ErrorEventView {
  id: string;
  source: string;
  kind: string;
  severity: string;
  message: string;
  fingerprint: string;
  context: Record<string, any> | null;
  occurred_at: string | null;
  created_at: string | null;
  agent_id: string | null;
  agent_name: string | null;
  agent_slug: string | null;
  account_id: string | null;
  account_slug: string | null;
}

const SEVERITY_COLOR: Record<string, string> = {
  critical: '#ef4444', error: '#f97316', warning: '#eab308', info: 'var(--text-dim)',
};
// 068: monday.com-style board cells. API values stay open/resolved/regressed;
// the operator-facing labels are new / resolved / not resolved.
const STATUS_COLOR: Record<string, string> = {
  open: '#579bfc', resolved: '#00c875', regressed: '#e2445c',
};
const STATUS_LABEL: Record<string, string> = {
  open: 'new', resolved: 'resolved', regressed: 'not resolved',
};
const SOURCE_ICON: Record<string, any> = { ui: Globe, agent: Bot, service: Server };
const KINDS = [
  'js_error', 'unhandled_rejection', 'page_load_failed', 'resource_error',
  'fetch_error', 'http_5xx', 'timeout', 'proxy_502', 'proxy_read_timeout',
  'agent_wake_failed', 'plugin_exception', 'llm_timeout', 'embed_error',
  'agent_report', 'unhandled_exception', 'gateway_auth', 'upstream_4xx',
];

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

function SeverityChip({ severity }: { severity: string }) {
  const c = SEVERITY_COLOR[severity] || 'var(--text-dim)';
  return (
    <span className="text-xs px-2 py-0.5 rounded-full font-medium capitalize"
      style={{ color: c, background: `${c}22` }}>{severity}</span>
  );
}

function StatusChip({ status }: { status: string }) {
  const c = STATUS_COLOR[status] || 'var(--text-dim)';
  return (
    <span className="text-xs px-2 py-0.5 rounded-full font-medium capitalize"
      style={{ color: '#fff', background: c }}>
      {STATUS_LABEL[status] || status}
    </span>
  );
}

// 068: monday-style board cell — the status color fills the WHOLE cell.
// Hovering shows the resolve/reopen reason (note), who and when.
function StatusCell({ g }: { g: Group }) {
  const c = STATUS_COLOR[g.status] || 'var(--ink-light)';
  const hasTip = !!(g.note || g.resolved_at || g.status === 'regressed');
  return (
    <td className="p-0 relative group/st" style={{ background: c, minWidth: '7.5rem' }}>
      <div className="flex items-center justify-center px-3 py-3 h-full text-xs font-semibold"
        style={{ color: '#fff' }}>
        {STATUS_LABEL[g.status] || g.status}
      </div>
      {hasTip && (
        <div className="pointer-events-none absolute left-1/2 top-full z-30 hidden w-64 -translate-x-1/2 group-hover/st:block"
          onClick={e => e.stopPropagation()}>
          <div className="mt-1 rounded-lg border px-3 py-2 text-left text-xs shadow-xl"
            style={{ background: 'var(--ink)', borderColor: 'var(--ink-lighter)', color: 'var(--text)' }}>
            {g.note
              ? <p className="whitespace-pre-wrap">{g.note}</p>
              : <p style={dimText}>No reason given.</p>}
            {g.status === 'regressed' && (
              <p className="mt-1 font-medium" style={{ color: STATUS_COLOR.regressed }}>
                Kept happening after resolve.
              </p>
            )}
            {g.resolved_at && (
              <p className="mt-1" style={dimText}>
                {g.status === 'open' ? 'reopened' : 'resolved'} by {g.resolved_by_email || 'unknown'} · {fmtAgo(g.resolved_at)}
              </p>
            )}
          </div>
        </div>
      )}
    </td>
  );
}

function SourceBadge({ source }: { source: string }) {
  const Icon = SOURCE_ICON[source] || Globe;
  return (
    <span className="text-xs px-2 py-0.5 rounded-full font-medium inline-flex items-center gap-1"
      style={source === 'service'
        ? { color: 'var(--moon)', background: 'rgba(201,184,255,0.15)' }
        : { color: 'var(--text-dim)', background: 'var(--ink-light)' }}>
      <Icon size={11} />
      {source}
    </span>
  );
}

export default function ErrorsPage() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [totals, setTotals] = useState<Record<string, number>>({});
  const [statusTotals, setStatusTotals] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [sourceF, setSourceF] = useState('');
  const [severityF, setSeverityF] = useState('');
  const [kindF, setKindF] = useState('');
  // 068: default shows EVERYTHING — resolved rows stay visible, marked green.
  const [statusF, setStatusF] = useState('');
  const [hours, setHours] = useState('168');
  const [sort, setSort] = useState('last_seen');
  const [q, setQ] = useState('');
  const [selected, setSelected] = useState<string | null>(null);

  const fetchList = useCallback(async () => {
    const params = new URLSearchParams();
    if (sourceF) params.set('source', sourceF);
    if (severityF) params.set('severity', severityF);
    if (kindF) params.set('kind', kindF);
    if (statusF) params.set('status', statusF);
    if (q) params.set('q', q);
    params.set('hours', hours);
    params.set('sort', sort);
    try {
      const res = await fetch(`/api/admin/errors?${params}`);
      if (res.ok) {
        const body = await res.json();
        setGroups(body.groups || []);
        setTotals(body.totals_by_severity || {});
        setStatusTotals(body.totals_by_status || {});
      }
    } catch { /* offline; keep prior list */ }
    setLoading(false);
  }, [sourceF, severityF, kindF, statusF, q, hours, sort]);

  useEffect(() => { fetchList(); }, [fetchList]);

  return (
    <div className="max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          <Bug size={20} style={{ color: 'var(--moon)' }} />
          Error Tracking
        </h2>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            {(['critical', 'error', 'warning', 'info'] as const).map(s => (
              <span key={s} className="text-xs font-mono" style={{ color: SEVERITY_COLOR[s] }}>
                {s}: {totals[s] || 0}
              </span>
            ))}
            <span className="text-xs" style={{ color: 'var(--ink-lighter)' }}>·</span>
            <span className="text-xs font-mono" style={{ color: STATUS_COLOR.open }}>
              new: {statusTotals.open || 0}
            </span>
            <span className="text-xs font-mono" style={{ color: STATUS_COLOR.regressed }}>
              not resolved: {statusTotals.regressed || 0}
            </span>
            <span className="text-xs font-mono" style={{ color: STATUS_COLOR.resolved }}>
              resolved: {statusTotals.resolved || 0}
            </span>
          </div>
          <button onClick={fetchList}
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition-all hover:scale-105"
            style={{ border: '1px solid var(--ink-lighter)', color: 'var(--text-dim)' }}>
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {/* filters */}
      <div className="flex flex-wrap gap-2 mb-4 items-center">
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search message…"
          className="px-3 py-1.5 rounded-lg text-sm border bg-transparent"
          style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text)' }} />
        <Select value={sourceF} onChange={setSourceF}
          options={[['', 'All sources'], ['ui', 'Browser'], ['agent', 'Agent'], ['service', 'Service']]} />
        <Select value={severityF} onChange={setSeverityF}
          options={[['', 'All severities'], ['critical', 'Critical'], ['error', 'Error'], ['warning', 'Warning'], ['info', 'Info']]} />
        <Select value={kindF} onChange={setKindF}
          options={[['', 'All kinds'], ...KINDS.map(k => [k, k] as [string, string])]} />
        <Select value={statusF} onChange={setStatusF}
          options={[['', 'All statuses'], ['active', 'New + not resolved'], ['open', 'New'], ['resolved', 'Resolved'], ['regressed', 'Not resolved']]} />
        <Select value={hours} onChange={setHours}
          options={[['24', 'Last 24h'], ['168', 'Last 7d'], ['720', 'Last 30d'], ['1440', 'Last 60d']]} />
        <Select value={sort} onChange={setSort}
          options={[['last_seen', 'Latest first'], ['count', 'Most frequent']]} />
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
                {['Severity', 'Status', 'Kind', 'Message', 'Source', 'Count', 'Agents', 'Last seen'].map((h, i) => (
                  <th key={i} className="text-left text-xs font-medium px-4 py-3" style={dimText}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {groups.length === 0 ? (
                <tr style={{ background: 'var(--surface)' }}>
                  <td colSpan={8} className="px-4 py-8 text-center text-sm" style={dimText}>
                    {statusF === 'active'
                      ? 'No new or not-resolved errors in this window — resolved ones are hidden by the status filter.'
                      : "No errors in this window. Events arrive from browsers and agents via plugin-feedback, and from luna-service's own edge (proxy, wakes, 5xx)."}
                  </td>
                </tr>
              ) : groups.map(g => (
                <tr key={g.fingerprint} onClick={() => setSelected(g.fingerprint)}
                  className="border-t cursor-pointer hover:opacity-90"
                  style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}>
                  <td className="px-4 py-3"><SeverityChip severity={g.severity} /></td>
                  <StatusCell g={g} />
                  <td className="px-4 py-3 text-xs font-mono" style={dimText}>{g.kind}</td>
                  <td className="px-4 py-3 text-sm max-w-md truncate" style={{ color: 'var(--text)' }}>{g.sample_message}</td>
                  <td className="px-4 py-3"><SourceBadge source={g.source} /></td>
                  <td className="px-4 py-3 text-sm font-mono" style={{ color: 'var(--text)' }}>{g.count}</td>
                  <td className="px-4 py-3 text-xs" style={dimText}>{g.agent_count || '—'}</td>
                  <td className="px-4 py-3 text-xs" style={dimText}>{fmtAgo(g.last_seen)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <GroupDrawer fingerprint={selected} onClose={() => setSelected(null)}
          onStatusChange={fetchList} />
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

function GroupDrawer({ fingerprint, onClose, onStatusChange }: {
  fingerprint: string; onClose: () => void; onStatusChange: () => void;
}) {
  const [events, setEvents] = useState<ErrorEventView[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [groupStatus, setGroupStatus] = useState<GroupStatus | null>(null);
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`/api/admin/errors/${fingerprint}`);
        if (res.ok) {
          const body = await res.json();
          setEvents(body.events || []);
          setOpen((body.events || [])[0]?.id || null);
          setGroupStatus(body.group_status || null);
          setNote(body.group_status?.note || '');
        } else setError(`${res.status} ${res.statusText}`);
      } catch (e: any) { setError(String(e)); }
    })();
  }, [fingerprint]);

  const setStatus = async (status: 'open' | 'resolved') => {
    setSaving(true);
    try {
      const res = await fetch(`/api/admin/errors/${fingerprint}/status`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, note: note.trim() || null }),
      });
      if (res.ok) {
        setGroupStatus((await res.json()).group_status);
        onStatusChange();
      } else setError(`${res.status} ${res.statusText}`);
    } catch (e: any) { setError(String(e)); }
    setSaving(false);
  };

  const head = events[0];

  return (
    <div className="fixed inset-0 z-50 flex justify-end" style={{ background: 'rgba(0,0,0,0.4)' }} onClick={onClose}>
      <div className="w-full max-w-2xl h-full overflow-y-auto p-6 border-l"
        style={{ background: 'var(--ink)', borderColor: 'var(--ink-lighter)' }}
        onClick={e => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-4">
          <div>
            <div className="text-xs mb-1 font-mono" style={dimText}>{head?.kind || ''} · {fingerprint.slice(0, 12)}</div>
            <h3 className="text-lg font-bold break-words" style={{ color: 'var(--text)' }}>{head?.message || 'Loading…'}</h3>
            {head && (
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <SeverityChip severity={head.severity} />
                <SourceBadge source={head.source} />
                {groupStatus && <StatusChip status={groupStatus.status} />}
                <span className="text-xs" style={dimText}>{events.length} recent event{events.length === 1 ? '' : 's'}</span>
              </div>
            )}
          </div>
          <button onClick={onClose} style={dimText}><X size={20} /></button>
        </div>

        {error && (
          <div className="rounded-lg px-3 py-2 mb-3 text-sm" style={{ color: '#ef4444', background: '#ef444411' }}>{error}</div>
        )}

        {groupStatus && (
          <div className="rounded-xl border p-3 mb-4" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
            {groupStatus.status !== 'open' && (
              <div className="text-xs mb-2" style={dimText}>
                Resolved {fmtAgo(groupStatus.resolved_at)}
                {groupStatus.resolved_by_email ? ` by ${groupStatus.resolved_by_email}` : ''}
                {groupStatus.status === 'regressed' && (
                  <span style={{ color: STATUS_COLOR.regressed }}> — new events arrived since</span>
                )}
              </div>
            )}
            <div className="flex items-center gap-2">
              <input value={note} onChange={e => setNote(e.target.value)}
                placeholder="Note (optional) — e.g. fixed in 0.54.003"
                className="flex-1 px-3 py-1.5 rounded-lg text-sm border bg-transparent"
                style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text)' }} />
              {groupStatus.status !== 'open' && (
                <button onClick={() => setStatus('open')} disabled={saving}
                  className="px-3 py-1.5 rounded-lg text-sm border"
                  style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text-dim)' }}>
                  Reopen
                </button>
              )}
              {groupStatus.status !== 'resolved' && (
                <button onClick={() => setStatus('resolved')} disabled={saving}
                  className="px-3 py-1.5 rounded-lg text-sm border font-medium"
                  style={{ borderColor: STATUS_COLOR.resolved, color: STATUS_COLOR.resolved }}>
                  {groupStatus.status === 'regressed' ? 'Re-resolve' : 'Mark resolved'}
                </button>
              )}
            </div>
          </div>
        )}

        <div className="space-y-3">
          {events.map(e => <EventCard key={e.id} event={e} open={open === e.id} onToggle={() => setOpen(open === e.id ? null : e.id)} />)}
        </div>
      </div>
    </div>
  );
}

function EventCard({ event, open, onToggle }: { event: ErrorEventView; open: boolean; onToggle: () => void }) {
  const client = event.context?.client || {};
  const server = event.context?.server || {};
  const flat = { ...(event.context || {}) };
  delete (flat as any).client; delete (flat as any).server;
  const ctx = { ...flat, ...client };
  const crumbs: any[] = Array.isArray(ctx.breadcrumbs) ? ctx.breadcrumbs : [];

  const fact = (label: string, value: any) => value != null && value !== '' && (
    <div className="flex gap-2 text-xs">
      <span className="shrink-0 w-28" style={dimText}>{label}</span>
      <span className="font-mono break-all" style={{ color: 'var(--text)' }}>{String(value)}</span>
    </div>
  );

  return (
    <div className="rounded-xl border p-3" style={{ background: 'var(--surface)', borderColor: open ? 'var(--moon)' : 'var(--ink-lighter)' }}>
      <button onClick={onToggle} className="w-full flex items-center justify-between text-left">
        <span className="flex items-center gap-2">
          <SeverityChip severity={event.severity} />
          <span className="text-xs" style={dimText}>{fmtAgo(event.created_at)}</span>
          {event.agent_slug && <span className="text-xs font-mono" style={dimText}>{event.agent_slug}</span>}
        </span>
        <span className="text-xs" style={dimText}>{open ? 'collapse' : 'expand'}</span>
      </button>

      {open && (
        <div className="mt-3 space-y-1.5">
          <div className="text-sm whitespace-pre-wrap break-words" style={{ color: 'var(--text)' }}>{event.message}</div>
          {fact('Route', ctx.route)}
          {fact('URL', ctx.url)}
          {fact('Method', ctx.method)}
          {fact('Status', ctx.status)}
          {fact('Target', ctx.target)}
          {fact('Latency', ctx.latency_ms != null ? `${ctx.latency_ms} ms` : null)}
          {fact('Plugin', ctx.plugin)}
          {fact('Turn', ctx.turn_id)}
          {fact('Agent', event.agent_name ? `${event.agent_name} (${event.agent_slug})` : event.agent_slug)}
          {fact('Account', event.account_slug || event.account_id)}
          {fact('Image', server.image_version || ctx.image_version)}
          {fact('User agent', ctx.user_agent)}
          {fact('Occurred', event.occurred_at)}
          {fact('Received', event.created_at)}

          {ctx.stack && (
            <pre className="mt-2 text-xs p-2 rounded overflow-x-auto max-h-64 overflow-y-auto"
              style={{ background: 'var(--ink-light)', color: 'var(--text-dim)' }}>{ctx.stack}</pre>
          )}

          {crumbs.length > 0 && (
            <details className="mt-2">
              <summary className="text-xs cursor-pointer" style={dimText}>Breadcrumbs ({crumbs.length})</summary>
              <div className="mt-1 space-y-0.5">
                {crumbs.map((c: any, i: number) => (
                  <div key={i} className="text-xs font-mono" style={dimText}>
                    {typeof c === 'string' ? c : JSON.stringify(c)}
                  </div>
                ))}
              </div>
            </details>
          )}

          <details className="mt-2">
            <summary className="text-xs cursor-pointer" style={dimText}>Raw context</summary>
            <pre className="mt-1 text-xs p-2 rounded overflow-x-auto"
              style={{ background: 'var(--ink-light)', color: 'var(--text-dim)' }}>
              {JSON.stringify(event.context, null, 2)}
            </pre>
          </details>
        </div>
      )}
    </div>
  );
}
