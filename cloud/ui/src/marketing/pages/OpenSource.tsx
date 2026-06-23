import { Link } from 'react-router-dom';
import Reveal from '../components/Reveal';
import { StartFree } from '../components/cta';
import { useSeo } from '../lib/seo';
import { GITHUB_URL, DOCS_URL } from '../lib/constants';
import ossImg from '../assets/open-source.png';

export default function OpenSource() {
  useSeo({
    title: 'Luna Open Source — the MIT agent you can self-host',
    description:
      'Luna is open source under MIT — self-host on a $5 VPS, inside your VPC or fully air-gapped to fit any security restriction. A deliberately lean, auditable core you expand with plugins: use any plugins, run across environments, and roll your own.',
  });

  return (
    <>
      <section className="mkt-section flush">
        <div className="wrap">
          <div className="phero">
            <div className="sg-eyebrow">Luna Open Source</div>
            <h1>The agent itself —<br /><em>open, all the way down</em></h1>
            <p>
              Luna is open source under the MIT license. Self-host it on a $5 VPS. The whole platform
              that makes Luna trustworthy is open too — so trust isn't a promise, it's something you
              can read.
            </p>
            <div className="btn-row">
              <a className="btn btn-primary btn-lg" href={GITHUB_URL} target="_blank" rel="noopener noreferrer">Star on GitHub ↗</a>
              <a className="btn btn-ghost btn-lg" href={DOCS_URL} target="_blank" rel="noopener noreferrer">Read the docs ↗</a>
            </div>
          </div>
          <Reveal>
            <div className="media" style={{ marginTop: 30 }}>
              <img src={ossImg} alt="Engineers collaborating around a laptop in a co-working space" />
            </div>
          </Reveal>
        </div>
      </section>

      <section className="mkt-section">
        <div className="wrap">
          <div className="sg-eyebrow">Why open</div>
          <h2 className="sg-h2">Trustworthy <em className="stext gtext">because</em> it's open</h2>
          <p className="sg-lead">
            You can't ask anyone to hand an agent their credentials and their production systems on
            faith. So the parts that earn that trust are open — the vault, the rollback, the
            approval gates. Inspect them, run them, fork them.
          </p>
          <div className="grid cols-3" style={{ marginTop: 30 }}>
            {[
              ['MIT licensed', 'Use it commercially, modify it, ship it. No rug-pull license traps.'],
              ['Self-host anywhere', 'A single Luna runs happily on a $5 VPS. Your machine, your data, your rules.'],
              ['Readable security', 'The vault, rollback and approval-gate code are open — verify the claims yourself.'],
              ['Plugin architecture', 'Everything is a plugin. Build your own tools, channels and skills with the SDK.'],
              ['Bonded security plugins', 'Sensitive capabilities are isolated and bounded — not free to touch the machine.'],
              ['Open-platform promise', 'We never relicense backwards. If we ever break the promise, you keep a working fork.'],
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

      <section className="mkt-section">
        <div className="wrap">
          <div className="sg-eyebrow">Lean core, expand anywhere</div>
          <h2 className="sg-h2">A tiny core you can run <em className="stext gtext">anywhere</em> — and grow with plugins</h2>
          <p className="sg-lead">
            Luna's core is deliberately lean: a small, auditable engine that does one job — run agents
            safely. Everything else — tools, channels, skills, connectors — is a plugin you add only
            when you need it. A small core means a small attack surface, a fast read-through, and a
            footprint that drops into any environment.
          </p>
          <div className="grid cols-3" style={{ marginTop: 30 }}>
            {[
              ['Fits any security restriction', 'Self-host inside your own VPC, on-prem, or fully air-gapped. Because it runs in your environment, Luna bends to your compliance and security posture — not the other way around.'],
              ['A lean, auditable core', 'The core stays small and readable on purpose. Less to trust, less to attack, less to hold in your head — you can review the whole base, not a sprawling framework.'],
              ['Expandable everywhere', 'Self-hosting keeps the entire plugin model. Add connectors and tools, mix a different plugin set per environment, and grow Luna without ever touching the core.'],
              ['Roll your own plugins', 'Build private plugins on the open SDK for your internal and legacy systems — no upstream permission, no forking the core.'],
              ['Same core, many environments', 'One lean footprint runs on a $5 VPS or a hardened internal box — expanded differently wherever it lands.'],
              ['Built to be extended', 'We expect Luna to grow through plugins. The core is the stable, trustworthy base; capability lives at the edges, where you control it.'],
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

      <section className="mkt-section">
        <div className="wrap">
          <Reveal>
            <div className="card" style={{ textAlign: 'center', padding: '44px 28px' }}>
              <h2 className="sg-h2">Want it without the setup?</h2>
              <p className="sg-lead" style={{ margin: '14px auto 0' }}>
                Skip the VPS, the keys and the ops. Get the same Luna, hosted, isolated and managed —
                running in about a minute.
              </p>
              <div className="btn-row" style={{ justifyContent: 'center', marginTop: 24 }}>
                <StartFree withGoogle />
                <Link className="btn btn-ghost" to="/products/hosting">Luna Hosting Service</Link>
              </div>
            </div>
          </Reveal>
        </div>
      </section>
    </>
  );
}
