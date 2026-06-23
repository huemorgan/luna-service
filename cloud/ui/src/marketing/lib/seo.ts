import { useEffect } from 'react';

const SITE = 'Luna';

function upsertMeta(attr: 'name' | 'property', key: string, content: string) {
  let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute('content', content);
}

function upsertCanonical(href: string) {
  let el = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  if (!el) {
    el = document.createElement('link');
    el.setAttribute('rel', 'canonical');
    document.head.appendChild(el);
  }
  el.setAttribute('href', href);
}

/** Per-page title/description/OG. Client-side for now (full static prerender
 *  is deferred — see plans/021 D6). */
export function useSeo({ title, description }: { title: string; description: string }) {
  useEffect(() => {
    const full = title.includes(SITE) ? title : `${title} · ${SITE}`;
    document.title = full;
    upsertMeta('name', 'description', description);
    upsertMeta('property', 'og:title', full);
    upsertMeta('property', 'og:description', description);
    upsertMeta('property', 'og:type', 'website');
    upsertMeta('property', 'og:site_name', SITE);
    upsertMeta('name', 'twitter:card', 'summary_large_image');
    upsertMeta('name', 'twitter:title', full);
    upsertMeta('name', 'twitter:description', description);
    upsertCanonical(window.location.origin + window.location.pathname);
  }, [title, description]);
}
