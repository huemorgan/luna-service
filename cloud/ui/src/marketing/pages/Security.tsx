import Reveal from '../components/Reveal';
import { useSeo } from '../lib/seo';
import trustImg from '../assets/trust-vault.jpg';

export default function Security() {
  useSeo({
    title: 'Trust & security — the page to send your ops lead',
    description:
      'Physical per-tenant isolation, a one-way vault we can\'t read, no data access, approval gates, rollback on every change, and transparent audit. Trust, by architecture.',
  });

  return (
    <>
      <section className="mkt-section flush">
        <div className="wrap">
          <div className="phero">
            <div className="sg-eyebrow">Trust &amp; security</div>
            <h1>Trust, <em>by architecture</em></h1>
            <p>
              An agent is only useful if you can hand it real credentials and real production systems.
              So safety isn't a setting in Luna — it's the structure. Here's exactly how it's built.
            </p>
          </div>
          <Reveal>
            <div className="media" style={{ marginTop: 30 }}>
              <img src={trustImg} alt="A technician working hands-on inside a secured server rack" />
            </div>
          </Reveal>
        </div>
      </section>

      <section className="mkt-section">
        <div className="wrap">
          <div className="grid cols-2" style={{ marginTop: 6 }}>
            {[
              ['Physical per-tenant isolation', 'Each tenant gets its own microVM, database, vault key and MCP subprocesses. No shared schema, no noisy-neighbor blast radius. Even a malicious plugin author is sandboxed to their own machine.'],
              ['A one-way vault', 'Secrets resolve below the plugin layer. The LLM receives the action to take, never the credential itself — and the vault key is per-tenant, so we can\'t read it either.'],
              ['Your IP and credentials stay yours', 'Per-tenant keys and a one-way vault we can\'t read. We analyze sessions and usage to learn and improve Luna — statistically, to make the product and our models better — never to act in your accounts, and your IP remains yours.'],
              ['Approval gates', 'Anything sensitive pauses for a human. Autonomy stays bounded — the agent proposes, you approve, then it acts.'],
              ['Rollback on every change', 'Luna records and can undo what it changed. There\'s no silent, irreversible damage to discover later.'],
              ['Transparent audit', 'A clear, reviewable record of what ran, what changed and why. No black box about what your agent did.'],
            ].map(([title, body]) => (
              <Reveal key={title}>
                <div className="card hov feature">
                  <h3>{title}</h3>
                  <p style={{ fontSize: 14.5 }}>{body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="mkt-section">
        <div className="wrap">
          <div className="sg-eyebrow">The contrast</div>
          <h2 className="sg-h2">Why first-gen agents aren't safe enough</h2>
          <div className="grid cols-3" style={{ marginTop: 30 }}>
            <Reveal>
              <div className="diagram">
                <h4>Luna · bounded &amp; gated</h4>
                <div className="lane flow"><span className="node" /><span className="node" /><span className="node" /></div>
                <p>Capabilities can do a lot — but can't touch the machine, read keys, or act without approval.</p>
              </div>
            </Reveal>
            <Reveal>
              <div className="diagram">
                <h4>First-gen · unbounded</h4>
                <div className="lane chaos"><span className="node" /><span className="node" /><span className="node" /></div>
                <p>Self-coding can touch any key, override any constraint, and wreck itself.</p>
              </div>
            </Reveal>
            <Reveal>
              <div className="diagram">
                <h4>One-way vault</h4>
                <div className="vault"><span className="key" /><span className="pipe" /><span className="wall">no keys to&nbsp;LLM</span></div>
                <p>Secrets never enter the model's context.</p>
              </div>
            </Reveal>
          </div>
        </div>
      </section>
    </>
  );
}
