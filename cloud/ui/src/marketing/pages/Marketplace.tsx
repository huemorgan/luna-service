import Reveal from '../components/Reveal';
import { MarketplaceCta } from '../components/cta';
import MarketplaceCtaBand from '../components/MarketplaceCtaBand';
import { useSeo } from '../lib/seo';
import { PLUGIN_CURSOR_ZIP_URL, MARKETPLACE_BASE_URL } from '../lib/constants';
import marketImg from '../assets/marketplaces.jpg';

export default function Marketplace() {
  useSeo({
    title: 'Luna Marketplaces — your own plugin marketplace',
    description:
      'Luna Marketplaces is a separate product: open your own plugin marketplace and point your Lunas at a source you trust. Organizations curate internal directories; vendors sell their catalog. Build plugins with the downloadable Cursor environment.',
  });

  return (
    <div className="t-market">
      <section className="mkt-section flush">
        <div className="wrap">
          <div className="phero">
            <div className="sg-eyebrow">Luna Marketplaces · a separate product</div>
            <h1>Your own plugin<br /><em>marketplace</em></h1>
            <p>
              Everything in Luna is a plugin — and a marketplace is a plugin directory you trust.
              Open your own, fill it with the connectors, tools and packs you sanction, and point
              every Luna you run straight at it.
            </p>
            <div className="btn-row">
              <MarketplaceCta size="btn-lg" secondary />
            </div>
          </div>
          <Reveal>
            <div className="media" style={{ marginTop: 30 }}>
              <img src={marketImg} alt="Operators walking a warehouse floor, scanner in hand" />
            </div>
          </Reveal>
        </div>
      </section>

      <section className="mkt-section">
        <div className="wrap">
          <div className="sg-eyebrow">What it is</div>
          <h2 className="sg-h2">A directory of capability — from a source you <em className="stext gtext">control</em></h2>
          <p className="sg-lead">
            Instead of installing plugins off the open internet, you run your own marketplace and
            connect your Lunas to it. Installs come from somewhere you own and govern — not a stranger
            on the web.
          </p>
        </div>
      </section>

      <section className="mkt-section">
        <div className="wrap">
          <div className="sg-eyebrow">What you do here</div>
          <h2 className="sg-h2">Sign up → create → connect</h2>
          <div className="steps cols-3 grid" style={{ marginTop: 30 }}>
            {[
              ['Sign up', 'Create a Marketplaces account — separate from your hosted Luna, with its own dashboard.'],
              ['Create a marketplace', 'Spin up your directory and add the connectors, tools, templates and packs you sanction.'],
              ['Connect your Lunas', 'Point your agents at it. They install only from your source — curated, governed, yours.'],
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
          <div className="sg-eyebrow">Who it's for</div>
          <h2 className="sg-h2">Open a marketplace for your team — or your customers</h2>
          <div className="grid cols-2" style={{ marginTop: 30 }}>
            <Reveal>
              <div className="card hov">
                <h3>For organizations</h3>
                <p style={{ marginBottom: 14 }}>Roll your own internal plugin directory and wire it into every employee's Luna.</p>
                <ul className="checklist">
                  <li><span>Curate the connectors and packs you sanction.</span></li>
                  <li><span>Employees get instant, approved access — no ad-hoc installs.</span></li>
                  <li><span>Your directory, your governance.</span></li>
                </ul>
              </div>
            </Reveal>
            <Reveal>
              <div className="card hov">
                <h3>For vendors</h3>
                <p style={{ marginBottom: 14 }}>Stand up your own marketplace and give customers unified access to all your plugins.</p>
                <ul className="checklist">
                  <li><span>One place for your whole plugin catalog.</span></li>
                  <li><span>Customers point their Lunas straight at it.</span></li>
                  <li><span>You own versioning, support and updates.</span></li>
                </ul>
              </div>
            </Reveal>
          </div>
          <Reveal>
            <div className="card" style={{ marginTop: 18 }}>
              <span className="badge soft">Monetization</span>
              <p style={{ marginTop: 12 }}>
                Today, monetization is the vendor's to own — price, license and sell your plugins
                however you like. A first-party paid-plugin wrapper is something we may add down the
                line; for now Luna stays out of your commercial model.
              </p>
            </div>
          </Reveal>
        </div>
      </section>

      <section className="mkt-section">
        <div className="wrap">
          <div className="sg-eyebrow">Trust model</div>
          <h2 className="sg-h2">Plugins are powerful — so only run ones you trust</h2>
          <p className="sg-lead">
            A Luna plugin can act: reach into systems, move data, run real work. That power is the
            point — and exactly why provenance matters. First-generation marketplaces let anyone
            publish, and untrusted community plugins became a plague. Luna's rule is simple: install
            from sources you trust.
          </p>
          <div className="grid cols-3" style={{ marginTop: 30 }}>
            <Reveal>
              <div className="card hov">
                <h3>Built by Luna</h3>
                <p style={{ marginBottom: 14 }}>Official connectors, tools and packs we build and stand behind.</p>
                <ul className="checklist">
                  <li><span>Reviewed and supported by us.</span></li>
                  <li><span>Maintained with the platform.</span></li>
                </ul>
              </div>
            </Reveal>
            <Reveal>
              <div className="card hov">
                <h3>Built by you</h3>
                <p style={{ marginBottom: 14 }}>Your own plugins on the open SDK — the most trusted source there is.</p>
                <ul className="checklist">
                  <li><span>Your code, your rules.</span></li>
                  <li><span>Installed per-agent and fully isolated.</span></li>
                </ul>
              </div>
            </Reveal>
            <Reveal>
              <div className="card hov">
                <h3>Built by a vendor you trust</h3>
                <p style={{ marginBottom: 14 }}>Commercial packs with deep domain expertise, from partners you choose.</p>
                <ul className="checklist">
                  <li><span>Vertical agent templates &amp; knowhow packs.</span></li>
                  <li><span>Supported and maintained.</span></li>
                </ul>
              </div>
            </Reveal>
          </div>
          <Reveal>
            <div className="card" style={{ marginTop: 18 }}>
              <span className="badge soft">Community</span>
              <p style={{ marginTop: 12 }}>
                There's a real community of professionals around Luna, and we're working to validate
                their plugins over time. Until a plugin carries that trust, treat anything from the
                open community as install-at-your-own-risk — never the default.
              </p>
            </div>
          </Reveal>
        </div>
      </section>

      <section className="mkt-section">
        <div className="wrap">
          <div className="sg-eyebrow">Build plugins</div>
          <h2 className="sg-h2">Luna Plugin Studio <em className="stext gtext">for Cursor</em></h2>
          <Reveal>
            <div className="card" style={{ marginTop: 26 }}>
              <div className="kit">
                <div>
                  <p style={{ fontSize: 16 }}>
                    A ready-to-go Cursor environment for building Luna plugins. Open it, and you have
                    the SDK, a scaffold and a test harness already wired up — write a plugin, run it
                    against a local Luna, and publish it to your marketplace.
                  </p>
                  <ul className="kit-list">
                    <li>Plugin SDK + typed manifest, preinstalled.</li>
                    <li>A starter plugin scaffold you can rename and ship.</li>
                    <li>Local test harness — run your plugin against a dev Luna.</li>
                    <li>Cursor rules &amp; tasks tuned for plugin work.</li>
                  </ul>
                  <div className="btn-row" style={{ marginTop: 22 }}>
                    <a className="btn btn-primary" href={PLUGIN_CURSOR_ZIP_URL}>Download for Cursor ↓</a>
                    <a className="btn btn-ghost" href={MARKETPLACE_BASE_URL} target="_blank" rel="noopener noreferrer">Docs on marketplaces.com.ai ↗</a>
                  </div>
                  <p className="sg-note" style={{ marginTop: 14 }}>
                    Hosted on marketplaces.com.ai and kept current there — you always get the latest kit.
                  </p>
                </div>
                <div className="filebox">
                  <div className="term-bar">
                    <span className="dot" /><span className="dot" /><span className="dot" />
                    <i>luna-plugin-cursor/</i>
                  </div>
                  <pre style={{ margin: 0, padding: 18, fontFamily: "'JetBrains Mono',ui-monospace,monospace", fontSize: 12.5, lineHeight: 1.7, color: 'var(--text-dim)', whiteSpace: 'pre' }}>{`luna-plugin-cursor/
├─ .cursor/        rules + tasks
├─ src/
│  └─ plugin.ts    your plugin
├─ manifest.json   typed manifest
├─ test/
│  └─ harness.ts   run vs dev Luna
└─ README.md`}</pre>
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      <MarketplaceCtaBand />
    </div>
  );
}
