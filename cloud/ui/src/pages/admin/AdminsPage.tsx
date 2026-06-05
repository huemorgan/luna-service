import { useEffect, useState } from 'react';
import { Shield, Loader2, Plus, Trash2, Search } from 'lucide-react';

interface Admin {
  id: string;
  email: string;
  name: string | null;
  avatar_url: string | null;
}

interface UserOption {
  id: string;
  email: string;
  name: string | null;
  is_admin: boolean;
}

export default function AdminsPage() {
  const [admins, setAdmins] = useState<Admin[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [users, setUsers] = useState<UserOption[]>([]);
  const [search, setSearch] = useState('');
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);

  const fetchAdmins = async () => {
    const res = await fetch('/api/admin/admins');
    if (res.ok) setAdmins(await res.json());
    setLoading(false);
  };

  useEffect(() => { fetchAdmins(); }, []);

  const openAddDialog = async () => {
    setShowAdd(true);
    const res = await fetch('/api/admin/users');
    if (res.ok) setUsers(await res.json());
  };

  const handleAdd = async (email: string) => {
    setAdding(true);
    const res = await fetch('/api/admin/admins', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    if (res.ok) {
      await fetchAdmins();
      setShowAdd(false);
      setSearch('');
    }
    setAdding(false);
  };

  const handleRemove = async (userId: string) => {
    setRemoving(userId);
    const res = await fetch(`/api/admin/admins/${userId}`, { method: 'DELETE' });
    if (res.ok) setAdmins(prev => prev.filter(a => a.id !== userId));
    setRemoving(null);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  const filteredUsers = users
    .filter(u => !u.is_admin)
    .filter(u => u.email.toLowerCase().includes(search.toLowerCase()) || (u.name || '').toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="max-w-2xl">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          <Shield size={20} style={{ color: 'var(--moon)' }} />
          Admins
        </h2>
        <button
          onClick={openAddDialog}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all hover:scale-105"
          style={{ background: 'var(--moon)', color: 'var(--ink)' }}
        >
          <Plus size={16} />
          Add Admin
        </button>
      </div>

      {showAdd && (
        <div className="rounded-2xl p-5 border mb-6" style={{ background: 'var(--surface)', borderColor: 'var(--moon)' }}>
          <div className="flex items-center gap-2 mb-3">
            <Search size={16} style={{ color: 'var(--text-dim)' }} />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search users by email..."
              className="flex-1 bg-transparent outline-none text-sm"
              style={{ color: 'var(--text)' }}
              autoFocus
            />
            <button onClick={() => { setShowAdd(false); setSearch(''); }} className="text-xs" style={{ color: 'var(--text-dim)' }}>
              Cancel
            </button>
          </div>
          <div className="max-h-48 overflow-y-auto space-y-1">
            {filteredUsers.map(u => (
              <button
                key={u.id}
                onClick={() => handleAdd(u.email)}
                disabled={adding}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-left transition-colors hover:opacity-80 disabled:opacity-50"
                style={{ color: 'var(--text)', background: 'var(--ink)' }}
              >
                <span>{u.email}</span>
                {u.name && <span style={{ color: 'var(--text-dim)' }}>({u.name})</span>}
              </button>
            ))}
            {filteredUsers.length === 0 && (
              <p className="text-sm py-2 px-3" style={{ color: 'var(--text-dim)' }}>No users found</p>
            )}
          </div>
        </div>
      )}

      <div className="space-y-2">
        {admins.map(admin => (
          <div
            key={admin.id}
            className="flex items-center justify-between px-5 py-3 rounded-xl border"
            style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}
          >
            <div className="flex items-center gap-3">
              {admin.avatar_url ? (
                <img src={admin.avatar_url} alt="" className="w-8 h-8 rounded-full" />
              ) : (
                <div className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold" style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
                  {(admin.name || admin.email)[0].toUpperCase()}
                </div>
              )}
              <div>
                <div className="text-sm font-medium" style={{ color: 'var(--text)' }}>{admin.name || admin.email}</div>
                <div className="text-xs" style={{ color: 'var(--text-dim)' }}>{admin.email}</div>
              </div>
            </div>
            <button
              onClick={() => handleRemove(admin.id)}
              disabled={removing === admin.id}
              className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs transition-colors hover:opacity-80 disabled:opacity-50"
              style={{ color: 'var(--text-dim)' }}
              title="Remove admin"
            >
              {removing === admin.id ? <Loader2 className="animate-spin" size={12} /> : <Trash2 size={12} />}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
