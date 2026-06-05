import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Landing from './pages/Landing';
import Dashboard from './pages/Dashboard';
import AgentDetail from './pages/AgentDetail';
import UserLuna from './pages/UserLuna';
import AdminLayout from './pages/admin/AdminLayout';
import AdminsPage from './pages/admin/AdminsPage';
import ImagesPage from './pages/admin/ImagesPage';
import MachinesPage from './pages/admin/MachinesPage';
import ImageConfigPage from './pages/admin/ImageConfigPage';

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
          <Route path="machines" element={<MachinesPage />} />
        </Route>
        <Route path="/:slug" element={<UserLuna />} />
      </Routes>
    </BrowserRouter>
  );
}
