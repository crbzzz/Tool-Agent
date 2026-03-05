import { useEffect, useRef, useState } from 'react';
import { Send, Menu, Bot, User, Mic, Paperclip } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';

type MessageKind = 'text' | 'file';

type PendingUpload = {
  file_id: string;
  filename: string;
  size_bytes?: number;
  mime_type?: string;
};

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  apiContent?: string;
  kind?: MessageKind;
  fileName?: string;
  timestamp: Date;
}

interface ChatInterfaceProps {
  onMenuClick: () => void;
  resetCounter: number;
  chatId: string | null;
  initialMessages: Message[];
  onChatIdChange: (chatId: string | null) => void;
  onChatActivity?: () => void;
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
  chatId,
  initialMessages,
  onChatIdChange,
  onChatActivity,
}: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);

  const [isUploadingDocument, setIsUploadingDocument] = useState(false);
  const [pendingUploads, setPendingUploads] = useState<PendingUpload[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const dragDepthRef = useRef(0);
  const [isDraggingFile, setIsDraggingFile] = useState(false);

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
    setMessages(Array.isArray(initialMessages) ? initialMessages : []);
    setInput('');
    setIsLoading(false);
  }, [initialMessages]);

  useEffect(() => {
    // Important: when the backend returns a new session_id on the first message,
    // the parent updates chatId. We should not wipe the in-flight local messages.
    setSessionId(chatId || null);
  }, [chatId]);

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

  const sendMessage = async (
    content: string,
    opts?: { displayContent?: string; kind?: MessageKind; fileName?: string }
  ): Promise<boolean> => {
    const text = (content || '').trim();
    if (!text || isLoading) return false;

    const authed = await isAuthenticated();
    if (!authed) {
      showToast('Please sign in in Settings to send a message.');
      return false;
    }

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: typeof opts?.displayContent === 'string' ? opts.displayContent : text,
      apiContent: text,
      kind: opts?.kind,
      fileName: opts?.fileName,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);

    try {
      const r = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMessage.apiContent ?? userMessage.content, session_id: sessionId || chatId }),
      });

      if (!r.ok) {
        const text = await r.text();
        throw new Error(text || `HTTP ${r.status}`);
      }

      const data = (await r.json()) as ChatResponse;
      if (typeof data.session_id === 'string' && data.session_id.trim()) {
        setSessionId(data.session_id);
        if (data.session_id !== sessionId) onChatIdChange(data.session_id);
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

    return true;
  };

  const handleSend = async () => {
    const note = input.trim();

    const attachmentsText =
      pendingUploads.length > 0
        ? `Attachments (file_id):\n${pendingUploads
            .map((u) => `- ${u.file_id} (${u.filename})`)
            .join('\n')}`
        : '';

    const content = [attachmentsText, note].filter(Boolean).join('\n\n').trim();
    if (!content) return;

    const ok = await sendMessage(content);
    if (ok) {
      setInput('');
      setPendingUploads([]);
      onChatActivity?.();
    }
  };

  const uploadAttachment = async (file: File) => {
    const form = new FormData();
    form.append('file', file, file.name);

    const r = await fetch('/uploads', { method: 'POST', body: form });
    if (!r.ok) {
      const text = await r.text();
      throw new Error(text || `HTTP ${r.status}`);
    }
    const data = (await r.json()) as {
      ok?: boolean;
      data?: { file_id?: string; filename?: string; size_bytes?: number; mime_type?: string };
      error?: string | null;
    };

    const fid = data?.data?.file_id;
    const filename = data?.data?.filename;
    if (!fid || !filename) throw new Error(data?.error || 'Upload failed');

    return data.data;
  };

  const attachFile = async (file: File) => {
    if (isLoading || isUploadingDocument) return;

    const authed = await isAuthenticated();
    if (!authed) {
      showToast('Please sign in in Settings to send a message.');
      return;
    }

    setIsUploadingDocument(true);
    try {
      const uploaded = await uploadAttachment(file);
      const file_id = uploaded?.file_id || '';
      const filename = uploaded?.filename || file.name || 'document';
      if (!file_id) throw new Error('Upload failed');

      setPendingUploads((prev) => {
        if (prev.some((p) => p.file_id === file_id)) return prev;
        return [
          ...prev,
          {
            file_id,
            filename,
            size_bytes: uploaded?.size_bytes,
            mime_type: uploaded?.mime_type,
          },
        ];
      });

      showToast(`Attached: ${filename}`);
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e));
    } finally {
      setIsUploadingDocument(false);
      dragDepthRef.current = 0;
      setIsDraggingFile(false);
    }
  };

  const eventHasFiles = (dt: DataTransfer | null) => {
    if (!dt) return false;
    if (dt.files && dt.files.length > 0) return true;
    if (dt.items) {
      for (let i = 0; i < dt.items.length; i++) {
        if (dt.items[i]?.kind === 'file') return true;
      }
    }
    return false;
  };

  const startRecording = async () => {
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

  const isAuthenticated = async (): Promise<boolean> => {
    try {
      const r = await fetch('/auth/status', { credentials: 'same-origin' });
      if (!r.ok) return false;
      const data = (await r.json()) as { signed_in?: unknown; authenticated?: unknown; user?: unknown };
      const signedIn = Boolean(data?.signed_in ?? data?.authenticated);
      return Boolean(signedIn && data?.user);
    } catch {
      return false;
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

        <div className="flex items-center gap-2" />
      </header>

      <main
        className="flex-1 overflow-y-auto px-6 py-8 relative"
        onDragEnter={(e) => {
          if (!eventHasFiles(e.dataTransfer)) return;
          e.preventDefault();
          dragDepthRef.current += 1;
          setIsDraggingFile(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
          if (dragDepthRef.current === 0) setIsDraggingFile(false);
        }}
        onDragOver={(e) => {
          if (!eventHasFiles(e.dataTransfer)) return;
          e.preventDefault();
        }}
        onDrop={(e) => {
          if (!eventHasFiles(e.dataTransfer)) return;
          e.preventDefault();
          dragDepthRef.current = 0;
          setIsDraggingFile(false);

          const f = e.dataTransfer.files?.[0];
          if (f) attachFile(f);
        }}
      >
        {isDraggingFile && (
          <div className="absolute inset-0 flex items-center justify-center z-40 pointer-events-none">
            <div className="w-full max-w-lg mx-auto">
              <div className="rounded-2xl border-2 border-dashed border-emerald-400/70 bg-white/70 dark:bg-slate-950/70 backdrop-blur-sm px-6 py-8 text-center transition-all duration-150 ease-out scale-100 opacity-100">
                <div className="text-base font-semibold text-slate-900 dark:text-slate-100">
                  Drop your file to attach
                </div>
                <div className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                  The document will be uploaded and attached.
                </div>
              </div>
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

                          const trimmed = codeText.trim();
                          const isSingleLine = !codeText.includes('\n');
                          const isTinyBlock = !inline && !language && isSingleLine && trimmed.length > 0 && trimmed.length <= 80;

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

                          if (isTinyBlock) {
                            return (
                              <div className="my-1">
                                <code
                                  className="px-1.5 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-100 text-[0.85em] whitespace-pre-wrap"
                                  {...props}
                                >
                                  {trimmed}
                                </code>
                              </div>
                            );
                          }

                          if (!trimmed) return null;

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
                      {message.kind === 'file' ? (
                        <div className="flex items-center justify-center">
                          <Paperclip className="w-5 h-5" aria-hidden="true" />
                          <span className="sr-only">
                            Fichier envoyé{message.fileName ? `: ${message.fileName}` : ''}
                          </span>
                        </div>
                      ) : (
                        message.content
                      )}
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
          {pendingUploads.length > 0 && (
            <div className="mb-3 flex flex-wrap gap-2">
              {pendingUploads.map((u) => (
                <div
                  key={u.file_id}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-xs text-slate-700 dark:text-slate-200"
                  title={u.file_id}
                >
                  <Paperclip className="w-3.5 h-3.5" aria-hidden="true" />
                  <span className="max-w-[220px] truncate">{u.filename}</span>
                  <button
                    type="button"
                    onClick={() => setPendingUploads((prev) => prev.filter((p) => p.file_id !== u.file_id))}
                    className="text-slate-500 hover:text-slate-800 dark:hover:text-slate-100 transition-colors"
                    aria-label={`Remove ${u.filename}`}
                    title="Remove"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}
          <div className="flex items-center gap-3">
            <div className="flex-1 relative">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder={'Type your message...'}
                rows={1}
                className="w-full box-border px-4 py-3 pr-12 rounded-xl border border-slate-300 dark:border-slate-700 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 focus:outline-none resize-none text-slate-800 dark:text-slate-100 bg-white dark:bg-slate-900 placeholder-slate-400 transition-all disabled:bg-slate-50 dark:disabled:bg-slate-900/50 disabled:text-slate-500 disabled:cursor-not-allowed"
                style={{ minHeight: '48px', maxHeight: '120px' }}
              />
            </div>

            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                // Reset so selecting the same file twice triggers change.
                e.currentTarget.value = '';
                if (f) attachFile(f);
              }}
            />

            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isLoading || isUploadingDocument}
              className="w-12 h-12 border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200 rounded-xl flex items-center justify-center transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              title="Attach a file"
            >
              <Paperclip className="w-5 h-5" />
            </button>

            <button
              onClick={() => (isRecording ? stopRecording() : startRecording())}
              disabled={isLoading || isTranscribing || isUploadingDocument}
              className="w-12 h-12 border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200 rounded-xl flex items-center justify-center transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              title={isRecording ? 'Stop recording' : 'Start voice input'}
            >
              <Mic className={`w-5 h-5 ${isRecording ? 'text-rose-500' : ''}`} />
            </button>

            <button
              onClick={handleSend}
              disabled={(!input.trim() && pendingUploads.length === 0) || isLoading || isUploadingDocument}
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
