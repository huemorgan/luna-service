import { Link } from 'react-router-dom';
import Brand from '../components/Brand';
import { DOCS_URL, GITHUB_URL } from '../lib/constants';

export default function Footer() {
  return (
    <footer className="mkt-footer">
      <div className="wrap">
        <div className="foot">
          <div className="col" style={{ maxWidth: 260 }}>
            <Brand />
            <p style={{ marginTop: 6 }}>Reliable, trustworthy agents that do real work.</p>
          </div>
          <div className="col">
            <b>Products</b>
            <Link to="/products/open-source">Open Source</Link>
            <Link to="/products/hosting">Hosting Service</Link>
            <Link to="/products/marketplace">Marketplaces</Link>
          </div>
          <div className="col">
            <b>Resources</b>
            <a href={DOCS_URL} target="_blank" rel="noopener noreferrer">Docs</a>
            <Link to="/security">Security</Link>
            <Link to="/pricing">Pricing</Link>
          </div>
          <div className="col">
            <b>Project</b>
            <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer">GitHub</a>
            <Link to="/about">About</Link>
            <Link to="/products/open-source">Open platform promise</Link>
          </div>
          <div className="col">
            <b>Legal</b>
            <Link to="/terms">Terms of Service</Link>
            <Link to="/privacy">Privacy Policy</Link>
          </div>
        </div>
        <p className="sg-note" style={{ marginTop: 36 }}>
          © {new Date().getFullYear()} Luna · operated by Novalystrix · There are no limits to what Luna can be.
        </p>
      </div>
    </footer>
  );
}
