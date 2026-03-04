import { useCallback, useEffect, useMemo, useState } from 'react';
import ChatInterface from './components/ChatInterface';
import Sidebar from './components/Sidebar';
import SettingsPage from './components/SettingsPage';

type View = 'chat' | 'settings';

function App() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [resetCounter, setResetCounter] = useState(0);
  const [view, setView] = useState<View>(() => {
    try {
      const v = new URLSearchParams(window.location.search).get('view');
      return v === 'settings' ? 'settings' : 'chat';
    } catch {
      return 'chat';
    }
  });
  const [googleConnected, setGoogleConnected] = useState(false);

  const refreshGoogleStatus = useCallback(async () => {
    const r = await fetch('/oauth/google/status');
    if (!r.ok) throw new Error(await r.text());
    const data = (await r.json()) as { connected?: boolean };
    setGoogleConnected(Boolean(data.connected));
  }, []);

  useEffect(() => {
    refreshGoogleStatus().catch(() => setGoogleConnected(false));

    const onFocus = () => {
      refreshGoogleStatus().catch(() => undefined);
    };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [refreshGoogleStatus]);

  const content = useMemo(() => {
    if (view === 'settings') {
      return (
        <SettingsPage
          onBackToChat={() => setView('chat')}
          googleConnected={googleConnected}
          refreshGoogleStatus={refreshGoogleStatus}
        />
      );
    }

    return (
      <ChatInterface
        onMenuClick={() => setIsSidebarOpen(true)}
        resetCounter={resetCounter}
        googleConnected={googleConnected}
        onOpenSettings={() => setView('settings')}
      />
    );
  }, [googleConnected, refreshGoogleStatus, resetCounter, view]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-slate-100 flex">
      <Sidebar
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        onNewChat={() => setResetCounter((c) => c + 1)}
        onOpenSettings={() => {
          setView('settings');
          setIsSidebarOpen(false);
        }}
        activeView={view}
      />
      {content}
    </div>
  );
}

export default App;
