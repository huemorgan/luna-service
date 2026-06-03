import { useEffect, useState } from 'react';
import { Moon, LogOut, Bot, Loader2 } from 'lucide-react';

interface UserInfo {
  user: { id: string; email: string; name: string | null; avatar_url: string | null };
  account: { id: string; slug: string; name: string; plan: string } | null;
}

interface AgentInfo {
  id: string;
  name: string;
  status: string;
  created_at: string;
}

export default function Dashboard() {
  const [data, setData] = useState<UserInfo | null>(null);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch('/api/auth/me').then(r => r.ok ? r.json() : Promise.reject()),
      fetch('/api/agents').then(r => r.ok ? r.json() : []),
    ])
      .then(([me, ag]) => { setData(me); setAgents(ag); })
      .catch(() => { window.location.href = '/'; })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--ink)' }}>
        <Loader2 className="animate-spin" size={32} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  if (!data) return null;

  const { user, account } = data;

  return (
    <div className="min-h-screen" style={{ background: 'var(--ink)' }}>
      {/* Header */}
      <header
        className="flex items-center justify-between px-6 py-4 border-b"
        style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}
      >
        <div className="flex items-center gap-3">
          <Moon size={24} style={{ color: 'var(--moon)' }} />
          <span className="text-lg font-semibold" style={{ color: 'var(--text)' }}>Luna Service</span>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            {user.avatar_url ? (
              <img src={user.avatar_url} alt="" className="w-8 h-8 rounded-full" />
            ) : (
              <div className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold" style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
                {(user.name || user.email)[0].toUpperCase()}
              </div>
            )}
            <span className="text-sm" style={{ color: 'var(--text-dim)' }}>{user.name || user.email}</span>
          </div>
          <a
            href="/auth/logout"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors hover:opacity-80"
            style={{ color: 'var(--text-dim)' }}
          >
            <LogOut size={14} />
            Sign out
          </a>
        </div>
      </header>

      {/* Main */}
      <main className="max-w-4xl mx-auto px-6 py-10">
        {account && (
          <div className="mb-8">
            <h2 className="text-2xl font-bold mb-1" style={{ color: 'var(--text)' }}>{account.name}</h2>
            <p className="text-sm" style={{ color: 'var(--text-dim)' }}>
              luna.com.ai/<span style={{ color: 'var(--moon-dim)' }}>{account.slug}</span>
              {' · '}
              <span className="capitalize">{account.plan} plan</span>
            </p>
          </div>
        )}

        {/* Agent Card */}
        <div
          className="rounded-2xl p-8 border"
          style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}
        >
          <div className="flex items-center gap-3 mb-4">
            <Bot size={28} style={{ color: 'var(--moon)' }} />
            <h3 className="text-xl font-semibold" style={{ color: 'var(--text)' }}>Your Luna</h3>
          </div>

          {agents.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-lg mb-2" style={{ color: 'var(--text-dim)' }}>Not provisioned yet</p>
              <p className="text-sm" style={{ color: 'var(--text-dim)' }}>
                Luna agent provisioning is coming in the next update.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {agents.map(a => (
                <div
                  key={a.id}
                  className="flex items-center justify-between p-4 rounded-xl"
                  style={{ background: 'var(--ink-light)' }}
                >
                  <div>
                    <p className="font-medium" style={{ color: 'var(--text)' }}>{a.name}</p>
                    <p className="text-sm" style={{ color: 'var(--text-dim)' }}>
                      Status: <span className="capitalize">{a.status}</span>
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
