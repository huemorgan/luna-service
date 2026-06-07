import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  ChevronDown, ChevronLeft, ChevronRight, ChevronUp,
  Filter, Loader2, Search, X,
} from 'lucide-react';

interface AuditActor {
  id: string;
  name: string | null;
  email: string;
  avatar_url: string | null;
}

interface AuditEntry {
  id: string;
  action: string;
  actor: AuditActor | null;
  actor_ip: string | null;
  target: string | null;
  metadata: Record<string, any> | null;
  before_state: Record<string, any> | null;
  after_state: Record<string, any> | null;
  created_at: string;
}

interface AuditResponse {
  items: AuditEntry[];
  total: number;
  page: number;
  per_page: number;
}

const ACTION_LABELS: Record<string, (m: any) => string> = {
  'admin.added':              m => `${m?.email || 'User'} added as admin`,
  'admin.removed':            m => `${m?.email || 'User'} removed from admins`,
  'admin.add_admin':          m => `${m?.email || 'User'} added as admin`,
  'admin.remove_admin':       m => `${m?.email || 'User'} removed from admins`,
  'image.build_triggered':    m => `Build triggered for v${m?.version || '?'}`,
  'image.build_completed':    m => `Build completed for v${m?.version || '?'}`,
  'image.build_failed':       m => `Build failed for v${m?.version || '?'}${m?.error ? `: ${m.error}` : ''}`,
  'image.config_updated':     m => `Config updated for v${m?.version || '?'}`,
  'image.promoted_to_main':   m => `v${m?.version || '?'} promoted to main`,
  'image.deleted':            m => `Image v${m?.version || '?'} deleted`,
  'admin.set_main_image':     m => `v${m?.version || '?'} promoted to main`,
  'admin.update_image_config': m => `Config updated for v${m?.version || '?'}`,
  'admin.delete_image':       m => `Image v${m?.version || '?'} deleted`,
  'machine.image_updated':    m => `Machine updated to v${m?.version || '?'} (${m?.agent || '?'})`,
  'machine.migrate_all':      m => `${m?.updated || 0} machines migrated to v${m?.version || '?'}`,
  'admin.update_machine_image': m => `Machine updated to v${m?.version || '?'} (${m?.agent || '?'})`,
  'admin.migrate_all':        m => `${m?.updated || 0} machines migrated to v${m?.version || '?'}`,
  'agent.test_created':       m => `Test agent "${m?.agent_slug || '?'}" created on v${m?.version || '?'}`,
  'admin.test_agent':         m => `Test agent "${m?.agent_slug || '?'}" created on v${m?.version || '?'}`,
};

const ACTION_COLORS: Record<string, string> = {
  'admin.added': '#22c55e',
  'admin.removed': '#ef4444',
  'image.build_triggered': '#3b82f6',
  'image.build_completed': '#22c55e',
  'image.build_failed': '#ef4444',
  'image.config_updated': '#3b82f6',
  'image.promoted_to_main': '#a78bfa',
  'image.deleted': '#ef4444',
  'machine.image_updated': '#eab308',
  'machine.migrate_all': '#eab308',
  'agent.test_created': '#22c55e',
};

function getActionColor(action: string): string {
  if (ACTION_COLORS[action]) return ACTION_COLORS[action];
  if (action.includes('delete') || action.includes('remove') || action.includes('failed')) return '#ef4444';
  if (action.includes('create') || action.includes('add') || action.includes('built') || action.includes('completed')) return '#22c55e';
  if (action.includes('migrate')) return '#eab308';
  if (action.includes('update') || action.includes('promote') || action.includes('main')) return '#a78bfa';
  return '#6b7280';
}

