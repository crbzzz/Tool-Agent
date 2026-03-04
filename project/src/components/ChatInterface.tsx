import { useEffect, useRef, useState } from 'react';
import { Send, Menu, Bot, User, Mic, Square } from 'lucide-react';

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
  const [isOnline, setIsOnline] = useState<boolean>(true);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    setMessages([]);
    setInput('');
    setIsLoading(false);
    setSessionId(null);
    setIsRecording(false);
    setIsTranscribing(false);
    try {
      recorderRef.current?.stop();
    } catch {
      // ignore
    }
    recorderRef.current = null;
    chunksRef.current = [];
    try {
      streamRef.current?.getTracks().forEach((t) => t.stop());
    } catch {
      // ignore
    }
    streamRef.current = null;
  }, [resetCounter]);

  const getSelectedAudioInputDeviceId = () => {
    try {
      return localStorage.getItem('bart_ai.audioInputDeviceId') || '';
    } catch {
      return '';
    }
  };

  const startRecording = async () => {
    if (!googleConnected) return;
    if (isLoading || isTranscribing) return;
    if (isRecording) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      setMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: 'Error: audio capture is not supported in this environment.',
          timestamp: new Date(),
        },
      ]);
      return;
    }

    const deviceId = getSelectedAudioInputDeviceId();
    const constraints: MediaStreamConstraints = {
      audio: deviceId ? { deviceId: { exact: deviceId } } : true,
      video: false,
    };

    const stream = await navigator.mediaDevices.getUserMedia(constraints);
    streamRef.current = stream;

    const preferredTypes = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/ogg;codecs=opus',
      'audio/ogg',
    ];
    const mimeType = preferredTypes.find((t) => MediaRecorder.isTypeSupported(t)) || '';

    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    chunksRef.current = [];
    recorderRef.current = recorder;

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
    };

    recorder.onstop = async () => {
      setIsRecording(false);
      setIsTranscribing(true);
      try {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        chunksRef.current = [];

        const fd = new FormData();
        const ext = (blob.type || '').includes('ogg') ? 'ogg' : 'webm';
        fd.append('file', blob, `recording.${ext}`);

        const r = await fetch('/voice/transcribe', { method: 'POST', body: fd });
        if (!r.ok) throw new Error(await r.text());
        const data = (await r.json()) as { text?: string };
        const text = (data.text || '').trim();
        if (text) {
          setInput((prev) => {
            if (!prev.trim()) return text;
            return prev.replace(/\s+$/g, '') + ' ' + text;
          });
        }
        setIsOnline(true);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          {
            id: (Date.now() + 1).toString(),
            role: 'assistant',
            content: `Error: ${err instanceof Error ? err.message : String(err)}`,
            timestamp: new Date(),
          },
        ]);
        setIsOnline(false);
      } finally {
        setIsTranscribing(false);
        try {
          streamRef.current?.getTracks().forEach((t) => t.stop());
        } catch {
          // ignore
        }
        streamRef.current = null;
        recorderRef.current = null;
      }
    };

    recorder.start();
    setIsRecording(true);
  };

  const stopRecording = () => {
    try {
      recorderRef.current?.stop();
    } catch {
      setIsRecording(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch('/health');
        if (!cancelled) setIsOnline(r.ok);
      } catch {
        if (!cancelled) setIsOnline(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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
      setIsOnline(true);
    } catch (err) {
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: `Error: ${err instanceof Error ? err.message : String(err)}`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMessage]);
      setIsOnline(false);
    } finally {
      setIsLoading(false);
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
      <header className="bg-white/80 backdrop-blur-sm border-b border-slate-200 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={onMenuClick}
            className="p-2 hover:bg-slate-100 rounded-lg transition-colors"
          >
            <Menu className="w-5 h-5 text-slate-600" />
          </button>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-gradient-to-br from-emerald-400 to-teal-500 rounded-lg flex items-center justify-center">
              <Bot className="w-5 h-5 text-white" />
            </div>
            <h1 className="text-xl font-semibold text-slate-800">Bart AI</h1>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full ${isOnline ? 'bg-emerald-400' : 'bg-rose-400'} ${
              isOnline ? 'animate-pulse' : ''
            }`}
          ></div>
          <span className="text-sm text-slate-600">{isOnline ? 'Active' : 'Offline'}</span>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-6 py-8">
        {!googleConnected && (
          <div className="max-w-3xl mx-auto mb-6">
            <div className="bg-amber-50 border border-amber-200 text-amber-900 rounded-2xl px-4 py-3 flex items-center justify-between gap-3">
              <div className="text-sm">
                Connexion Google requise pour utiliser le chat.
              </div>
              <button
                onClick={onOpenSettings}
                className="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-900 text-white text-sm transition-colors"
              >
                Se connecter
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
              <h2 className="text-2xl font-semibold text-slate-800 mb-2">
                Welcome to Bart AI
              </h2>
              <p className="text-slate-600">
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
                      : 'bg-white border border-slate-200 text-slate-800'
                  }`}
                >
                  <div
                    className={`text-sm leading-relaxed break-words ${
                      message.role === 'assistant' ? 'whitespace-pre-wrap' : 'whitespace-pre-wrap'
                    }`}
                  >
                    {message.role === 'assistant'
                      ? extractAssistantAnswer(message.content)
                      : message.content}
                  </div>
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
                <div className="px-4 py-3 rounded-2xl bg-white border border-slate-200">
                  <div className="flex gap-1">
                    <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce"></div>
                    <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }}></div>
                    <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </main>

      <footer className="bg-white/80 backdrop-blur-sm border-t border-slate-200 px-6 py-4">
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
                    : 'Connectez-vous à Google pour envoyer un message...'
                }
                rows={1}
                disabled={!googleConnected}
                className="w-full px-4 py-3 pr-12 rounded-xl border border-slate-300 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 focus:outline-none resize-none text-slate-800 placeholder-slate-400 transition-all disabled:bg-slate-50 disabled:text-slate-500 disabled:cursor-not-allowed"
                style={{ minHeight: '48px', maxHeight: '120px' }}
              />
            </div>

            <button
              onClick={isRecording ? stopRecording : () => startRecording().catch(() => undefined)}
              disabled={!googleConnected || isLoading || isTranscribing}
              className="w-12 h-12 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 flex items-center justify-center transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title={isRecording ? 'Stop' : 'Transcrire (micro)'}
            >
              {isRecording ? (
                <Square className="w-5 h-5" />
              ) : (
                <Mic className="w-5 h-5" />
              )}
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
