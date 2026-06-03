import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Moon, Loader2, AlertCircle } from 'lucide-react';

export default function UserLuna() {
  const { slug } = useParams<{ slug: string }>();
  const [status, setStatus] = useState<string>('loading');

  useEffect(() => {
    const poll = async () => {
      try {
        const res = await fetch('/api/agents/me/status');
        if (!res.ok) {
          window.location.href = '/';
          return;
        }
        const data = await res.json();
        setStatus(data.status);

        if (data.status === 'running') return;
        if (data.status === 'error') return;

        setTimeout(poll, 2000);
      } catch {
        setTimeout(poll, 3000);
      }
    };
    poll();
  }, [slug]);

  if (status === 'loading' || status === 'pending' || status === 'provisioning') {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center" style={{ background: 'var(--ink)' }}>
        <Moon className="mb-6" size={48} style={{ color: 'var(--moon)' }} />
        <Loader2 className="animate-spin mb-4" size={32} style={{ color: 'var(--moon-dim)' }} />
        <h2 className="text-xl font-semibold mb-2" style={{ color: 'var(--text)' }}>Setting up your Luna...</h2>
        <p className="text-sm" style={{ color: 'var(--text-dim)' }}>This usually takes about 20 seconds.</p>
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center" style={{ background: 'var(--ink)' }}>
        <AlertCircle className="mb-4" size={48} style={{ color: '#ef4444' }} />
        <h2 className="text-xl font-semibold mb-2" style={{ color: 'var(--text)' }}>Something went wrong</h2>
        <p className="text-sm mb-6" style={{ color: 'var(--text-dim)' }}>
          Your Luna couldn't be provisioned. Please try again or contact support.
        </p>
        <button
          onClick={() => window.location.reload()}
          className="px-6 py-2 rounded-lg font-medium"
          style={{ background: 'var(--moon)', color: 'var(--ink)' }}
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <iframe
      src={`/${slug}/`}
      className="w-full h-screen border-0"
      title="Luna"
    />
  );
}
