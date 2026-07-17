// 039/008 — shared types + helpers for the customer billing pages.
// Customer surfaces show credits only; the API never sends internal pricing.

export const API = '/api/billing';

export interface BillingSummary {
  posted_balance_credits: number;
  open_exposure_credits: number;
  debt_credits: number;
  balances: { paid: number; bonus: number; gift: number; free: number; topup: number };
  next_expiry_at: string | null;
  trial: {
    is_trial: boolean;
    expires_at: string | null;
    days_remaining: number | null;
    active_luna_cap: number | null;
  };
  hosting: Array<{
    agent_id: string;
    agent_name: string;
    agent_status: string;
    state: string | null;
    period_starts_at: string | null;
    period_ends_at: string | null;
    price_credits: number | null;
  }>;
  hosting_price_credits: number | null;
  recovery: {
    debt_credits: number;
    credits_required_for_positive_balance: number;
    hosting_restart_credits: number | null;
    payment_action_required: boolean;
    next_payment_retry_at: string | null;
  };
  billing_status: string;
  subscription: {
    product_key: string;
    status: string;
    pending_product_key: string | null;
    cancel_at_period_end: boolean;
    current_period_end: string | null;
  } | null;
  payments_enabled: boolean;
}

export interface Grant {
  id: string;
  category: string;
  original_credits: number;
  remaining_credits: number;
  effective_at: string;
  expires_at: string | null;
  status: string;
  use_next_order: number | null;
}

export interface Products {
  trial: Record<string, number | null>;
  hosting: { price_credits: number; period: string };
  products: Array<{
    key: string;
    kind: string;
    interval: string | null;
    price_usd_cents: number;
    paid_credits: number;
    bonus_credits: number;
    yearly_gift_credits: number;
    monthly_paid_lot_credits: number | null;
    monthly_bonus_lot_credits: number | null;
  }>;
  topup_steps_usd_cents: number[];
  credit_value_usd_cents: number;
  payments_enabled: boolean;
}

export interface UsageSummary {
  range: { since: string; until: string };
  used_credits: number;
  today_credits: number;
  month_credits: number;
  remaining_credits: number;
  next_expiry_at: string | null;
  trend: Array<{ day: string; credits: number }>;
  projected_depletion_days: number | null;
  projection_is_estimate: boolean;
  per_luna: Array<{
    agent_id: string;
    agent_name: string;
    daily: PerLunaWindow;
    monthly: PerLunaWindow;
    warning_threshold_pct: number | null;
  }>;
}

export interface PerLunaWindow {
  used_credits: number;
  limit_credits: number | null;
  resets_at: string | null;
}

export interface ChannelTrendPoint {
  day: string;
  credits: number;
}

export interface ChannelTrigger {
  key: string;
  name: string;
  total: number;
  trend: ChannelTrendPoint[];
}

export interface ChannelSection {
  total: number;
  trend: ChannelTrendPoint[];
  triggers?: ChannelTrigger[];
}

export interface ChannelUsage {
  range: { since: string; until: string };
  y_max: number;
  sections: {
    web: ChannelSection;
    scheduler: ChannelSection;
    whatsapp: ChannelSection;
    telegram: ChannelSection;
  };
}

export interface BreakdownRow {
  key: string;
  id: string | null;
  credits: number;
  calls: number;
}

export interface ActionRow {
  root_action_id: string;
  at: string;
  agent_id: string | null;
  agent_name: string | null;
  label: string;
  service: string;
  status: string;
  credits: number;
  children: Array<{
    call_id: string;
    at: string;
    service: string;
    plugin: string | null;
    model: string | null;
    credits: number;
    status: string;
  }>;
}

export interface StatementRow {
  at: string;
  type: string;
  reason: string | null;
  service: string | null;
  agent_name: string | null;
  credits: number;
  balance_after: number;
}

/** Frozen 402 contract (039/004) — customer-honest labels for every block code. */
export const BLOCK_MESSAGES: Record<string, { title: string; body: string }> = {
  credits_exhausted: {
    title: 'Out of credits',
    body: 'Your balance is used up. Add credits to keep your Lunas working.',
  },
  luna_daily_limit: {
    title: 'Daily limit reached',
    body: 'This Luna hit its daily credit limit. It resumes when the day resets, or raise the limit below.',
  },
  luna_monthly_limit: {
    title: 'Monthly limit reached',
    body: 'This Luna hit its monthly credit limit. It resumes when the month resets, or raise the limit below.',
  },
  hosting_payment_due: {
    title: 'Hosting payment due',
    body: 'An always-on Luna could not be renewed and was paused. Add credits to restart it.',
  },
  sku_unpriced: {
    title: 'Service not priced yet',
    body: 'This action is not in the price list yet — our fault, not yours. Nothing was charged.',
  },
  exposure_limit: {
    title: 'Too many open actions',
    body: 'Safety cap on in-flight spending reached. Wait for running actions to finish and retry.',
  },
  billing_temporarily_unavailable: {
    title: 'Billing briefly unavailable',
    body: 'We could not verify your balance just now. This is on our side — retry in a moment.',
  },
};

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

export function getJson<T>(url: string): Promise<T> {
  return fetch(url).then(r => (r.ok ? r.json() : apiError(r).then(m => Promise.reject(new Error(m)))));
}

export function postJson<T>(url: string, body?: unknown): Promise<T> {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then(r => (r.ok ? r.json() : apiError(r).then(m => Promise.reject(new Error(m)))));
}

export const credits = (n: number) => `${n.toLocaleString()} cr`;
export const usd = (cents: number) =>
  `$${(cents / 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

export const fmtDate = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '—';

export const fmtDateTime = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleString(undefined, {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
      })
    : '—';
