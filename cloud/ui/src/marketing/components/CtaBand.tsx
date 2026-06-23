import Reveal from './Reveal';
import { StartFree } from './cta';

/** The closing conversion band shown at the foot of every marketing page.
 *  Carries the plan's verbatim "no limits … trust and reliability" line. */
export default function CtaBand() {
  return (
    <section style={{ padding: '36px 0 8px' }}>
      <div className="wrap">
        <Reveal>
          <div className="cta-band">
            <span className="orb b" style={{ opacity: 0.4 }} />
            <h2>
              There are no limits to what Luna can be —<br />
              <span className="stext gtext">we built it with trust and reliability in mind.</span>
            </h2>
            <p>Get your own private Luna in about a minute. No credit card. No API keys to wrangle.</p>
            <div className="btn-row" style={{ justifyContent: 'center', marginTop: 24 }}>
              <StartFree size="btn-lg" withGoogle />
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
