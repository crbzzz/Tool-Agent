import { useEffect, useRef, useState } from 'react';
import { Send, Menu, Bot, User, Mic } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

interface ChatInterfaceProps {
  onMenuClick: () => void;
  resetCounter: number;
  googleConnected: boolean;
  onOpenSettings: () => void;
}

interface ChatResponse {
  final_answer: string;
  tool_trace: Array<{ name: string; ok: boolean; error?: string | null }>;
  session_id?: string | null;
}

function extractAssistantAnswer(raw: string): string {
  const text = (raw ?? '').toString();
  const trimmed = text.trim();
  if (!trimmed) return '';

  // If the agent returns a JSON payload (e.g. {"answer":..., "sources":...}),
  // only display the human-readable `answer` field.
  if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
    try {
      const parsed = JSON.parse(trimmed) as unknown;
      if (parsed && typeof parsed === 'object') {
        const maybeAnswer = (parsed as { answer?: unknown }).answer;
        if (typeof maybeAnswer === 'string') return maybeAnswer;
      }
    } catch {
      // Not JSON; fall through.
    }
  }

  return text;
}

export default function ChatInterface({
  onMenuClick,
  resetCounter,
  googleConnected,
  onOpenSettings,
}: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);

  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | null>(null);

  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioStreamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);

  useEffect(() => {
    setMessages([]);
    setInput('');
    setIsLoading(false);
    setSessionId(null);
  }, [resetCounter]);

  useEffect(() => {
    return () => {
      if (toastTimer.current) {
        window.clearTimeout(toastTimer.current);
        toastTimer.current = null;
      }
      try {
        audioStreamRef.current?.getTracks().forEach((t) => t.stop());
      } catch {
        // ignore
      }
      audioStreamRef.current = null;
      mediaRecorderRef.current = null;
      chunksRef.current = [];
    };
  }, []);

  const showToast = (message: string) => {
    setToast(message);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => {
      setToast(null);
      toastTimer.current = null;
    }, 3500);
  };

  const copyText = async (text: string) => {
    const value = (text || '').toString();
    if (!value) return;

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        const el = document.createElement('textarea');
        el.value = value;
        el.style.position = 'fixed';
        el.style.left = '-9999px';
        document.body.appendChild(el);
        el.focus();
        el.select();
        document.execCommand('copy');
        document.body.removeChild(el);
      }

      showToast('Copied to clipboard.');
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e));
    }
  };

  const getSelectedAudioInputId = (): string => {
    try {
      return localStorage.getItem('bart_ai.audioInputDeviceId') || '';
    } catch {
      return '';
    }
  };

  const ensureMicPermission = async (): Promise<boolean> => {
    if (!navigator.mediaDevices?.getUserMedia) return false;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      stream.getTracks().forEach((t) => t.stop());
      return true;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      showToast(msg || 'Microphone permission was denied.');
      return false;
    }
  };

  const pickFirstAudioInputAfterPermission = async (): Promise<string> => {
    try {
      const devices = await navigator.mediaDevices?.enumerateDevices?.();
      if (!devices) return '';

      const inputs = devices.filter((d) => d.kind === 'audioinput');
      const first =
        inputs.find((d) => d.deviceId && d.deviceId !== 'default') || inputs[0];
      if (!first?.deviceId) return '';

      try {
        localStorage.setItem('bart_ai.audioInputDeviceId', first.deviceId);
      } catch {
        // ignore
      }
      return first.deviceId;
    } catch {
      return '';
    }
  };

  const handleSend = async () => {
    if (!googleConnected) return;
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const r = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMessage.content, session_id: sessionId }),
      });

      if (!r.ok) {
        const text = await r.text();
        throw new Error(text || `HTTP ${r.status}`);
      }

      const data = (await r.json()) as ChatResponse;
      if (typeof data.session_id === 'string' && data.session_id.trim()) {
        setSessionId(data.session_id);
      }

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: extractAssistantAnswer(data.final_answer || ''),
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: `Error: ${err instanceof Error ? err.message : String(err)}`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const startRecording = async () => {
    if (!googleConnected) return;
    if (isLoading || isRecording || isTranscribing) return;

    if (!navigator.mediaDevices?.getUserMedia) {
      showToast('Audio capture is not supported in this environment.');
      return;
    }

    // Important: ask for microphone permission first, otherwise device labels / selection
    // can be empty and the user cannot pick an input yet.
    const hasPermission = await ensureMicPermission();
    if (!hasPermission) return;

    let selected = getSelectedAudioInputId();
    if (!selected) {
      selected = await pickFirstAudioInputAfterPermission();
      if (!selected) {
        showToast('No audio input selected. Open Settings, allow microphone access, then select an input device.');
        return;
      }
    }

    try {
      const constraints: MediaStreamConstraints = {
        audio: { deviceId: { exact: selected } },
        video: false,
      };
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      audioStreamRef.current = stream;

      const mimeType =
        ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/ogg'].find(
          (t) => MediaRecorder.isTypeSupported(t)
        ) || '';

      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        setIsRecording(false);
        setIsTranscribing(true);

        try {
          const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
          chunksRef.current = [];

          const form = new FormData();
          const ext = (blob.type || '').includes('ogg') ? 'ogg' : 'webm';
          form.append('file', blob, `recording.${ext}`);

          const r = await fetch('/voice/transcribe', { method: 'POST', body: form });
          if (!r.ok) {
            const raw = await r.text();
            try {
              const parsed = JSON.parse(raw) as { detail?: unknown };
              if (typeof parsed?.detail === 'string' && parsed.detail.trim()) {
                showToast(parsed.detail);
                return;
              }
            } catch {
              // ignore
            }
            showToast(raw || 'No audio detected. Please choose an input device in Settings and try again.');
            return;
          }

          const data = (await r.json()) as { text?: string };
          const text = (data.text || '').trim();
          if (!text) {
            showToast('No audio detected. Please choose an input device in Settings and try again.');
            return;
          }

          setInput((prev) => (prev.trim() ? prev.replace(/\s+$/g, '') + ' ' + text : text));
        } catch (e) {
          showToast(e instanceof Error ? e.message : String(e));
        } finally {
          setIsTranscribing(false);
          try {
            audioStreamRef.current?.getTracks().forEach((t) => t.stop());
          } catch {
            // ignore
          }
          audioStreamRef.current = null;
          mediaRecorderRef.current = null;
        }
      };

      recorder.start();
      setIsRecording(true);
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e));
      try {
        audioStreamRef.current?.getTracks().forEach((t) => t.stop());
      } catch {
        // ignore
      }
      audioStreamRef.current = null;
      mediaRecorderRef.current = null;
    }
  };

  const stopRecording = () => {
    try {
      mediaRecorderRef.current?.stop();
    } catch {
      setIsRecording(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex-1 flex flex-col h-screen">
      <header className="bg-white/80 dark:bg-slate-950/80 backdrop-blur-sm border-b border-slate-200 dark:border-slate-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={onMenuClick}
            className="p-2 hover:bg-slate-100 dark:hover:bg-slate-900 rounded-lg transition-colors"
          >
            <Menu className="w-5 h-5 text-slate-600 dark:text-slate-300" />
          </button>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-gradient-to-br from-emerald-400 to-teal-500 rounded-lg flex items-center justify-center">
              <Bot className="w-5 h-5 text-white" />
            </div>
            <h1 className="text-xl font-semibold text-slate-800 dark:text-slate-100">Bart AI</h1>
          </div>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-6 py-8">
        {!googleConnected && (
          <div className="max-w-3xl mx-auto mb-6">
            <div className="bg-amber-50 border border-amber-200 text-amber-900 dark:bg-amber-950/30 dark:border-amber-900 dark:text-amber-100 rounded-2xl px-4 py-3 flex items-center justify-between gap-3">
              <div className="text-sm">
                Google connection is required to use chat.
              </div>
              <button
                onClick={onOpenSettings}
                className="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-900 text-white text-sm transition-colors"
              >
                Connect
              </button>
            </div>
          </div>
        )}

        {messages.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <div className="text-center max-w-md">
              <div className="w-16 h-16 bg-gradient-to-br from-emerald-400 to-teal-500 rounded-2xl flex items-center justify-center mx-auto mb-4">
                <Bot className="w-8 h-8 text-white" />
              </div>
              <h2 className="text-2xl font-semibold text-slate-800 dark:text-slate-100 mb-2">
                Welcome to Bart AI
              </h2>
              <p className="text-slate-600 dark:text-slate-300">
                Start a conversation with your AI assistant. Ask questions, get help with tasks, or explore possibilities.
              </p>
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto space-y-6">
            {messages.map((message) => (
              <div
                key={message.id}
                className={`flex gap-3 ${
                  message.role === 'user' ? 'justify-end' : 'justify-start'
                }`}
              >
                {message.role === 'assistant' && (
                  <div className="w-8 h-8 bg-gradient-to-br from-emerald-400 to-teal-500 rounded-lg flex items-center justify-center flex-shrink-0">
                    <Bot className="w-5 h-5 text-white" />
                  </div>
                )}
                <div
                  className={`px-4 py-3 rounded-2xl max-w-[80%] ${
                    message.role === 'user'
                      ? 'bg-slate-800 text-white'
                      : 'bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-800 dark:text-slate-100'
                  }`}
                >
                  {message.role === 'assistant' ? (
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm, remarkBreaks]}
                      components={{
                        p: ({ children }) => (
                          <p className="text-sm leading-relaxed break-words whitespace-pre-wrap">
                            {children}
                          </p>
                        ),
                        li: ({ children }) => (
                          <li className="text-sm leading-relaxed break-words whitespace-pre-wrap">
                            {children}
                          </li>
                        ),
                        code: ({ inline, className, children, ...props }) => {
                          const raw = String(children ?? '');
                          const codeText = raw.replace(/\n$/g, '');
                          const match = /language-([\w-]+)/.exec(className || '');
                          const language = match?.[1] || '';

                          if (inline) {
                            return (
                              <code
                                className="px-1.5 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-100 text-[0.85em]"
                                {...props}
                              >
                                {children}
                              </code>
                            );
                          }

                          return (
                            <div className="my-2 overflow-hidden rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-950">
                              <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-slate-800/60">
                                <div className="text-xs text-slate-300">
                                  {language ? language : 'code'}
                                </div>
                                <button
                                  type="button"
                                  onClick={() => copyText(codeText)}
                                  className="text-xs px-2 py-1 rounded-md bg-white/10 hover:bg-white/15 text-slate-100 transition-colors duration-200"
                                  title="Copy"
                                >
                                  Copy
                                </button>
                              </div>
                              <SyntaxHighlighter
                                language={language || 'text'}
                                style={oneDark}
                                customStyle={{
                                  margin: 0,
                                  background: 'transparent',
                                  padding: '12px',
                                  fontSize: '0.85rem',
                                  lineHeight: 1.5,
                                }}
                                codeTagProps={{ style: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace' } }}
                              >
                                {codeText}
                              </SyntaxHighlighter>
                            </div>
                          );
                        },
                      }}
                    >
                      {extractAssistantAnswer(message.content)}
                    </ReactMarkdown>
                  ) : (
                    <div className="text-sm leading-relaxed break-words whitespace-pre-wrap">
                      {message.content}
                    </div>
                  )}
                </div>
                {message.role === 'user' && (
                  <div className="w-8 h-8 bg-slate-800 rounded-lg flex items-center justify-center flex-shrink-0">
                    <User className="w-5 h-5 text-white" />
                  </div>
                )}
              </div>
            ))}
            {isLoading && (
              <div className="flex gap-3 justify-start">
                <div className="w-8 h-8 bg-gradient-to-br from-emerald-400 to-teal-500 rounded-lg flex items-center justify-center flex-shrink-0">
                  <Bot className="w-5 h-5 text-white" />
                </div>
                <div className="px-4 py-3 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800">
                  <div className="flex gap-1">
                    <div className="w-2 h-2 bg-slate-400 dark:bg-slate-500 rounded-full animate-bounce"></div>
                    <div className="w-2 h-2 bg-slate-400 dark:bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }}></div>
                    <div className="w-2 h-2 bg-slate-400 dark:bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </main>

      {toast && (
        <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50">
          <div className="bg-slate-900 text-white px-4 py-2 rounded-xl text-sm shadow-md">
            {toast}
          </div>
        </div>
      )}

      <footer className="bg-white/80 dark:bg-slate-950/80 backdrop-blur-sm border-t border-slate-200 dark:border-slate-800 px-6 py-4">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-center gap-3">
            <div className="flex-1 relative">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder={
                  googleConnected
                    ? 'Type your message...'
                    : 'Connect Google to send a message...'
                }
                rows={1}
                disabled={!googleConnected}
                className="w-full box-border px-4 py-3 pr-12 rounded-xl border border-slate-300 dark:border-slate-700 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 focus:outline-none resize-none text-slate-800 dark:text-slate-100 bg-white dark:bg-slate-900 placeholder-slate-400 transition-all disabled:bg-slate-50 dark:disabled:bg-slate-900/50 disabled:text-slate-500 disabled:cursor-not-allowed"
                style={{ minHeight: '48px', maxHeight: '120px' }}
              />
            </div>

            <button
              onClick={() => (isRecording ? stopRecording() : startRecording())}
              disabled={!googleConnected || isLoading || isTranscribing}
              className="w-12 h-12 border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200 rounded-xl flex items-center justify-center transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              title={isRecording ? 'Stop recording' : 'Start voice input'}
            >
              <Mic className={`w-5 h-5 ${isRecording ? 'text-rose-500' : ''}`} />
            </button>

            <button
              onClick={handleSend}
              disabled={!googleConnected || !input.trim() || isLoading}
              className="w-12 h-12 bg-gradient-to-br from-emerald-400 to-teal-500 hover:from-emerald-500 hover:to-teal-600 text-white rounded-xl flex items-center justify-center transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-sm hover:shadow-md"
            >
              <Send className="w-5 h-5" />
            </button>
          </div>
        </div>
      </footer>
    </div>
  );
}
