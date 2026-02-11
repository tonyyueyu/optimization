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

const API_BASE = window.location.hostname === "localhost"
    ? "http://localhost:8000"
    : "https://backend-service-696616516071.us-west1.run.app";


const logErrorToBackend = async (message, stack = null, additionalData = null) => {
    try {
        await fetch(`${API_BASE}/api/log_error`, {
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

const extractCodeCells = (steps = []) => {
    if (!steps || !Array.isArray(steps)) {
        return [];
    }
    return steps
        .map((step) => ({
            stepNumber: step.number,
            code: step.code || '',
            output: step.output || '',
            error: step.error || '',
            language: step.language || 'python',
            plots: step.plots || [],
            files: step.files || []
        }))
        .filter(cell => cell.code || cell.output || cell.error || (cell.plots && cell.plots.length > 0) || (cell.files && cell.files.length > 0))
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
                    <button type="button" className="btn-outline" onClick={onClose}>Keep</button>
                    <button type="button" className="btn-destructive" onClick={onConfirm}>Remove</button>
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
        <aside className="app-sidebar" style={{ display: isOpen ? 'flex' : 'none' }} aria-label="Threads">
            <div className="sidebar-header">
                <button
                    type="button"
                    className="sidebar-new-btn"
                    onClick={onCreateSession}
                    disabled={isLoading}
                    style={{ opacity: isLoading ? 0.5 : 1, cursor: isLoading ? 'not-allowed' : 'pointer' }}
                >
                    <span className="sidebar-plus">+</span>
                    <span>New thread</span>
                </button>
            </div>

            <div className="sidebar-list">
                {sessions.map(session => (
                    <div
                        key={session.id}
                        className={`sidebar-item ${currentSessionId === session.id ? 'sidebar-item-active' : ''}`}
                        onClick={() => !isLoading && onSelectSession(session.id)}
                        style={{
                            opacity: isLoading && currentSessionId !== session.id ? 0.5 : 1,
                            cursor: isLoading ? 'not-allowed' : 'pointer',
                            pointerEvents: isLoading ? 'none' : 'auto'
                        }}
                    >
                        <span className="sidebar-item-icon" aria-hidden>◇</span>
                        <span className="sidebar-item-title">
                            {session.title || 'New thread'}
                        </span>
                        <button
                            type="button"
                            className="sidebar-item-remove"
                            onClick={(e) => {
                                e.stopPropagation();
                                if (!isLoading) onDeleteSession(session.id);
                            }}
                            disabled={isLoading}
                            title="Remove thread"
                            aria-label="Remove thread"
                        >
                            ×
                        </button>
                    </div>
                ))}
            </div>
        </aside>
    );
};

const RunBlock = ({ cell }) => {
    const [isCodeVisible, setIsCodeVisible] = useState(false);

    return (
        <section className="run-block">
            <header
                className="run-block-head"
                onClick={() => setIsCodeVisible(!isCodeVisible)}
            >
                <div className={`run-block-chevron ${isCodeVisible ? 'expanded' : ''}`}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="9 18 15 12 9 6" />
                    </svg>
                </div>
                <span>
                    {Number.isInteger(cell.stepNumber) || (typeof cell.stepNumber === 'string' && cell.stepNumber.match(/^\d+$/))
                        ? `Step ${cell.stepNumber}`
                        : cell.stepNumber}
                </span>
            </header>

            <div className="run-block-content">
                {isCodeVisible && cell.code && (
                    <pre className="run-block-code"><code>{cell.code}</code></pre>
                )}

                {(cell.output || cell.error) && (
                    <div className={`run-block-out ${cell.error ? 'run-block-out-error' : ''}`}>
                        {cell.error ? <strong>Error: </strong> : null}
                        {cell.output || cell.error}
                    </div>
                )}

                {cell.plots && cell.plots.length > 0 && (
                    <div className="run-block-plot">
                        {cell.plots.map((plot, plotIdx) => (
                            <img key={plotIdx} src={`data:image/png;base64,${plot}`} alt={`Plot ${plotIdx + 1}`} />
                        ))}
                    </div>
                )}

                {/* UPDATED FILE SECTION */}
                {cell.files && cell.files.length > 0 && (
                    <div className="run-block-files">
                        {cell.files.map((file, idx) => (
                            <button
                                key={idx}
                                type="button"
                                className="download-btn"
                                onClick={(e) => {
                                    e.stopPropagation();
                                    window.open(file.download_url, '_blank');
                                }}
                            >
                                <span className="download-btn-icon">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                                        <polyline points="7 10 12 15 17 10" />
                                        <line x1="12" y1="15" x2="12" y2="3" />
                                    </svg>
                                </span>
                                <span>Download {file.name}</span>
                            </button>
                        ))}
                    </div>
                )}
            </div>
        </section>
    );
};

const ResizableSplitLayout = ({ left, right, widthPercent, setWidthPercent, leftClassName, rightClassName }) => {
    const [isDragging, setIsDragging] = useState(false);
    const containerRef = useRef(null);

    const onMouseDown = (e) => {
        e.preventDefault();
        setIsDragging(true);
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        document.body.classList.add('resizing');
    };

    useEffect(() => {
        const onMouseMove = (e) => {
            if (!isDragging || !containerRef.current) return;
            const containerRect = containerRef.current.getBoundingClientRect();
            let newWidth = ((e.clientX - containerRect.left) / containerRect.width) * 100;
            if (newWidth < 20) newWidth = 20;
            if (newWidth > 80) newWidth = 80;
            setWidthPercent(newWidth);
        };

        const onMouseUp = () => {
            setIsDragging(false);
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            document.body.classList.remove('resizing');
        };

        if (isDragging) {
            window.addEventListener('mousemove', onMouseMove);
            window.addEventListener('mouseup', onMouseUp);
        }
        return () => {
            window.removeEventListener('mousemove', onMouseMove);
            window.removeEventListener('mouseup', onMouseUp);
        };
    }, [isDragging, setWidthPercent]);

    return (
        <div className="app-split" ref={containerRef}>
            <div className={leftClassName} style={{ width: `${widthPercent}%` }}>
                {left}
            </div>
            <div className="app-split-resizer" onMouseDown={onMouseDown} />
            <div className={rightClassName} style={{ flex: 1 }}>
                {right}
            </div>
        </div>
    );
};

function App() {
    const [messages, setMessages] = useState([])
    const [codePanelWidth, setCodePanelWidth] = useState(45);
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
            const res = await fetch(`${API_BASE}/api/sessions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userId })
            });

            const rawText = await res.text();
            console.log("RAW RESPONSE:", rawText);

            if (!res.ok) {
                throw new Error(`Server responded with ${res.status}`);
            }

            const data = JSON.parse(rawText);

            const sessionsArr = Object.entries(data.sessions || {})
                .map(([id, meta]) => ({ id, ...meta }))
                .sort((a, b) => new Date(b.last_updated) - new Date(a.last_updated));

            setSessions(sessionsArr);
            return sessionsArr;

        } catch (e) {
            console.error("Failed to fetch sessions", e);
            return [];
        }
    }, []);


    const fetchSessionMessages = useCallback(async (userId, sessionId) => {
        setHistoryLoading(true);
        setHistoryError(null);
        try {
            const res = await fetch(`${API_BASE}/api/chathistory`, {
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
                        title: 'Steps',
                        summary: msg.summary || '',
                        steps: steps.map((step, idx) => ({
                            number: step.step_id || idx + 1,
                            title: `Step ${step.step_id || idx + 1}`,
                            description: step.description || '',
                            code: step.code || '',
                            language: 'python',
                            output: step.output || '',
                            error: step.error || '',
                            plots: step.plots || [],
                            files: step.files || []
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
            logErrorToBackend(`History Fetch Error: ${e.message}`, e.stack, { userId: userUID });
            setHistoryError(e.message);
            setMessages([]);
        } finally {
            setHistoryLoading(false);
        }
    }, []);

    const saveMessageToHistory = async (userId, sessionId, role, content) => {
        try {
            await fetch(`${API_BASE}/api/chathistory/save`, {
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
            console.error("Failed to save message", err);
        }
    };

    useEffect(() => {
        if (isSignedIn && user?.id) {
            fetchSessions(user.id);
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

    useEffect(() => {
        // Clear the current active run state when switching threads
        setStreamingContent(null); // <--- Add this line
        setUploadedFileName(null);
        setFileContext(null);
    }, [currentSessionId]);

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
            await fetch(`${API_BASE}/api/chathistory/clear`, {
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

    const handleFileUpload = async (file) => {
        if (!file) return;

        setIsUploading(true);
        let sessionId = currentSessionId;

        try {
            // 1. If no session exists, create one immediately
            if (!sessionId) {
                const isAnonymous = !isSignedIn || !user?.id;
                const createRes = await fetch(`${API_BASE}/api/sessions/create`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_id: user?.id || 'anonymous',
                        title: `Upload: ${file.name}`
                    })
                });

                if (createRes.ok) {
                    const sData = await createRes.json();
                    sessionId = sData.session_id;
                    setCurrentSessionId(sessionId); // Set for the rest of the app
                    if (!isAnonymous) fetchSessions(user.id); // Refresh sidebar
                } else {
                    throw new Error("Failed to initialize session for upload.");
                }
            }

            // 2. Now proceed with the upload using the (newly created or existing) sessionId
            const formData = new FormData();
            formData.append('file', file);
            formData.append('user_id', user?.id || 'anonymous');
            formData.append('session_id', sessionId); // <--- We now definitely have this

            const response = await fetch(`${API_BASE}/api/upload`, {
                method: 'POST',
                body: formData,
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(JSON.stringify(errorData));
            }

            const data = await response.json();
            setUploadedFileName(file.name);
            setFileContext(data.summary || `File '${file.name}' uploaded successfully.`);

        } catch (error) {
            console.error("Upload Error:", error);
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

        const isAnonymous = !isSignedIn || !user?.id;

        const userMessageText = input.trim();

        let targetSessionId = currentSessionId;
        if (!isAnonymous && !targetSessionId) {
            try {
                const createRes = await fetch(`${API_BASE}/api/sessions/create`, {
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
                alert("Error creating chat session." + e);
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

        if (!isAnonymous && targetSessionId) {
            saveMessageToHistory(user.id, targetSessionId, 'user', finalQuery);
        }

        setIsLoading(true);
        setStreamingContent({
            steps: [],
            currentStep: null,
            currentTokens: '',
            status: 'retrieving'
        });
        abortControllerRef.current = new AbortController();

        try {
            setStreamingContent(prev => ({
                ...(prev || { steps: [], currentStep: null, currentTokens: '' }),
                status: 'solving'
            }));

            const formattedHistory = messages.map(msg => {
                if (msg.role === 'user') return { role: 'user', content: msg.content || '' };
                if (msg.role === 'assistant') {
                    if (msg.type === 'steps' && msg.steps && Array.isArray(msg.steps)) {
                        const stepsSummary = msg.steps.map(s => `- ${s.description}\nCode:\n${s.code}`).join('\n');
                        return { role: 'assistant', content: `Solution Steps:\n${stepsSummary}` };
                    }
                    return { role: 'assistant', content: typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content) };
                }
                return null;
            }).filter(Boolean);

            const response = await fetch(`${API_BASE}/api/solve`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_query: finalQuery,
                    user_id: user?.id,
                    session_id: targetSessionId,
                    chat_history: formattedHistory
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
                if (!isAnonymous && targetSessionId) {
                    const payload = JSON.stringify({
                        type: 'steps',
                        steps: finalExecutionSteps
                    });
                    await saveMessageToHistory(user.id, targetSessionId, 'assistant', payload);
                    await fetchSessionMessages(user.id, targetSessionId);
                } else {
                    const lastStep = finalExecutionSteps[finalExecutionSteps.length - 1];
                    const summary = lastStep?.description || '';

                    const newMsg = {
                        role: 'assistant',
                        type: 'steps',
                        title: 'Steps',
                        summary: summary,
                        steps: finalExecutionSteps.map((step, idx) => ({
                            number: step.step_id || idx + 1,
                            title: `Step ${step.step_id || idx + 1}`,
                            description: step.description || '',
                            code: step.code || '',
                            language: 'python',
                            output: step.output || '',
                            error: step.error || '',
                            plots: step.plots || [],
                            files: step.files || []
                        }))
                    };
                    setMessages(prev => [...prev, newMsg]);
                }
            }

        } catch (error) {
            if (error.name !== 'AbortError') {
                const errMsg = "Error: " + error.message;
                logErrorToBackend(`Chat Error: ${error.message}`, error.stack, { userQuery: input });

                setMessages(prev => [...prev, { role: 'assistant', type: 'text', content: errMsg }]);
            }
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
                setStreamingContent(prev => {
                    const steps = Array.isArray(prev?.steps) ? prev.steps : [];
                    return {
                        ...prev,
                        steps,
                        currentStep: event.data.step_number,
                        currentTokens: '',
                        status: 'generating'
                    };
                });
                break;
            case 'token':
                setStreamingContent(prev => {
                    const steps = Array.isArray(prev?.steps) ? prev.steps : [];
                    return {
                        ...prev,
                        steps,
                        currentTokens: (prev?.currentTokens || '') + (event.data.text || '')
                    };
                });
                break;
            case 'generation_complete':
                setStreamingContent(prev => {
                    const steps = Array.isArray(prev?.steps) ? prev.steps : [];
                    return {
                        ...prev,
                        steps,
                        status: 'executing',
                        currentTokens: JSON.stringify(event.data.step_data, null, 2)
                    };
                });
                break;
            case 'executing':
                setStreamingContent(prev => {
                    const steps = Array.isArray(prev?.steps) ? prev.steps : [];
                    return {
                        ...prev,
                        steps,
                        status: 'executing'
                    };
                });
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
                    files: event.data.step.files || [],
                };
                setStreamingContent(prev => {
                    // If prev is null/undefined, bootstrap a fresh state
                    if (!prev) {
                        return {
                            steps: [formattedStep],
                            currentStep: null,
                            currentTokens: '',
                            status: 'waiting'
                        };
                    }
                    const currentSteps = Array.isArray(prev.steps) ? prev.steps : [];
                    const exists = currentSteps.some(s => s.number === formattedStep.number);
                    if (exists) {
                        return { ...prev, steps: currentSteps, currentStep: null, currentTokens: '', status: 'waiting' };
                    }
                    return {
                        ...prev,
                        steps: [...currentSteps, formattedStep],
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



    const renderStepCard = (step, { isActive = false, isSummary = false } = {}) => (
        <div
            key={step.number}
            className={`run-step ${isActive ? 'run-step-active' : ''} ${isSummary ? 'run-step-summary' : ''}`}
        >
            <span className="run-step-badge">
                {isSummary ? '◆' : isActive ? step.number : '✓'}
            </span>
            <div className="run-step-body">
                <div className="run-step-title">{isSummary ? 'Summary' : step.title}</div>
                {step.description && <div className="run-step-desc">{step.description}</div>}
                {(step.output || step.error) && !isSummary && (
                    <div className={`run-step-outcome ${step.error ? 'run-step-outcome-error' : ''}`}>
                        {step.error ? `Error: ${step.error}` : step.output}
                    </div>
                )}
            </div>
        </div>
    );

    const renderStreamingContent = () => {
        if (!streamingContent) return null;
        return (
            <div className="message assistant">
                <div className="message-content chat-steps-wrap">
                    <div className="chat-steps-status">
                        <span className="status-dot" />
                        <span>
                            {streamingContent.status === 'retrieving' && 'Looking up context…'}
                            {streamingContent.status === 'generating' && 'Generating steps…'}
                            {streamingContent.status === 'executing' && 'Running code…'}
                            {streamingContent.status === 'waiting' && 'Processing…'}
                        </span>
                    </div>
                    <div className="run-steps" ref={streamingStepsRef} style={{ scrollBehavior: 'smooth' }}>
                        {(streamingContent.steps || []).map((step) => renderStepCard(step, { isActive: false }))}
                        {streamingContent.currentStep && (
                            <div className="run-step run-step-active">
                                <span className="run-step-badge">{streamingContent.currentStep}</span>
                                <div className="run-step-body">
                                    <div className="run-step-title">Reasoning…</div>
                                    <div className="run-step-desc">
                                        {streamingContent.currentTokens && (
                                            <pre className="run-step-stream">
                                                {streamingContent.currentTokens}
                                                <span className="stream-caret">|</span>
                                            </pre>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        );
    };

    const renderMessageContent = (message, messageIndex = null) => {
        if (message.role === 'assistant' && message.type === 'steps' && message.steps?.length) {
            return renderAssistantSteps(message, {
                messageIndex,
            });
        }
        if (message.role === 'assistant') {
            return renderPlainText(message.content);
        }
        return renderUserMessage(message.content);
    }

    const renderAssistantSteps = (message, { messageIndex = null } = {}) => (
        <div className="assistant-message">
            {message.summary && (
                <div className="message-summary-block">
                    <strong className="message-summary-label">Summary</strong>
                    <div className="message-summary-text">{message.summary}</div>
                </div>
            )}
            <div className="run-steps">
                {message.steps.map((step, index) => {
                    const isFinalSummary = index === message.steps.length - 1 && !step.code;

                    let stepToRender = step;
                    if (message.steps.length === 1 && !isFinalSummary) {
                        stepToRender = { ...step, title: 'Solution' };
                    }

                    return renderStepCard(stepToRender, { isSummary: isFinalSummary });
                })}
            </div>
        </div>
    );

    const renderPlainText = (text = '') => (
        <div className="assistant-message">
            <pre className="plain-response">{text}</pre>
        </div>
    )

    const renderUserMessage = (text = '') => (
        <pre className="user-message-text">{text}</pre>
    )
    useEffect(() => {
        // We only want to attempt cleanup if there is an active session
        if (!currentSessionId) return;

        const handleTabClose = () => {
            const url = `${API_BASE}/api/session/close`; // Uses your dynamic dynamic base
            const payload = JSON.stringify({
                user_id: user?.id || 'anonymous', // Correctly access Clerk user ID
                session_id: currentSessionId
            });

            // 'keepalive: true' is essential. It tells the browser to finish 
            // the request even if the tab is fully destroyed.
            fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: payload,
                keepalive: true,
            });
        };

        window.addEventListener("beforeunload", handleTabClose);
        return () => window.removeEventListener("beforeunload", handleTabClose);
    }, [currentSessionId, user?.id, API_BASE]); // Dependencies ensure the listener stays updated

    if (!isLoaded) return <div className="app app-loading">Starting…</div>;

    return (

        <div className="app">
            <div className="app-layout" onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}>
                {isDragging && <div className="drag-overlay" role="status">Drop file here</div>}

                <ConfirmationModal
                    isOpen={isDeleteModalOpen}
                    onClose={() => setIsDeleteModalOpen(false)}
                    onConfirm={confirmDeleteSession}
                    title="Remove this thread?"
                    message="This thread and its messages will be permanently removed. You can’t undo this."
                />

                <div className="sidebar-toggle-strip" title={isSidebarOpen ? "Hide threads" : "Show threads"}>
                    <button
                        type="button"
                        className="sidebar-toggle-btn"
                        onClick={() => setIsSidebarOpen(!isSidebarOpen)}
                        aria-label={isSidebarOpen ? "Hide threads" : "Show threads"}
                        aria-expanded={isSidebarOpen}
                    >
                        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <line x1="3" y1="12" x2="21" y2="12" />
                            <line x1="3" y1="6" x2="21" y2="6" />
                            <line x1="3" y1="18" x2="21" y2="18" />
                        </svg>
                        <span className="sidebar-toggle-label">Threads</span>
                    </button>
                </div>

                <Sidebar
                    sessions={sessions}
                    currentSessionId={currentSessionId}
                    onSelectSession={setCurrentSessionId}
                    onCreateSession={handleCreateSession}
                    onDeleteSession={handleDeleteSession}
                    isLoading={isLoading}
                    isOpen={isSidebarOpen}
                />

                {(() => {
                    const codeGroups = [];
                    let responseCount = 0;
                    messages.forEach((msg, idx) => {
                        if (msg.role === 'assistant' && msg.type === 'steps' && msg.steps?.length) {
                            const cells = extractCodeCells(msg.steps);

                            // IF SINGLE STEP, Rename to "Solution"
                            if (msg.steps.length === 1 && cells.length === 1) {
                                cells[0].stepNumber = "Solution";
                            }

                            if (cells.length > 0) {
                                responseCount++;
                                codeGroups.push({
                                    id: `msg-${idx}`,
                                    title: msg.summary ? truncateText(msg.summary, 60) : `Response ${responseCount}`,
                                    cells
                                });
                            }
                        }
                    });

                    if (streamingContent) {
                        const cells = extractCodeCells(streamingContent.steps || []);
                        if (cells.length > 0) {
                            codeGroups.push({
                                id: 'streaming',
                                title: 'Current Generation',
                                cells
                            });
                        }
                    }
                    return (
                        <ResizableSplitLayout
                            widthPercent={codePanelWidth}
                            setWidthPercent={setCodePanelWidth}
                            leftClassName="chat-panel"
                            rightClassName="code-output-panel"
                            left={
                                <>
                                    <header className="app-header">
                                        <div className="app-header-left">
                                            <span className="app-logo" aria-hidden>
                                                <img src="/favicon.png" alt="Solver" width="28" height="28" />
                                            </span>
                                            <h1 className="app-header-title">{sessions.find(s => s.id === currentSessionId)?.title || "Solver"}</h1>
                                        </div>
                                        <div className="app-header-right">
                                            {isLoading && (
                                                <button type="button" onClick={() => abortControllerRef.current?.abort()} className="app-header-stop-btn">Stop</button>
                                            )}
                                            <a href="https://discord.gg/vdffZG9hES" target="_blank" rel="noopener noreferrer" className="app-header-discord-btn" title="Join our Discord" aria-label="Join our Discord community">
                                                <svg width="20" height="20" viewBox="0 0 127.14 96.36" fill="currentColor">
                                                    <path d="M107.7,8.07A105.15,105.15,0,0,0,81.47,0a72.06,72.06,0,0,0-3.36,6.83A99.89,99.89,0,0,0,49,6.83,72.37,72.37,0,0,0,45.64,0A105.89,105.89,0,0,0,19.39,8.09C2.79,32.65-1.71,56.6.54,80.21h0A105.73,105.73,0,0,0,32.71,96.36,77.7,77.7,0,0,0,39.6,85.25a68.42,68.42,0,0,1-10.85-5.18c.91-.66,1.8-1.34,2.66-2a77.15,77.15,0,0,0,64.32,0c.87.71,1.76,1.39,2.66,2a68.68,68.68,0,0,1-10.87,5.22,77,77,0,0,0,6.89,11.1A105.73,105.73,0,0,0,126.6,80.22h0C129.24,52.84,122.09,29.11,107.7,8.07ZM42.45,65.69C36.18,65.69,31,60.6,31,54s5-11.74,11.43-11.74S54,47.41,54,54,48.84,65.69,42.45,65.69Zm42.24,0C78.41,65.69,73.25,60.6,73.25,54s5-11.74,11.44-11.74S96.23,47.41,96.23,54,91.09,65.69,84.69,65.69Z" />
                                                </svg>
                                            </a>
                                            <SignedIn>
                                                <UserButton />
                                            </SignedIn>
                                            <SignedOut>
                                                <SignInButton mode="modal">
                                                    <button type="button" className="app-header-signin-btn">Log in</button>
                                                </SignInButton>
                                            </SignedOut>
                                        </div>
                                    </header>

                                    <div className="messages-area">
                                        {!currentSessionId && messages.length === 0 ? (
                                            <div className="empty-state">
                                                <h2 className="empty-state-heading">What would you like to work on?</h2>
                                                <p className="empty-state-text">Create a thread or type below to get started.</p>
                                                <SignedOut>
                                                    <p className="empty-state-hint">Sign in to save your threads and history.</p>
                                                </SignedOut>
                                            </div>
                                        ) : (
                                            <>
                                                {messages.length === 0 && !isLoading && !streamingContent && (
                                                    <div className="empty-state empty-state-small">
                                                        <p className="empty-state-text">No messages in this thread.</p>
                                                    </div>
                                                )}

                                                {messages.map((message, index) => (
                                                    <div key={index} className={`message ${message.role}`}>
                                                        <div className="message-content">{renderMessageContent(message, index)}</div>
                                                    </div>
                                                ))}

                                                {isLoading && streamingContent && renderStreamingContent()}
                                            </>
                                        )}
                                        <div ref={messagesEndRef} />
                                    </div>

                                    <div className="composer">
                                        {uploadedFileName && (
                                            <div className="composer-attachment">
                                                <span className="composer-attachment-name">{uploadedFileName}</span>
                                                <button type="button" className="composer-attachment-remove" onClick={() => { setUploadedFileName(null); setFileContext(null); }} aria-label="Remove file">×</button>
                                            </div>
                                        )}
                                        <div className="composer-inner">
                                            <button type="button" className="composer-attach-btn" onClick={() => fileInputRef.current?.click()} title="Attach file" aria-label="Attach file">
                                                {isUploading ? <span className="composer-spinner" /> : (
                                                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                                        <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
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
                                                placeholder="Ask anything or describe your task…"
                                                rows={1}
                                                className="composer-input"
                                                aria-label="Message"
                                            />
                                            <button type="button" onClick={handleSend} disabled={isLoading || !input.trim()} className="composer-send-btn" aria-label="Send">
                                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                                    <line x1="22" y1="2" x2="11" y2="13" />
                                                    <polygon points="22 2 15 22 11 13 2 9 22 2" />
                                                </svg>
                                            </button>
                                        </div>
                                    </div>
                                </>
                            }
                            right={
                                <>
                                    <div className="code-output-header">
                                        <div className="code-output-header-top">
                                            <span className="code-output-label">Code output</span>
                                        </div>
                                    </div>
                                    <div className="code-output-body run-log" ref={streamingCodeRef} style={{ scrollBehavior: 'smooth' }}>
                                        {codeGroups.length > 0 ? (
                                            codeGroups.map((group, groupIdx) => (
                                                <div key={group.id} className="code-group">
                                                    <div className="code-group-header">
                                                        <span className="code-group-title">{group.title}</span>
                                                    </div>
                                                    {group.cells.map((cell, idx) => <RunBlock key={`${group.id}-${idx}`} cell={cell} />)}
                                                    {groupIdx < codeGroups.length - 1 && <div className="code-group-separator" />}
                                                </div>
                                            ))
                                        ) : (
                                            <div className="workspace-code-placeholder">
                                                {streamingContent ? 'Waiting for output…' : 'Code from your runs will appear here.'}
                                            </div>
                                        )}
                                    </div>
                                </>
                            }
                        />
                    );
                })()}
            </div>
        </div>
    )
}

export default App