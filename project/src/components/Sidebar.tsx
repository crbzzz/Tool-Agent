import { useEffect, useRef, useState } from 'react';
import { X, Plus, MessageSquare, Settings, History, Trash2, Pencil } from 'lucide-react';

export interface ChatSummary {
  id: string;
  title?: string | null;
  updated_at?: string | null;
  created_at?: string | null;
}

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  onNewChat: () => void;
  chats: ChatSummary[];
  activeChatId: string | null;
  onOpenChat: (chatId: string) => void;
  onDeleteChat: (chatId: string) => void;
  onRenameChat: (chatId: string, title: string) => void;
  onOpenSettings: () => void;
  activeView: 'chat' | 'settings';
}

export default function Sidebar({
  isOpen,
  onClose,
  onNewChat,
  chats,
  activeChatId,
  onOpenChat,
  onDeleteChat,
  onRenameChat,
  onOpenSettings,
  activeView,
}: SidebarProps) {
  const [ctx, setCtx] = useState<{ chatId: string; x: number; y: number } | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ctx) return;

    const onMouseDown = (e: MouseEvent) => {
      const el = menuRef.current;
      if (el && e.target instanceof Node && el.contains(e.target)) return;
      setCtx(null);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setCtx(null);
    };

    window.addEventListener('mousedown', onMouseDown);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('mousedown', onMouseDown);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [ctx]);

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/20 backdrop-blur-sm z-40"
          onClick={onClose}
        ></div>
      )}

      <aside
        className={`fixed inset-y-0 left-0 w-64 bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 flex flex-col z-50 transform transition-transform duration-300 ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="p-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-100">Conversations</h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-slate-100 dark:hover:bg-slate-900 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-slate-600 dark:text-slate-300" />
          </button>
        </div>

        <div className="p-4">
          <button
            onClick={() => {
              onNewChat();
              onClose();
            }}
            className="w-full flex items-center gap-2 px-4 py-3 bg-gradient-to-br from-emerald-400 to-teal-500 hover:from-emerald-500 hover:to-teal-600 text-white rounded-lg transition-all shadow-sm hover:shadow-md"
          >
            <Plus className="w-5 h-5" />
            <span className="font-medium">New Chat</span>
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-4 space-y-1">
          {(chats || []).map((c) => {
            const isActive = activeChatId === c.id;
            const title = (c.title || '').trim() || 'New chat';
            return (
              <button
                key={c.id}
                onClick={() => {
                  onOpenChat(c.id);
                  onClose();
                }}
                onContextMenu={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setCtx({ chatId: c.id, x: e.clientX, y: e.clientY });
                }}
                className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors duration-200 text-left ${
                  isActive
                    ? 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100'
                    : 'text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800'
                }`}
                title={title}
              >
                <MessageSquare className="w-5 h-5" />
                <span className="text-sm truncate">{title}</span>
              </button>
            );
          })}
        </nav>

        <div className="p-4 border-t border-slate-200 dark:border-slate-800 space-y-1">
          <button className="w-full flex items-center gap-3 px-4 py-3 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors duration-200">
            <History className="w-5 h-5" />
            <span className="text-sm">History</span>
          </button>
          <button
            onClick={() => {
              onOpenSettings();
              onClose();
            }}
            className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
              activeView === 'settings'
                ? 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100'
                : 'text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800'
            }`}
          >
            <Settings className="w-5 h-5" />
            <span className="text-sm">Settings</span>
          </button>
        </div>
      </aside>

      {ctx && (
        <div
          ref={menuRef}
          className="fixed z-[60] min-w-40 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-md overflow-hidden"
          style={{ left: ctx.x, top: ctx.y }}
        >
          <button
            className="w-full flex items-center gap-2 px-3 py-2 text-left text-sm text-slate-800 dark:text-slate-100 hover:bg-slate-50 dark:hover:bg-slate-800"
            onClick={() => {
              const id = ctx.chatId;
              const current = (chats || []).find((c) => c.id === id);
              const currentTitle = (current?.title || '').toString();
              setCtx(null);

              const next = window.prompt('Rename chat', currentTitle);
              if (typeof next !== 'string') return;
              const trimmed = next.trim();
              if (!trimmed) return;
              onRenameChat(id, trimmed);
            }}
          >
            <Pencil className="w-4 h-4" />
            Rename chat
          </button>
          <button
            className="w-full flex items-center gap-2 px-3 py-2 text-left text-sm text-rose-700 dark:text-rose-300 hover:bg-slate-50 dark:hover:bg-slate-800"
            onClick={() => {
              const id = ctx.chatId;
              setCtx(null);
              onDeleteChat(id);
            }}
          >
            <Trash2 className="w-4 h-4" />
            Delete chat
          </button>
        </div>
      )}
    </>
  );
}
