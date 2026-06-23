// Shared links for the marketing site. CTAs route into the existing auth flow.
export const LOGIN_URL = '/auth/login';
export const DASHBOARD_URL = '/dashboard';
export const GITHUB_URL = 'https://github.com/huemorgan/luna';
export const DOCS_URL = 'https://github.com/huemorgan/luna#readme';
export const CONTACT_EMAIL = 'mailto:hello@luna.com.ai';

export interface ProductLink {
  to: string;
  title: string;
  blurb: string;
  vis: 'oss' | 'host' | 'market';
}

export const PRODUCTS: ProductLink[] = [
  { to: '/products/open-source', title: 'Luna Open Source', blurb: 'The MIT agent. Self-host anywhere.', vis: 'oss' },
  { to: '/products/hosting', title: 'Luna Hosting Service', blurb: 'Your private Luna in 60 seconds.', vis: 'host' },
  { to: '/products/marketplace', title: 'Luna Marketplaces', blurb: 'Plugins, templates & packs.', vis: 'market' },
];
