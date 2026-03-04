import { useEffect, useMemo, useState } from 'react';
import { Bot, ExternalLink, LogOut, RefreshCcw } from 'lucide-react';

interface SettingsPageProps {
  onBackToChat: () => void;
  googleConnected: boolean;
  refreshGoogleStatus: () => Promise<void>;
}

export default function SettingsPage({
  onBackToChat,
  googleConnected,
  refreshGoogleStatus,
}: SettingsPageProps) {
  const [isWorking, setIsWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const statusLabel = useMemo(() => {
    return googleConnected ? 'Connecté' : 'Non connecté';
  }, [googleConnected]);

  useEffect(() => {
    // Best-effort refresh on entry.
    refreshGoogleStatus().catch(() => undefined);
  }, [refreshGoogleStatus]);

  const connectUrl =
    window.location.origin +
    '/oauth/google/start?return_to=' +
    encodeURIComponent('/oauth/google/connected');

  const openExternal = async (url: string) => {
    const w = window as unknown as {
      pywebview?: { api?: { open_external?: (u: string) => Promise<{ ok: boolean; error?: string }> } };
    };

    if (w.pywebview?.api?.open_external) {
      const res = await w.pywebview.api.open_external(url);
      if (!res?.ok) throw new Error(res?.error || 'Cannot open external browser');
      return;
    }

    // Fallback (dev in normal browser)
    window.open(url, '_blank', 'noopener,noreferrer');
  };

  const handleConnect = async () => {
    setIsWorking(true);
    setError(null);
    try {
      await openExternal(connectUrl);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsWorking(false);
    }
  };

  const handleDisconnect = async () => {
    setIsWorking(true);
    setError(null);
    try {
      const r = await fetch('/oauth/google/logout', { method: 'POST' });
      if (!r.ok) throw new Error(await r.text());
      await refreshGoogleStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsWorking(false);
    }
  };

  const handleRefresh = async () => {
    setIsWorking(true);
    setError(null);
    try {
      await refreshGoogleStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsWorking(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-screen">
      <header className="bg-white/80 backdrop-blur-sm border-b border-slate-200 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-gradient-to-br from-emerald-400 to-teal-500 rounded-lg flex items-center justify-center">
            <Bot className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-slate-800">Settings</h1>
            <p className="text-xs text-slate-500">Connexion Google</p>
          </div>
        </div>

        <button
          onClick={onBackToChat}
          className="px-4 py-2 rounded-lg border border-slate-200 text-slate-700 hover:bg-slate-50 transition-colors"
        >
          Retour au chat
        </button>
      </header>

      <main className="flex-1 overflow-y-auto px-6 py-8">
        <div className="max-w-3xl mx-auto space-y-4">
          <div className="bg-white border border-slate-200 rounded-2xl p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-base font-semibold text-slate-800">Google</h2>
                <p className="text-sm text-slate-600 mt-1">
                  Statut :{' '}
                  <span
                    className={
                      googleConnected
                        ? 'text-emerald-700 font-medium'
                        : 'text-rose-700 font-medium'
                    }
                  >
                    {statusLabel}
                  </span>
                </p>
              </div>

              <button
                onClick={handleRefresh}
                disabled={isWorking}
                className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 text-slate-700 hover:bg-slate-50 transition-colors disabled:opacity-50"
              >
                <RefreshCcw className="w-4 h-4" />
                Rafraîchir
              </button>
            </div>

            <div className="mt-4 flex flex-wrap gap-3">
              {!googleConnected ? (
                <button
                  onClick={handleConnect}
                  disabled={isWorking}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-br from-emerald-400 to-teal-500 hover:from-emerald-500 hover:to-teal-600 text-white transition-all shadow-sm hover:shadow-md disabled:opacity-50"
                >
                  <ExternalLink className="w-4 h-4" />
                  Se connecter
                </button>
              ) : (
                <button
                  onClick={handleDisconnect}
                  disabled={isWorking}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-900 text-white transition-colors disabled:opacity-50"
                >
                  <LogOut className="w-4 h-4" />
                  Se déconnecter
                </button>
              )}
            </div>

            {error && (
              <div className="mt-4 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
                {error}
              </div>
            )}

            {!googleConnected && (
              <div className="mt-4 text-sm text-slate-700 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
                Tant que Google n’est pas connecté, le chat est désactivé.
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
