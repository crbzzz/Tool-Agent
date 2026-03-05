import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, BarChart3 } from 'lucide-react';

type UsageDayRow = {
  day: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_tokens: number;
};

type UsageResponse = {
  ok: boolean;
  quota_daily: number;
  day: string;
  used_today: UsageDayRow;
  remaining_today: number;
  series: UsageDayRow[];
};

interface UsagePageProps {
  onBackToChat: () => void;
}

function clampInt(value: unknown, fallback = 0): number {
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(0, Math.floor(n));
}

export default function UsagePage({ onBackToChat }: UsagePageProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<UsageResponse | null>(null);
  const [authRequired, setAuthRequired] = useState(false);
  const chartRef = useRef<HTMLDivElement | null>(null);
  const plotRef = useRef<HTMLDivElement | null>(null);
  const [hover, setHover] = useState<
    { day: string; tokens: number; x: number; y: number; xPlot: number; hPct: number } | null
  >(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    setAuthRequired(false);
    try {
      const r = await fetch('/usage/tokens?days=30', { credentials: 'same-origin' });
      if (r.status === 401) {
        setData(null);
        setAuthRequired(true);
        return;
      }
      if (!r.ok) throw new Error(await r.text());
      const json = (await r.json()) as UsageResponse;
      if (!json?.ok) throw new Error('Usage endpoint returned an error');

      // Normalize numeric fields defensively.
      const normalized: UsageResponse = {
        ...json,
        quota_daily: clampInt(json.quota_daily, 48000),
        remaining_today: clampInt(json.remaining_today, 0),
        used_today: {
          ...json.used_today,
          prompt_tokens: clampInt(json.used_today?.prompt_tokens, 0),
          completion_tokens: clampInt(json.used_today?.completion_tokens, 0),
          total_tokens: clampInt(json.used_today?.total_tokens, 0),
          estimated_tokens: clampInt(json.used_today?.estimated_tokens, 0),
        },
        series: Array.isArray(json.series)
          ? json.series.map((row) => ({
              day: String((row as any)?.day ?? ''),
              prompt_tokens: clampInt((row as any)?.prompt_tokens, 0),
              completion_tokens: clampInt((row as any)?.completion_tokens, 0),
              total_tokens: clampInt((row as any)?.total_tokens, 0),
              estimated_tokens: clampInt((row as any)?.estimated_tokens, 0),
            }))
          : [],
      };

      setData(normalized);
    } catch (e) {
      setData(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load().catch(() => undefined);
    const onFocus = () => load().catch(() => undefined);
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, []);

  const quota = data?.quota_daily ?? 48000;
  const used = data?.used_today?.total_tokens ?? 0;
  const remaining = Math.max(0, quota - used);
  const pct = quota > 0 ? Math.min(100, Math.max(0, (used / quota) * 100)) : 0;

  const series = data?.series ?? [];
  const maxY = useMemo(() => {
    const m = Math.max(1, ...series.map((d) => d.total_tokens || 0));
    return m;
  }, [series]);

  const last30 = series.slice(-30);

  const monthly = useMemo(() => {
    const map = new Map<string, number>();
    for (const row of series) {
      const day = (row.day || '').slice(0, 10);
      if (!day || day.length < 7) continue;
      const key = day.slice(0, 7); // YYYY-MM
      map.set(key, (map.get(key) || 0) + (row.total_tokens || 0));
    }
    const entries = Array.from(map.entries())
      .sort((a, b) => (a[0] < b[0] ? -1 : 1))
      .map(([month, total]) => ({ month, total }));
    return entries;
  }, [series]);

  const monthlyLast6 = useMemo(() => {
    const tail = monthly.slice(-6);
    return tail;
  }, [monthly]);

  const currentMonthTotal = useMemo(() => {
    const cur = (data?.day || '').slice(0, 7);
    if (!cur) return 0;
    return monthly.find((m) => m.month === cur)?.total ?? 0;
  }, [data, monthly]);

  const estimatedNote = useMemo(() => {
    const est = data?.used_today?.estimated_tokens ?? 0;
    if (!est) return null;
    return 'Some token counts are estimated.';
  }, [data]);

  const tooltipStyle = useMemo(() => {
    if (!hover) return null;
    const container = chartRef.current;
    const tip = tooltipRef.current;
    if (!container || !tip) {
      return { left: hover.x, top: hover.y, transform: 'translate(-50%, -110%)' } as const;
    }

    const pad = 10;
    const w = Math.max(1, tip.offsetWidth);
    const h = Math.max(1, tip.offsetHeight);
    const rect = container.getBoundingClientRect();

    let left = hover.x - w / 2;
    if (left < pad) left = pad;
    if (left > rect.width - pad - w) left = rect.width - pad - w;

    // Prefer above cursor; if not enough room, show below.
    let top = hover.y - h - 12;
    if (top < pad) top = hover.y + 12;
    if (top > rect.height - pad - h) top = rect.height - pad - h;

    return { left, top } as const;
  }, [hover]);

  return (
    <main className="flex-1 px-6 py-6 overflow-y-auto">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between gap-3 mb-6">
          <div className="flex items-center gap-3">
            <button
              onClick={onBackToChat}
              className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-900 transition-colors"
              title="Back"
            >
              <ArrowLeft className="w-5 h-5 text-slate-700 dark:text-slate-200" />
            </button>
            <div>
              <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Utilisation</h1>
              <p className="text-sm text-slate-600 dark:text-slate-400">Daily token usage and history</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => load()}
              disabled={loading}
              className="px-4 py-2 rounded-lg bg-slate-900 text-white dark:bg-white dark:text-slate-900 hover:opacity-95 disabled:opacity-60 transition-opacity"
            >
              {loading ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>
        </div>

        {authRequired && (
          <div className="mb-6 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5">
            <div className="text-sm text-slate-700 dark:text-slate-200">
              Sign in is required to view your usage.
            </div>
            <div className="mt-2 text-sm text-slate-600 dark:text-slate-400">
              Go to Settings → Account to sign in.
            </div>
          </div>
        )}

        {!authRequired && error && (
          <div className="mb-6 rounded-2xl border border-rose-200 dark:border-rose-900 bg-rose-50 dark:bg-rose-950/30 p-4">
            <div className="text-sm text-rose-800 dark:text-rose-200 break-words">{error}</div>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm text-slate-600 dark:text-slate-400">Today</div>
                <div className="text-3xl font-semibold text-slate-900 dark:text-slate-100">
                  {used.toLocaleString()} <span className="text-base font-medium text-slate-600 dark:text-slate-400">/ {quota.toLocaleString()}</span>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-400 to-teal-500 flex items-center justify-center">
                  <BarChart3 className="w-5 h-5 text-white" />
                </div>
                <div
                  className="h-12 w-3 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden border border-slate-200 dark:border-slate-700"
                  title={`${used.toLocaleString()} / ${quota.toLocaleString()} tokens`}
                  aria-label="Today token usage"
                >
                  <div
                    className="w-full bg-gradient-to-t from-emerald-400 to-teal-500"
                    style={{ height: `${pct}%` }}
                  />
                </div>
              </div>
            </div>

            <div className="mt-4">
              <div className="flex items-center justify-between text-xs text-slate-600 dark:text-slate-400 mb-2">
                <span>{pct.toFixed(1)}% used</span>
                <span>{remaining.toLocaleString()} remaining</span>
              </div>
              <div className="h-3 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden border border-slate-200 dark:border-slate-700">
                <div
                  className="h-full bg-gradient-to-r from-emerald-400 to-teal-500"
                  style={{ width: `${pct}%` }}
                />
              </div>

              {estimatedNote && (
                <div className="mt-3 text-xs text-slate-500 dark:text-slate-400">{estimatedNote}</div>
              )}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5">
            <div className="text-sm text-slate-600 dark:text-slate-400">Quota</div>
            <div className="mt-1 text-2xl font-semibold text-slate-900 dark:text-slate-100">
              48,000 tokens / day
            </div>
            <div className="mt-3 text-sm text-slate-600 dark:text-slate-400 leading-relaxed">
              Token usage is stored per user in the database and aggregated by day.
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5">
          <div className="flex items-center justify-between gap-3 mb-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Tokens used per day</h2>
              <p className="text-sm text-slate-600 dark:text-slate-400">Last {last30.length} days</p>
            </div>
          </div>

          {last30.length === 0 ? (
            <div className="text-sm text-slate-600 dark:text-slate-400">No data yet.</div>
          ) : (
            <div className="relative">
              <div
                ref={chartRef}
                className="relative h-48 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/60 dark:bg-slate-950/20 overflow-hidden"
                onMouseLeave={() => setHover(null)}
              >
                {/* Horizontal grid (table look) */}
                <div className="pointer-events-none absolute inset-0">
                  {[25, 50, 75].map((p) => (
                    <div
                      key={p}
                      className="absolute left-0 right-0 border-t border-slate-200/70 dark:border-slate-800/70"
                      style={{ top: `${100 - p}%` }}
                    />
                  ))}
                </div>

                {/* Tooltip */}
                {hover && (
                  <div
                    ref={tooltipRef}
                    className="pointer-events-none absolute z-10 px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 shadow-md"
                    style={tooltipStyle ?? { left: hover.x, top: hover.y, transform: 'translate(-50%, -110%)' }}
                  >
                    <div className="text-xs text-slate-600 dark:text-slate-400">{hover.day}</div>
                    <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {hover.tokens.toLocaleString()} tokens
                    </div>
                  </div>
                )}

                {/* Bars */}
                <div
                  ref={plotRef}
                  className="absolute inset-0 px-2 pb-8 pt-3"
                  onMouseLeave={() => setHover(null)}
                  onMouseMove={(e) => {
                    const container = chartRef.current;
                    const plot = plotRef.current;
                    if (!container || !plot) return;
                    if (last30.length === 0) return;

                    const rect = container.getBoundingClientRect();
                    const plotRect = plot.getBoundingClientRect();

                    const x = e.clientX - rect.left;
                    const y = e.clientY - rect.top;

                    const plotW = Math.max(1, plotRect.width);
                    const xPlotRaw = e.clientX - plotRect.left;
                    const xPlotClamped = Math.min(plotW, Math.max(0, xPlotRaw));

                    const idx = Math.min(
                      last30.length - 1,
                      Math.max(0, Math.floor((xPlotClamped / plotW) * last30.length))
                    );

                    const d = last30[idx];
                    const label = (d?.day || '').slice(0, 10);
                    const tokens = d?.total_tokens || 0;
                    const h = maxY > 0 ? Math.max(2, Math.round((tokens / maxY) * 100)) : 2;

                    const xPlotCenter = ((idx + 0.5) / last30.length) * plotW;
                    setHover({ day: label, tokens, x, y, xPlot: xPlotCenter, hPct: h });
                  }}
                >
                  {/* Hover stick (like stats) */}
                  {hover && (
                    <div
                      className="pointer-events-none absolute top-0 bottom-0"
                      style={{ left: hover.xPlot }}
                    >
                      <div
                        className="absolute top-0 bottom-0 w-px bg-emerald-400/80"
                        style={{ transform: 'translateX(-50%)' }}
                      />
                      <div
                        className="absolute w-2 h-2 bg-gradient-to-br from-emerald-400 to-teal-500 rounded-full"
                        style={{ bottom: `${Math.max(2, hover.hPct)}%`, transform: 'translate(-50%, 50%)' }}
                      />
                    </div>
                  )}

                  <div className="h-full flex items-end">
                    {last30.map((d) => {
                      const h = maxY > 0 ? Math.max(2, Math.round((d.total_tokens / maxY) * 100)) : 2;
                      const label = (d.day || '').slice(0, 10);
                      const tokens = d.total_tokens || 0;

                      return (
                        <div
                          key={d.day}
                          className="flex-1 h-full flex items-end border-l border-slate-200/60 dark:border-slate-800/60 first:border-l-0"
                        >
                          <div className="w-full px-[2px]">
                            <div
                              className="w-full rounded-md bg-gradient-to-t from-emerald-400 to-teal-500"
                              style={{ height: `${h}%` }}
                              aria-label={`${label}: ${tokens} tokens`}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* X axis labels (inside chart, fixed placement) */}
                <div className="absolute left-0 right-0 bottom-0 px-3 py-2 border-t border-slate-200/80 dark:border-slate-800/80 bg-white/70 dark:bg-slate-900/30">
                  <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                    <span>{(last30[0]?.day || '').slice(0, 10)}</span>
                    <span>{(last30[last30.length - 1]?.day || '').slice(0, 10)}</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="mt-6 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Monthly usage</h2>
              <p className="text-sm text-slate-600 dark:text-slate-400">Totals aggregated by month</p>
            </div>
            <div className="text-right">
              <div className="text-xs text-slate-600 dark:text-slate-400">This month</div>
              <div className="text-xl font-semibold text-slate-900 dark:text-slate-100">
                {currentMonthTotal.toLocaleString()} tokens
              </div>
            </div>
          </div>

          {monthlyLast6.length === 0 ? (
            <div className="mt-4 text-sm text-slate-600 dark:text-slate-400">No monthly data yet.</div>
          ) : (
            <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 dark:border-slate-800">
              <div className="grid grid-cols-2 bg-slate-50 dark:bg-slate-950/20 text-xs text-slate-600 dark:text-slate-400">
                <div className="px-3 py-2">Month</div>
                <div className="px-3 py-2 text-right">Tokens</div>
              </div>
              {monthlyLast6
                .slice()
                .reverse()
                .map((m) => (
                  <div
                    key={m.month}
                    className="grid grid-cols-2 border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900"
                  >
                    <div className="px-3 py-2 text-sm text-slate-900 dark:text-slate-100">{m.month}</div>
                    <div className="px-3 py-2 text-sm text-slate-900 dark:text-slate-100 text-right">
                      {m.total.toLocaleString()}
                    </div>
                  </div>
                ))}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
