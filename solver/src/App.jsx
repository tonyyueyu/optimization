import { useState, useRef, useEffect, useCallback } from 'react'
import './App.css'

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [streamingContent, setStreamingContent] = useState(null)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState(null)
  const messagesEndRef = useRef(null)
  const abortControllerRef = useRef(null)
  const userUIDRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    let userUID = localStorage.getItem('user_uid')
    if (!userUID) {
      userUID = `user_${Math.random().toString(36).substr(2, 9)}`
      localStorage.setItem('user_uid', userUID)
      console.log('Created new user UID:', userUID)
    } else {
      console.log('Existing user UID:', userUID)
    }
    userUIDRef.current = userUID
  }, [])

  const fetchChatHistory = useCallback(async () => {
    const userUID = localStorage.getItem('user_uid')

    if (!userUID) {
      setHistoryLoading(false);
      return;
    }

    setHistoryLoading(true);
    setHistoryError(null);

    try {
      const response = await fetch('http://localhost:5000/api/chathistory', {
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
      console.log('Loaded chat history:', formattedMessages.length, 'messages')
    } catch (err) {
      console.error('Failed to fetch chat history:', err)
      setHistoryError(err.message)
    } finally {
      setHistoryLoading(false)
    }


  }, []);
  useEffect(() => {
    fetchChatHistory()
  }, [fetchChatHistory])

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
          console.error('Failed to parse SSE data:', e)
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
      const retrieveResponse = await fetch('http://localhost:5000/api/retrieve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: userMessage.content, top_n: 2 }),
        signal: abortControllerRef.current.signal
      });

      if (!retrieveResponse.ok) {
        throw new Error('Failed to retrieve relevant problems');
      }

      const retrievedProblems = await retrieveResponse.json();
      console.log('Retrieved Problems:', retrievedProblems);
      const first = retrievedProblems[0]?.problem || "";
      const second = retrievedProblems[1]?.problem || "";

      setStreamingContent(prev => ({ ...prev, status: 'solving' }));

      const response = await fetch('http://localhost:5000/api/solve', {
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
        console.log('Request was cancelled');
        return;
      }

      console.error('Error:', error);
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
          number: event.data.step.step_id || event.data.step_number,
          title: `Step ${event.data.step.step_id || event.data.step_number}`,
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
        console.log('Unknown event:', event);
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
      const response = await fetch('http://localhost:5000/api/chathistory/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: userUID }),
      })

      if (response.ok) {
        setMessages([])
        console.log('Chat history cleared')
      }
    } catch (err) {
      console.error('Failed to clear history:', err)
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

  return (
    <div className="app">
      <div className="chat-container">
        <div className="chat-header">
          <h1>Chat Assistant</h1>
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