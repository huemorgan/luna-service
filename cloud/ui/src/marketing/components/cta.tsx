import { useSession } from '../lib/session';
import { LOGIN_URL, DASHBOARD_URL } from '../lib/constants';
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
