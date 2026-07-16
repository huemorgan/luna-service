import { Link } from 'react-router-dom';
import Reveal from '../components/Reveal';
import { StartFree } from '../components/cta';
import { useSeo } from '../lib/seo';
import hostingImg from '../assets/hosting-service.png';

export default function Hosting() {
  useSeo({
    title: 'Luna Hosting Service — your private Luna in ~60 seconds',
    description:
      'Sign up with Google and get your own private, isolated, persistent Luna in about a minute. Unified billing — access to every model and service under one credit system. Physical isolation and a vault we can\'t read.',
  });

  return (
    <>
      <section className="mkt-section flush">
        <div className="wrap">
          <div className="phero">
            <div className="sg-eyebrow">Luna Hosting Service</div>
            <h1>Your own private Luna,<br /><em>ready in about a minute</em></h1>
            <p>
              Sign up with Google and get a private, isolated, persistent Luna — no installing, no
              sysadmin, nothing to wrangle. As polished as ChatGPT, as private as self-hosting, and it
              actually <em className="stext">does</em> things.
            </p>
            <div className="btn-row">
              <StartFree size="btn-lg" withGoogle />
              <Link className="btn btn-ghost btn-lg" to="/pricing">See pricing</Link>
            </div>
          </div>
          <Reveal>
            <div className="media" style={{ marginTop: 30 }}>
              <img src={hostingImg} alt="A person setting up Luna effortlessly on a laptop" />
            </div>
          </Reveal>
        </div>
      </section>

      <section className="mkt-section">
        <div className="wrap">
          <div className="sg-eyebrow">Why hosted</div>
          <h2 className="sg-h2">Everything handled, nothing leaked</h2>
          <div className="grid cols-3" style={{ marginTop: 30 }}>
            {[
              ['Unified billing · any model', 'Access every model and service under one credit system — switch Opus / Sonnet / Haiku / GPT / Gemini freely. One usage meter.'],
              ['Physical isolation', 'Your own microVM, database schema, vault key and MCP subprocesses. Not a shared row in someone\'s table.'],
              ['Your work stays yours', 'Per-tenant keys; your IP stays yours. We learn from usage to improve Luna — never to act in your accounts.'],
              ['Always-on & triggers', '"Email me a summary at 9am." Scheduled, autonomous work — even while you sleep. (Paid plans.)'],
              ['Fleet dashboard', 'Run many agents — one per project or client — with costs visible at a glance.'],
              ['Polished, mobile-first UX', 'A first-class interface on every device, from the first second.'],
            ].map(([title, body]) => (
              <Reveal key={title}>
                <div className="card hov feature">
                  <h3>{title}</h3>
                  <p>{body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="mkt-section">
        <div className="wrap">
          <div className="sg-eyebrow">Hosted vs self-host</div>
          <h2 className="sg-h2">Convenience, or total control</h2>
          <p className="sg-lead">Same open-source Luna underneath. Pick how you want to run it.</p>
          <Reveal>
            <table className="compare" style={{ marginTop: 26 }}>
              <thead>
                <tr><th>What you get</th><th>Hosting Service</th><th>Self-host (OSS)</th></tr>
              </thead>
              <tbody>
                <tr><th scope="row">Setup time</th><td className="hi">~60 seconds, sign in with Google</td><td>You provision a server &amp; deploy</td></tr>
                <tr><th scope="row">Model keys</th><td className="hi">Included — one bill, any model</td><td>Bring your own keys</td></tr>
                <tr><th scope="row">Isolation</th><td className="hi">Managed microVM + DB + vault per tenant</td><td>Your machine, your rules</td></tr>
                <tr><th scope="row">Always-on triggers</th><td className="hi">Built in (paid plans)</td><td>You run the scheduler</td></tr>
                <tr><th scope="row">Updates &amp; backups</th><td className="hi">Handled for you</td><td>You operate it</td></tr>
                <tr><th scope="row">Cost</th><td className="hi">Free to start, usage-based</td><td>Your hosting + model usage</td></tr>
              </tbody>
            </table>
          </Reveal>
          <p className="sg-note" style={{ marginTop: 14 }}>
            Want full control instead? <Link className="btn-link" to="/products/open-source" style={{ paddingLeft: 0 }}>Explore Luna Open Source <span className="arrow">→</span></Link>
          </p>
        </div>
      </section>
    </>
  );
}
