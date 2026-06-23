import Reveal from '../components/Reveal';
import { useSeo } from '../lib/seo';
import { LOGIN_URL, CONTACT_EMAIL } from '../lib/constants';
import { StartFree } from '../components/cta';

interface Tier {
  name: string;
  amount: string;
  per?: string;
  featured?: boolean;
  features: string[];
  cta: { label: string; href: string };
}

const TIERS: Tier[] = [
  {
    name: 'Free',
    amount: '$0',
    features: ['Suspended Luna, chat anytime', 'Web access + secure vault', 'Cheap-model budget to explore'],
    cta: { label: 'Start free', href: LOGIN_URL },
  },
  {
    name: 'Pro',
    amount: '$29',
    per: '/mo',
    featured: true,
    features: ['Always-on + scheduled triggers', 'Any model, generous budget', 'MCP + multi-channel'],
    cta: { label: 'Start free', href: LOGIN_URL },
  },
  {
    name: 'Power',
    amount: '$99',
    per: '/mo',
    features: ['Dedicated CPU', 'Frontier models', 'Code execution sandbox'],
    cta: { label: 'Start free', href: LOGIN_URL },
  },
  {
    name: 'Enterprise',
    amount: 'Custom',
    features: ['Dedicated Postgres', 'SSO + data residency', 'Audit exports & support'],
    cta: { label: 'Contact us', href: CONTACT_EMAIL },
  },
];

export default function Pricing() {
  useSeo({
    title: 'Pricing — one bill, any model, no BYOK',
    description:
      'Free / Pro / Power / Enterprise. One usage meter, no API keys to manage, switch any model freely. Free to start; upgrade for always-on, bigger budgets and frontier models.',
  });

  return (
    <>
      <section className="mkt-section flush">
        <div className="wrap">
          <div className="phero">
            <div className="sg-eyebrow">Pricing</div>
            <h1>One bill. Any model.<br /><em>No keys to manage.</em></h1>
            <p>
              Switch between Opus, Sonnet, Haiku, GPT and Gemini freely — a single usage meter, no
              BYOK. Start free; upgrade when you want always-on autonomy, bigger budgets and frontier
              models. Budgets degrade gracefully instead of failing hard.
            </p>
          </div>

          <div className="grid cols-4" style={{ marginTop: 36 }}>
            {TIERS.map(t => (
              <Reveal key={t.name}>
                <div className={`card price ${t.featured ? 'featured' : ''}`}>
                  <span className={`tier ${t.featured ? 'gtext' : ''}`}>{t.name}</span>
                  <span className="amt">{t.amount}{t.per && <small>{t.per}</small>}</span>
                  <ul>
                    {t.features.map(f => <li key={f}>{f}</li>)}
                  </ul>
                  <a
                    className={`btn ${t.featured ? 'btn-primary' : 'btn-ghost'} btn-sm`}
                    href={t.cta.href}
                    style={{ marginTop: 6 }}
                  >
                    {t.cta.label}
                  </a>
                </div>
              </Reveal>
            ))}
          </div>
          <p className="sg-note" style={{ marginTop: 18 }}>
            All plans include physical isolation, the one-way vault and full transparency. Pricing is
            informational while billing rolls out — every CTA gets you a working Luna today.
          </p>
        </div>
      </section>

      <section className="mkt-section">
        <div className="wrap">
          <div className="grid cols-3">
            {[
              ['No BYOK', 'You never manage an Anthropic or OpenAI key. We meter usage; you get one bill.'],
              ['Any model, anytime', 'Pick the right model per task — frontier when it matters, cheap when it doesn\'t.'],
              ['Graceful budgets', 'Hit a limit and Luna degrades gracefully instead of breaking mid-task.'],
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
