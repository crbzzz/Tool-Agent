import { ArrowLeft } from 'lucide-react';
import { useMemo, useState } from 'react';

interface AppsPageProps {
  onBackToChat: () => void;
}

type AppId = 'attachments_to_drive' | 'weekly_important_summary' | 'spam_hygiene';

type AppCard = {
  id: AppId;
  title: string;
  description: string;
  example: string;
};

export default function AppsPage({ onBackToChat }: AppsPageProps) {
  const [activeAppId, setActiveAppId] = useState<AppId | null>(null);

  const apps: AppCard[] = useMemo(
    () => [
      {
        id: 'attachments_to_drive',
        title: 'Email attachments → Drive automation',
        description:
          'Automatically collects and routes email attachments into a dedicated Google Drive folder so you never miss a file.',
        example: 'Example: put every PDF received by email into a “PDF” Drive folder.',
      },
      {
        id: 'weekly_important_summary',
        title: 'Weekly summary of important emails',
        description:
          'Summarizes the most important emails you received this week so you can focus on what matters and ignore noise.',
        example: 'Example: a weekly digest highlighting key threads, skipping low-value messages.',
      },
      {
        id: 'spam_hygiene',
        title: 'Spam hygiene (triage / delete)',
        description:
          'Identifies spam-like emails and automates how they are handled to keep your inbox clean.',
        example: 'Example: move obvious spam to Trash and keep only relevant emails in Inbox.',
      },
    ],
    []
  );

  const active = useMemo(() => apps.find((a) => a.id === activeAppId) || null, [apps, activeAppId]);

  return (
    <main className="flex-1 px-6 py-6 overflow-y-auto">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between gap-3 mb-6">
          <div className="flex items-center gap-3">
            <button
              onClick={() => {
                if (activeAppId) setActiveAppId(null);
                else onBackToChat();
              }}
              className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-900 transition-colors"
              title="Back"
            >
              <ArrowLeft className="w-5 h-5 text-slate-700 dark:text-slate-200" />
            </button>
            <div>
              <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Apps</h1>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                Agentic apps to automate workflows (email, Drive, triage…)
              </p>
            </div>
          </div>
        </div>

        {active ? (
          <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5">
            <div className="text-xl font-semibold text-slate-900 dark:text-slate-100">{active.title}</div>
            <div className="mt-3 text-sm text-slate-700 dark:text-slate-200">{active.description}</div>
            <div className="mt-3 text-sm text-slate-600 dark:text-slate-400">{active.example}</div>

            <div className="mt-5">
              <button
                onClick={() => setActiveAppId(null)}
                className="px-4 py-2 rounded-lg bg-slate-900 text-white dark:bg-white dark:text-slate-900 hover:opacity-95 transition-opacity"
              >
                Back to Apps
              </button>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {apps.map((a) => (
              <button
                key={a.id}
                onClick={() => setActiveAppId(a.id)}
                className="text-left rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 hover:bg-slate-50 dark:hover:bg-slate-900/80 transition-colors"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="text-lg font-semibold text-slate-900 dark:text-slate-100">{a.title}</div>
                  <div className="shrink-0">
                    <span className="text-sm text-slate-600 dark:text-slate-300">Open</span>
                  </div>
                </div>
                <div className="mt-2 text-sm text-slate-700 dark:text-slate-200">{a.description}</div>
                <div className="mt-3 text-sm text-slate-600 dark:text-slate-400">{a.example}</div>
              </button>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
