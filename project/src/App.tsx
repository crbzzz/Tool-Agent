import { useCallback, useEffect, useMemo, useState } from 'react';
import ChatInterface from './components/ChatInterface';
import Sidebar from './components/Sidebar';
import SettingsPage from './components/SettingsPage';

type View = 'chat' | 'settings';

type Theme = 'light' | 'dark';

function getInitialTheme(): Theme {
  try {
    const raw = (localStorage.getItem('bart_ai.theme') || '').toLowerCase();
    return raw === 'dark' ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

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
  const [theme, setTheme] = useState<Theme>(() => getInitialTheme());

  useEffect(() => {
    try {
      localStorage.setItem('bart_ai.theme', theme);
    } catch {
      // ignore
    }

    const root = document.documentElement;
    if (theme === 'dark') root.classList.add('dark');
    else root.classList.remove('dark');
  }, [theme]);

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
          theme={theme}
          onThemeChange={setTheme}
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
  }, [googleConnected, refreshGoogleStatus, resetCounter, theme, view]);

  return (
    <div className="min-h-screen flex bg-slate-50 dark:bg-slate-950 transition-colors">
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
