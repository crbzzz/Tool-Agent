import { X, Plus, MessageSquare, Settings, History } from 'lucide-react';

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  onNewChat: () => void;
  onOpenSettings: () => void;
  activeView: 'chat' | 'settings';
}

export default function Sidebar({
  isOpen,
  onClose,
  onNewChat,
  onOpenSettings,
  activeView,
}: SidebarProps) {
  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/20 backdrop-blur-sm z-40 lg:hidden"
          onClick={onClose}
        ></div>
      )}

      <aside
        className={`fixed lg:static inset-y-0 left-0 w-64 bg-white border-r border-slate-200 flex flex-col z-50 transform transition-transform duration-300 ${
          isOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
      >
        <div className="p-4 border-b border-slate-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-800">Conversations</h2>
          <button
            onClick={onClose}
            className="lg:hidden p-2 hover:bg-slate-100 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-slate-600" />
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
          <button className="w-full flex items-center gap-3 px-4 py-3 text-slate-700 hover:bg-slate-100 rounded-lg transition-colors text-left">
            <MessageSquare className="w-5 h-5" />
            <span className="text-sm truncate">Sample Conversation</span>
          </button>
        </nav>

        <div className="p-4 border-t border-slate-200 space-y-1">
          <button className="w-full flex items-center gap-3 px-4 py-3 text-slate-700 hover:bg-slate-100 rounded-lg transition-colors">
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
                ? 'bg-slate-100 text-slate-900'
                : 'text-slate-700 hover:bg-slate-100'
            }`}
          >
            <Settings className="w-5 h-5" />
            <span className="text-sm">Settings</span>
          </button>
        </div>
      </aside>
    </>
  );
}
