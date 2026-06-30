import { useEffect, useState, useCallback, useRef } from 'react';
import type { ReactNode } from 'react';
import { AlertTriangle, Hammer, Loader2, CheckCircle2, ArrowUpCircle } from 'lucide-react';

type RebakeState = 'none' | 'building' | 'ready';

interface StaleStatus {
  stale: boolean;
  main_version: string | null;
  main_image_id: string | null;
  current_count: number;
  baked_count: number;
  rebake_state: RebakeState;
  rebake_version: string | null;
  rebake_image_id: string | null;
}

/**
 * Plan 033 — two-step rebake banner. Walks the admin through:
 *   stale  → "Bake new image with current defaults"  (POST /images/rebake)
 *   building → "Baking v… — a few minutes" (self-polls)
 *   ready  → "Promote v… to Main" (POST /images/{id}/promote-main): migrates
 *            agents and deletes the old main image.
 * The current main is never mutated in place. `refreshKey` lets the host page
 * force a re-check after edits.
 */
export default function DefaultsStaleBanner({ refreshKey }: { refreshKey?: unknown }) {
  const [status, setStatus] = useState<StaleStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const check = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/defaults/stale');
      if (res.ok) setStatus(await res.json());
    } catch {
      /* best-effort; banner just stays hidden */
    }
  }, []);

  useEffect(() => { check(); }, [check, refreshKey]);

  // Poll while a rebake is building so the banner flips to "ready" on its own.
  useEffect(() => {
    if (status?.rebake_state === 'building') {
      if (!pollRef.current) pollRef.current = setInterval(check, 5000);
    } else if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [status?.rebake_state, check]);

  const bake = async () => {
    setBusy(true);
    try {
      const res = await fetch('/api/admin/images/rebake', { method: 'POST' });
      if (res.ok) {
        await check();
      } else {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        alert(`Bake failed: ${err.detail || JSON.stringify(err)}`);
      }
    } catch (e: unknown) {
      alert(`Bake error: ${e instanceof Error ? e.message : e}`);
    }
    setBusy(false);
  };

  const promote = async () => {
    if (!status?.rebake_image_id) return;
    const oldMain = status.main_version ? ` and remove old main v${status.main_version}` : '';
    if (!window.confirm(
      `Promote v${status.rebake_version} to Main?\n\nThis migrates all agents to it${oldMain}.`,
    )) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/admin/images/${status.rebake_image_id}/promote-main`, { method: 'POST' });
      const data = await res.json().catch(() => null);
      if (res.ok && data) {
        const removed = data.deleted_old ? ` Removed old main v${data.deleted_old}.` : '';
        const failed = data.errors?.length ? ` ${data.errors.length} agent(s) failed to migrate — old main kept.` : '';
        alert(`v${data.promoted} is now Main. Migrated ${data.migrated} agent(s).${removed}${failed}`);
        await check();
      } else {
        alert(`Promote failed: ${data?.detail || res.statusText}`);
      }
    } catch (e: unknown) {
      alert(`Promote error: ${e instanceof Error ? e.message : e}`);
    }
    setBusy(false);
  };

  if (!status) return null;
  const visible = status.stale || status.rebake_state !== 'none';
  if (!visible) return null;

  // ── ready: green promote step ──────────────────────────────────────────────
  if (status.rebake_state === 'ready') {
    return (
      <Shell
        tone="green"
        icon={<CheckCircle2 size={16} style={{ color: '#22c55e' }} />}
        left={
          <Text
            title={`New image v${status.rebake_version} is baked with the current defaults`}
            sub={`Promote it to Main — migrates all agents${status.main_version ? ` and removes the old main v${status.main_version}` : ''}.`}
          />
        }
        right={
          <Btn onClick={promote} disabled={busy} bg="#22c55e"
            icon={busy ? <Loader2 className="animate-spin" size={14} /> : <ArrowUpCircle size={14} />}>
            Promote to Main
          </Btn>
        }
      />
    );
  }

  // ── building: amber spinner, no action ─────────────────────────────────────
  if (status.rebake_state === 'building') {
    return (
      <Shell
        tone="amber"
        icon={<Loader2 className="animate-spin" size={16} style={{ color: '#facc15' }} />}
        left={
          <Text
            title={`Baking new image v${status.rebake_version} with the current defaults…`}
            sub="This takes a few minutes. You can leave this page — it'll be ready to promote when done."
          />
        }
      />
    );
  }

  // ── stale: amber bake step ─────────────────────────────────────────────────
  return (
    <Shell
      tone="amber"
      icon={<AlertTriangle size={16} style={{ color: '#facc15' }} />}
      left={
        <Text
          title={`Default plugin set changed since main image${status.main_version ? ` v${status.main_version}` : ''} was built`}
          sub="Bake a new image with the current defaults, then promote it to roll out to agents."
        />
      }
      right={
        <Btn onClick={bake} disabled={busy} bg="#facc15"
          icon={busy ? <Loader2 className="animate-spin" size={14} /> : <Hammer size={14} />}>
          Bake new image
        </Btn>
      }
    />
  );
}

function Shell({ tone, icon, left, right }: {
  tone: 'amber' | 'green'; icon: ReactNode; left: ReactNode; right?: ReactNode;
}) {
  const c = tone === 'green'
    ? { bg: 'rgba(34,197,94,0.08)', border: 'rgba(34,197,94,0.35)' }
    : { bg: 'rgba(250,204,21,0.08)', border: 'rgba(250,204,21,0.35)' };
  return (
    <div
      className="rounded-xl border p-4 mb-6 flex items-center justify-between gap-4 flex-wrap"
      style={{ background: c.bg, borderColor: c.border }}
    >
      <div className="flex items-start gap-2.5 min-w-0">
        <span className="flex-shrink-0 mt-0.5">{icon}</span>
        {left}
      </div>
      {right ?? null}
    </div>
  );
}

function Text({ title, sub }: { title: string; sub: string }) {
  return (
    <div>
      <div className="text-sm font-medium" style={{ color: 'var(--text)' }}>{title}</div>
      <div className="text-xs mt-0.5" style={{ color: 'var(--text-dim)' }}>{sub}</div>
    </div>
  );
}

function Btn({ onClick, disabled, bg, icon, children }: {
  onClick: () => void; disabled: boolean; bg: string; icon: ReactNode; children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all hover:scale-105 disabled:opacity-50 flex-shrink-0"
      style={{ background: bg, color: 'var(--ink)' }}
    >
      {icon}
      {children}
    </button>
  );
}
