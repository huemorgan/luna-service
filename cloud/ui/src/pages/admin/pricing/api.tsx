// 039/002 — shared types + fetch helpers for the admin Pricing section.

export const API = '/api/admin/pricing';

export interface PricingVersion {
  id: string;
  version_number: number;
  name: string | null;
  status: 'draft' | 'published' | 'retired';
  parent_version_id: string | null;
  config_hash: string;
  config_schema_version: number;
  notes: string | null;
  created_at: string | null;
  published_at: string | null;
  config?: PricingConfig;
  diff_vs_parent?: ConfigDiff;
  uncovered_models?: string[];
}

// The config is admin-authored JSON validated server-side; the UI treats it
// as a loosely typed document and never computes prices itself.
export interface PricingConfig {
  credit_value_micro_usd: number;
  top_tier_models: string[];
  mid_tier_models: string[];
  llm_constants: Record<string, Record<string, number>>;
  skus: Array<{
    key: string; service: string; formula: string; enabled: boolean;
    constants?: Record<string, number>;
    [k: string]: unknown;
  }>;
  hosting: { price_credits: number;[k: string]: unknown };
  products: Array<{
    key: string; kind: string; price_usd_cents: number; paid_credits: number;
    bonus_credits?: number; interval?: string | null;
    [k: string]: unknown;
  }>;
  trial: Record<string, number>;
  migration_gift: Record<string, number>;
  [k: string]: unknown;
}

export type ConfigDiff = Record<string, { from: unknown; to: unknown }>;

export interface Overview {
  default_version: PricingVersion | null;
  version_status_counts: Record<string, number>;
  customer_liability_credits: number;
  uncovered_debt_credits: number;
  dead_billing_jobs: number;
  needs_reconciliation_holds: number;
  assigned_accounts: number;
}

export interface ProviderCostVersionOut {
  id: string;
  version_number: number;
  status: string;
  effective_at: string | null;
  config_hash: string;
  notes: string | null;
  created_at: string | null;
  published_at: string | null;
  rates?: ProviderRate[];
}

export interface ProviderRate {
  provider: string;
  sku: string;
  dimension: string;
  unit: string;
  rate_numerator: number;
  rate_denominator: number;
  quality: string;
  source_url: string | null;
}

export interface Rollout {
  id: string;
  commercial_pricing_version_id: string;
  audience: string;
  selected_account_ids: string[] | null;
  effective_at: string | null;
  migration_policy: string | null;
  status: string;
  accounts_scheduled: number | null;
  accounts_applied: number | null;
  accounts_failed: number | null;
  created_at: string | null;
}

/** Coerce a FastAPI error body to a display string (422 details are arrays). */
export async function apiError(res: Response): Promise<string> {
  const body = await res.json().catch(() => null);
  const d = body?.detail;
  if (Array.isArray(d)) {
    return d
      .map((e: { loc?: (string | number)[]; msg?: string }) =>
        `${e.loc?.slice(1).join('.') || 'field'}: ${e.msg || 'invalid'}`)
      .join('; ');
  }
  if (typeof d === 'string') return d;
  return `Failed (${res.status})`;
}

export const credits = (n: number) => `${n.toLocaleString()} cr`;
export const creditsUsd = (n: number) =>
  `${n.toLocaleString()} cr ($${(n / 100).toLocaleString(undefined, { maximumFractionDigits: 2 })})`;

export const STATUS_COLORS: Record<string, { bg: string; fg: string }> = {
  draft: { bg: 'rgba(122,162,255,0.15)', fg: '#7aa2ff' },
  published: { bg: 'rgba(120,220,160,0.15)', fg: '#78dca0' },
  retired: { bg: 'rgba(160,160,160,0.15)', fg: '#a0a0a0' },
  scheduled: { bg: 'rgba(122,162,255,0.15)', fg: '#7aa2ff' },
  running: { bg: 'rgba(255,200,100,0.15)', fg: '#ffc864' },
  completed: { bg: 'rgba(120,220,160,0.15)', fg: '#78dca0' },
  completed_with_failures: { bg: 'rgba(255,107,107,0.15)', fg: '#ff6b6b' },
  failed: { bg: 'rgba(255,107,107,0.15)', fg: '#ff6b6b' },
  pending: { bg: 'rgba(122,162,255,0.15)', fg: '#7aa2ff' },
  succeeded: { bg: 'rgba(120,220,160,0.15)', fg: '#78dca0' },
  cancelled: { bg: 'rgba(160,160,160,0.15)', fg: '#a0a0a0' },
};

export function StatusPill({ status }: { status: string }) {
  const c = STATUS_COLORS[status] ?? STATUS_COLORS.retired;
  return (
    <span className="px-2 py-0.5 rounded-full text-xs font-medium"
      style={{ background: c.bg, color: c.fg }}>
      {status.replaceAll('_', ' ')}
    </span>
  );
}
