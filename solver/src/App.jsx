import { useState, useRef, useEffect, useCallback } from 'react'
import './App.css'
import 'katex/dist/katex.min.css';
import Latex from 'react-latex-next';
import {
    SignedIn,
    SignedOut,
    SignInButton,
    SignOutButton,
    UserButton,
    useUser
} from '@clerk/clerk-react'


import FileDisplayer from './components/FileDisplayer'

// const API_BASE = "https://backend-service-696616516071.us-west1.run.app";
const API_BASE = "http://localhost:8000";

const LATEX_DELIMITERS = [
    { left: '$$', right: '$$', display: true },
    { left: '\\[', right: '\\]', display: true },
    { left: '$', right: '$', display: false },
    { left: '\\(', right: '\\)', display: false },
];

/**
 * SafeLatex wraps the react-latex-next component to handle potential nulls 
 * and ensures mathematical equations are properly formatted.
 */
const SafeLatex = ({ children }) => (
    <Latex delimiters={LATEX_DELIMITERS} strict={false}>
        {String(children ?? '')}
    </Latex>
);

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
    if (!steps || !Array.isArray(steps)) return [];

    return steps
        .map((step) => ({
            // Use step_id if number is missing (common when switching from streaming to history)
            stepNumber: step.number || step.step_id || '?',
            code: step.code || '',
            output: step.output || '',
            error: step.error || '',
            language: 'python',
            // Explicitly ensure plots and files are passed as arrays
            plots: Array.isArray(step.plots) ? step.plots : [],
            files: Array.isArray(step.files) ? step.files : []
        }))
        // Ensure we don't filter out a step just because it has no text output
        .filter(cell =>
            cell.code.trim() !== '' ||
            cell.output.trim() !== '' ||
            cell.error.trim() !== '' ||
            cell.plots.length > 0 ||
            cell.files.length > 0
        );
};

const truncateText = (text, maxLength = 100) => {
    if (!text) return ''
    return text.length > maxLength ? text.substring(0, maxLength) + '...' : text
}

const updateHistoricalToDos = (prevHist, currentToDo) => {
    const hist = prevHist ? [...prevHist] : [];
    if (!currentToDo || !Array.isArray(currentToDo)) return hist;

    currentToDo.forEach(task => {
        if (!hist.find(t => t.task === task)) {
            hist.push({ task, done: false });
        }
    });

    hist.forEach(item => {
        if (!currentToDo.includes(item.task)) {
            item.done = true;
        }
    });

    return hist;
};

/**
 * Reusable modal for confirming destructive actions like session deletion.
 */
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

