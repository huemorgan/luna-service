import Markdown from '../components/Markdown';
import { useSeo } from '../lib/seo';
import { TERMS_MD } from '../lib/legal';

export default function Terms() {
  useSeo({
    title: 'Terms of Service — Luna',
    description:
      'The terms governing the hosted Luna Service at luna.com.ai and the plugin marketplace at marketplaces.com.ai, operated by Novalystrix.',
  });

  return (
    <section className="mkt-section">
      <div className="wrap">
        <div className="legal-doc">
          <Markdown source={TERMS_MD} />
        </div>
      </div>
    </section>
  );
}
