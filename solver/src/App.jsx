import { useState, useRef, useEffect, useCallback } from 'react'
import { useGoogleLogin } from '@react-oauth/google'
import './App.css'

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [streamingContent, setStreamingContent] = useState(null)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState(null)
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [isCheckingAuth, setIsCheckingAuth] = useState(true)
  const messagesEndRef = useRef(null)
  const abortControllerRef = useRef(null)
  const userUIDRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  // Check if user is authenticated on mount
  useEffect(() => {
    const userUID = localStorage.getItem('user_uid')
    if (userUID) {
      // Check if it's a Google user ID (typically a numeric string) or generated UID
      setIsAuthenticated(true)
      userUIDRef.current = userUID
    } else {
      setIsAuthenticated(false)
    }
    setIsCheckingAuth(false)
  }, [])

  // Google OAuth login handler
  const googleLogin = useGoogleLogin({
    // For popup flows, the redirect URI is typically just the origin
    // But we can try to use the callback path if configured
    redirectUri: window.location.origin, // Use origin for popup flows
    onSuccess: async (tokenResponse) => {
      try {
        // Get user info from Google
        const userInfoResponse = await fetch('https://www.googleapis.com/oauth2/v3/userinfo', {
          headers: {
            Authorization: `Bearer ${tokenResponse.access_token}`
          }
        })
        
        if (!userInfoResponse.ok) {
          throw new Error('Failed to fetch user info')
        }
        
        const userInfo = await userInfoResponse.json()
        
        // Store Google user ID in localStorage
        if (userInfo.sub) {
          localStorage.setItem('user_uid', userInfo.sub)
          userUIDRef.current = userInfo.sub
          setIsAuthenticated(true)
          
          // Fetch chat history after login
          fetchChatHistory()
        }
      } catch (error) {
        alert('Failed to complete login. Please try again.')
      }
    },
    onError: (error) => {
      let errorMessage = 'Login failed. Please try again.'
      
      if (error.error === 'redirect_uri_mismatch' || error.error_description?.includes('redirect_uri_mismatch')) {
        const currentOrigin = window.location.origin
        
        errorMessage = `Redirect URI Mismatch Error!\n\n` +
          `Popup OAuth flows use the ORIGIN (no path) as redirect URI.\n\n` +
          `You currently have: http://localhost:5173/auth/callback\n` +
          `But popup flows need: ${currentOrigin}\n\n` +
          `SOLUTION: In Google Cloud Console:\n` +
          `1. Go to: APIs & Services → Credentials → Your OAuth 2.0 Client ID\n` +
          `2. Under "Authorized JavaScript origins", add:\n` +
          `   - ${currentOrigin}\n` +
          `   - http://localhost\n` +
          `   - http://localhost:5173\n\n` +
          `3. Under "Authorized redirect URIs", ADD THIS:\n` +
          `   - ${currentOrigin}\n\n` +
          `   (Keep your existing: http://localhost:5173/auth/callback)\n\n` +
          `4. Click SAVE\n` +
          `5. Wait 1-2 minutes, then try again\n\n` +
          `The popup flow uses ${currentOrigin} (origin only, no path).`
      }
      
      alert(errorMessage)
    }
  })

  const handleLogout = () => {
    localStorage.removeItem('user_uid')
    setIsAuthenticated(false)
    setMessages([])
    userUIDRef.current = null
  }

  const fetchChatHistory = useCallback(async () => {
    const userUID = localStorage.getItem('user_uid')

    if (!userUID) {
      setHistoryLoading(false);
      return;
    }

    setHistoryLoading(true);
    setHistoryError(null);

    try {
      const response = await fetch('http://localhost:5001/api/chathistory', {
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
              error: step.error || ''
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


  }, []);
  
  useEffect(() => {
    if (isAuthenticated) {
      fetchChatHistory()
    }
  }, [fetchChatHistory, isAuthenticated])

  useEffect(() => {
    scrollToBottom()
  }, [messages, streamingContent])

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

    const userUID = localStorage.getItem('user_uid')
    const userMessage = { role: 'user', content: input.trim() };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    setStreamingContent({
      steps: [],
      currentStep: null,
      currentTokens: '',
      status: 'retrieving'
    });

    abortControllerRef.current = new AbortController();

    try {
      const retrieveResponse = await fetch('http://localhost:5001/api/retrieve', {
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
      const first = retrievedProblems[0]?.problem || "";
      const second = retrievedProblems[1]?.problem || "";

      setStreamingContent(prev => ({ ...prev, status: 'solving' }));

      const response = await fetch('http://localhost:5001/api/solve', {
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
        };

        setStreamingContent(prev => ({
          ...prev,
          steps: [...prev.steps, formattedStep],
          currentStep: null,
          currentTokens: '',
          status: 'waiting'
        }));
        break;

      case 'done':
        setStreamingContent(prev => {
          const finalSteps = prev.steps;

          const assistantMessage = finalSteps.length > 0
            ? {
              role: 'assistant',
              type: 'steps',
              title: 'Solution Steps',
              summary: '',
              steps: finalSteps,
            }
            : {
              role: 'assistant',
              type: 'text',
              content: 'No solution steps were generated.',
            };

          setMessages(msgs => [...msgs, assistantMessage]);
          return null;
        });
        break;

      case 'error':
        setStreamingContent(null);
        const errorMessage = {
          role: 'assistant',
          type: 'text',
          content: `Error: ${event.data.message}`
        };
        setMessages(prev => [...prev, errorMessage]);
        break;

      default:
        // Unknown event type
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
    const userUID = localStorage.getItem('user_uid')
    if (!userUID) return

    try {
      const response = await fetch('http://localhost:5001/api/chathistory/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: userUID }),
      })

      if (response.ok) {
        setMessages([])
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

  const renderStreamingContent = () => {
    if (!streamingContent) return null;

    return (
      <div className="message assistant">
        <div className="message-content">
          <div className="assistant-message streaming">
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

            <div className="steps-list">
              {/* Completed steps */}
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
                    {step.code && (
                      <div className="step-field">
                        <div className="step-label">Code</div>
                        {renderCodeBlock(step.code, step.language)}
                      </div>
                    )}
                    {step.output && (
                      <div className="step-field">
                        <div className="step-label">Output</div>
                        {renderPlainBlock(step.output)}
                      </div>
                    )}
                    {step.error && (
                      <div className="step-field error">
                        <div className="step-label">Error</div>
                        {renderPlainBlock(step.error)}
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {/* Currently streaming step */}
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
                      <div className="streaming-tokens">
                        <pre className="token-stream">{streamingContent.currentTokens}</pre>
                        <span className="cursor">|</span>
                      </div>
                    )}
                  </div>
                </div>
              )}
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

  const renderAssistantSteps = (message) => (
    <div className="assistant-message">
      <div className="steps-header">
        <div className="steps-title">
          <span role="img" aria-label="solution">📝</span>
          <span>{message.title || 'Solution Steps'}</span>
        </div>
        {message.summary && <p className="steps-summary">{message.summary}</p>}
      </div>

      <div className="steps-list">
        {message.steps.map((step) => (
          <div key={step.number} className="step-container">
            <div className="step-header">
              <span className="step-number">{step.number}</span>
              <span className="step-title">{step.title}</span>
            </div>
            <div className="step-content">
              {step.description && (
                <p className="step-text">{step.description}</p>
              )}
              {step.code && (
                <div className="step-field">
                  <div className="step-label">Code</div>
                  {renderCodeBlock(step.code, step.language)}
                </div>
              )}
              {step.output && (
                <div className="step-field">
                  <div className="step-label">Output</div>
                  {renderPlainBlock(step.output)}
                </div>
              )}
              {step.error && (
                <div className="step-field error">
                  <div className="step-label">Error</div>
                  {renderPlainBlock(step.error)}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )

  const renderPlainText = (text = '') => (
    <div className="assistant-message">
      <pre className="plain-response">{text}</pre>
    </div>
  )

  const renderUserMessage = (text = '') => (
    <pre className="user-message-text">{text}</pre>
  )

  const renderCodeBlock = (code, language = 'text') => (
    <pre className="code-block">
      <code className={language ? `language-${language}` : ''}>{code}</code>
    </pre>
  )

  const renderPlainBlock = (value = '') => (
    <pre className="plain-block">{value}</pre>
  )

  // Show loading state while checking authentication
  if (isCheckingAuth) {
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

  // Show login screen if not authenticated
  if (!isAuthenticated) {
    return (
      <div className="app">
        <div className="chat-container">
          <div className="empty-state">
            <h2>Welcome to Chat Assistant</h2>
            <p>Please sign in with Google to continue</p>
            <button 
              onClick={googleLogin} 
              className="login-button"
              style={{
                marginTop: '20px',
                padding: '12px 24px',
                fontSize: '16px',
                backgroundColor: '#4285f4',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '10px'
              }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24">
                <path fill="currentColor" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                <path fill="currentColor" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                <path fill="currentColor" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                <path fill="currentColor" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
              </svg>
              Sign in with Google
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="app">
      <div className="chat-container">
        <div className="chat-header">
          <h1>Chat Assistant</h1>
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
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
            <button 
              onClick={handleLogout} 
              className="cancel-button"
              style={{ fontSize: '14px', padding: '8px 16px' }}
            >
              Logout
            </button>
          </div>
        </div>

        <div className="messages-container">
          {messages.length === 0 && !streamingContent ? (
            <div className="empty-state">
              <h2>Start a conversation</h2>
              <p>Type a message below to begin</p>
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
              {renderStreamingContent()}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="input-container">
          <div className="input-wrapper">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyPress}
              placeholder="Type your message here..."
              rows={1}
              disabled={isLoading}
              className="chat-input"
            />
            <button
              onClick={handleSend}
              disabled={isLoading || !input.trim()}
              className="send-button"
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
  )
}

export default App