import { Link } from 'react-router-dom';
import Reveal from '../components/Reveal';
import { StartFree } from '../components/cta';
import { useSeo } from '../lib/seo';
import { GITHUB_URL, PRODUCTS } from '../lib/constants';

import heroImg from '../assets/hero.png';
import reliabilityImg from '../assets/reliability.png';
import trustImg from '../assets/trust-vault.png';
import selfImg from '../assets/self-improving.png';
import ossImg from '../assets/open-source.png';
import hostingImg from '../assets/hosting-service.png';
import marketImg from '../assets/marketplaces.png';

const PRODUCT_IMG: Record<string, string> = {
  '/products/open-source': ossImg,
  '/products/hosting': hostingImg,
  '/products/marketplace': marketImg,
};

export default function Home() {
  useSeo({
    title: 'Luna — agents you can actually rely on',
    description:
      'Luna is the second generation of self-improving agents — built reliable, secure and transparent, fit to own business-critical work. Your own private Luna in ~60 seconds.',
  });

  return (
    <>
      {/* ── HERO ───────────────────────────────────────────── */}
      <section className="mkt-section flush" style={{ paddingTop: 28 }}>
        <div className="wrap">
          <div className="hero">
            <span className="orb a" /><span className="orb b" /><span className="orb c" />
            <span className="badge soft" style={{ marginBottom: 18 }}>Second-generation agents</span>
            <h1>Agents you can <em>actually rely on</em></h1>
            <p>
              Self-improving, like the first generation promised — but reliable, secure and
              transparent. Fit to own the work that matters.
            </p>
            <div className="btn-row">
              <StartFree size="btn-lg" withGoogle />
              <a className="btn btn-ghost btn-lg" href={GITHUB_URL} target="_blank" rel="noopener noreferrer">
                Explore open source
              </a>
            </div>
            <p className="eyebrow">For the people who need agents that do real work — FDEs, ops, founders, builders.</p>
          </div>

          <Reveal>
            <div className="stats" style={{ marginTop: 18 }}>
              <div><i className="stat-kicker">Instant</i><b className="gtext">~60s</b><span>signup to working Luna</span></div>
              <div><i className="stat-kicker">Secure</i><b className="gtext">0</b><span>keys exposed to the LLM</span></div>
              <div><i className="stat-kicker">Unified billing</i><b className="gtext">1</b><span>bill · any model</span></div>
              <div><i className="stat-kicker">Limitless Luna</i><b className="gtext">∞</b><span>plugins &amp; capabilities</span></div>
            </div>
          </Reveal>

          <Reveal>
            <div className="media" style={{ marginTop: 18 }}>
              <img src={heroImg} alt="An operations lead watching Luna work through her task list" />
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── THE PROBLEM ────────────────────────────────────── */}
      <section className="mkt-section">
        <div className="wrap">
          <div className="sg-eyebrow">The problem</div>
          <h2 className="sg-h2">The first generation showed the promise — then broke.</h2>
          <p className="sg-lead">
            "Claw-style" agents proved autonomous work is possible, but they keep breaking, run
            inconsistently, and aren't safe near anything that matters. Two root flaws: unbounded
            self-coding that can touch any key or override any constraint, and everything riding on
            raw LLM reasoning with no framework — so execution drifts into chaos.
          </p>
          <div className="grid cols-3" style={{ marginTop: 30 }}>
            <Reveal>
              <div className="diagram">
                <h4>Luna · deterministic workflow</h4>
                <div className="lane flow"><span className="node" /><span className="node" /><span className="node" /></div>
                <div className="lane flow"><span className="node" /><span className="node" /></div>
                <p>Repeatable. Precise. Built &amp; improved by the agent — not run by raw LLM reasoning.</p>
              </div>
            </Reveal>
            <Reveal>
              <div className="diagram">
                <h4>First-gen "Claw" chaos</h4>
                <div className="lane chaos"><span className="node" /><span className="node" /></div>
                <div className="lane chaos"><span className="node" /><span className="node" /><span className="node" /></div>
                <p>Everything on the LLM. Inconsistent. Breaks under real-world load.</p>
              </div>
            </Reveal>
            <Reveal>
              <div className="diagram">
                <h4>One-way vault</h4>
                <div className="vault">
                  <span className="key" /><span className="pipe" /><span className="wall">no keys to&nbsp;LLM</span>
                </div>
                <p>Secrets resolve below the plugin layer. They never enter the model's context.</p>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ── TWO PILLARS ────────────────────────────────────── */}
      <section className="mkt-section">
        <div className="wrap">
          <div className="sg-eyebrow">The Luna difference</div>
          <h2 className="sg-h2">Two pillars: reliability and trust</h2>
          <p className="sg-lead">
            Keep everything self-reflective and self-improving — but make it dependable enough to own
            business-critical work, and safe enough to hand real credentials.
          </p>
          <div className="grid cols-2" style={{ marginTop: 30 }}>
            <Reveal>
              <div className="card hov">
                <img className="visual" src={reliabilityImg} alt="An SRE watching steady, all-green dashboards" />
                <h3>Reliable</h3>
                <ul className="checklist" style={{ marginTop: 14 }}>
                  <li><span><b>Repeats tasks without failing.</b> Deterministic playbooks the agent builds and refines.</span></li>
                  <li><span><b>Improves without breaking itself.</b> The self-improvement loop is bounded and operator-gated.</span></li>
                  <li><span><b>Solid execution.</b> Real framework underneath, not raw LLM volatility.</span></li>
                </ul>
              </div>
            </Reveal>
            <Reveal>
              <div className="card hov">
                <img className="visual" src={trustImg} alt="A security lead confident in a modern server room" />
                <h3>Trustworthy</h3>
                <ul className="checklist" style={{ marginTop: 14 }}>
                  <li><span><b>Secure.</b> No keys to the LLM, a proper one-way vault, safe on any environment.</span></li>
                  <li><span><b>Truthful.</b> Architecture that limits hallucination instead of hoping against it.</span></li>
                  <li><span><b>Transparent.</b> No black box — you can see and audit what it actually did.</span></li>
                </ul>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ── HOW IT WORKS ───────────────────────────────────── */}
      <section className="mkt-section">
        <div className="wrap">
          <div className="sg-eyebrow">How it works</div>
          <h2 className="sg-h2">Everything is a plugin — on a scaffold built for trust</h2>
          <p className="sg-lead">
            Plugins let Luna extend to any task. The scaffold makes that safe: capabilities can do a
            lot, but they can't touch the machine, read keys, or act without approval.
          </p>
          <div className="grid cols-3" style={{ marginTop: 30 }}>
            {[
              ['Plugin scaffold', 'Everything — tools, channels, skills — is a plugin. Add capability without forking, isolated per agent.'],
              ['One-way vault', 'Keys resolve below the plugin layer. The LLM gets the action, never the secret.'],
              ['Rollback on every change', 'Luna can always see and undo what it changed. No silent, irreversible damage.'],
              ['Deterministic workflows', 'Repeatable playbooks the agent authors and improves — run by a real engine, not by reasoning each time.'],
              ['Approval gates', 'Anything sensitive pauses for a human. Autonomy with a seatbelt.'],
              ['Cloud + a real database', 'Persistent state on real infrastructure — adapts to any environment, even legacy systems.'],
            ].map(([title, body]) => (
              <Reveal key={title}>
                <div className="card hov feature">
                  <h3>{title}</h3>
                  <p>{body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ── SELF-IMPROVING, MADE SAFE ──────────────────────── */}
      <section className="mkt-section">
        <div className="wrap">
          <div className="split">
            <div>
              <div className="sg-eyebrow">Self-reflective &amp; self-improving</div>
              <h2 className="sg-h2">It learns like a teammate — safely</h2>
              <p className="sg-lead" style={{ marginBottom: 18 }}>
                Talk to it, it learns. It tries, you correct, it improves. The human-like loop the first
                generation promised — except the improvement loop lives <em className="stext">inside</em> the
                agent, bounded and gated by the operator, so getting better never means breaking itself.
              </p>
              <ul className="checklist">
                <li><span>Describe the goal in plain language — it builds the workflow.</span></li>
                <li><span>You review and correct — it folds your feedback into the playbook.</span></li>
                <li><span>It runs reliably next time, and keeps tightening over time.</span></li>
              </ul>
            </div>
            <Reveal className="media">
              <img src={selfImg} alt="An analyst beside an upward-trending performance chart" />
            </Reveal>
          </div>
        </div>
      </section>

      {/* ── USE CASES ──────────────────────────────────────── */}
      <section className="mkt-section">
        <div className="wrap">
          <div className="sg-eyebrow">What you can do</div>
          <h2 className="sg-h2">Put it on the work you keep redoing</h2>
          <div className="grid cols-3" style={{ marginTop: 30 }}>
            {[
              ['Recurring ops reports', 'Pull from your systems, compile, and deliver the same report every morning — on a trigger.'],
              ['Inbox & ticket triage', 'Read, classify, draft and route — with approval gates before anything is sent.'],
              ['Wire up legacy systems', 'Connectors and MCP let Luna talk to internal and legacy tools others can\'t reach.'],
              ['Scheduled autonomy', '"Email me a summary at 9am." Always-on triggers do the work while you sleep.'],
              ['Agent-built internal tooling', 'Luna writes and runs the small tools your team keeps wishing existed.'],
              ['Run a fleet', 'One Luna per project or client, each isolated, all visible from one dashboard.'],
            ].map(([title, body]) => (
              <Reveal key={title}>
                <div className="card hov feature">
                  <h3>{title}</h3>
                  <p>{body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ── TRUST STRIP ────────────────────────────────────── */}
      <section className="mkt-section">
        <div className="wrap">
          <div className="sg-eyebrow">Trust &amp; security</div>
          <h2 className="sg-h2">Built for the skeptical ops lead</h2>
          <div className="grid cols-4" style={{ marginTop: 30 }}>
            {[
              ['Physical isolation', 'Own microVM, database, vault key and subprocesses — per tenant.'],
              ['A vault we can\'t read', 'Per-tenant key. Secrets never reach the LLM, or us.'],
              ['We never look at your data', 'No conversation telemetry. Your work stays yours.'],
              ['Transparent audit', 'A clear record of what ran, what changed, and why.'],
            ].map(([title, body]) => (
              <Reveal key={title}>
                <div className="card hov feature">
                  <h3 style={{ fontSize: 15 }}>{title}</h3>
                  <p style={{ fontSize: 13 }}>{body}</p>
                </div>
              </Reveal>
            ))}
          </div>
          <p className="sg-note" style={{ marginTop: 16 }}>
            <Link className="btn-link" to="/security" style={{ paddingLeft: 0 }}>Read the full trust &amp; security story <span className="arrow">→</span></Link>
          </p>
        </div>
      </section>

      {/* ── PRODUCTS TRIPTYCH ──────────────────────────────── */}
      <section className="mkt-section">
        <div className="wrap">
          <div className="sg-eyebrow">Explore Luna</div>
          <h2 className="sg-h2">One platform, three ways in</h2>
          <div className="grid cols-3" style={{ marginTop: 30 }}>
            {PRODUCTS.map(p => (
              <Reveal key={p.to}>
                <Link to={p.to} className="card glow hov" style={{ display: 'block' }}>
                  <img className="visual" src={PRODUCT_IMG[p.to]} alt={p.title} />
                  <h3>{p.title}</h3>
                  <p>{p.blurb}</p>
                  <div className="more btn-link" style={{ paddingLeft: 0 }}>Learn more <span className="arrow">→</span></div>
                </Link>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ── PRICING TEASER ─────────────────────────────────── */}
      <section className="mkt-section">
        <div className="wrap">
          <Reveal>
            <div className="card" style={{ textAlign: 'center', padding: '44px 28px' }}>
              <div className="sg-eyebrow" style={{ justifyContent: 'center' }}>Pricing</div>
              <h2 className="sg-h2">One bill. No API keys to manage. Use any model.</h2>
              <p className="sg-lead" style={{ margin: '14px auto 0' }}>
                Switch between Opus, Sonnet, Haiku, GPT and Gemini freely — one usage meter, no BYOK.
                Free to start; upgrade for always-on, bigger budgets and frontier models.
              </p>
              <div className="btn-row" style={{ justifyContent: 'center', marginTop: 24 }}>
                <Link className="btn btn-ghost" to="/pricing">See pricing</Link>
                <StartFree />
              </div>
            </div>
          </Reveal>
        </div>
      </section>
    </>
  );
}
