import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

interface Session {
  loggedIn: boolean;
  loading: boolean;
}

const SessionCtx = createContext<Session>({ loggedIn: false, loading: true });

/** Detects whether the visitor is signed in (so the header can flip the
 *  primary CTA to "Go to your Luna"). Single fetch shared via context. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session>({ loggedIn: false, loading: true });

  useEffect(() => {
    let active = true;
    fetch('/api/auth/me', { credentials: 'include' })
      .then(async r => {
        if (!r.ok) return false;
        try {
          const data = await r.json();
          return Boolean(data && data.user);
        } catch {
          return false;
        }
      })
      .then(loggedIn => { if (active) setSession({ loggedIn, loading: false }); })
      .catch(() => { if (active) setSession({ loggedIn: false, loading: false }); });
    return () => { active = false; };
  }, []);

  return <SessionCtx.Provider value={session}>{children}</SessionCtx.Provider>;
}

export const useSession = () => useContext(SessionCtx);
