import { useCallback, useEffect, useMemo, useState } from 'react';
import ChatInterface, { Message } from './components/ChatInterface';
import Sidebar, { ChatSummary } from './components/Sidebar';
import SettingsPage from './components/SettingsPage';
import UsagePage from './components/UsagePage';

type View = 'chat' | 'settings' | 'usage';

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

  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [activeChatMessages, setActiveChatMessages] = useState<Message[]>([]);

  const loadChats = useCallback(async () => {
    try {
      const r = await fetch('/chats', { credentials: 'same-origin' });
      if (!r.ok) {
        setChats([]);
        return;
      }
      const data = (await r.json()) as { chats?: ChatSummary[] };
      setChats(Array.isArray(data?.chats) ? data.chats : []);
    } catch {
      setChats([]);
    }
  }, []);

  const openChat = useCallback(async (chatId: string) => {
    setView('chat');
    setActiveChatId(chatId);
    setActiveChatMessages([]);
    try {
      const r = await fetch(`/chats/${encodeURIComponent(chatId)}/messages`, { credentials: 'same-origin' });
      if (!r.ok) {
        setActiveChatMessages([]);
        return;
      }
      const data = (await r.json()) as {
        messages?: Array<{ id: number | string; role: string; content: string; created_at?: string }>;
      };
      const rows = Array.isArray(data?.messages) ? data.messages : [];
      const mapped: Message[] = rows
        .filter((m) => m && (m.role === 'user' || m.role === 'assistant'))
        .map((m, idx) => ({
          id: String(m.id ?? idx),
          role: m.role as 'user' | 'assistant',
          content: String(m.content ?? ''),
          timestamp: m.created_at ? new Date(m.created_at) : new Date(),
        }));
      setActiveChatMessages(mapped);
    } catch {
      setActiveChatMessages([]);
    }
  }, []);

  const renameChat = useCallback(
    async (chatId: string, title: string) => {
      const trimmed = (title || '').trim();
      if (!trimmed) return;

      try {
        await fetch(`/chats/${encodeURIComponent(chatId)}`, {
          method: 'PATCH',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: trimmed }),
        });
      } catch {
        // ignore
      }

      loadChats().catch(() => undefined);
    },
    [loadChats]
  );

  const createNewChat = useCallback(async () => {
    try {
      const r = await fetch('/chats', { method: 'POST', credentials: 'same-origin' });
      if (!r.ok) throw new Error(await r.text());
      const data = (await r.json()) as { chat?: { id?: string } };
      const id = (data?.chat?.id || '').toString();
      if (!id) throw new Error('Invalid chat');
      await loadChats();
      setActiveChatId(id);
      setActiveChatMessages([]);
      setResetCounter((c) => c + 1);
      setView('chat');
    } catch {
      // If not signed in yet, ChatInterface will prompt on send.
      setActiveChatId(null);
      setActiveChatMessages([]);
      setResetCounter((c) => c + 1);
      setView('chat');
    }
  }, [loadChats]);

  const deleteChat = useCallback(
    async (chatId: string) => {
      try {
        await fetch(`/chats/${encodeURIComponent(chatId)}`, {
          method: 'DELETE',
          credentials: 'same-origin',
        });
      } catch {
        // ignore
      }

      if (activeChatId === chatId) {
        setActiveChatId(null);
        setActiveChatMessages([]);
        setResetCounter((c) => c + 1);
      }
      loadChats().catch(() => undefined);
    },
    [activeChatId, loadChats]
  );

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

    loadChats().catch(() => undefined);

    const onFocus = () => {
      refreshGoogleStatus().catch(() => undefined);
      loadChats().catch(() => undefined);
    };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [refreshGoogleStatus, loadChats]);

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

    if (view === 'usage') {
      return <UsagePage onBackToChat={() => setView('chat')} />;
    }

    return (
      <ChatInterface
        onMenuClick={() => setIsSidebarOpen(true)}
        resetCounter={resetCounter}
        chatId={activeChatId}
        initialMessages={activeChatMessages}
        onChatIdChange={(id) => {
          setActiveChatId(id);
          if (id) loadChats().catch(() => undefined);
        }}
        onChatActivity={() => loadChats().catch(() => undefined)}
      />
    );
  }, [activeChatId, activeChatMessages, googleConnected, loadChats, refreshGoogleStatus, resetCounter, theme, view]);

  return (
    <div className="min-h-screen flex bg-slate-50 dark:bg-slate-950 transition-colors">
      <Sidebar
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        onNewChat={() => createNewChat()}
        chats={chats}
        activeChatId={activeChatId}
        onOpenChat={(id) => openChat(id)}
        onDeleteChat={(id) => deleteChat(id)}
        onRenameChat={(id, title) => renameChat(id, title)}
        onOpenUsage={() => {
          setView('usage');
          setIsSidebarOpen(false);
        }}
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
