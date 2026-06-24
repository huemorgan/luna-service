import { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import './marketing.css';
import './themes.css';
import { SessionProvider } from './lib/session';
import Header from './layout/Header';
import Footer from './layout/Footer';
import CtaBand from './components/CtaBand';

// Pages that render their own closing CTA (plan 022) opt out of the shared,
// hosted "Start free" band so we never stack two competing calls to action.
const SELF_CTA_ROUTES = ['/products/marketplace'];

export default function MarketingLayout() {
  const { pathname } = useLocation();

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
  }, [pathname]);

  const showDefaultCta = !SELF_CTA_ROUTES.includes(pathname);

  return (
    <SessionProvider>
      <div className="mkt">
        <Header />
        <main>
          <Outlet />
        </main>
        {showDefaultCta && <CtaBand />}
        <Footer />
      </div>
    </SessionProvider>
  );
}
