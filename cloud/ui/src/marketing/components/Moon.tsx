import { useEffect, useRef } from 'react';

/** The signature motif: a moon emerging from shadow (eclipse sweep). Reveals
 *  shortly after mount. */
export default function Moon() {
  const stage = useRef<HTMLDivElement>(null);
  const moon = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      moon.current?.classList.add('is-revealed');
      stage.current?.classList.add('is-revealed');
    }, 350);
    return () => clearTimeout(t);
  }, []);

  return (
    <div className="moon-stage" ref={stage} aria-hidden="true">
      <div className="orbit-ring" />
      <div className="moon" ref={moon}>
        <div className="moon__surface" />
        <div className="moon__shade" />
      </div>
      <div className="moon__glow" />
    </div>
  );
}
