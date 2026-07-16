import Markdown from '../components/Markdown';
import { useSeo } from '../lib/seo';
import { PRIVACY_MD } from '../lib/legal';

export default function Privacy() {
  useSeo({
    title: 'Privacy Policy — Luna',
    description:
      'How Novalystrix collects and uses data on the hosted Luna Service, including learning from usage and sessions to improve the Service and our AI models.',
  });

  return (
    <section className="mkt-section">
      <div className="wrap">
        <div className="legal-doc">
          <Markdown source={PRIVACY_MD} />
        </div>
      </div>
    </section>
  );
}
