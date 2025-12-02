import { useState, useRef, useEffect } from 'react'
import './App.css'

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const userMessage = { role: 'user', content: input.trim() };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const retrieveResponse = await fetch('http://localhost:5000/api/retrieve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: userMessage.content, top_n: 2 })
      });

      if (!retrieveResponse.ok) {
        throw new Error('Failed to retrieve relevant problems');
      }

      const retrievedProblems = await retrieveResponse.json();
      console.log('Retrieved Problems:', retrievedProblems);
      const first = retrievedProblems[0];
      const second = retrievedProblems[1];

      const steps = await fetch('http://localhost:5000/api/solve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          problem: first,
          second_problem: second,
          user_query: userMessage.content
        })
      });

      const raw = await steps.text();

      if (!steps.ok) {
        console.error("Server returned error:", raw);
        throw new Error('Failed to get solution steps. Please try again later.');
      }

      let data;
      try {
        data = JSON.parse(raw);
      } catch (err) {
        console.error("Invalid JSON from server:", raw);
        throw new Error("Server returned invalid JSON.");
      }

      console.log('Solution Steps:', data);

      const stepsRaw = Array.isArray(data?.steps) ? data.steps : [];
      const formattedSteps = stepsRaw.map((step, index) => ({
        number: index + 1,
        title: step.title || step.name || step.heading || `Step ${index + 1}`,
        description: step.description || step.step || step.details || '',
        code: step.code || step.snippet || '',
        language: step.language || 'python',
        output: step.output || step.result || '',
        error: step.error || '',
        notes: step.notes || step.comment || ''
      }));

      const fallbackResponse =
        data.solution ||
        data.response ||
        data.message ||
        data.summary ||
        (typeof data === 'string' ? data : JSON.stringify(data, null, 2));

      const assistantMessage = formattedSteps.length
        ? {
            role: 'assistant',
            type: 'steps',
            title: data.title || 'Solution Steps',
            summary: data.summary || '',
            steps: formattedSteps,
            content: fallbackResponse,
          }
        : {
            role: 'assistant',
            type: 'text',
            content: fallbackResponse || 'No solution steps returned.',
          };

      setMessages(prev => [...prev, assistantMessage]);

    }
    catch (error) {
      console.error('Error:', error);
      const errorMessage = {
        role: 'assistant',
        type: 'text',
        content: `Sorry, I ran into a problem: ${error.message}. Please try again.`
      };
      setMessages(prev => [...prev, errorMessage]);
      return;
    } finally {
      setIsLoading(false);
    }
  }

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

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

              {step.notes && (
                <div className="step-field">
                  <div className="step-label">Notes</div>
                  <p>{step.notes}</p>
                </div>
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
        </div>

        <div className="messages-container">
          {messages.length === 0 ? (
            <div className="empty-state">
              <h2>Start a conversation</h2>
              <p>Type a message below to begin</p>
            </div>
          ) : (
            messages.map((message, index) => (
              <div key={index} className={`message ${message.role}`}>
                <div className="message-content">
                  {renderMessageContent(message)}
                </div>
              </div>
            ))
          )}
          {isLoading && (
            <div className="message assistant">
              <div className="message-content">
                <div className="typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            </div>
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