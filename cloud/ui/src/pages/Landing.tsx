import { Moon, Code, Shield, Puzzle, Github } from 'lucide-react';

export default function Landing() {
  return (
    <div className="min-h-screen flex flex-col" style={{ background: 'var(--ink)' }}>
      {/* Hero */}
      <main className="flex-1 flex flex-col items-center justify-center px-4 pt-16 pb-10">
        <Moon className="mb-6 animate-pulse" size={72} style={{ color: 'var(--moon)' }} />

        <h1 className="text-5xl sm:text-6xl font-bold mb-4 text-center" style={{ color: 'var(--text)' }}>
          Your own AI agent.
        </h1>
        <h2 className="text-2xl sm:text-3xl font-medium mb-3 text-center" style={{ color: 'var(--moon)' }}>
          In the cloud. In under a minute.
        </h2>
        <p className="text-lg max-w-md text-center mb-12" style={{ color: 'var(--text-dim)' }}>
          Luna is a plugin-extensible AI agent that writes code, searches the web,
          remembers everything, and works for you 24/7.
        </p>

        <a
          href="/auth/login"
          className="inline-flex items-center gap-3 px-10 py-4 rounded-2xl text-lg font-semibold transition-all hover:scale-105 shadow-lg"
          style={{
            background: 'var(--moon)',
            color: 'var(--ink)',
            boxShadow: '0 0 40px rgba(250, 204, 21, 0.25)',
          }}
        >
          <svg width="22" height="22" viewBox="0 0 24 24">
            <path fill="currentColor" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/>
            <path fill="currentColor" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
            <path fill="currentColor" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
            <path fill="currentColor" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
          </svg>
          Sign in with Google
        </a>

        {/* Features */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 mt-20 max-w-3xl w-full px-4">
          <FeatureCard icon={<Code size={28} />} title="Writes & runs code" desc="Full code execution sandbox. Build, test, iterate — all inside your agent." />
          <FeatureCard icon={<Shield size={28} />} title="Your data, your agent" desc="Encrypted vault per user. No shared context, no data leaks between tenants." />
          <FeatureCard icon={<Puzzle size={28} />} title="Plugin-extensible" desc="Web search, memory, file system, approval gates — and growing." />
        </div>
      </main>

      {/* Footer */}
      <footer className="flex flex-col sm:flex-row items-center justify-between px-8 py-6 gap-4 border-t" style={{ borderColor: 'rgba(255,255,255,0.08)' }}>
        <p className="text-sm" style={{ color: 'var(--text-dim)' }}>
          Powered by <span style={{ color: 'var(--moon-dim)' }}>Novalystrix</span>
        </p>
        <div className="flex items-center gap-6 text-sm" style={{ color: 'var(--text-dim)' }}>
          <a href="https://github.com/huemorgan/luna" target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 hover:underline">
            <Github size={16} /> Open Source
          </a>
          <span>Terms</span>
          <span>Privacy</span>
        </div>
      </footer>
    </div>
  );
}

function FeatureCard({ icon, title, desc }: { icon: React.ReactNode; title: string; desc: string }) {
  return (
    <div className="rounded-2xl p-6 text-center" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}>
      <div className="flex justify-center mb-3" style={{ color: 'var(--moon)' }}>{icon}</div>
      <h3 className="font-semibold mb-2" style={{ color: 'var(--text)' }}>{title}</h3>
      <p className="text-sm leading-relaxed" style={{ color: 'var(--text-dim)' }}>{desc}</p>
    </div>
  );
}
