import { useState, useRef, useEffect, useCallback } from 'react'
import './App.css'
import {
  SignedIn,
  SignedOut,
  SignInButton,
  SignOutButton,
  UserButton,
  useUser
} from '@clerk/clerk-react'

const API_BASE = 'http://localhost:5001/api'

const logErrorToBackend = async (message, stack = null, additionalData = null) => {
  try {
    await fetch(`${API_BASE}/log_error`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source: 'frontend',
        message: message,
        stack_trace: stack,
        additional_data: additionalData
      })
    });
  } catch (err) {
    console.error("Failed to log error to backend:", err);
  }
};

const formatReference = (data) => {
  if (!data) return "";

  let formatted = `PROBLEM DESCRIPTION:\n${data.problem}\n\n`;

  if (data.solution) {
    formatted += `SOLUTION SUMMARY:\n${data.solution}\n\n`;
  }

  if (data.steps && Array.isArray(data.steps)) {
    formatted += `REFERENCE IMPLEMENTATION STEPS:\n`;
    data.steps.forEach(step => {
      formatted += `Step ${step.step_number}: ${step.description}\n`;
      formatted += `Code:\n${step.code}\n\n`;
    });
  }

  return formatted;
};

const extractCodeCells = (steps) => {
  return steps
    .map((step) => ({
      stepNumber: step.number,
      code: step.code || '',
      output: step.output || '',
      error: step.error || '',
      language: step.language || 'python',
      plots: step.plots || []
    }))
    .filter(cell => cell.code || cell.output || cell.error || (cell.plots && cell.plots.length > 0))
}

const truncateText = (text, maxLength = 100) => {
  if (!text) return ''
  return text.length > maxLength ? text.substring(0, maxLength) + '...' : text
}

const ConfirmationModal = ({ isOpen, onClose, onConfirm, title, message }) => {
  if (!isOpen) return null;
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <div className="modal-header">{title}</div>
        <div className="modal-body">{message}</div>
        <div className="modal-actions">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-danger" onClick={onConfirm}>Delete</button>
        </div>
      </div>
    </div>
  );
};