const AddFileModal = ({
    isOpen,
    onClose,
    subTab,
    setSubTab,
    onFileUpload,
    onLinkUpload,
    linkName,
    setLinkName,
    linkUrl,
    setLinkUrl,
    isUploading
}) => {
    if (!isOpen) return null;

    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="modal-content add-file-modal" onClick={e => e.stopPropagation()}>
                <div className="modal-header">Add Resource</div>

                <div className="modal-tabs">
                    <button
                        className={`modal-tab ${subTab === 'upload' ? 'active' : ''}`}
                        onClick={() => setSubTab('upload')}
                    >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: '6px' }}>
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                            <polyline points="17 8 12 3 7 8" />
                            <line x1="12" y1="3" x2="12" y2="15" />
                        </svg>
                        Upload
                    </button>
                    <button
                        className={`modal-tab ${subTab === 'link' ? 'active' : ''}`}
                        onClick={() => setSubTab('link')}
                    >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: '6px' }}>
                            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                        </svg>
                        Link
                    </button>
                </div>

                <div className="modal-body">
                    {subTab === 'upload' ? (
                        <div className="upload-section">
                            <label className="upload-dropzone">
                                <input
                                    type="file"
                                    style={{ display: 'none' }}
                                    onChange={(e) => {
                                        if (e.target.files?.[0]) onFileUpload(e.target.files[0]);
                                        onClose();
                                    }}
                                />
                                <div className="upload-icon">
                                    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                                        <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242" />
                                        <path d="M12 12v9" />
                                        <path d="m8 17 4-4 4 4" />
                                    </svg>
                                </div>
                                <p>{isUploading ? 'Preparing upload…' : 'Select or drag & drop files'}</p>
                                <span>CSV, Excel, Images, PDFs Up to 1.5GB</span>
                            </label>
                        </div>
                    ) : (
                        <div className="link-form">
                            <div className="form-group">
                                <label>Resource Name</label>
                                <input
                                    placeholder="e.g. Project Documentation"
                                    value={linkName}
                                    onChange={(e) => setLinkName(e.target.value)}
                                />
                            </div>
                            <div className="form-group">
                                <label>URL</label>
                                <input
                                    placeholder="https://example.com/docs"
                                    value={linkUrl}
                                    onChange={(e) => setLinkUrl(e.target.value)}
                                />
                            </div>
                            <button
                                className="btn-primary"
                                onClick={onLinkUpload}
                                disabled={!linkName || !linkUrl || isUploading}
                                style={{ marginTop: '8px' }}
                            >
                                {isUploading ? 'Saving…' : 'Add Link'}
                            </button>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

/**
 * Sidebar component that lists chat sessions. 
 * Allows creating new threads and deleting existing ones.
 */
const Sidebar = ({
    sessions,
    currentSessionId,
    onSelectSession,
    onCreateSession,
    onDeleteSession,
    isLoading,
    isOpen,
    sidebarTab,
    sessionFiles,
    onAddFile,
    onDeleteFile,
    selectedFileIds,
    toggleFileSelection
}) => {
    if (!isOpen) return null;
    return (
        <aside className="app-sidebar" style={{ display: isOpen ? 'flex' : 'none' }}>
            <div className="sidebar-content">
                {sidebarTab === 'threads' ? (
                    <>
                        <div className="sidebar-header">
                            <button
                                type="button"
                                className="sidebar-new-btn"
                                onClick={onCreateSession}
                                disabled={isLoading}
                            >
                                <span className="sidebar-plus">+</span>
                                <span>New thread</span>
                            </button>
                        </div>

                        <div className="sidebar-list">
                            {sessions.length === 0 ? (
                                <div className="sidebar-empty">No threads yet.</div>
                            ) : (
                                sessions.map(session => (
                                    <div
                                        key={session.id}
                                        className={`sidebar-item ${currentSessionId === session.id ? 'sidebar-item-active' : ''}`}
                                        onClick={() => !isLoading && onSelectSession(session.id)}
                                    >
                                        <span className="sidebar-item-icon">◇</span>
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
                                        >
                                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                                <path d="M3 6h18m-2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                                            </svg>
                                        </button>
                                    </div>
                                ))
                            )}
                        </div>
                    </>
                ) : (
                    <FileDisplayer
                        isOpen={true}
                        files={sessionFiles}
                        onAddFile={onAddFile}
                        onDeleteFile={onDeleteFile}
                        selectedFileIds={selectedFileIds}
                        toggleFileSelection={toggleFileSelection}
                    />
                )}
            </div>


        </aside>
    );
};

/**
 * RunBlock renders a single step generated by the AI,
 * displaying code, execution output, errors, plots, and downloadable files.
 */
const RunBlock = ({ cell }) => {
    const [isCodeVisible, setIsCodeVisible] = useState(false);
    const isFatalError = cell.error && (cell.error.includes("Traceback") || cell.error.includes("Error:"));
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

                {/* Render Output */}
                {cell.output ? (
                    <div className="run-block-out">
                        <SafeLatex>{cell.output}</SafeLatex>
                    </div>
                ) : (
                    !cell.error && cell.plots?.length === 0 && cell.files?.length === 0 && (
                        <div className="run-block-out" style={{ color: 'var(--text-secondary)', fontStyle: 'italic', padding: '12px' }}>
                            Step executed successfully (no output).
                        </div>
                    )
                )}

                {/* Render Error/Warning */}
                {cell.error && (
                    <div className={`run-block-out ${isFatalError ? 'run-block-out-error' : 'run-block-out-warning'}`}>
                        {isFatalError ? <strong>Exception: </strong> : <strong>Note: </strong>}
                        <SafeLatex>{cell.error}</SafeLatex>
                    </div>
                )}

                {Array.isArray(cell.plots) && cell.plots.length > 0 && (
                    <div className="run-block-plot">
                        {cell.plots.map((plot, plotIdx) => {
                            if (!plot) return null; // Skip empty plot data

                            // Check if plot already has the data prefix
                            const src = plot.startsWith('data:')
                                ? plot
                                : `data:image/png;base64,${plot}`;

                            return (
                                <img
                                    key={plotIdx}
                                    src={src}
                                    alt={`Plot ${plotIdx + 1}`}
                                    // Handle image load errors
                                    onError={(e) => e.target.style.display = 'none'}
                                />
                            );
                        })}
                    </div>
                )}

                {/* {cell.files && cell.files.length > 0 && (
                    <div className="run-block-files">
                        {cell.files
                            .filter(file => !/\.(png|jpg|jpeg|gif|webp|svg)$/i.test(file.name))
                            .map((file, idx) => (
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
                )} */}
            </div>
        </section>
    );
};

/**
 * ResizableSplitLayout provides a draggable vertical divider 
 * separating the left (chat) and right (solver/code view) panels.
 */
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

/**
 * Main application component. Manages overarching state:
 * authentication, active chats, streaming completions, active sessions, and layouts.
 */
function App() {
    const { isLoaded, isSignedIn, user } = useUser()
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
    const [isSidebarOpen, setIsSidebarOpen] = useState(() => window.innerWidth > 768);
    const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
    const [sessionToDelete, setSessionToDelete] = useState(null);
    const [editingIndex, setEditingIndex] = useState(null);
    const [editValue, setEditValue] = useState("");

    const [anonId] = useState(() => {
        const saved = localStorage.getItem('solver_anon_id');
        if (saved) return saved;
        const newId = `anon_${Math.random().toString(36).substring(2, 11)}`;
        localStorage.setItem('solver_anon_id', newId);
        return newId;
    });

    const [sessions, setSessions] = useState([]);
    const [currentSessionId, setCurrentSessionId] = useState(null);
    const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'dark');
    const [isMobile, setIsMobile] = useState(false);
    const [activeMobileTab, setActiveMobileTab] = useState('chat');

    const [sidebarTab, setSidebarTab] = useState('threads');
    const [sessionFiles, setSessionFiles] = useState([]);
    const [selectedFileIds, setSelectedFileIds] = useState(new Set());
    const [isAddFileModalOpen, setIsAddFileModalOpen] = useState(false);
    const [linkName, setLinkName] = useState('');
    const [linkUrl, setLinkUrl] = useState('');
    const [modalSubTab, setModalSubTab] = useState('upload');

    useEffect(() => {
        if (!isLoaded) return;
        const bootId = user?.id || anonId;
        fetch(`${API_BASE}/api/boot`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: bootId })
        }).catch(err => console.error("Boot call failed:", err));
    }, [isLoaded, user?.id, anonId]);

    const sessionRef = useRef(currentSessionId);
    useEffect(() => {
        if (!isLoaded) return;
        const key = `selectedFiles_${user?.id || anonId}_${currentSessionId || 'global'}`;


        if (currentSessionId !== sessionRef.current) {
            const saved = localStorage.getItem(key);
            if (saved) {
                try {
                    const parsed = JSON.parse(saved);
                    setSelectedFileIds(new Set(parsed));
                } catch (e) {
                    setSelectedFileIds(new Set());
                }
            } else {
                setSelectedFileIds(new Set());
            }
            sessionRef.current = currentSessionId;
        } else {
            localStorage.setItem(key, JSON.stringify(Array.from(selectedFileIds)));
        }
    }, [selectedFileIds, isLoaded, user?.id, currentSessionId, anonId]);

    useEffect(() => {
        const saved = localStorage.getItem('lastSidebarTab');
        if (saved) setSidebarTab(saved);
    }, []);

    useEffect(() => {
        localStorage.setItem('lastSidebarTab', sidebarTab);
    }, [sidebarTab]);

    useEffect(() => {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);
    }, [theme]);

    useEffect(() => {
        const handleResize = () => setIsMobile(window.innerWidth <= 768);
        handleResize();
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);


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
                let attachments = [];
                let to_do_list = [];

                try {
                    if (msg.content && (msg.content.startsWith('{') || msg.content.startsWith('['))) {
                        const parsed = JSON.parse(msg.content);
                        if (msg.role === 'assistant' && (parsed.type === 'steps' || parsed.steps)) {
                            type = 'steps';
                            steps = parsed.steps || [];
                            to_do_list = parsed.to_do_list || [];
                            parsedContent = "";
                        } else if (msg.role === 'user' && parsed.attachments) {
                            attachments = parsed.attachments;
                            parsedContent = parsed.content;
                        }
                    }
                } catch (e) { }

                if (type === 'steps') {
                    return {
                        role: 'assistant',
                        type: 'steps',
                        title: 'Steps',
                        summary: msg.summary || '',
                        to_do_list: to_do_list,
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
                    content: parsedContent,
                    attachments: attachments
                };
            });

            setMessages(formatted);
        } catch (e) {
            logErrorToBackend(`History Fetch Error: ${e.message}`, e.stack, { userId: user?.id });
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
            setActiveMobileTab('chat');
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
        console.log("Current Session ID loaded:", currentSessionId);
        setStreamingContent(null);
        setUploadedFileName(null);
        setFileContext(null);
        setActiveMobileTab('chat');
    }, [currentSessionId]);

    const handleCreateSession = () => {
        setCurrentSessionId(null);
        setMessages([]);
        setFileContext(null);
        setUploadedFileName(null);
        if (fileInputRef.current) fileInputRef.current.value = '';
        setActiveMobileTab('chat');
        if (isMobile) setIsSidebarOpen(false);
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

    const fetchSessionFiles = useCallback(async (sessionId = currentSessionId) => {
        if (!isLoaded) return;
        const userId = user?.id || anonId;
        const targetSessionId = sessionId || 'global';

        console.log(`[Files] Fetching library for user: ${userId}, session: ${targetSessionId}`);

        try {
            const res = await fetch(`${API_BASE}/api/files/${targetSessionId}?user_id=${userId}`);
            if (!res.ok) {
                console.error(`Failed to fetch files: ${res.status}`);
                return;
            }
            const data = await res.json();
            if (data.status === 'success') {
                setSessionFiles(data.files || []);
            } else {
                console.warn("Server returned error for files list:", data.message || data.error);
            }
        } catch (e) {
            console.error("Error fetching session files", e);
        }
    }, [currentSessionId, user?.id, anonId, isLoaded]);

    const prevSessionIdRef = useRef(currentSessionId);
    useEffect(() => {
        if (!isLoaded) return;

        if (currentSessionId !== prevSessionIdRef.current) {
            prevSessionIdRef.current = currentSessionId;
        }

        fetchSessionFiles(currentSessionId);
    }, [currentSessionId, fetchSessionFiles, isSignedIn, isLoaded]);


    const handleFileUpload = useCallback(async (file) => {
        if (!file) return;

        setIsUploading(true);
        let sessionId = currentSessionId;

        try {
            if (!sessionId) {
                const isAnonymous = !isSignedIn || !user?.id;
                const createRes = await fetch(`${API_BASE}/api/sessions/create`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_id: user?.id || anonId,
                        title: `Upload: ${file.name}`
                    })
                });

                if (createRes.ok) {
                    const sData = await createRes.json();
                    sessionId = sData.session_id;
                    setCurrentSessionId(sessionId);
                    if (!isAnonymous) fetchSessions(user.id);
                } else {
                    throw new Error("Failed to initialize session for upload.");
                }
            }

            const formData = new FormData();
            formData.append('file', file);
            formData.append('user_id', user?.id || anonId);
            formData.append('session_id', sessionId || 'global');

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
            setFileContext(data.summary || `File '${file.name}' uploaded successfully. Access URL: ${data.url}`);

            const newFile = {
                name: file.name,
                size: fsize(file.size),
                id: data.id || `${user?.id || anonId}/${sessionId || 'global'}/${file.name}`,
                type: 'file',
                session_id: sessionId,
                updated: new Date().toISOString(),
                url: data.url
            };
            setSessionFiles(prev => [newFile, ...prev.filter(f => f.id !== newFile.id)]);

            fetchSessionFiles(sessionId);
            setSelectedFileIds(prev => new Set(prev).add(newFile.id));

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
    }, [currentSessionId, isSignedIn, user?.id, API_BASE, fetchSessions, fetchSessionFiles]);

    // Helper for formatting size
    function fsize(bytes) {
        if (!bytes) return '0 B';
        const k = 1024;
        const dm = 1;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    const handleLinkUpload = useCallback(async () => {
        if (!linkName || !linkUrl) return;

        setIsUploading(true);
        try {
            let sessionId = currentSessionId;
            if (!sessionId) {
                const createRes = await fetch(`${API_BASE}/api/sessions/create`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_id: user?.id || anonId,
                        title: linkName.substring(0, 30)
                    })
                });
                if (createRes.ok) {
                    const sData = await createRes.json();
                    sessionId = sData.session_id;
                    setCurrentSessionId(sessionId);
                    if (isSignedIn) fetchSessions(user.id);
                }
            }

            const formData = new FormData();
            formData.append('user_id', user?.id || anonId);
            formData.append('session_id', sessionId || 'global');
            formData.append('name', linkName);
            formData.append('url', linkUrl);

            const response = await fetch(`${API_BASE}/api/links/save`, {
                method: 'POST',
                body: formData,
            });

            if (response.ok) {
                const data = await response.json();

                // Optimistic update
                const newLink = {
                    name: linkName,
                    url: linkUrl,
                    type: 'link',
                    id: data.id || `${user?.id || anonId}/${sessionId || 'global'}/${linkName}.link`,
                    session_id: sessionId,
                    updated: new Date().toISOString()
                };
                setSessionFiles(prev => [newLink, ...prev.filter(f => f.id !== newLink.id)]);

                setLinkName('');
                setLinkUrl('');
                setIsAddFileModalOpen(false);
                fetchSessionFiles(sessionId);
                if (newLink.id) {
                    setSelectedFileIds(prev => new Set(prev).add(newLink.id));
                }
            }
        } catch (error) {
            console.error("Link Error:", error);
        } finally {
            setIsUploading(false);
        }
    }, [linkName, linkUrl, currentSessionId, isSignedIn, user?.id, API_BASE, fetchSessions, fetchSessionFiles]);

    const handleDeleteFile = async (file) => {
        try {
            const formData = new FormData();
            formData.append('user_id', user?.id || anonId);
            formData.append('session_id', file.session_id || currentSessionId);
            formData.append('id', file.id);

            const res = await fetch(`${API_BASE}/api/files/delete`, {
                method: 'POST',
                body: formData
            });

            if (res.ok) {
                fetchSessionFiles();
                setSelectedFileIds(prev => {
                    const next = new Set(prev);
                    next.delete(file.id);
                    return next;
                });
            }
        } catch (e) {
            console.error("Error deleting file", e);
        }
    };

    const toggleFileSelection = useCallback((fileId) => {
        setSelectedFileIds(prev => {
            const next = new Set(prev);
            if (next.has(fileId)) next.delete(fileId);
            else next.add(fileId);
            return next;
        });
    }, []);

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
    }, [handleFileUpload]);

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

    const handleModifyPrompt = async (index, newQuery) => {
        console.log("Modifying prompt at index:", index);

        setEditingIndex(null);

        const truncatedHistory = messages.slice(0, index);
        setMessages(truncatedHistory);

        try {
            if (currentSessionId && isSignedIn) {
                await fetch(`${API_BASE}/api/prompt/modify`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_id: user?.id,
                        session_id: currentSessionId,
                        message_index: index,
                        new_query: newQuery
                    })
                });
            }

            await handleSend(newQuery, truncatedHistory, true);

        } catch (e) {
            console.error("Modify error:", e);
            setIsLoading(false);
        }
    };

    const handleSend = async (overrideQuery = null, overrideHistory = null, isRetry = false) => {
        const queryToUse = (overrideQuery !== null && typeof overrideQuery === 'string') ? overrideQuery : input;

        if (!queryToUse.trim() || (isLoading && !isRetry)) return;

        setIsLoading(true);

        const isAnonymous = !isSignedIn || !user?.id;
        const userMessageText = queryToUse.trim();

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

        const currentSelectedFiles = Array.from(selectedFileIds);
        const attachments = currentSelectedFiles.map(fid => {
            const f = sessionFiles.find(sf => sf.id === fid);
            return f ? { name: f.name, type: f.type, id: f.id } : null;
        }).filter(Boolean);

        const userMessage = { role: 'user', content: userMessageText, attachments };
        const baseHistory = overrideHistory !== null ? overrideHistory : messages;
        setMessages([...baseHistory, userMessage]);

        // Clear selection and uploaded state after capturing
        setSelectedFileIds(new Set());
        setUploadedFileName(null);
        setFileContext(null);
        setInput('');

        let finalQuery = userMessageText;
        // ... (rest of the logic doesn't strictly need fileContext anymore if we use attachments uniformly, 
        // but keeping it for backward compat if preferred. Actually user wants to see them in UI)

        if (textareaRef.current) textareaRef.current.style.height = 'auto';

        if (!isAnonymous && targetSessionId) {
            const historyContent = attachments.length > 0
                ? JSON.stringify({ content: userMessageText, attachments })
                : userMessageText;
            saveMessageToHistory(user.id, targetSessionId, 'user', historyContent);
        }

        setIsLoading(true);
        setStreamingContent({
            steps: [],
            currentStep: null,
            currentTokens: '',
            status: 'retrieving',
            to_do: [],
            historical_to_dos: []
        });
        abortControllerRef.current = new AbortController();

        try {
            const formattedHistory = baseHistory.map(msg => {
                if (msg.role === 'user') return { role: 'user', content: msg.content || '' };
                if (msg.role === 'assistant') {
                    if (msg.type === 'steps') {
                        const stepsSummary = msg.steps.map(s => `- ${s.description}\nCode:\n${s.code}`).join('\n');
                        return { role: 'assistant', content: `Solution Steps:\n${stepsSummary}` };
                    }
                    return { role: 'assistant', content: msg.content };
                }
                return null;
            }).filter(Boolean);

            const response = await fetch(`${API_BASE}/api/solve`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_query: finalQuery,
                    user_id: user?.id || anonId,
                    session_id: targetSessionId,
                    chat_history: formattedHistory,
                    selected_files: Array.from(selectedFileIds)
                }),
                signal: abortControllerRef.current.signal
            });

            if (!response.ok) throw new Error('Failed to get solution');

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let finalExecutionSteps = [];
            let currentHistoricalToDos = [];

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const events = parseSSE(buffer);
                const lastEventEnd = buffer.lastIndexOf('\n\n');
                if (lastEventEnd !== -1) buffer = buffer.slice(lastEventEnd + 2);

                for (const event of events) {
                    if (event.event === 'step_start' || event.event === 'executing') {
                        currentHistoricalToDos = updateHistoricalToDos(currentHistoricalToDos, event.data.to_do);
                    }
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
                        steps: finalExecutionSteps,
                        to_do_list: currentHistoricalToDos
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
                        to_do_list: currentHistoricalToDos,
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
                    const newToDo = event.data.to_do || prev?.to_do || [];
                    return {
                        ...prev,
                        steps,
                        currentStep: event.data.step_number,
                        currentTokens: '',
                        status: 'generating',
                        to_do: newToDo,
                        historical_to_dos: updateHistoricalToDos(prev?.historical_to_dos, newToDo)
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
                    const newToDo = event.data.to_do || prev?.to_do || [];
                    return {
                        ...prev,
                        steps,
                        status: 'executing',
                        to_do: newToDo,
                        historical_to_dos: updateHistoricalToDos(prev?.historical_to_dos, newToDo)
                    };
                });
                break;
            case 'step_complete':
                const finishedStep = {
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
                    // Handle initial null state
                    if (!prev) {
                        return {
                            steps: [finishedStep],
                            currentStep: null,
                            currentTokens: '',
                            status: 'waiting'
                        };
                    }

                    const currentSteps = Array.isArray(prev.steps) ? prev.steps : [];
                    const index = currentSteps.findIndex(s => s.number === finishedStep.number);

                    let newSteps;
                    if (index !== -1) {
                        // REPLACE the placeholder with the data-rich step
                        newSteps = [...currentSteps];
                        newSteps[index] = finishedStep;
                    } else {
                        // Append if it doesn't exist
                        newSteps = [...currentSteps, finishedStep];
                    }

                    return {
                        ...prev,
                        steps: newSteps,
                        currentStep: null,
                        currentTokens: '',
                        status: 'waiting'
                    };
                });
                break;
            case 'done':
                setStreamingContent(null);
                setIsLoading(false);
                fetchSessionFiles();
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
                {step.description && (
                    <div className="run-step-desc">
                        <SafeLatex>{step.description}</SafeLatex>
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

                    {streamingContent.historical_to_dos && streamingContent.historical_to_dos.length > 0 && (
                        <div className="task-plan-container">
                            <div className="task-plan-title">Plan</div>
                            <div className="task-plan-list">
                                {streamingContent.historical_to_dos.map((item, idx) => (
                                    <div key={idx} className={`task-plan-item ${item.done ? 'task-done' : ''}`}>
                                        {item.done ? (
                                            <svg className="task-icon done" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                                        ) : (
                                            <svg className="task-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"></circle></svg>
                                        )}
                                        <span className="task-text">{item.task}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

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
            return renderAssistantSteps(message, { messageIndex });
        }
        if (message.role === 'assistant') {
            return renderPlainText(message.content);
        }
        return renderUserMessage(message, messageIndex);
    }

    const renderAssistantSteps = (message, { messageIndex = null } = {}) => {
        // Check for "Trivial" case: 2 steps, and the 2nd is a summary (no code)
        const isTrivial =
            message.steps.length === 2 &&
            !message.steps[1].code &&
            message.steps[1].number === 2;

        if (isTrivial) {
            // Only render the summary description from Step 2 as a plain message
            return (
                <div className="assistant-message">
                    <div className="plain-response">
                        <SafeLatex>{message.steps[1].description}</SafeLatex>
                    </div>
                </div>
            );
        }

        // Standard rendering for complex problems
        return (
            <div className="assistant-message">
                {message.to_do_list && message.to_do_list.length > 0 && (
                    <div className="task-plan-container">
                        <div className="task-plan-title">Plan</div>
                        <div className="task-plan-list">
                            {message.to_do_list.map((item, idx) => (
                                <div key={idx} className={`task-plan-item ${item.done ? 'task-done' : ''}`}>
                                    {item.done ? (
                                        <svg className="task-icon done" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                                    ) : (
                                        <svg className="task-icon done" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                                    )}
                                    <span className="task-text">{item.task}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
                <div className="run-steps">
                    {message.steps.map((step, index) => {
                        const isFinalSummary = index === message.steps.length - 1 && !step.code;

                        // Logic: If step_id == 2 and it's an empty final summary, 
                        // and we didn't trigger 'isTrivial' above, we might still want to hide the badge
                        if (step.number === 2 && isFinalSummary && message.steps.length === 2) {
                            return (
                                <div key={step.number} className="run-step-summary-only">
                                    <SafeLatex>{step.description}</SafeLatex>
                                </div>
                            );
                        }

                        return renderStepCard(step, { isSummary: isFinalSummary });
                    })}
                </div>
            </div>
        );
    };

    const renderPlainText = (text = '') => (
        <div className="assistant-message">
            <div className="plain-response" style={{ whiteSpace: 'pre-wrap' }}>
                <SafeLatex>{text}</SafeLatex>
            </div>
        </div>
    )

    const renderUserMessage = (message, index) => {
        const isEditing = editingIndex === index;
        const msgObj = typeof message === 'string' ? { content: message, attachments: [] } : message;
        const { content: text = '', attachments = [] } = msgObj;

        if (isEditing) {
            return (
                <div className="edit-prompt-box">
                    <textarea
                        className="edit-prompt-textarea"
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        autoFocus
                    />
                    <div className="edit-prompt-actions">
                        <button
                            className="btn-save"
                            type="button"
                            onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                handleModifyPrompt(index, editValue);
                            }}
                        >
                            Save & Run
                        </button>
                        <button className="btn-cancel" onClick={() => setEditingIndex(null)}>Cancel</button>
                    </div>
                </div>
            );
        }


        const getMiniIcon = (att) => {
            if (att.type === 'link') return '🔗';
            const name = att.name || '';
            const ext = name.split('.').pop().toLowerCase();
            switch (ext) {
                case 'pdf': return '📕';
                case 'py': return '🐍';
                case 'json': return '📋';
                default: return '📄';
            }
        };

        return (
            <div className="user-message-container">
                {attachments.length > 0 && (
                    <div className="user-message-attachments">
                        {attachments.map((att, i) => (
                            <div key={i} className="user-attachment-tag" title={att.name}>
                                <span className="user-attachment-icon">{getMiniIcon(att)}</span>
                                <span className="user-attachment-name">{att.name}</span>
                            </div>
                        ))}
                    </div>
                )}
                <pre className="user-message-text">{text}</pre>
                <button
                    className="edit-button"
                    onClick={() => {
                        setEditingIndex(index);
                        setEditValue(text);
                    }}
                >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                    </svg>
                    <span>Edit</span>
                </button>
            </div>
        );
    }
    useEffect(() => {
        if (!currentSessionId) return;

        const handleTabClose = () => {
            const url = `${API_BASE}/api/session/close`;
            const payload = JSON.stringify({
                user_id: user?.id || 'anonymous',
                session_id: currentSessionId
            });

            fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: payload,
                keepalive: true,
            });
        };

        window.addEventListener("beforeunload", handleTabClose);
        return () => window.removeEventListener("beforeunload", handleTabClose);
    }, [currentSessionId, user?.id, API_BASE]);

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
                    message="This thread and its messages will be permanently removed. You can't undo this."
                />

                {!isMobile && (
                    <div className="sidebar-toggle-strip">
                        <button
                            type="button"
                            className={`sidebar-toggle-btn ${sidebarTab === 'threads' ? 'active' : ''}`}
                            onClick={() => {
                                setSidebarTab('threads');
                                setIsSidebarOpen(true);
                            }}
                            title="Threads"
                        >
                            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <line x1="3" y1="12" x2="21" y2="12" />
                                <line x1="3" y1="6" x2="21" y2="6" />
                                <line x1="3" y1="18" x2="21" y2="18" />
                            </svg>
                            <span className="sidebar-toggle-label">Threads</span>
                        </button>

                        <button
                            type="button"
                            className={`sidebar-toggle-btn ${sidebarTab === 'files' ? 'active' : ''}`}
                            onClick={() => {
                                setSidebarTab('files');
                                setIsSidebarOpen(true);
                                fetchSessionFiles();
                            }}
                            title="Files"
                            style={{ marginTop: '12px' }}
                        >
                            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                                <polyline points="13 2 13 9 20 9"></polyline>
                            </svg>
                            <span className="sidebar-toggle-label">Files</span>
                        </button>

                        <button
                            type="button"
                            className="sidebar-toggle-btn"
                            onClick={() => setTheme(prev => prev === 'dark' ? 'light' : 'dark')}
                            title={theme === 'dark' ? "Switch to light mode" : "Switch to dark mode"}
                            style={{ marginTop: 'auto', marginBottom: '12px' }}
                        >
                            {theme === 'dark' ? (
                                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <circle cx="12" cy="12" r="5"></circle>
                                    <line x1="12" y1="1" x2="12" y2="3"></line>
                                    <line x1="12" y1="21" x2="12" y2="23"></line>
                                    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
                                    <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
                                    <line x1="1" y1="12" x2="3" y2="12"></line>
                                    <line x1="21" y1="12" x2="23" y2="12"></line>
                                    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
                                    <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
                                </svg>
                            ) : (
                                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
                                </svg>
                            )}
                        </button>
                    </div>
                )}

                <Sidebar
                    sessions={sessions}
                    currentSessionId={currentSessionId}
                    onSelectSession={(sessionId) => {
                        setCurrentSessionId(sessionId);
                        setActiveMobileTab('chat');
                        if (isMobile) setIsSidebarOpen(false);
                    }}
                    onCreateSession={handleCreateSession}
                    onDeleteSession={handleDeleteSession}
                    isLoading={isLoading}
                    isOpen={isSidebarOpen}
                    sidebarTab={sidebarTab}
                    sessionFiles={sessionFiles}
                    onAddFile={() => setIsAddFileModalOpen(true)}
                    onDeleteFile={handleDeleteFile}
                    selectedFileIds={selectedFileIds}
                    toggleFileSelection={toggleFileSelection}
                />

                <AddFileModal
                    isOpen={isAddFileModalOpen}
                    onClose={() => setIsAddFileModalOpen(false)}
                    subTab={modalSubTab}
                    setSubTab={setModalSubTab}
                    onFileUpload={handleFileUpload}
                    onLinkUpload={handleLinkUpload}
                    linkName={linkName}
                    setLinkName={setLinkName}
                    linkUrl={linkUrl}
                    setLinkUrl={setLinkUrl}
                    isUploading={isUploading}
                />

                {isMobile && isSidebarOpen && (
                    <div
                        className="app-sidebar-overlay"
                        onClick={() => setIsSidebarOpen(false)}
                    />
                )}

                {(() => {
                    const codeGroups = [];
                    let responseCount = 0;
                    messages.forEach((msg, idx) => {
                        if (msg.role === 'assistant' && msg.type === 'steps' && msg.steps?.length) {
                            const cells = extractCodeCells(msg.steps);

                            if (msg.steps.length === 1 && cells.length === 1) {
                                cells[0].stepNumber = "Solution";
                            }

                            if (cells.length > 0) {
                                responseCount++;
                                codeGroups.push({
                                    id: `msg-${idx}`,
                                    title: `Response ${responseCount}`,
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
                                title: `Response ${responseCount + 1}`,
                                cells
                            });
                        }
                    }

                    const chatPanelContent = (
                        <>
                            <div className="messages-area">
                                {!currentSessionId && messages.length === 0 ? (
                                    <div className="empty-state">
                                        <h2 className="empty-state-heading">What would you like to work on?</h2>
                                        <p className="empty-state-text">Type below to get started.</p>
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
                                {(selectedFileIds.size > 0 || uploadedFileName) && (
                                    <div className="composer-attachments">
                                        {Array.from(selectedFileIds).map(fid => {
                                            const file = sessionFiles.find(f => f.id === fid);
                                            if (!file) return null;
                                            return (
                                                <div key={fid} className="composer-attachment">
                                                    <span className="composer-attachment-icon">{file.type === 'link' ? '🔗' : '📄'}</span>
                                                    <span className="composer-attachment-name">{file.name}</span>
                                                    <button type="button" className="composer-attachment-remove" onClick={() => toggleFileSelection(fid)} aria-label="Remove">×</button>
                                                </div>
                                            );
                                        })}
                                        {!Array.from(selectedFileIds).some(fid => sessionFiles.find(f => f.id === fid)?.name === uploadedFileName) && uploadedFileName && (
                                            <div className="composer-attachment">
                                                <span className="composer-attachment-name">{uploadedFileName}</span>
                                                <button type="button" className="composer-attachment-remove" onClick={() => { setUploadedFileName(null); setFileContext(null); }} aria-label="Remove file">×</button>
                                            </div>
                                        )}
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
                                    <button type="button" onClick={() => handleSend()} disabled={isLoading || !input.trim()} className="composer-send-btn" aria-label="Send">
                                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                            <line x1="22" y1="2" x2="11" y2="13" />
                                            <polygon points="22 2 15 22 11 13 2 9 22 2" />
                                        </svg>
                                    </button>
                                </div>
                            </div>
                        </>
                    );

                    const codePanelContent = (
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
                    );

                    return (
                        <div className="main-workspace">
                            <header className="app-header">
                                <div className="app-header-left">
                                    {isMobile && (
                                        <button
                                            type="button"
                                            className="app-header-menu-btn"
                                            onClick={() => setIsSidebarOpen(!isSidebarOpen)}
                                            aria-label="Toggle sidebar"
                                            style={{ marginRight: '8px' }}
                                        >
                                            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                                <line x1="3" y1="12" x2="21" y2="12" />
                                                <line x1="3" y1="6" x2="21" y2="6" />
                                                <line x1="3" y1="18" x2="21" y2="18" />
                                            </svg>
                                        </button>
                                    )}
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
                            <ResizableSplitLayout
                                widthPercent={codePanelWidth}
                                setWidthPercent={setCodePanelWidth}
                                leftClassName={`chat-panel ${isMobile ? 'mobile-full' : ''} ${isMobile && activeMobileTab !== 'chat' ? 'hidden' : ''}`}
                                rightClassName={`code-output-panel ${isMobile ? 'mobile-full' : ''} ${isMobile && activeMobileTab !== 'code' ? 'hidden' : ''}`}
                                left={chatPanelContent}
                                right={codePanelContent}
                            />
                        </div>
                    );
                })()}
            </div>
            {isMobile && (
                <div className="mobile-tab-bar">
                    <button
                        className={`mobile-tab-btn ${activeMobileTab === 'chat' ? 'active' : ''}`}
                        onClick={() => setActiveMobileTab('chat')}
                    >
                        Chat
                    </button>
                    <button
                        className={`mobile-tab-btn ${activeMobileTab === 'code' ? 'active' : ''}`}
                        onClick={() => setActiveMobileTab('code')}
                    >
                        Code
                    </button>
                </div>
            )}
        </div>
    )
}


export default App