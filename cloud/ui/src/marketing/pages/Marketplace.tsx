import Reveal from '../components/Reveal';
import { StartFree } from '../components/cta';
import { useSeo } from '../lib/seo';
import { GITHUB_URL } from '../lib/constants';
import marketImg from '../assets/marketplaces.png';

export default function Marketplace() {
  useSeo({
    title: 'Luna Marketplaces — add capability in one click',
    description:
      'Because everything in Luna is a plugin, marketplaces are how you add capability without forking: connectors, tools, channels, agent templates and vertical packs. Anyone can open their own marketplace — organizations for their teams, vendors for their customers.',
  });

  return (
    <>
      <section className="mkt-section flush">
        <div className="wrap">
          <div className="phero">
            <div className="sg-eyebrow">Luna Marketplaces</div>
            <h1>Add capability —<br /><em>one click, no forking</em></h1>
            <p>
              Luna is "everything is a plugin." A marketplace is simply how you extend it: connectors,
              tools, channels, ready-made agent templates and whole vertical packs — installed per
              agent, isolated, and easy to remove.
            </p>
            <div className="btn-row">
              <StartFree size="btn-lg" withGoogle />
              <a className="btn btn-ghost btn-lg" href={GITHUB_URL} target="_blank" rel="noopener noreferrer">Build a plugin ↗</a>
            </div>
          </div>
          <Reveal>
            <div className="media" style={{ marginTop: 30 }}>
              <img src={marketImg} alt="A person browsing a grid of installable app tiles on a monitor" />
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
          <div className="sg-eyebrow">Open marketplaces</div>
          <h2 className="sg-h2">Anyone can open a marketplace — and point their Lunas at it</h2>
          <p className="sg-lead">
            A marketplace is just a plugin directory you trust. Open your own and connect it to your
            Lunas, so installs come from a source you control — not the open internet.
          </p>
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
          <div className="sg-eyebrow">How it works</div>
          <h2 className="sg-h2">Browse → add → it's installed</h2>
          <div className="grid cols-3" style={{ marginTop: 30 }}>
            {[
              ['Browse', 'Find connectors, tools, templates and packs for the job you have.'],
              ['One-click add', 'Hosted users get a curated install. OSS users get the SDK to build & publish.'],
              ['Isolated per agent', 'Each capability runs scoped to the agent that uses it — add and remove freely.'],
            ].map(([title, body]) => (
              <Reveal key={title}>
                <div className="card hov feature">
                  <h3>{title}</h3>
                  <p>{body}</p>
                </div>
              </Reveal>
            ))}
          </div>
          <Reveal>
            <div className="card" style={{ marginTop: 18 }}>
              <span className="badge">Coming soon</span>
              <p style={{ marginTop: 12 }}>
                The marketplace framework is shipping inside Luna now; the browse-and-install storefront
                is rolling out next. We label genuinely-future items "coming soon" rather than show a
                catalog that isn't real — trust is the whole point.
              </p>
            </div>
          </Reveal>
        </div>
      </section>
    </>
  );
}
