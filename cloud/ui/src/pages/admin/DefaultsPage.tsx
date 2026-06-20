import { useEffect, useState, useCallback, useRef } from 'react';
import { Loader2, Brain, Boxes, Check } from 'lucide-react';
import ImagesTabs from './ImagesTabs';
import PluginSetEditor from '../../components/PluginSetEditor';
import type { PluginSetEntry } from '../../components/PluginSetEditor';

interface ModelHead { provider?: string; model?: string }
interface Defaults {
  models: { primary: ModelHead; fast: ModelHead };
  plugin_set: PluginSetEntry[];
}
interface CatalogModel {
  provider: string;
  model: string;
  label?: string;
  kinds: string[];
  enabled: boolean;
  recommended_default?: boolean;
}

export default function DefaultsPage() {
  const [defaults, setDefaults] = useState<Defaults | null>(null);
  const [catalog, setCatalog] = useState<CatalogModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  const saveTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const fetchData = useCallback(async () => {
    const [defRes, modelsRes] = await Promise.all([
      fetch('/api/admin/defaults'),
      fetch('/api/admin/gateway/models'),
    ]);
    if (defRes.ok) {
      const d = await defRes.json();
      setDefaults({
        models: { primary: d.models?.primary || {}, fast: d.models?.fast || {} },
        plugin_set: d.plugin_set || [],
      });
    }
    if (modelsRes.ok) setCatalog((await modelsRes.json()).filter((m: CatalogModel) => m.enabled));
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const save = useCallback(async (patch: Partial<Defaults>) => {
    setSaveStatus('saving');
    clearTimeout(saveTimer.current);
    await fetch('/api/admin/defaults', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    setSaveStatus('saved');
    saveTimer.current = setTimeout(() => setSaveStatus('idle'), 2000);
  }, []);

  const updateModel = (role: 'primary' | 'fast', modelKey: string) => {
    if (!defaults) return;
    const entry = catalog.find(m => m.model === modelKey);
    const value = modelKey && entry ? { provider: entry.provider, model: entry.model } : {};
    const models = { ...defaults.models, [role]: value };
    setDefaults({ ...defaults, models });
    save({ models });
  };

  const updatePluginSet = (next: PluginSetEntry[]) => {
    if (!defaults) return;
    setDefaults({ ...defaults, plugin_set: next });
    save({ plugin_set: next });
  };

  if (loading || !defaults) {
    return (
      <div>
        <ImagesTabs />
        <div className="flex items-center justify-center py-20">
          <Loader2 className="animate-spin" size={28} style={{ color: 'var(--moon)' }} />
        </div>
      </div>
    );
  }

  return (
    <div>
      <ImagesTabs />

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: 'var(--text)' }}>Image Defaults</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--text-dim)' }}>
            Applied to new images and to any image that hasn't overridden the value.
          </p>
        </div>
        {saveStatus !== 'idle' && (
          <span className="flex items-center gap-1.5 text-xs" style={{ color: 'var(--text-dim)' }}>
            {saveStatus === 'saving'
              ? <><Loader2 size={12} className="animate-spin" /> Saving…</>
              : <><Check size={12} style={{ color: '#4ade80' }} /> Saved</>}
          </span>
        )}
      </div>

      <div className="space-y-6" style={{ maxWidth: 720 }}>
        {/* Default model */}
        <SectionCard icon={Brain} title="Default model">
          <div>
            <p className="text-xs mb-3" style={{ color: 'var(--text-dim)' }}>
              The head new images run unless an image or machine overrides it.
              Empty inherits the model-catalog default (Key Registry).
            </p>
            {(['primary', 'fast'] as const).map((role, i) => {
              const kind = role === 'primary' ? 'reasoning' : 'summarization';
              const currentModel = defaults.models[role]?.model || '';
              const kindModels = catalog.filter(m => m.kinds.includes(kind));
              const inList = kindModels.some(m => m.model === currentModel);
              const options = [
                { value: '', label: 'Inherit catalog default' },
                ...kindModels.map(m => ({
                  value: m.model,
                  label: `${m.provider} — ${m.label || m.model}${m.recommended_default ? ' (catalog default)' : ''}`,
                })),
                ...(currentModel && !inList ? [{ value: currentModel, label: `${currentModel} (off-catalog)` }] : []),
              ];
              return (
                <FieldRow
                  key={role}
                  label={role === 'primary' ? 'Primary (reasoning)' : 'Fast (summarization)'}
                  noBorder={i === 1}
                >
                  <Select value={currentModel} options={options} onChange={v => updateModel(role, v)} />
                </FieldRow>
              );
            })}
          </div>
        </SectionCard>

        {/* Default plugin set */}
        <SectionCard icon={Boxes} title="Default plugin set">
          <div>
            <p className="text-xs mb-3" style={{ color: 'var(--text-dim)' }}>
              Baked into new images by default. Each image can override this in its
              own config. Connectors are not bakeable yet.
            </p>
            <PluginSetEditor value={defaults.plugin_set} onChange={updatePluginSet} />
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

/* ---- local primitives (match ImageConfigPage styling) ---- */

function SectionCard({ icon: Icon, title, children }: {
  icon: React.ElementType; title: string; children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border overflow-hidden" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
      <div className="flex items-center gap-2.5 px-5 py-3.5 border-b" style={{ borderColor: 'var(--ink-lighter)' }}>
        <Icon size={16} style={{ color: 'var(--moon)' }} />
        <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>{title}</span>
      </div>
      <div className="px-5 py-4">{children}</div>
    </div>
  );
}

function FieldRow({ label, children, noBorder }: { label: string; children: React.ReactNode; noBorder?: boolean }) {
  return (
    <div className="flex items-center justify-between py-2" style={noBorder ? undefined : { borderBottom: '1px solid var(--ink-lighter)' }}>
      <span className="text-sm" style={{ color: 'var(--text-dim)' }}>{label}</span>
      {children}
    </div>
  );
}

function Select({ value, options, onChange }: {
  value: string | number;
  options: { value: string | number; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="rounded-lg px-3 py-2 text-sm font-medium outline-none appearance-none cursor-pointer"
      style={{ background: 'var(--ink-light)', color: 'var(--text)', border: '1px solid var(--ink-lighter)', minWidth: 220 }}
    >
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}