const Sidebar = ({
  sessions,
  currentSessionId,
  onSelectSession,
  onCreateSession,
  onDeleteSession,
  isLoading,
  isOpen
}) => {
  if (!isOpen) return null;
  return (
    <div className="sidebar" style={{ display: isOpen ? 'flex' : 'none' }}>
      <div className="sidebar-header">
        <button
          className="new-chat-btn"
          onClick={onCreateSession}
          disabled={isLoading}
          style={{ opacity: isLoading ? 0.5 : 1, cursor: isLoading ? 'not-allowed' : 'pointer' }}
        >
          <div className="plus-icon">+</div>
          <span>New Chat</span>
        </button>
      </div>

      <div className="sessions-list">
        {sessions.map(session => (
          <div
            key={session.id}
            className={`session-item ${currentSessionId === session.id ? 'active' : ''}`}
            onClick={() => !isLoading && onSelectSession(session.id)}
            style={{
              opacity: isLoading && currentSessionId !== session.id ? 0.5 : 1,
              cursor: isLoading ? 'not-allowed' : 'pointer',
              pointerEvents: isLoading ? 'none' : 'auto'
            }}
          >
            <div className="message-icon">💬</div>
            <div className="session-title">
              {session.title || 'New Chat'}
            </div>
            <button
              className="delete-session-btn"
              onClick={(e) => {
                e.stopPropagation();
                if (!isLoading) onDeleteSession(session.id);
              }}
              disabled={isLoading}
              title="Delete Chat"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
};

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [streamingContent, setStreamingContent] = useState(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState(null)
  const [fileContext, setFileContext] = useState(null)
  const [uploadedFileName, setUploadedFileName] = useState(null)
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [sessionToDelete, setSessionToDelete] = useState(null);

  const [sessions, setSessions] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(null);

  const { isLoaded, isSignedIn, user } = useUser()
  const messagesEndRef = useRef(null)
  const abortControllerRef = useRef(null)
  const fileInputRef = useRef(null)
  const textareaRef = useRef(null)

  const streamingStepsRef = useRef(null);
  const streamingCodeRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: "end" })
  }, [messages])

  useEffect(() => {
    if (streamingContent) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'auto', block: "end" })
    }
  }, [streamingContent])

  useEffect(() => {
    if (streamingContent) {
      requestAnimationFrame(() => {
        if (streamingStepsRef.current) {
          streamingStepsRef.current.scrollTop = streamingStepsRef.current.scrollHeight;
        }
        if (streamingCodeRef.current) {
          streamingCodeRef.current.scrollTop = streamingCodeRef.current.scrollHeight;
        }
      });
    }
  }, [streamingContent]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [input]);

  const fetchSessions = useCallback(async (userId) => {
    try {
      const res = await fetch(`${API_BASE}/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
      });
      if (res.ok) {
        const data = await res.json();
        const sessionsArr = Object.entries(data.sessions || {}).map(([id, meta]) => ({
          id,
          ...meta
        })).sort((a, b) => new Date(b.last_updated) - new Date(a.last_updated));

        setSessions(sessionsArr);
        fetchSessionMessages(userId, sessionsArr[0].id);
        return sessionsArr;
      }
    } catch (e) {
      console.error("Failed to fetch sessions", e);
    }
    return [];
    body: formData,
      });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Upload failed: ${errorText}`);
  }

  const data = await response.json();
  const summary = data.summary || `File '${file.name}' uploaded successfully.`;

  setFileContext(summary);
  setUploadedFileName(file.name);
  // Removed chat message for upload as per request

} catch (error) {
  console.error("Upload error:", error);
  logErrorToBackend(`Upload Error: ${error.message}`, error.stack, { fileName: file.name });
  setMessages(prev => [...prev, {
    role: 'assistant',
    type: 'text',
    content: `❌ Error uploading file: ${error.message}`
  }]);
} finally {
  setIsUploading(false);
}
  };

const onDragOver = useCallback((e) => {
  e.preventDefault();
  e.stopPropagation();
  if (!isLoading && !isUploading) {
    setIsDragging(true);
  }
}, [isLoading, isUploading]);

const onDragLeave = useCallback((e) => {
  e.preventDefault();
  e.stopPropagation();
  setIsDragging(false);
}, []);

const fetchSessionMessages = useCallback(async (userId, sessionId) => {
  setHistoryLoading(true);
  setHistoryError(null);
  try {
    const res = await fetch(`${API_BASE}/chathistory`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, session_id: sessionId })
    });

    if (!res.ok) throw new Error("Failed to load history");

    const data = await res.json();
    const formatted = data.history.map(msg => {
      let parsedContent = msg.content;
      let type = 'text';
      let steps = [];

      if (msg.role === 'assistant') {
        try {
          if (msg.content && (msg.content.startsWith('{') || msg.content.startsWith('['))) {
            const parsed = JSON.parse(msg.content);
            if (parsed.type === 'steps' || parsed.steps) {
              type = 'steps';
              steps = parsed.steps || [];
              parsedContent = "";
            }
          }
        } catch (e) { }
      }

      if (type === 'steps') {
        return {
          role: 'assistant',
          type: 'steps',
          title: 'Solution Steps',
          summary: msg.summary || '',
          steps: steps.map((step, idx) => ({
            number: step.step_id || idx + 1,
            title: `Step ${step.step_id || idx + 1}`,
            description: step.description || '',
            code: step.code || '',
            language: 'python',
            output: step.output || '',
            error: step.error || '',
            plots: step.plots || []
          }))
        };
      }

      return {
        role: msg.role,
        type: 'text',
        content: parsedContent
      };
    });

    setMessages(formatted);
  } catch (e) {
    setHistoryError(e.message);
    setMessages([]);
  } finally {
    setHistoryLoading(false);
  }
}, []);

