import { useEffect, useMemo, useRef, useState } from 'react';
import { Bot, ExternalLink, LogOut, RefreshCcw } from 'lucide-react';

interface SettingsPageProps {
  onBackToChat: () => void;
  googleConnected: boolean;
  refreshGoogleStatus: () => Promise<void>;
  theme: 'light' | 'dark';
  onThemeChange: (t: 'light' | 'dark') => void;
}

export default function SettingsPage({
  onBackToChat,
  googleConnected,
  refreshGoogleStatus,
  theme,
  onThemeChange,
}: SettingsPageProps) {
  const [isWorking, setIsWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [authUser, setAuthUser] = useState<any | null>(null);
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authInfo, setAuthInfo] = useState<string | null>(null);
  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const oauthPollTimer = useRef<number | null>(null);
  const [micPermissionError, setMicPermissionError] = useState<string | null>(null);
  const [audioInputs, setAudioInputs] = useState<Array<{ deviceId: string; label: string }>>(
    []
  );
  const [selectedAudioInputId, setSelectedAudioInputId] = useState<string>(() => {
    try {
      return localStorage.getItem('bart_ai.audioInputDeviceId') || '';
    } catch {
      return '';
    }
  });

  const statusLabel = useMemo(() => {
    return googleConnected ? 'Connected' : 'Not connected';
  }, [googleConnected]);

  const showMicPermissionHint = useMemo(() => {
    if (audioInputs.length === 0) return true;
    // Without permission, browsers typically return empty labels.
    // We map empty labels to "Microphone", so if all labels are that placeholder,
    // it's very likely the user still needs to grant access.
    return audioInputs.every((d) => (d.label || '').trim().toLowerCase() === 'microphone');
  }, [audioInputs]);

  useEffect(() => {
    // Best-effort refresh on entry.
    refreshGoogleStatus().catch(() => undefined);
  }, [refreshGoogleStatus]);

  const refreshAuthStatus = async () => {
    setAuthLoading(true);
    setAuthError(null);
    try {
      const r = await fetch('/auth/status');
      if (!r.ok) throw new Error(await r.text());
      const data = (await r.json()) as { signed_in?: boolean; user?: any };
      setAuthUser(data.signed_in ? data.user ?? null : null);
    } catch (e) {
      setAuthUser(null);
      setAuthError(e instanceof Error ? e.message : String(e));
    } finally {
      setAuthLoading(false);
    }
  };

  useEffect(() => {
    refreshAuthStatus().catch(() => undefined);
    const onFocus = () => refreshAuthStatus().catch(() => undefined);
    window.addEventListener('focus', onFocus);
    return () => {
      window.removeEventListener('focus', onFocus);
      if (oauthPollTimer.current) {
        window.clearInterval(oauthPollTimer.current);
        oauthPollTimer.current = null;
      }
    };
  }, []);

  useEffect(() => {
    try {
      const hash = (window.location.hash || '').toLowerCase();
      if (hash === '#account' || hash === '#google') {
        const el = document.getElementById(hash.slice(1));
        el?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
      }
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    const loadDevices = async () => {
      try {
        if (!navigator.mediaDevices?.enumerateDevices) {
          if (!cancelled) setAudioInputs([]);
          return;
        }

        const devices = await navigator.mediaDevices.enumerateDevices();
        const inputs = devices
          .filter((d) => d.kind === 'audioinput')
          .map((d) => ({ deviceId: d.deviceId, label: d.label || 'Microphone' }));
        if (!cancelled) setAudioInputs(inputs);
      } catch {
        if (!cancelled) setAudioInputs([]);
      }
    };

    loadDevices().catch(() => undefined);

    const onDeviceChange = () => {
      loadDevices().catch(() => undefined);
    };
    navigator.mediaDevices?.addEventListener?.('devicechange', onDeviceChange);

    return () => {
      cancelled = true;
      navigator.mediaDevices?.removeEventListener?.('devicechange', onDeviceChange);
    };
  }, []);

  const requestMicPermissionAndReload = async () => {
    setMicPermissionError(null);

    if (!navigator.mediaDevices?.getUserMedia) {
      setMicPermissionError('Microphone access is not supported in this environment.');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      stream.getTracks().forEach((t) => t.stop());

      const devices = await navigator.mediaDevices.enumerateDevices();
      const inputs = devices
        .filter((d) => d.kind === 'audioinput')
        .map((d) => ({ deviceId: d.deviceId, label: d.label || 'Microphone' }));
      setAudioInputs(inputs);

      if (!selectedAudioInputId) {
        const first = inputs.find((d) => d.deviceId && d.deviceId !== 'default') || inputs[0];
        if (first?.deviceId) setSelectedAudioInputId(first.deviceId);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setMicPermissionError(msg || 'Microphone permission was denied.');
    }
  };

  useEffect(() => {
    try {
      localStorage.setItem('bart_ai.audioInputDeviceId', selectedAudioInputId);
    } catch {
      // ignore
    }
  }, [selectedAudioInputId]);

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

  const stopOauthPolling = () => {
    if (oauthPollTimer.current) {
      window.clearInterval(oauthPollTimer.current);
      oauthPollTimer.current = null;
    }
  };

  const startOauthFlow = async (mode: 'signin' | 'link') => {
    stopOauthPolling();
    setAuthError(null);
    setAuthInfo(null);
    setAuthLoading(true);
    try {
      const r = await fetch('/auth/oauth/google/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
      });
      if (!r.ok) throw new Error(await r.text());
      const data = (await r.json()) as { auth_url?: string; poll_token?: string };
      if (!data.auth_url || !data.poll_token) throw new Error('Invalid OAuth response');

      await openExternal(data.auth_url);

      // Poll until the system browser callback completes.
      const pollToken = data.poll_token;
      let tries = 0;
      oauthPollTimer.current = window.setInterval(async () => {
        tries += 1;
        try {
          const pr = await fetch(`/auth/oauth/poll?poll_token=${encodeURIComponent(pollToken)}`);
          if (!pr.ok) throw new Error(await pr.text());
          const pdata = (await pr.json()) as { status?: string; error?: string };
          if (pdata.status === 'pending') return;
          if (pdata.status === 'done') {
            stopOauthPolling();
            const cr = await fetch('/auth/oauth/consume', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ poll_token: pollToken }),
            });
            if (!cr.ok) throw new Error(await cr.text());
            setAuthInfo(mode === 'link' ? 'Google linked.' : 'Signed in.' );
            await refreshAuthStatus();
            setAuthLoading(false);
            return;
          }
          if (pdata.status === 'error') {
            stopOauthPolling();
            setAuthError(pdata.error || 'OAuth failed');
            setAuthLoading(false);
            return;
          }
          if (pdata.status === 'expired') {
            stopOauthPolling();
            setAuthError('Login expired. Please try again.');
            setAuthLoading(false);
            return;
          }
        } catch (e) {
          stopOauthPolling();
          setAuthError(e instanceof Error ? e.message : String(e));
          setAuthLoading(false);
        }

        if (tries > 160) {
          // ~2 minutes at 750ms
          stopOauthPolling();
          setAuthError('Timed out waiting for login.');
          setAuthLoading(false);
        }
      }, 750);
    } catch (e) {
      setAuthError(e instanceof Error ? e.message : String(e));
      setAuthLoading(false);
    }
  };

  const handleSignup = async () => {
    stopOauthPolling();
    setAuthLoading(true);
    setAuthError(null);
    setAuthInfo(null);
    try {
      const r = await fetch('/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: authEmail, password: authPassword }),
      });
      if (!r.ok) throw new Error(await r.text());
      const data = (await r.json()) as { needs_email_confirmation?: boolean };
      setAuthInfo(data.needs_email_confirmation ? 'Check your email to confirm your account.' : 'Account created.');
      await refreshAuthStatus();
    } catch (e) {
      setAuthError(e instanceof Error ? e.message : String(e));
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLogin = async () => {
    stopOauthPolling();
    setAuthLoading(true);
    setAuthError(null);
    setAuthInfo(null);
    try {
      const r = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: authEmail, password: authPassword }),
      });
      if (!r.ok) throw new Error(await r.text());
      setAuthInfo('Signed in.');
      await refreshAuthStatus();
    } catch (e) {
      setAuthError(e instanceof Error ? e.message : String(e));
    } finally {
      setAuthLoading(false);
    }
  };

  const handleAuthLogout = async () => {
    stopOauthPolling();
    setAuthLoading(true);
    setAuthError(null);
    setAuthInfo(null);
    try {
      const r = await fetch('/auth/logout', { method: 'POST' });
      if (!r.ok) throw new Error(await r.text());
      setAuthInfo('Signed out.');
      await refreshAuthStatus();
    } catch (e) {
      setAuthError(e instanceof Error ? e.message : String(e));
    } finally {
      setAuthLoading(false);
    }
  };

  const hasGoogleIdentity = useMemo(() => {
    const identities = Array.isArray(authUser?.identities) ? authUser.identities : [];
    return identities.some((i: any) => (i?.provider || i) === 'google');
  }, [authUser]);

  return (
    <div className="flex-1 flex flex-col h-screen">
      <header className="bg-white/80 dark:bg-slate-950/80 backdrop-blur-sm border-b border-slate-200 dark:border-slate-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-gradient-to-br from-emerald-400 to-teal-500 rounded-lg flex items-center justify-center">
            <Bot className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-slate-800 dark:text-slate-100">Settings</h1>
          </div>
        </div>

        <button
          onClick={onBackToChat}
          className="px-4 py-2 rounded-lg border border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-900 transition-colors"
        >
          Back to chat
        </button>
      </header>

      <main className="flex-1 overflow-y-auto px-6 py-8">
        <div className="max-w-3xl mx-auto space-y-4">
          <div id="account" className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">Account</h2>
                <p className="text-sm text-slate-600 dark:text-slate-300 mt-1">
                  {authUser ? (
                    <>
                      Signed in as <span className="font-medium text-slate-800 dark:text-slate-100">{authUser.email || 'user'}</span>
                    </>
                  ) : (
                    'Not signed in'
                  )}
                </p>
              </div>

              <button
                onClick={() => refreshAuthStatus().catch(() => undefined)}
                disabled={authLoading}
                className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-900 transition-colors disabled:opacity-50"
              >
                <RefreshCcw className="w-4 h-4" />
                Refresh
              </button>
            </div>

            {!authUser && (
              <>
                <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm text-slate-700 dark:text-slate-200">Email</label>
                    <input
                      value={authEmail}
                      onChange={(e) => setAuthEmail(e.target.value)}
                      placeholder="you@example.com"
                      className="mt-2 w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-950 text-slate-800 dark:text-slate-100"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-slate-700 dark:text-slate-200">Password</label>
                    <input
                      value={authPassword}
                      onChange={(e) => setAuthPassword(e.target.value)}
                      placeholder="••••••••"
                      type="password"
                      className="mt-2 w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-950 text-slate-800 dark:text-slate-100"
                    />
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap gap-3">
                  <button
                    onClick={handleSignup}
                    disabled={authLoading || !authEmail.trim() || !authPassword.trim()}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-900 text-white transition-colors disabled:opacity-50"
                  >
                    Create account
                  </button>
                  <button
                    onClick={handleLogin}
                    disabled={authLoading || !authEmail.trim() || !authPassword.trim()}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-900 transition-colors disabled:opacity-50"
                  >
                    Sign in
                  </button>
                  <button
                    onClick={() => startOauthFlow('signin')}
                    disabled={authLoading}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-br from-emerald-400 to-teal-500 hover:from-emerald-500 hover:to-teal-600 text-white transition-all shadow-sm hover:shadow-md disabled:opacity-50"
                  >
                    <ExternalLink className="w-4 h-4" />
                    Sign in with Google
                  </button>
                </div>
              </>
            )}

            {authUser && !hasGoogleIdentity && (
              <div className="mt-4">
                <button
                  onClick={() => startOauthFlow('link')}
                  disabled={authLoading}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-emerald-200 dark:border-emerald-900/50 text-emerald-700 dark:text-emerald-200 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-colors disabled:opacity-50"
                >
                  <ExternalLink className="w-4 h-4" />
                  Link Google
                </button>
              </div>
            )}

            {authInfo && (
              <div className="mt-4 text-sm text-emerald-800 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2">
                {authInfo}
              </div>
            )}
            {authError && (
              <div className="mt-4 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
                {authError}
              </div>
            )}

            {authUser && (
              <div className="mt-4 flex justify-end">
                <button
                  onClick={handleAuthLogout}
                  disabled={authLoading}
                  className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl text-white bg-rose-700 hover:bg-rose-800 transition-colors disabled:opacity-50"
                >
                  <LogOut className="w-4 h-4" />
                  Sign out
                </button>
              </div>
            )}
          </div>

          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">Appearance</h2>
                <p className="text-sm text-slate-600 dark:text-slate-300 mt-1">
                  Toggle dark mode.
                </p>
              </div>

              <div className="inline-flex items-center gap-3 select-none">
                <span className="text-sm text-slate-700 dark:text-slate-200">Dark mode</span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={theme === 'dark'}
                  onClick={() => onThemeChange(theme === 'dark' ? 'light' : 'dark')}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full border transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-emerald-200 dark:focus:ring-emerald-900/40 hover:shadow-sm ${
                    theme === 'dark'
                      ? 'bg-emerald-500 border-emerald-600'
                      : 'bg-slate-200 border-slate-300'
                  }`}
                  title={theme === 'dark' ? 'Disable dark mode' : 'Enable dark mode'}
                >
                  <span
                    className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform duration-200 ${
                      theme === 'dark' ? 'translate-x-5' : 'translate-x-0.5'
                    }`}
                  />
                </button>
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">Audio input</h2>
                <p className="text-sm text-slate-600 dark:text-slate-300 mt-1">
                  Select the microphone used for voice input.
                </p>
              </div>

              <button
                onClick={() => {
                  // trigger re-enumeration via devicechange listeners
                  try {
                    navigator.mediaDevices?.enumerateDevices?.().then((devices) => {
                      const inputs = devices
                        .filter((d) => d.kind === 'audioinput')
                        .map((d) => ({ deviceId: d.deviceId, label: d.label || 'Microphone' }));
                      setAudioInputs(inputs);
                    });
                  } catch {
                    // ignore
                  }
                }}
                className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-900 transition-colors"
              >
                <RefreshCcw className="w-4 h-4" />
                Refresh
              </button>
            </div>

            <div className="mt-4">
              <div className="flex items-center justify-between gap-3">
                <label className="block text-sm text-slate-700 dark:text-slate-200">
                  Microphone
                </label>
                <button
                  onClick={requestMicPermissionAndReload}
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-900 text-white text-sm transition-colors"
                >
                  Allow microphone access
                </button>
              </div>
              <select
                value={selectedAudioInputId}
                onChange={(e) => setSelectedAudioInputId(e.target.value)}
                className="mt-2 w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-950 text-slate-800 dark:text-slate-100"
              >
                <option value="">Select an input device…</option>
                {audioInputs.map((d) => (
                  <option key={d.deviceId} value={d.deviceId}>
                    {d.label}
                  </option>
                ))}
              </select>

              {micPermissionError && (
                <div className="mt-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
                  {micPermissionError}
                </div>
              )}

              {showMicPermissionHint && (
                <div className="mt-3 text-sm text-slate-700 dark:text-slate-200 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2">
                  Microphone permission is required to list input devices. Click “Allow microphone access”, then select your microphone.
                </div>
              )}
            </div>
          </div>

          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id="google" className="text-base font-semibold text-slate-800 dark:text-slate-100">Google (Gmail/Drive tools)</h2>
                <p className="text-sm text-slate-600 dark:text-slate-300 mt-1">
                  Status:{' '}
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
                <p className="text-sm text-slate-600 dark:text-slate-300 mt-1">
                  Optional: link a Google account to enable Gmail/Drive actions.
                </p>
              </div>

              <button
                onClick={handleRefresh}
                disabled={isWorking}
                className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-900 transition-colors disabled:opacity-50"
              >
                <RefreshCcw className="w-4 h-4" />
                Refresh
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
                  Connect
                </button>
              ) : (
                <button
                  onClick={handleDisconnect}
                  disabled={isWorking}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-900 text-white transition-colors disabled:opacity-50"
                >
                  <LogOut className="w-4 h-4" />
                  Disconnect
                </button>
              )}
            </div>

            {error && (
              <div className="mt-4 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
                {error}
              </div>
            )}

            {!googleConnected && (
              <div className="mt-4 text-sm text-slate-700 dark:text-slate-200 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2">
                You can use the chatbot without linking Google.
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
