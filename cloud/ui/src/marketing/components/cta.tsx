import { useSession } from '../lib/session';
import {
  LOGIN_URL,
  DASHBOARD_URL,
  MARKETPLACE_SIGNUP_URL,
  MARKETPLACE_BROWSE_URL,
} from '../lib/constants';
import { GoogleG } from './icons';

/** The one CTA that matters. Logged out → "Start free" into Google OAuth.
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
    <a href={LOGIN_URL} className={`btn btn-primary ${size} ${className}`.trim()}>
      {withGoogle && <GoogleG />}
      Start free
    </a>
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
