import Reveal from '../components/Reveal';
import { StartFree } from '../components/cta';
import { useSeo } from '../lib/seo';
import { GITHUB_URL } from '../lib/constants';
import marketImg from '../assets/marketplaces.png';

export default function Marketplace() {
  useSeo({
    title: 'Luna Marketplaces — add capability in one click',
    description:
      'Because everything in Luna is a plugin, marketplaces are how you add capability without forking: connectors, tools, channels, agent templates and vertical packs.',
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
          <div className="sg-eyebrow">Two layers</div>
          <h2 className="sg-h2">Community plugins and commercial packs</h2>
          <div className="grid cols-2" style={{ marginTop: 30 }}>
            <Reveal>
              <div className="card hov">
                <h3>OSS plugins</h3>
                <p style={{ marginBottom: 14 }}>Free, community-built, open. The long tail of connectors and tools.</p>
                <ul className="checklist">
                  <li><span>Built with the open plugin SDK.</span></li>
                  <li><span>Installed per-agent and fully isolated.</span></li>
                  <li><span>Anyone can publish.</span></li>
                </ul>
              </div>
            </Reveal>
            <Reveal>
              <div className="card hov">
                <h3>Commercial packs</h3>
                <p style={{ marginBottom: 14 }}>Vertical, supported, entitlement-checked — the deep domain expertise.</p>
                <ul className="checklist">
                  <li><span>Agent templates: "Marketing Agent," "Ops Agent."</span></li>
                  <li><span>Knowhow / vertical packs for a specific job.</span></li>
                  <li><span>Curated and maintained.</span></li>
                </ul>
              </div>
            </Reveal>
          </div>
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
