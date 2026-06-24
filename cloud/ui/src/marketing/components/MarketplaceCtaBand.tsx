import Reveal from './Reveal';
import { MarketplaceCta } from './cta';

/** Closing band for the Marketplaces product page. Warm-themed (it renders
 *  inside the page's `.t-market` wrapper) and points at marketplaces.com.ai
 *  rather than the hosted Google signup. */
export default function MarketplaceCtaBand() {
  return (
    <section style={{ padding: '36px 0 8px' }}>
      <div className="wrap">
        <Reveal>
          <div className="cta-band">
            <span className="orb a" style={{ opacity: 0.35 }} />
            <h2>
              Open your marketplace —<br />
              <span className="stext gtext">make the capability you trust one click away.</span>
            </h2>
            <p>Sign up, create a marketplace, and point your Lunas at a source you control.</p>
            <div className="btn-row" style={{ justifyContent: 'center', marginTop: 24 }}>
              <MarketplaceCta size="btn-lg" secondary />
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