const saveMessageToHistory = async (userId, sessionId, role, content) => {
  try {
    await fetch(`${API_BASE}/chathistory/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId,
        session_id: sessionId,
        role,
        content
      })
    });
    fetchSessions(userId);
  } catch (err) {
    logErrorToBackend(`History Fetch Error: ${err.message}`, err.stack, { userId: userUID });
    setHistoryError(err.message)
  } finally {
    setHistoryLoading(false)
  }
};

useEffect(() => {
  if (isSignedIn && user?.id) {
    fetchSessions(user.id).then(sessions => {
      if (sessions.length > 0 && !currentSessionId) {

      }
    });
  } else {
    setSessions([]);
    setMessages([]);
  }
}, [isSignedIn, user?.id, fetchSessions]);

useEffect(() => {
  if (isSignedIn && user?.id && currentSessionId) {
    fetchSessionMessages(user.id, currentSessionId);
  } else {
    setMessages([]);
  }
}, [currentSessionId, isSignedIn, user?.id, fetchSessionMessages]);

const handleCreateSession = () => {
  setCurrentSessionId(null);
  setMessages([]);
  setFileContext(null);
  setUploadedFileName(null);
  if (fileInputRef.current) fileInputRef.current.value = '';
};

const handleDeleteSession = (sessionId) => {
  setSessionToDelete(sessionId);
  setIsDeleteModalOpen(true);
};

const confirmDeleteSession = async () => {
  if (!user?.id || !sessionToDelete) return;

  try {
    await fetch(`${API_BASE}/chathistory/clear`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: user.id,
        session_id: sessionToDelete
      })
    });

    if (currentSessionId === sessionToDelete) {
      setCurrentSessionId(null);
      setMessages([]);
    }
    fetchSessions(user.id);
  } catch (e) {
    console.error("Error deleting session", e);
  } finally {
    setIsDeleteModalOpen(false);
    setSessionToDelete(null);
  }
};

// --- FILE UPLOAD ---
const handleFileUpload = async (file) => {
  if (!file || !user?.id) return;
  setIsUploading(true);
  const formData = new FormData();
  formData.append('file', file);
  formData.append('user_id', user.id);

  try {
    const response = await fetch(`${API_BASE}/upload`, {
      method: 'POST',
      body: formData,
    });
    if (!response.ok) {
      const txt = await response.text();
      throw new Error(txt);
    }
    const data = await response.json();
    const summary = data.summary || `File '${file.name}' uploaded successfully.`;
    setFileContext(summary);
    setUploadedFileName(file.name);
  } catch (error) {
    setMessages(prev => [...prev, {
      role: 'assistant',
      type: 'text',
      content: `❌ Error uploading file: ${error.message}`
    }]);
  } finally {
    setIsUploading(false);
  }
};

const onDragOver = useCallback((e) => {
  e.preventDefault(); e.stopPropagation();
  if (!isLoading && !isUploading) setIsDragging(true);
}, [isLoading, isUploading]);
const onDragLeave = useCallback((e) => {
  e.preventDefault(); e.stopPropagation();
  setIsDragging(false);
}, []);
const onDrop = useCallback((e) => {
  e.preventDefault(); e.stopPropagation();
  setIsDragging(false);
  if (e.dataTransfer.files?.[0]) handleFileUpload(e.dataTransfer.files[0]);
}, [user?.id]);

const parseSSE = (text) => {
  const events = []
  const lines = text.split('\n')
  let currentEvent = {}
  for (const line of lines) {
    if (line.startsWith('event: ')) {
      currentEvent.event = line.slice(7)
    } else if (line.startsWith('data: ')) {
      try {
        currentEvent.data = JSON.parse(line.slice(6))
        events.push({ ...currentEvent })
        currentEvent = {}
      } catch (e) { }
    }
  }
  return events
}

const handleSend = async () => {
  if (!input.trim() || isLoading) return;
  if (!isSignedIn || !user?.id) {
    alert('Please sign in to continue.');
    return;
  }

  const userMessageText = input.trim();

  let targetSessionId = currentSessionId;
  if (!targetSessionId) {
    try {
      const createRes = await fetch(`${API_BASE}/sessions/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: user.id, title: truncateText(userMessageText, 30) })
      });
      if (createRes.ok) {
        const sData = await createRes.json();
        targetSessionId = sData.session_id;
        setCurrentSessionId(targetSessionId);
        fetchSessions(user.id);
      } else {
        throw new Error("Could not create session");
      }
    } catch (e) {
      alert("Error creating chat session.");
      return;
    }
  }

  const userMessage = { role: 'user', content: userMessageText };
  setMessages(prev => [...prev, userMessage]);
  setInput('');

  let finalQuery = userMessageText;
  if (fileContext) {
    finalQuery = `CONTEXT FROM UPLOADED FILE:\n${fileContext}\n\nUSER QUERY: ${finalQuery}`;
  }
  setFileContext(null);
  setUploadedFileName(null);
  if (textareaRef.current) textareaRef.current.style.height = 'auto';

  saveMessageToHistory(user.id, targetSessionId, 'user', finalQuery);

  setIsLoading(true);
  setStreamingContent({
    steps: [],
    currentStep: null,
    currentTokens: '',
    status: 'retrieving'
  });
  abortControllerRef.current = new AbortController();

  try {
    const retrieveRes = await fetch(`${API_BASE}/retrieve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: userMessage.content, top_n: 2 }),
      signal: abortControllerRef.current.signal
    });

    let first = "", second = "";
    if (retrieveRes.ok) {
      const probs = await retrieveRes.json();
      first = formatReference(probs[0]);
      second = formatReference(probs[1]);
    }

    setStreamingContent(prev => ({ ...prev, status: 'solving' }));

    const response = await fetch(`${API_BASE}/solve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        problem: first,
        second_problem: second,
        user_query: finalQuery,
        user_id: user.id
      }),
      signal: abortControllerRef.current.signal
    });

    if (!response.ok) throw new Error('Failed to get solution');

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let finalExecutionSteps = [];

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = parseSSE(buffer);
      const lastEventEnd = buffer.lastIndexOf('\n\n');
      if (lastEventEnd !== -1) buffer = buffer.slice(lastEventEnd + 2);

      for (const event of events) {
        if (event.event === 'done') {
          finalExecutionSteps = event.data.steps || [];
        }
        handleSSEEvent(event);
      }
    }

    if (finalExecutionSteps.length > 0) {
      const payload = JSON.stringify({
        type: 'steps',
        steps: finalExecutionSteps
      });
      await saveMessageToHistory(user.id, targetSessionId, 'assistant', payload);
    }

  } catch (error) {
    if (error.name !== 'AbortError') {
      const errMsg = "Error: " + error.message;
      setMessages(prev => [...prev, { role: 'assistant', type: 'text', content: errMsg }]);
    }
  } catch (error) {
    if (error.name === 'AbortError') {
      return;
    }
    logErrorToBackend(`Chat Error: ${error.message}`, error.stack, { userQuery: input });

    setStreamingContent(null);
    const errorMessage = {
      role: 'assistant',
      type: 'text',
      content: `Sorry, I ran into a problem: ${error.message}. Please try again.`
    };
    setMessages(prev => [...prev, errorMessage]);
  } finally {
    setIsLoading(false);
    abortControllerRef.current = null;
    setStreamingContent(null);
    setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: "end" });
    }, 100);
  }
};

