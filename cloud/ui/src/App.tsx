import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Landing from './pages/Landing';
import Dashboard from './pages/Dashboard';
import AgentDetail from './pages/AgentDetail';
import UserLuna from './pages/UserLuna';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/dashboard/agents/:id" element={<AgentDetail />} />
        <Route path="/:slug" element={<UserLuna />} />
      </Routes>
    </BrowserRouter>
  );
}