function describeAction(action: string, metadata: any): string {
  const fn = ACTION_LABELS[action];
  if (fn) return fn(metadata);
  return action;
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

const ACTION_OPTIONS = [
  { value: '', label: 'All actions' },
  { value: 'admin.', label: 'Admin changes' },
  { value: 'image.', label: 'Image actions' },
  { value: 'machine.', label: 'Machine actions' },
  { value: 'agent.', label: 'Agent actions' },
];

export default function ChangelogPage() {
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<AuditResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState(params.get('q') || '');

  const page = parseInt(params.get('page') || '1');
  const actionFilter = params.get('action') || '';
  const q = params.get('q') || '';

  const fetchData = useCallback(async () => {
    setLoading(true);
    const qs = new URLSearchParams();
    qs.set('page', String(page));
    qs.set('per_page', '50');
    if (actionFilter) qs.set('action', actionFilter);
    if (q) qs.set('q', q);

    try {
      const res = await fetch(`/api/admin/audit-log?${qs}`);
      if (res.ok) setData(await res.json());
    } finally {
      setLoading(false);
    }
  }, [page, actionFilter, q]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.set('page', '1');
    setParams(next);
  };

  const totalPages = data ? Math.ceil(data.total / data.per_page) : 0;

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6" style={{ color: 'var(--text)' }}>Changelog</h1>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 mb-6">
        <div className="relative">
          <Filter size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--text-dim)' }} />
          <select
            value={actionFilter}
            onChange={e => setFilter('action', e.target.value)}
            className="pl-9 pr-8 py-2 rounded-lg text-sm appearance-none cursor-pointer"
            style={{
              background: 'var(--ink-light)',
              color: 'var(--text)',
              border: '1px solid var(--ink-lighter)',
            }}
          >
            {ACTION_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        <form
          className="relative flex-1 min-w-[200px] max-w-sm"
          onSubmit={e => { e.preventDefault(); setFilter('q', searchInput); }}
        >
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--text-dim)' }} />
          <input
            type="text"
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
            placeholder="Search events..."
            className="w-full pl-9 pr-8 py-2 rounded-lg text-sm"
            style={{
              background: 'var(--ink-light)',
              color: 'var(--text)',
              border: '1px solid var(--ink-lighter)',
            }}
          />
          {searchInput && (
            <button
              type="button"
              onClick={() => { setSearchInput(''); setFilter('q', ''); }}
              className="absolute right-2 top-1/2 -translate-y-1/2"
              style={{ color: 'var(--text-dim)' }}
            >
              <X size={14} />
            </button>
          )}
        </form>

        {(actionFilter || q) && (
          <button
            onClick={() => { setSearchInput(''); setParams({}); }}
            className="text-xs px-3 py-2 rounded-lg hover:opacity-80 transition-opacity"
            style={{ color: 'var(--moon)', border: '1px solid var(--ink-lighter)' }}
          >
            Clear filters
          </button>
        )}

        <span className="ml-auto text-xs" style={{ color: 'var(--text-dim)' }}>
          {data ? `${data.total} event${data.total !== 1 ? 's' : ''}` : ''}
        </span>
      </div>

      {/* Events */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
        </div>
      ) : !data || data.items.length === 0 ? (
        <div className="text-center py-20" style={{ color: 'var(--text-dim)' }}>
          No events found{(actionFilter || q) ? ' matching filters' : ''}.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {data.items.map(entry => (
            <EventCard
              key={entry.id}
              entry={entry}
              isExpanded={expanded === entry.id}
              onToggle={() => setExpanded(expanded === entry.id ? null : entry.id)}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-4 mt-8">
          <button
            onClick={() => setFilter('page', String(page - 1))}
            disabled={page <= 1}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm disabled:opacity-30 hover:opacity-80 transition-opacity"
            style={{ color: 'var(--text-dim)' }}
          >
            <ChevronLeft size={14} /> Previous
          </button>
          <span className="text-sm" style={{ color: 'var(--text-dim)' }}>
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setFilter('page', String(page + 1))}
            disabled={page >= totalPages}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm disabled:opacity-30 hover:opacity-80 transition-opacity"
            style={{ color: 'var(--text-dim)' }}
          >
            Next <ChevronRight size={14} />
          </button>
        </div>
      )}
    </div>
  );
}

