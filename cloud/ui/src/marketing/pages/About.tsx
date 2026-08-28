import Reveal from '../components/Reveal';
import { useSeo } from '../lib/seo';
import { StartFree } from '../components/cta';
import selfImg from '../assets/self-improving.jpg';

export default function About() {
  useSeo({
    title: 'About Luna — the second generation of self-improving agents',
    description:
      'The first generation of self-improving agents showed the promise but broke. Luna keeps the self-reflective loop and makes it reliable and trustworthy — fit for real work.',
  });

  return (
    <>
      <section className="mkt-section flush">
        <div className="wrap">
          <div className="phero">
            <div className="sg-eyebrow">Our mission</div>
            <h1>The second generation of<br /><em>self-improving agents</em></h1>
            <p>
              The first generation proved that agents can reflect on their own work and get better.
              It also proved they break, run inconsistently, and aren't safe near anything that
              matters. Luna keeps the self-improving loop — and makes it reliable and trustworthy.
            </p>
          </div>
          <Reveal>
            <div className="media" style={{ marginTop: 30 }}>
              <img src={selfImg} alt="Two engineers testing and refining a robot arm" />
            </div>
          </Reveal>
        </div>
      </section>

      <section className="mkt-section">
        <div className="wrap">
          <div className="split">
            <div>
              <div className="sg-eyebrow">What we believe</div>
              <h2 className="sg-h2">Reliability and trust aren't features</h2>
              <p className="sg-lead" style={{ marginBottom: 16 }}>
                They're the prerequisites. An agent that's brilliant but flaky, or capable but unsafe,
                can't own real work. So we started from the constraints — bounded self-improvement, a
                vault the model can't read, deterministic workflows, rollback, approval gates — and
                built the intelligence on top of them.
              </p>
              <p className="lead-kicker gtext">"There are no limits to what Luna can be — we just built it with trust and reliability in mind."</p>
            </div>
            <div>
              <Reveal>
                <div className="card">
                  <h3>The generational story</h3>
                  <ul className="checklist" style={{ marginTop: 14 }}>
                    <li><span><b>Gen 1 — the promise.</b> Self-reflective agents that try, learn and improve.</span></li>
                    <li><span><b>The catch.</b> Unbounded self-coding and raw-LLM execution → breakage and risk.</span></li>
                    <li><span><b>Gen 2 — Luna.</b> Same self-improvement, made reliable and safe by architecture.</span></li>
                  </ul>
                </div>
              </Reveal>
            </div>
          </div>
          <div className="btn-row" style={{ justifyContent: 'center', marginTop: 36 }}>
            <StartFree size="btn-lg" withGoogle />
          </div>
        </div>
      </section>
    </>
  );
}
