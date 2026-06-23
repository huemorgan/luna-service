import { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import './marketing.css';
import { SessionProvider } from './lib/session';
import Header from './layout/Header';
import Footer from './layout/Footer';
import CtaBand from './components/CtaBand';

export default function MarketingLayout() {
  const { pathname } = useLocation();

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
  }, [pathname]);

  return (
    <SessionProvider>
      <div className="mkt">
        <Header />
        <main>
          <Outlet />
        </main>
        <CtaBand />
        <Footer />
      </div>
    </SessionProvider>
  );
}
