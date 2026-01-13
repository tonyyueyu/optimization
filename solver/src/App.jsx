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

// --- HELPER: Formats the retrieved JSON ---
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

// --- TYPEWRITER COMPONENT ---
const Typewriter = ({ text, isThinking = false }) => {
  const [displayedText, setDisplayedText] = useState('')
  const targetTextRef = useRef(text)
  const speed = 2 

  useEffect(() => {
    targetTextRef.current = text
  }, [text])

  useEffect(() => {
    const timer = setInterval(() => {
      setDisplayedText((current) => {
        const target = targetTextRef.current
        if (current.length < target.length) {
          return target.slice(0, current.length + 1)
        } else if (current.length > target.length) {
          return target
        }
        return current
      })
    }, speed)

    return () => clearInterval(timer)
  }, [])

  return (
    <pre className="token-stream">
      {displayedText}
      {displayedText.length < text.length || isThinking ? <span className="cursor">|</span> : null}
    </pre>
  )
}

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

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [streamingContent, setStreamingContent] = useState(null)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState(null)
  const [fileContext, setFileContext] = useState(null)

  const { isLoaded, isSignedIn, user } = useUser()
  const messagesEndRef = useRef(null)
  const abortControllerRef = useRef(null)
  const fileInputRef = useRef(null)
  
  // Ref for the auto-growing textarea
  const textareaRef = useRef(null);

  // --- REFS FOR INTERNAL SCROLLING ---
  const streamingStepsRef = useRef(null);
  const streamingCodeRef = useRef(null);

  // --- AUTO-SCROLL LOGIC ---
  
  // 1. Scroll main chat window (Smooth) on new completed messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: "end" })
  }, [messages])

  // 2. Scroll main chat window INSTANTLY during streaming (prevents lag)
  useEffect(() => {
    if (streamingContent) {
        messagesEndRef.current?.scrollIntoView({ behavior: 'auto', block: "end" })
    }
  }, [streamingContent])

  // 3. INTERNAL AUTO-SCROLL: Scroll step list and code block to bottom while streaming
  useEffect(() => {
    if (streamingContent) {
        // requestAnimationFrame waits for the DOM to paint the new height before scrolling
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
  // ----------------------------------

  // --- AUTO-GROW TEXTAREA LOGIC ---
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [input]);
  // --------------------------------

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
         const errorText = await response.text();
         throw new Error(`Upload failed: ${errorText}`);
      }

      const data = await response.json();
      const summary = data.summary || `File '${file.name}' uploaded successfully.`;
      
      setFileContext(summary);
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        type: 'text', 
        content: `✅ File uploaded: ${file.name}\n${summary}` 
      }]);

    } catch (error) {
      console.error("Upload error:", error);
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

  const onDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      handleFileUpload(file);
      e.dataTransfer.clearData();
    }
  }, [user?.id]); 

  const fetchChatHistory = useCallback(async (userUID) => {
    if (!userUID) {
      setHistoryLoading(false)
      setMessages([])
      return
    }

    setHistoryLoading(true);
    setHistoryError(null);

    try {
      const response = await fetch(`${API_BASE}/chathistory`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: userUID }),
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const result = await response.json();

      const formattedMessages = result.history.map(msg => {
        if (msg.role === 'assistant' && msg.type === 'steps') {
          return {
            role: 'assistant',
            type: 'steps',
            title: msg.title || 'Solution Steps',
            summary: msg.summary || '',
            steps: (msg.steps || []).map((step, idx) => ({
              number: step.step_id || idx + 1,
              title: `Step ${step.step_id || idx + 1}`,
              description: step.description || '',
              code: step.code || '',
              language: 'python',
              output: step.output || '',
              error: step.error || '',
              plots: step.plots || []
            }))
          }
        }

        return {
          role: msg.role,
          type: msg.type || 'text',
          content: msg.content || ''
        }
      })

      setMessages(formattedMessages)
    } catch (err) {
      setHistoryError(err.message)
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isSignedIn && user?.id) {
      fetchChatHistory(user.id)
    } else {
      setMessages([])
    }
  }, [fetchChatHistory, isSignedIn, user?.id])


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
        } catch (e) {
          // Failed to parse SSE data
        }
      }
    }
    return events
  }

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const userUID = user?.id
    if (!isSignedIn || !userUID) {
      alert('Please sign in to continue.')
      return
    }
    
    let finalQuery = input.trim();
    if (fileContext) {
      finalQuery = `CONTEXT FROM UPLOADED FILE:\n${fileContext}\n\nUSER QUERY: ${finalQuery}`;
    }

    const userMessage = { role: 'user', content: input.trim() };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    
    // Reset textarea height manually after sending
    if (textareaRef.current) textareaRef.current.style.height = 'auto';

    setIsLoading(true);

    setStreamingContent({
      steps: [],
      currentStep: null,
      currentTokens: '',
      status: 'retrieving'
    });

    abortControllerRef.current = new AbortController();

    try {
      const retrieveResponse = await fetch(`${API_BASE}/retrieve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: userMessage.content, top_n: 2 }),
        signal: abortControllerRef.current.signal
      });

      if (!retrieveResponse.ok) {
        const errorData = await retrieveResponse.json().catch(() => ({}));
        const errorMessage = errorData.detail || errorData.message || 'Failed to retrieve relevant problems';
        throw new Error(errorMessage);
      }

      const retrievedProblems = await retrieveResponse.json();
      const first = formatReference(retrievedProblems[0]);
      const second = formatReference(retrievedProblems[1]);
      
      console.log("Retrieval Complete. Problem IDs:", retrievedProblems.map(p => p.id));

      setStreamingContent(prev => ({ ...prev, status: 'solving' }));

      const response = await fetch(`${API_BASE}/solve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          problem: first,
          second_problem: second,
          user_query: userMessage.content,
          user_id: userUID
        }),
        signal: abortControllerRef.current.signal
      });

      if (!response.ok) {
        throw new Error('Failed to get solution');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = parseSSE(buffer);

        const lastEventEnd = buffer.lastIndexOf('\n\n');
        if (lastEventEnd !== -1) {
          buffer = buffer.slice(lastEventEnd + 2);
        }

        for (const event of events) {
          handleSSEEvent(event);
        }
      }

    } catch (error) {
      if (error.name === 'AbortError') {
        return;
      }

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
          currentTokens: event.data.accumulated
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
            if (exists) {
                return {
                    ...prev,
                    currentStep: null,
                    currentTokens: '',
                    status: 'waiting'
                };
            }
            
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
        const finalBackendSteps = event.data.steps || [];
        
        const assistantMessage = finalBackendSteps.length > 0
          ? {
            role: 'assistant',
            type: 'steps',
            title: 'Solution Steps',
            summary: '',
            steps: finalBackendSteps.map((step, idx) => ({
                number: step.step_id || idx + 1,
                title: `Step ${step.step_id || idx + 1}`,
                description: step.description,
                code: step.code,
                output: step.output,
                error: step.error
            })),
          }
          : {
            role: 'assistant',
            type: 'text',
            content: 'No solution steps were generated.',
          };

        setMessages(msgs => [...msgs, assistantMessage]);
        setStreamingContent(null);
        setIsLoading(false);
        break;

      case 'error':
        setStreamingContent(null);
        const errorMessage = {
          role: 'assistant',
          type: 'text',
          content: `Error: ${event.data.message}`
        };
        setMessages(prev => [...prev, errorMessage]);
        setIsLoading(false);
        break;

      default:
        break;
    }
  };

  const handleCancel = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      setIsLoading(false);
      setStreamingContent(null);
    }
  };

  const handleClearHistory = async () => {
    const userUID = user?.id
    if (!userUID) return

    try {
      const response = await fetch(`${API_BASE}/chathistory/clear`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: userUID }),
      })

      if (response.ok) {
        setMessages([])
        setFileContext(null)
      }
    } catch (err) {
      // Failed to clear history
    }
  }

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const renderJupyterCell = (cell, idx) => (
    <div key={idx} className="jupyter-cell">
      {cell.code && (
        <div className="jupyter-input-cell">
          <div className="jupyter-cell-prompt">In [{cell.stepNumber}]:</div>
          <div className="jupyter-code-content">
            <pre className="jupyter-code"><code>{cell.code}</code></pre>
          </div>
        </div>
      )}
      {cell.plots && cell.plots.length > 0 && (
        <div className="jupyter-plot-cell">
          <div className="jupyter-cell-prompt">Out [{cell.stepNumber}]:</div>
          <div className="jupyter-plot-content">
            {cell.plots.map((plot, plotIdx) => (
              <img
                key={plotIdx}
                src={`data:image/png;base64,${plot}`}
                alt={`Plot ${plotIdx + 1} from step ${cell.stepNumber}`}
                className="jupyter-plot-image"
              />
            ))}
          </div>
        </div>
      )}
      {cell.output && (
        <div className="jupyter-output-cell">
          <div className="jupyter-cell-prompt">Out [{cell.stepNumber}]:</div>
          <div className="jupyter-output-content">
            <pre className="jupyter-output">{cell.output}</pre>
          </div>
        </div>
      )}
      {cell.error && (
        <div className="jupyter-error-cell">
          <div className="jupyter-cell-prompt">Error:</div>
          <div className="jupyter-error-content">
            <pre className="jupyter-error">{cell.error}</pre>
          </div>
        </div>
      )}
    </div>
  )

  const renderStepPreview = (step) => (
    <>
      {step.output && (
        <div className="step-field">
          <div className="step-label">Output</div>
          <div className="step-output-preview">{truncateText(step.output)}</div>
        </div>
      )}
      {step.error && (
        <div className="step-field error">
          <div className="step-label">Error</div>
          <div className="step-error-preview">{truncateText(step.error)}</div>
        </div>
      )}
    </>
  )

  const renderStreamingContent = () => {
    if (!streamingContent) return null;

    const codeCells = extractCodeCells(streamingContent.steps);

    return (
      <div className="message assistant">
        <div className="message-content">
          <div className="assistant-message streaming two-column-layout">
            <div className="steps-column">
              <div className="steps-header">
                <div className="steps-title">
                  <span role="img" aria-label="solution">📝</span>
                  <span>Solution Steps</span>
                  <span className="streaming-indicator">
                    <span className="pulse"></span>
                    {streamingContent.status === 'retrieving' && ' Retrieving...'}
                    {streamingContent.status === 'generating' && ` Generating Step ${streamingContent.currentStep}...`}
                    {streamingContent.status === 'executing' && ` Executing Step ${streamingContent.currentStep}...`}
                    {streamingContent.status === 'waiting' && ' Processing...'}
                  </span>
                </div>
              </div>

              {/* ATTACHED REF TO STEPS LIST FOR AUTO-SCROLL */}
              {/* ADDED INLINE STYLES TO GUARANTEE SCROLLABILITY */}
              <div 
                className="steps-list" 
                ref={streamingStepsRef}
                style={{ maxHeight: '600px', overflowY: 'auto' }}
              >
                {streamingContent.steps.map((step) => (
                  <div key={step.number} className="step-container">
                    <div className="step-header">
                      <span className="step-number">{step.number}</span>
                      <span className="step-title">{step.title}</span>
                      <span className="step-status complete">✓</span>
                    </div>
                    <div className="step-content">
                      {step.description && (
                        <p className="step-text">{step.description}</p>
                      )}
                      {renderStepPreview(step)}
                    </div>
                  </div>
                ))}

                {streamingContent.currentStep && (
                  <div className="step-container streaming-step">
                    <div className="step-header">
                      <span className="step-number">{streamingContent.currentStep}</span>
                      <span className="step-title">Step {streamingContent.currentStep}</span>
                      <span className="step-status generating">
                        <span className="spinner"></span>
                      </span>
                    </div>
                    <div className="step-content">
                      {streamingContent.currentTokens && (
                         <Typewriter text={streamingContent.currentTokens} isThinking={true} />
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div className="code-column">
              <div className="jupyter-header">
                <div className="jupyter-title">
                  <span role="img" aria-label="code">💻</span>
                  <span>Code & Output</span>
                </div>
              </div>
               {/* ATTACHED REF TO NOTEBOOK FOR AUTO-SCROLL */}
               {/* ADDED INLINE STYLES TO GUARANTEE SCROLLABILITY */}
               <div 
                 className="jupyter-notebook" 
                 ref={streamingCodeRef}
                 style={{ maxHeight: '600px', overflowY: 'auto' }}
               >
                 {codeCells.length > 0 ? (
                   codeCells.map(renderJupyterCell)
                 ) : (
                   <div className="jupyter-empty">
                     <p>No code cells yet...</p>
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
      <div className="assistant-message two-column-layout">
        <div className="steps-column">
          <div className="steps-header">
            <div className="steps-title">
              <span role="img" aria-label="solution">📝</span>
              <span>{message.title || 'Solution Steps'}</span>
            </div>
            {message.summary && <p className="steps-summary">{message.summary}</p>}
          </div>

          <div className="steps-list">
            {message.steps.map((step, index) => {
              const isFinalSummary = index === message.steps.length - 1 && !step.code;

              return (
                <div 
                  key={step.number} 
                  className="step-container"
                  style={isFinalSummary ? { borderLeft: '4px solid #22c55e', backgroundColor: 'rgba(34, 197, 94, 0.05)' } : {}}
                >
                  <div className="step-header">
                    <span className="step-number">{step.number}</span>
                    <span className="step-title">
                      {isFinalSummary ? 'Final Solution' : step.title}
                    </span>
                    {isFinalSummary && <span style={{ marginLeft: '8px' }}>🎉</span>}
                  </div>
                  <div className="step-content">
                    {step.description && (
                      <p 
                        className="step-text"
                        style={isFinalSummary ? { fontWeight: '600', color: '#22c55e', fontSize: '1.05em' } : {}}
                      >
                        {step.description}
                      </p>
                    )}
                    {!isFinalSummary && renderStepPreview(step)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="code-column">
          <div className="jupyter-header">
            <div className="jupyter-title">
              <span role="img" aria-label="code">💻</span>
              <span>Code & Output</span>
            </div>
          </div>
          <div className="jupyter-notebook">
            {codeCells.length > 0 ? (
              codeCells.map(renderJupyterCell)
            ) : (
              <div className="jupyter-empty">
                <p>No code cells to display</p>
              </div>
            )}
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

  if (!isLoaded) {
    return (
      <div className="app">
        <div className="chat-container">
          <div className="empty-state">
            <h2>Loading...</h2>
          </div>
        </div>
      </div>
    )
  }

  return (
    <>
      <SignedOut>
        <div className="app">
          <div className="chat-container">
            <div className="empty-state">
              <h2>Welcome to Chat Assistant</h2>
              <p>Please sign in to continue</p>
              <SignInButton mode="modal">
                <button
                  className="login-button"
                  style={{
                    marginTop: '20px',
                    padding: '12px 24px',
                    fontSize: '16px'
                  }}
                >
                  Sign in with Clerk
                </button>
              </SignInButton>
            </div>
          </div>
        </div>
      </SignedOut>

      <SignedIn>
        <div 
            className="app"
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
        >
          {isDragging && (
            <div className="drag-overlay" style={{
                position: 'absolute',
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                backgroundColor: 'rgba(0,0,0,0.7)',
                zIndex: 1000,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'white',
                fontSize: '24px',
                fontWeight: 'bold',
                border: '4px dashed white',
                margin: '20px',
                borderRadius: '10px'
            }}>
                Drop file to upload
            </div>
          )}

          <div className="chat-container">
            <div className="chat-header">
              <h1>Chat Assistant</h1>
              <div className="header-buttons">
                {isLoading && (
                  <button onClick={handleCancel} className="cancel-button">
                    Cancel
                  </button>
                )}
                {messages.length > 0 && !isLoading && (
                  <button onClick={handleClearHistory} className="cancel-button">
                    Clear History
                  </button>
                )}
                <UserButton />
                <SignOutButton>
                  <button className="cancel-button logout-button">
                    Logout
                  </button>
                </SignOutButton>
              </div>
            </div>

            <div className="messages-container">
              {messages.length === 0 && !streamingContent ? (
                <div className="empty-state">
                  <h2>Start a conversation</h2>
                  <p>Type a message or drag & drop a file</p>
                </div>
              ) : (
                <>
                  {messages.map((message, index) => (
                    <div key={index} className={`message ${message.role}`}>
                      <div className="message-content">
                        {renderMessageContent(message)}
                      </div>
                    </div>
                  ))}
                  
                  {isLoading && streamingContent && renderStreamingContent()}
                </>
              )}
              <div ref={messagesEndRef} />
            </div>

            <div className="input-container">
              <div className="input-wrapper" style={{ display: 'flex', alignItems: 'flex-end', gap: '8px' }}>
                <input 
                    type="file" 
                    ref={fileInputRef} 
                    style={{ display: 'none' }} 
                    onChange={(e) => {
                        if (e.target.files?.[0]) handleFileUpload(e.target.files[0]);
                    }}
                />
                <button
                    className="upload-button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={isLoading || isUploading}
                    style={{
                        background: 'transparent',
                        border: '1px solid #ccc',
                        borderRadius: '6px',
                        width: '40px',
                        height: '40px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                        color: 'var(--text-color, #fff)',
                        padding: 0,
                        marginBottom: '2px' // Align with bottom of textarea
                    }}
                    title="Upload file"
                >
                    {isUploading ? (
                        <div className="spinner" style={{ width: '16px', height: '16px' }}></div>
                    ) : (
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <line x1="12" y1="5" x2="12" y2="19"></line>
                            <line x1="5" y1="12" x2="19" y2="12"></line>
                        </svg>
                    )}
                </button>

                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyPress}
                  placeholder={isUploading ? "Uploading..." : "Type your message here..."}
                  rows={1}
                  disabled={isLoading}
                  className="chat-input"
                  style={{ 
                    flex: 1, 
                    maxHeight: '200px', 
                    resize: 'none', 
                    overflowY: 'auto'
                  }} 
                />
                <button
                  onClick={handleSend}
                  disabled={isLoading || !input.trim()}
                  className="send-button"
                  style={{ marginBottom: '2px' }} // Align with bottom of textarea
                >
                  <svg
                    width="20"
                    height="20"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
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