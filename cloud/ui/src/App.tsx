import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import AgentDetail from './pages/AgentDetail';
import BillingPage from './pages/billing/BillingPage';
import UsagePage from './pages/billing/UsagePage';
import UserLuna from './pages/UserLuna';
import AdminLayout from './pages/admin/AdminLayout';
import AdminsPage from './pages/admin/AdminsPage';
import ImagesPage from './pages/admin/ImagesPage';
import MachinesPage from './pages/admin/MachinesPage';
import ChangelogPage from './pages/admin/ChangelogPage';
import ImageConfigPage from './pages/admin/ImageConfigPage';
import DefaultsPage from './pages/admin/DefaultsPage';
import DefaultEnvPage from './pages/admin/DefaultEnvPage';
import ModelsPage from './pages/admin/ModelsPage';
import ServicesPage from './pages/admin/ServicesPage';
import WhatsAppPage from './pages/admin/WhatsAppPage';
import TelegramPage from './pages/admin/TelegramPage';
import SchedulerPage from './pages/admin/SchedulerPage';
import WebhooksPage from './pages/admin/WebhooksPage';
import FeedbackPage from './pages/admin/FeedbackPage';
import ErrorsPage from './pages/admin/ErrorsPage';
import ApiKeysPage from './pages/admin/ApiKeysPage';
import PricingOverviewPage from './pages/admin/pricing/PricingOverviewPage';
import PricingVersionsPage from './pages/admin/pricing/PricingVersionsPage';
import PricingVersionDetailPage from './pages/admin/pricing/PricingVersionDetailPage';
import PricingModelsPage from './pages/admin/pricing/PricingModelsPage';
import PricingBucketsPage from './pages/admin/pricing/PricingBucketsPage';
import PricingOpsPage from './pages/admin/pricing/PricingOpsPage';
import PricingSimulationsPage from './pages/admin/pricing/PricingSimulationsPage';
import BillingTestingPage from './pages/admin/pricing/BillingTestingPage';
import CouponsPage from './pages/admin/pricing/CouponsPage';

// Marketing site (plan 021) — public, unauthenticated routes.
import MarketingLayout from './marketing/MarketingLayout';
import Home from './marketing/pages/Home';
import Hosting from './marketing/pages/Hosting';
import OpenSource from './marketing/pages/OpenSource';
import Marketplace from './marketing/pages/Marketplace';
import Pricing from './marketing/pages/Pricing';
import Security from './marketing/pages/Security';
import About from './marketing/pages/About';
import Terms from './marketing/pages/Terms';
import Privacy from './marketing/pages/Privacy';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Marketing site — static routes declared before the /:slug catch-all */}
        <Route element={<MarketingLayout />}>
          <Route path="/" element={<Home />} />
          <Route path="/products/hosting" element={<Hosting />} />
          <Route path="/products/open-source" element={<OpenSource />} />
          <Route path="/products/marketplace" element={<Marketplace />} />
          <Route path="/pricing" element={<Pricing />} />
          <Route path="/security" element={<Security />} />
          <Route path="/about" element={<About />} />
          <Route path="/terms" element={<Terms />} />
          <Route path="/privacy" element={<Privacy />} />
        </Route>

        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/dashboard/usage" element={<UsagePage />} />
        <Route path="/dashboard/billing" element={<BillingPage />} />
        <Route path="/dashboard/agents/:id" element={<AgentDetail />} />
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<Navigate to="/admin/admins" />} />
          <Route path="admins" element={<AdminsPage />} />
          <Route path="images" element={<ImagesPage />} />
          <Route path="images/:imageId" element={<ImageConfigPage />} />
          <Route path="defaults" element={<DefaultsPage />} />
          <Route path="defaults/models" element={<ModelsPage />} />
          <Route path="defaults/env" element={<DefaultEnvPage />} />
          <Route path="machines" element={<MachinesPage />} />
          <Route path="services" element={<ServicesPage />} />
          <Route path="whatsapp" element={<WhatsAppPage />} />
          <Route path="telegram" element={<TelegramPage />} />
          <Route path="scheduler" element={<SchedulerPage />} />
          <Route path="webhooks" element={<WebhooksPage />} />
          <Route path="feedback" element={<FeedbackPage />} />
          <Route path="errors" element={<ErrorsPage />} />
          <Route path="api-keys" element={<ApiKeysPage />} />
          <Route path="pricing" element={<PricingOverviewPage />} />
          <Route path="pricing/versions" element={<PricingVersionsPage />} />
          <Route path="pricing/versions/:versionId" element={<PricingVersionDetailPage />} />
          <Route path="pricing/models" element={<PricingModelsPage />} />
          <Route path="pricing/buckets" element={<PricingBucketsPage />} />
          <Route path="pricing/ops" element={<PricingOpsPage />} />
          <Route path="pricing/simulations" element={<PricingSimulationsPage />} />
          <Route path="pricing/testing" element={<BillingTestingPage />} />
          <Route path="pricing/coupons" element={<CouponsPage />} />
          <Route path="relay" element={<Navigate to="/admin/machines" replace />} />
          <Route path="changelog" element={<ChangelogPage />} />
        </Route>
        <Route path="/:slug" element={<UserLuna />} />
      </Routes>
    </BrowserRouter>
  );
}
