import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import AgentDetail from './pages/AgentDetail';
import UserLuna from './pages/UserLuna';
import AdminLayout from './pages/admin/AdminLayout';
import AdminsPage from './pages/admin/AdminsPage';
import ImagesPage from './pages/admin/ImagesPage';
import MachinesPage from './pages/admin/MachinesPage';
import ChangelogPage from './pages/admin/ChangelogPage';
import ImageConfigPage from './pages/admin/ImageConfigPage';
import DefaultsPage from './pages/admin/DefaultsPage';
import ModelsPage from './pages/admin/ModelsPage';
import ServicesPage from './pages/admin/ServicesPage';
import PluginKeysPage from './pages/admin/PluginKeysPage';
import RelayPage from './pages/admin/RelayPage';

// Marketing site (plan 021) — public, unauthenticated routes.
import MarketingLayout from './marketing/MarketingLayout';
import Home from './marketing/pages/Home';
import Hosting from './marketing/pages/Hosting';
import OpenSource from './marketing/pages/OpenSource';
import Marketplace from './marketing/pages/Marketplace';
import Pricing from './marketing/pages/Pricing';
import Security from './marketing/pages/Security';
import About from './marketing/pages/About';

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
        </Route>

        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/dashboard/agents/:id" element={<AgentDetail />} />
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<Navigate to="/admin/admins" />} />
          <Route path="admins" element={<AdminsPage />} />
          <Route path="images" element={<ImagesPage />} />
          <Route path="images/:imageId" element={<ImageConfigPage />} />
          <Route path="defaults" element={<DefaultsPage />} />
          <Route path="defaults/models" element={<ModelsPage />} />
          <Route path="machines" element={<MachinesPage />} />
          <Route path="services" element={<ServicesPage />} />
          <Route path="plugin-keys" element={<PluginKeysPage />} />
          <Route path="relay" element={<RelayPage />} />
          <Route path="changelog" element={<ChangelogPage />} />
        </Route>
        <Route path="/:slug" element={<UserLuna />} />
      </Routes>
    </BrowserRouter>
  );
}
