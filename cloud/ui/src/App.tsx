import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Landing from './pages/Landing';
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
import RelayPage from './pages/admin/RelayPage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
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
          <Route path="relay" element={<RelayPage />} />
          <Route path="changelog" element={<ChangelogPage />} />
        </Route>
        <Route path="/:slug" element={<UserLuna />} />
      </Routes>
    </BrowserRouter>
  );
}
