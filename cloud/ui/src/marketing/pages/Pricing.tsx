import { useEffect, useState } from 'react';
import Reveal from '../components/Reveal';
import { useSeo } from '../lib/seo';
import { LOGIN_URL } from '../lib/constants';
import { StartFree } from '../components/cta';

interface PublicProduct {
  key: string;
  kind: string;
  interval: string | null;
  price_usd_cents: number;
  paid_credits: number;
  bonus_credits: number;
  yearly_gift_credits: number;
  monthly_paid_lot_credits: number | null;
  monthly_bonus_lot_credits: number | null;
}

interface PublicPricing {
  trial: {
    gift_credits: number | null;
    days: number | null;
    daily_limit_credits: number | null;
    monthly_limit_credits: number | null;
    active_luna_cap: number | null;
  };
  hosting: { price_credits: number; period: string };
  products: PublicProduct[];
  topup_steps_usd_cents: number[];
  credit_value_usd_cents: number;
}

const PLAN_NAMES: Record<string, string> = {
  hobby_19: 'Hobby',
  recurring_99: 'Pro',
  recurring_199: 'Power',
};

const fmt = (n: number) => n.toLocaleString('en-US');
const usd = (cents: number) => `$${fmt(Math.round(cents / 100))}`;

export default function Pricing() {
  useSeo({
    title: 'Pricing — unified billing, any model, one credit system',
    description:
      'One usage meter, no API keys to manage, switch any model freely. Start with a free trial; ' +
      'subscribe for monthly credits, add top-ups anytime. 1 credit = $0.01.',
  });

  const [pricing, setPricing] = useState<PublicPricing | null>(null);
  const [failed, setFailed] = useState(false);
  const [yearly, setYearly] = useState(false);

  useEffect(() => {
    fetch('/api/public/pricing')
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(setPricing)
      .catch(() => setFailed(true));
  }, []);

  const monthlyPlans = (pricing?.products ?? []).filter(
    p => p.kind === 'subscription' && p.interval === 'month',
  );
  const plans = monthlyPlans.map(m => {
    const y = pricing?.products.find(
      p => p.kind === 'subscription' && p.interval === 'year' && p.key === `${m.key}_yearly`,
    );
    return yearly && y ? y : m;
  });
  const topups = (pricing?.products ?? []).filter(p => p.kind === 'topup');
  const trial = pricing?.trial;

  const planFeatures = (p: PublicProduct): string[] => {
    const monthlyPaid = p.interval === 'year' ? (p.monthly_paid_lot_credits ?? 0) : p.paid_credits;
    const monthlyBonus = p.interval === 'year' ? (p.monthly_bonus_lot_credits ?? 0) : p.bonus_credits;
    const rows = [`${fmt(monthlyPaid)} credits every month`];
    if (monthlyBonus > 0) rows.push(`+${fmt(monthlyBonus)} bonus credits monthly`);
    if (p.yearly_gift_credits > 0) rows.push(`+${fmt(p.yearly_gift_credits)} gift credits each year`);
    rows.push('Any model on one credit meter');
    return rows;
  };

  // Credits are worth $0.01 each, so a credit total IS a cent amount; when the
  // bonus makes the credit value exceed the price, show the value struck out.
  const planAmount = (p: PublicProduct) => {
    const yearlyPlan = p.interval === 'year';
    const priceCents = yearlyPlan ? p.price_usd_cents / 12 : p.price_usd_cents;
    const valueCents = yearlyPlan
      ? (p.monthly_paid_lot_credits ?? 0) + (p.monthly_bonus_lot_credits ?? 0)
      : p.paid_credits + p.bonus_credits;
    return {
      amount: usd(priceCents),
      per: yearlyPlan ? '/mo billed yearly' : '/mo',
      was: valueCents > priceCents ? usd(valueCents) : null,
    };
  };

  return (
    <>
      <section className="mkt-section flush">
        <div className="wrap">
          <div className="phero">
            <div className="sg-eyebrow">Pricing</div>
            <h1>One bill. Any model.<br /><em>No keys to manage.</em></h1>
            <p>
              Switch between Opus, Sonnet, Haiku, GPT and Gemini freely — unified billing puts every
              model and service on one credit system. 1 credit = $0.01. Start with a free trial;
              subscribe when you want always-on autonomy, and top up anytime.
            </p>
          </div>

          <div className="btn-row" style={{ justifyContent: 'center', marginTop: 28 }}>
            <button
              className={`btn btn-sm ${yearly ? 'btn-ghost' : 'btn-primary'}`}
              onClick={() => setYearly(false)}
            >
              Monthly
            </button>
            <button
              className={`btn btn-sm ${yearly ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => setYearly(true)}
            >
              Yearly
            </button>
          </div>

          {failed && (
            <p className="sg-note" style={{ marginTop: 24, textAlign: 'center' }}>
              Pricing is being published — check back shortly, or start free below.
            </p>
          )}

          {pricing && trial && (
            <div className="grid cols-4" style={{ marginTop: 24 }}>
              <Reveal>
                <div className="card price">
                  <span className="tier">Free trial</span>
                  <span className="amt">$0<small> to start</small></span>
                  <ul>
                    <li>{fmt(trial.gift_credits ?? 0)} credits included</li>
                    <li>{trial.days ?? 28} days to explore</li>
                    <li>Up to {fmt(trial.daily_limit_credits ?? 0)} credits/day</li>
                    <li>{trial.active_luna_cap ?? 1} active Luna</li>
                  </ul>
                  <a className="btn btn-ghost btn-sm" href={LOGIN_URL} style={{ marginTop: 6 }}>
                    Start free
                  </a>
                </div>
              </Reveal>
              {plans.map(p => {
                const base = p.key.replace(/_yearly$/, '');
                const featured = base === 'recurring_99';
                const { amount, per, was } = planAmount(p);
                return (
                  <Reveal key={base}>
                    <div className={`card price ${featured ? 'featured' : ''}`}>
                      <span className={`tier ${featured ? 'gtext' : ''}`}>
                        {PLAN_NAMES[base] ?? base}
                      </span>
                      <span className="amt">
                        {was && <s className="was">{was}</s>}
                        {amount}<small>{per}</small>
                      </span>
                      <ul>
                        {planFeatures(p).map(f => <li key={f}>{f}</li>)}
                      </ul>
                      <a
                        className={`btn ${featured ? 'btn-primary' : 'btn-ghost'} btn-sm`}
                        href={LOGIN_URL}
                        style={{ marginTop: 6 }}
                      >
                        Start free
                      </a>
                    </div>
                  </Reveal>
                );
              })}
            </div>
          )}

          {pricing && (
            <div className="grid cols-2" style={{ marginTop: 20 }}>
              <Reveal>
                <div className="card price">
                  <span className="tier">Top-ups</span>
                  <ul>
                    {topups.map(t => (
                      <li key={t.key}>
                        {usd(t.price_usd_cents)} → {fmt(t.paid_credits)} credits
                      </li>
                    ))}
                  </ul>
                  <p className="sg-note">One-time credits, no subscription needed.</p>
                </div>
              </Reveal>
              <Reveal>
                <div className="card price">
                  <span className="tier">Always-on hosting</span>
                  <ul>
                    <li>{fmt(pricing.hosting.price_credits)} credits per Luna / {pricing.hosting.period}</li>
                    <li>Paid from your credit balance</li>
                    <li>Suspended Lunas cost nothing</li>
                  </ul>
                  <p className="sg-note">Chat with a suspended Luna anytime — hosting is only for always-on.</p>
                </div>
              </Reveal>
            </div>
          )}

          <p className="sg-note" style={{ marginTop: 18 }}>
            All plans include physical isolation, the one-way vault and full transparency. Online
            payments are rolling out — every CTA gets you a working Luna today.
          </p>
        </div>
      </section>

      <section className="mkt-section">
        <div className="wrap">
          <div className="grid cols-3">
            {[
              ['Unified billing', 'Access every model and service under one credit system — no keys to manage, one bill.'],
              ['Any model, anytime', 'Pick the right model per task — frontier when it matters, cheap when it doesn\'t.'],
              ['Limits you control', 'Set daily and monthly credit caps per Luna and get warned before they hit.'],
            ].map(([title, body]) => (
              <Reveal key={title}>
                <div className="card hov feature"><h3>{title}</h3><p>{body}</p></div>
              </Reveal>
            ))}
          </div>
          <div className="btn-row" style={{ justifyContent: 'center', marginTop: 30 }}>
            <StartFree size="btn-lg" withGoogle />
          </div>
        </div>
      </section>
    </>
  );
}