const handleSSEEvent = (event) => {
  switch (event.event) {
    case 'step_start':
      setStreamingContent(prev => ({
        ...prev,
        currentStep: event.data.step_number,
        currentTokens: '',
        status: 'generating'
      }));
      break;
    case 'token':
      setStreamingContent(prev => ({
        ...prev,
        currentTokens: (prev.currentTokens || '') + (event.data.text || '')
      }));
      break;
    case 'generation_complete':
      setStreamingContent(prev => ({
        ...prev,
        status: 'executing',
        currentTokens: JSON.stringify(event.data.step_data, null, 2)
      }));
      break;
    case 'executing':
      setStreamingContent(prev => ({
        ...prev,
        status: 'executing'
      }));
      break;
    case 'step_complete':
      const formattedStep = {
        number: event.data.step.step_id,
        title: `Step ${event.data.step.step_id}`,
        description: event.data.step.description || '',
        code: event.data.step.code || '',
        language: 'python',
        output: event.data.step.output || '',
        error: event.data.step.error || '',
        plots: event.data.step.plots || [],
      };
      setStreamingContent(prev => {
        const exists = prev.steps.some(s => s.number === formattedStep.number);
        if (exists) return { ...prev, currentStep: null, currentTokens: '', status: 'waiting' };
        return {
          ...prev,
          steps: [...prev.steps, formattedStep],
          currentStep: null,
          currentTokens: '',
          status: 'waiting'
        };
      });
      break;
    case 'done':
      setStreamingContent(null);
      setIsLoading(false);
      break;
    case 'error':
      setStreamingContent(null);
      logErrorToBackend(`SSE Error Event: ${event.data.message}`, null, { raw: event.data });
      setMessages(prev => [...prev, { role: 'assistant', type: 'text', content: `Error: ${event.data.message}` }]);
      setIsLoading(false);
      break;
  }
};