function EventCard({ entry, isExpanded, onToggle }: { entry: AuditEntry; isExpanded: boolean; onToggle: () => void }) {
  const color = getActionColor(entry.action);
  const hasDetail = entry.before_state || entry.after_state || entry.metadata;

  return (
    <div
      className="rounded-xl border transition-colors"
      style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}
    >
      <button
        onClick={onToggle}
        className="w-full flex items-start gap-3 px-4 py-3 text-left"
        disabled={!hasDetail}
      >
        {/* Color dot */}
        <div
          className="w-2 h-2 rounded-full mt-2 flex-shrink-0"
          style={{ background: color }}
        />

        <div className="flex-1 min-w-0">
          {/* Action name */}
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="text-xs font-mono px-2 py-0.5 rounded"
              style={{ background: `${color}15`, color }}
            >
              {entry.action}
            </span>
          </div>

          {/* Description */}
          <div className="text-sm mt-1" style={{ color: 'var(--text)' }}>
            {describeAction(entry.action, entry.metadata)}
          </div>

          {/* Meta line */}
          <div className="flex items-center gap-3 mt-1.5 text-xs" style={{ color: 'var(--text-dim)' }}>
            {entry.actor ? (
              <span className="flex items-center gap-1.5">
                {entry.actor.avatar_url ? (
                  <img src={entry.actor.avatar_url} alt="" className="w-4 h-4 rounded-full" />
                ) : (
                  <div
                    className="w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold"
                    style={{ background: 'var(--moon)', color: 'var(--ink)' }}
                  >
                    {(entry.actor.name || entry.actor.email)[0].toUpperCase()}
                  </div>
                )}
                {entry.actor.name || entry.actor.email}
              </span>
            ) : (
              <span style={{ color: 'var(--text-dim)' }}>System</span>
            )}
            {entry.actor_ip && (
              <span style={{ fontFamily: 'monospace', fontSize: '11px' }}>{entry.actor_ip}</span>
            )}
            <span title={entry.created_at ? new Date(entry.created_at).toLocaleString() : ''}>
              {entry.created_at ? timeAgo(entry.created_at) : ''}
            </span>
          </div>
        </div>

        {hasDetail && (
          <div className="flex-shrink-0 mt-1" style={{ color: 'var(--text-dim)' }}>
            {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </div>
        )}
      </button>

      {isExpanded && hasDetail && (
        <div
          className="px-4 pb-3 pt-0 border-t mx-4 mb-2"
          style={{ borderColor: 'var(--ink-lighter)' }}
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
            {entry.before_state && (
              <div>
                <div className="text-xs font-medium mb-1.5" style={{ color: '#ef4444' }}>Before</div>
                <pre
                  className="text-xs p-3 rounded-lg overflow-auto max-h-48"
                  style={{ background: 'var(--ink)', color: 'var(--text-dim)', fontFamily: 'monospace' }}
                >
                  {JSON.stringify(entry.before_state, null, 2)}
                </pre>
              </div>
            )}
            {entry.after_state && (
              <div>
                <div className="text-xs font-medium mb-1.5" style={{ color: '#22c55e' }}>After</div>
                <pre
                  className="text-xs p-3 rounded-lg overflow-auto max-h-48"
                  style={{ background: 'var(--ink)', color: 'var(--text-dim)', fontFamily: 'monospace' }}
                >
                  {JSON.stringify(entry.after_state, null, 2)}
                </pre>
              </div>
            )}
          </div>
          {entry.metadata && (
            <div className="mt-3">
              <div className="text-xs font-medium mb-1.5" style={{ color: 'var(--text-dim)' }}>Metadata</div>
              <pre
                className="text-xs p-3 rounded-lg overflow-auto max-h-48"
                style={{ background: 'var(--ink)', color: 'var(--text-dim)', fontFamily: 'monospace' }}
              >
                {JSON.stringify(entry.metadata, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
