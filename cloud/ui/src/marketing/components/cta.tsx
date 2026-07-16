import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useSession } from '../lib/session';
import {
  LOGIN_URL,
  DASHBOARD_URL,
  MARKETPLACE_SIGNUP_URL,
  MARKETPLACE_BROWSE_URL,
} from '../lib/constants';
import { GoogleG } from './icons';

/** 044 — consent step shown before the Google OAuth redirect. The agreement
 *  box is checked by default; unchecking it disables the continue button.
 *  Acceptance (version + timestamp) is recorded server-side on callback. */
function ConsentModal({ onClose }: { onClose: () => void }) {
  const [agree, setAgree] = useState(true);
  return (
    <div className="consent-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="consent-card" onClick={e => e.stopPropagation()}>
        <h3>Continue to Luna</h3>
        <label className="consent-row">
          <input
            type="checkbox"
            checked={agree}
            onChange={e => setAgree(e.target.checked)}
          />
          <span>
            I agree to the <Link to="/terms" onClick={onClose}>Terms of Service</Link> and{' '}
            <Link to="/privacy" onClick={onClose}>Privacy Policy</Link>
          </span>
        </label>
        <a
          href={LOGIN_URL}
          className={`btn btn-primary ${agree ? '' : 'disabled'}`.trim()}
          aria-disabled={!agree}
          onClick={e => { if (!agree) e.preventDefault(); }}
        >
          <GoogleG />
          Continue with Google
        </a>
        <p className="consent-note">
          By continuing you agree to the Terms of Service and acknowledge the
          Privacy Policy.
        </p>
      </div>
    </div>
  );
}

/** Trigger that gates any login entry point behind the consent step. */
export function LoginGate({
  label,
  className = '',
  withGoogle = false,
}: {
  label: string;
  className?: string;
  withGoogle?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className={className} onClick={() => setOpen(true)}>
        {withGoogle && <GoogleG />}
        {label}
      </button>
      {open && <ConsentModal onClose={() => setOpen(false)} />}
    </>
  );
}

/** The one CTA that matters. Logged out → consent step, then Google OAuth.
 *  Logged in → "Go to your Luna" into the dashboard. */
export function StartFree({
  size = '',
  withGoogle = false,
  className = '',
}: {
  size?: '' | 'btn-sm' | 'btn-lg';
  withGoogle?: boolean;
  className?: string;
}) {
  const { loggedIn } = useSession();
  if (loggedIn) {
    return (
      <a href={DASHBOARD_URL} className={`btn btn-primary ${size} ${className}`.trim()}>
        Go to your Luna →
      </a>
    );
  }
  return (
    <LoginGate
      label="Start free"
      withGoogle={withGoogle}
      className={`btn btn-primary ${size} ${className}`.trim()}
    />
  );
}

/** Marketplaces is a separate product (plan 022). Its CTA leaves the marketing
 *  site for marketplaces.com.ai — distinct from the hosted Google signup. */
export function MarketplaceCta({
  size = '',
  secondary = false,
}: {
  size?: '' | 'btn-sm' | 'btn-lg';
  secondary?: boolean;
}) {
  return (
    <>
      <a
        href={MARKETPLACE_SIGNUP_URL}
        target="_blank"
        rel="noopener noreferrer"
        className={`btn btn-primary ${size}`.trim()}
      >
        Create your marketplace →
      </a>
      {secondary && (
        <a
          href={MARKETPLACE_BROWSE_URL}
          target="_blank"
          rel="noopener noreferrer"
          className={`btn btn-ghost ${size}`.trim()}
        >
          Browse Marketplaces ↗
        </a>
      )}
    </>
  );
}