const renderJupyterCell = (cell, idx) => (
  <div key={idx} className="notebook-cell">
    {cell.code && (
      <div className="cell-wrapper">
        <div className="cell-header-badge">Input [{cell.stepNumber}]</div>
        <pre className="code-display"><code>{cell.code}</code></pre>
      </div>
    )}
    {(cell.output || cell.error) && (
      <div className={`output-display ${cell.error ? 'error-display' : ''}`}>
        {cell.error ? <strong>Error: </strong> : null}
        {cell.output || cell.error}
      </div>
    )}
    {cell.plots && cell.plots.length > 0 && (
      <div className="plot-container">
        {cell.plots.map((plot, plotIdx) => (
          <img key={plotIdx} src={`data:image/png;base64,${plot}`} alt={`Plot ${plotIdx + 1}`} />
        ))}
      </div>
    )}
  </div>
)

const renderStreamingContent = () => {
  if (!streamingContent) return null;
  const codeCells = extractCodeCells(streamingContent.steps);

  return (
    <div className="message assistant">
      <div className="message-content">
        <div className="two-column-layout">
          <div className="steps-column">
            <div className="steps-header">
              <div className="steps-title">
                <div className="pulse-ring"></div>
                <span>
                  {streamingContent.status === 'retrieving' && 'ANALYZING...'}
                  {streamingContent.status === 'generating' && 'GENERATING STEPS...'}
                  {streamingContent.status === 'executing' && 'RUNNING CODE...'}
                  {streamingContent.status === 'waiting' && 'PROCESSING...'}
                </span>
              </div>
            </div>

            <div className="steps-list" ref={streamingStepsRef} style={{ scrollBehavior: 'smooth' }}>
              {streamingContent.steps.map((step) => (
                <div key={step.number} className="step-timeline-item complete">
                  <div className="step-marker-wrapper"><div className="step-marker">✓</div></div>
                  <div className="step-card">
                    <div className="step-card-title">{step.title}</div>
                    {step.description && <div className="step-card-text">{step.description}</div>}
                    {(step.output || step.error) && (
                      <div className="step-output" style={{ marginTop: '12px', background: '#0f172a', padding: '12px', borderRadius: '8px', fontSize: '0.85rem', fontFamily: 'monospace', color: step.error ? '#fca5a5' : '#4ade80', border: '1px solid rgba(255,255,255,0.1)', whiteSpace: 'pre-wrap', maxHeight: '200px', overflowY: 'auto' }}>
                        {step.error ? `Error: ${step.error}` : `> ${step.output}`}
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {streamingContent.currentStep && (
                <div className="step-timeline-item active">
                  <div className="step-marker-wrapper">
                    <div className="step-marker">{streamingContent.currentStep}</div>
                  </div>
                  <div className="step-card">
                    <div className="step-card-title">Thinking...</div>
                    <div className="step-card-text">
                      {streamingContent.currentTokens && (
                        <pre className="token-stream" style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace' }}>
                          {streamingContent.currentTokens}
                          <span className="cursor">|</span>
                        </pre>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="code-column">
            <div className="jupyter-header">
              <div className="window-controls">
                <div className="window-dot dot-red"></div>
                <div className="window-dot dot-yellow"></div>
                <div className="window-dot dot-green"></div>
              </div>
              <div className="jupyter-title-text">execution-environment</div>
            </div>

            <div className="jupyter-notebook" ref={streamingCodeRef} style={{ scrollBehavior: 'smooth' }}>
              {codeCells.length > 0 ? (
                codeCells.map(renderJupyterCell)
              ) : (
                <div style={{ color: 'var(--text-muted)', textAlign: 'center', marginTop: '60px', opacity: 0.7, fontStyle: 'italic' }}>
                     // Terminals ready. Waiting for input...
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

const renderMessageContent = (message) => {
  if (message.role === 'assistant' && message.type === 'steps' && message.steps?.length) {
    return renderAssistantSteps(message);
  }
  if (message.role === 'assistant') {
    return renderPlainText(message.content);
  }
  return renderUserMessage(message.content);
}

const renderAssistantSteps = (message) => {
  const codeCells = extractCodeCells(message.steps);
  return (
    <div className="assistant-message">
      {message.summary && (
        <div style={{ marginBottom: '32px', padding: '24px', background: 'rgba(51, 65, 85, 0.4)', borderRadius: '16px', border: '1px solid rgba(255,255,255,0.05)', maxWidth: '900px', margin: '0 auto 32px auto', backdropFilter: 'blur(5px)' }}>
          <strong style={{ color: 'var(--accent-primary)', display: 'block', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.1em', fontSize: '0.75rem' }}>Solution Summary</strong>
          <div style={{ lineHeight: '1.8', fontSize: '1.1rem', color: '#e2e8f0' }}>{message.summary}</div>
        </div>
      )}

      <div className="two-column-layout">
        <div className="steps-column">
          <div className="steps-header">
            <div className="steps-title">
              <span style={{ fontSize: '1.2rem' }}>🏁</span>
              <span>Solution Roadmap</span>
            </div>
          </div>

          <div className="steps-list">
            {message.steps.map((step, index) => {
              const isFinalSummary = index === message.steps.length - 1 && !step.code;
              return (
                <div
                  key={step.number}
                  className={`step-timeline-item ${isFinalSummary ? 'final complete' : 'complete'}`}
                >
                  <div className="step-marker-wrapper">
                    <div className="step-marker">{isFinalSummary ? '★' : step.number}</div>
                  </div>
                  <div className="step-card">
                    <div className="step-card-title">{isFinalSummary ? 'Conclusion' : step.title}</div>
                    {step.description && <div className="step-card-text">{step.description}</div>}
                    {(step.output || step.error) && !isFinalSummary && (
                      <div className="step-output" style={{ marginTop: '12px', background: '#0f172a', padding: '12px', borderRadius: '8px', fontSize: '0.85rem', fontFamily: 'monospace', color: step.error ? '#fca5a5' : '#4ade80', border: '1px solid rgba(255,255,255,0.1)', whiteSpace: 'pre-wrap', maxHeight: '200px', overflowY: 'auto' }}>
                        {step.error ? `Error: ${step.error}` : `> ${step.output}`}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="code-column">
          <div className="jupyter-header">
            <div className="window-controls">
              <div className="window-dot dot-red"></div>
              <div className="window-dot dot-yellow"></div>
              <div className="window-dot dot-green"></div>
            </div>
            <div className="jupyter-title-text">read-only-view</div>
          </div>
          <div className="jupyter-notebook">
            {codeCells.length > 0 ? (
              codeCells.map(renderJupyterCell)
            ) : (
              <div style={{ padding: '32px', color: 'var(--text-muted)', textAlign: 'center' }}>No code steps in this solution.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

const renderPlainText = (text = '') => (
  <div className="assistant-message">
    <pre className="plain-response">{text}</pre>
  </div>
)

const renderUserMessage = (text = '') => (
  <pre className="user-message-text">{text}</pre>
)

if (!isLoaded) return <div className="app loading">Loading...</div>;

return (
  <>
    <SignedOut>
      <div className="app">
        <div className="chat-container">
          <div className="empty-state">
            <h2>Welcome to Chat Assistant</h2>
            <SignInButton mode="modal">
              <button className="login-button" style={{ marginTop: '20px', padding: '12px 24px' }}>Sign in</button>
            </SignInButton>
          </div>
        </div>
      </div>
    </SignedOut>

    <SignedIn>
      <div className="app-layout" onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}>
        {isDragging && <div className="drag-overlay" style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.8)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', fontSize: '24px' }}>Drop file to upload</div>}

        <ConfirmationModal
          isOpen={isDeleteModalOpen}
          onClose={() => setIsDeleteModalOpen(false)}
          onConfirm={confirmDeleteSession}
          title="Delete Chat Session"
          message="Are you sure you want to delete this chat? This action cannot be undone."
        />

        <Sidebar
          sessions={sessions}
          currentSessionId={currentSessionId}
          onSelectSession={setCurrentSessionId}
          onCreateSession={handleCreateSession}
          onDeleteSession={handleDeleteSession}
          isLoading={isLoading}
          isOpen={isSidebarOpen}
        />

        <div className="chat-container">
          <div className="chat-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <button
                onClick={() => setIsSidebarOpen(!isSidebarOpen)}
                className="header-toggle-btn"
                title={isSidebarOpen ? "Close Sidebar" : "Open Sidebar"}
              >
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="3" y1="12" x2="21" y2="12"></line>
                  <line x1="3" y1="6" x2="21" y2="6"></line>
                  <line x1="3" y1="18" x2="21" y2="18"></line>
                </svg>
              </button>
              <h1>{sessions.find(s => s.id === currentSessionId)?.title || "Chat Assistant"}</h1>
            </div>
            <div className="header-buttons">
              {isLoading && <button onClick={() => abortControllerRef.current?.abort()} className="cancel-button">Stop</button>}
              <UserButton />
            </div>
          </div>

          <div className="messages-container">
            {!currentSessionId && messages.length === 0 ? (
              <div className="empty-state">
                <h2>How can I help you?</h2>
                <p>Start a new chat or select an existing one.</p>
              </div>
            ) : (
              <>
                {messages.length === 0 && !isLoading && !streamingContent && (
                  <div className="empty-state" style={{ minHeight: '200px' }}>
                    <p>No messages yet.</p>
                  </div>
                )}

                {messages.map((message, index) => (
                  <div key={index} className={`message ${message.role}`}>
                    <div className="message-content">{renderMessageContent(message)}</div>
                  </div>
                ))}

                {isLoading && streamingContent && renderStreamingContent()}
              </>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="input-container">
            {uploadedFileName && (
              <div className="file-attachment-indicator">
                <span>📄 {uploadedFileName}</span>
                <button className="remove-file-btn" onClick={() => { setUploadedFileName(null); setFileContext(null); }}>×</button>
              </div>
            )}
            <div className="input-wrapper" style={{ display: 'flex', alignItems: 'flex-end', gap: '8px' }}>
              <button className="upload-button" onClick={() => fileInputRef.current?.click()} title="Upload File">
                {isUploading ? (
                  <div className="spinner"></div>
                ) : (
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
                  </svg>
                )}
              </button>
              <input type="file" ref={fileInputRef} style={{ display: 'none' }} onChange={e => e.target.files?.[0] && handleFileUpload(e.target.files[0])} />

              <textarea
                ref={textareaRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder="Message..."
                rows={1}
                className="chat-input"
                style={{ flex: 1, maxHeight: '200px', resize: 'none', background: 'transparent', border: 'none', color: 'white', outline: 'none', padding: '10px' }}
              />

              <button onClick={handleSend} disabled={isLoading || !input.trim()} className="send-button">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="22" y1="2" x2="11" y2="13"></line>
                  <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </SignedIn>
  </>
)
}

export default App