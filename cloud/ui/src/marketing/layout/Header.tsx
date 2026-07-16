import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import Brand from '../components/Brand';
import { StartFree, LoginGate } from '../components/cta';
import { useSession } from '../lib/session';
import { PRODUCTS } from '../lib/constants';

export default function Header() {
  const { loggedIn } = useSession();
  const { pathname } = useLocation();
  const [productsOpen, setProductsOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerProducts, setDrawerProducts] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close menus on route change
  useEffect(() => {
    setProductsOpen(false);
    setDrawerOpen(false);
    setDrawerProducts(false);
  }, [pathname]);

  // Close the desktop dropdown on outside click
  useEffect(() => {
    if (!productsOpen) return;
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setProductsOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [productsOpen]);

  return (
    <header className="mkt-header">
      <div className="wrap">
        <div className="site-header">
          <Brand />

          {/* Desktop nav */}
          <nav className="site-nav" aria-label="Primary">
            <div className={`dropdown ${productsOpen ? 'open' : ''}`} ref={dropdownRef}>
              <button
                className="navlink"
                aria-haspopup="true"
                aria-expanded={productsOpen}
                onClick={() => setProductsOpen(o => !o)}
              >
                Products <span className="caret" />
              </button>
              {productsOpen && (
                <div className="menu" role="menu">
                  {PRODUCTS.map(p => (
                    <Link key={p.to} to={p.to} role="menuitem">
                      <span className={`vis ${p.vis}`} />
                      <span>
                        <b>{p.title}</b>
                        <span>{p.blurb}</span>
                      </span>
                    </Link>
                  ))}
                </div>
              )}
            </div>
            <Link className="navlink" to="/pricing">Pricing</Link>
            <Link className="navlink" to="/security">Security</Link>
          </nav>

          {/* Desktop actions */}
          <div className="hdr-actions">
            {!loggedIn && (
              <LoginGate label="Sign in" className="btn btn-link btn-sm" />
            )}
            <StartFree size="btn-sm" withGoogle />
          </div>

          {/* Mobile burger */}
          <button
            className={`mkt-burger ${drawerOpen ? 'open' : ''}`}
            aria-label="Menu"
            aria-expanded={drawerOpen}
            onClick={() => setDrawerOpen(o => !o)}
          >
            <span />
          </button>
        </div>

        {/* Mobile drawer */}
        {drawerOpen && (
          <div className="mkt-drawer">
            <button onClick={() => setDrawerProducts(o => !o)}>
              Products <span className="caret" style={{ transform: drawerProducts ? 'rotate(-135deg)' : 'rotate(45deg)' }} />
            </button>
            {drawerProducts && (
              <div className="sub">
                {PRODUCTS.map(p => (
                  <Link key={p.to} to={p.to}>{p.title}</Link>
                ))}
              </div>
            )}
            <Link to="/pricing">Pricing</Link>
            <Link to="/security">Security</Link>
            <Link to="/about">About</Link>
            {!loggedIn && <LoginGate label="Sign in" className="mkt-drawer-signin" />}
            <div className="drawer-cta"><StartFree withGoogle /></div>
          </div>
        )}
      </div>
    </header>
  );
}
