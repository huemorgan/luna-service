// Shared links for the marketing site. CTAs route into the existing auth flow.
export const LOGIN_URL = '/auth/login';
export const DASHBOARD_URL = '/dashboard';
export const GITHUB_URL = 'https://github.com/huemorgan/luna';
export const DOCS_URL = 'https://github.com/huemorgan/luna#readme';
export const CONTACT_EMAIL = 'mailto:hello@luna.com.ai';

// Luna Marketplaces is a separate product on its own domain (plan 022). Its CTAs
// leave the marketing site; the plugin-dev kit is hosted there and reached via a
// stable branded redirect on our side so updating the zip there updates the link.
export const MARKETPLACE_BASE_URL = 'https://marketplaces.com.ai';
export const MARKETPLACE_SIGNUP_URL = 'https://marketplaces.com.ai/';
export const MARKETPLACE_BROWSE_URL = 'https://marketplaces.com.ai/';
export const PLUGIN_CURSOR_ZIP_URL = '/downloads/luna-plugin-cursor.zip';

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
