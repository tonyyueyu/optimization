import { useState, useRef, useEffect } from 'react'
import './App.css'

// Helper to generate a random Session ID
const generateUUID = () => {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    var r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const [sessionId, setSessionId] = useState(null)
  const [chatHistory, setChatHistory] = useState([]) // List of past session IDs

  const messagesEndRef = useRef(null)

  // 1. Initialize Session on Load
  useEffect(() => {
    // Check if we have a saved history list in browser storage
    const storedHistory = JSON.parse(localStorage.getItem('my_chat_history') || '[]');
    setChatHistory(storedHistory);
    console.log("Loaded chat history:", storedHistory);
    // Check if there was a last active session
    const lastSession = localStorage.getItem('last_active_session');
    
    if (lastSession) {
      setSessionId(lastSession);
      loadChat(lastSession);
    } else {
      startNewChat();
    }
  }, []);

  // 2. Persist History when it changes
  useEffect(() => {
    localStorage.setItem('my_chat_history', JSON.stringify(chatHistory));
  }, [chatHistory]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // Actions
  const startNewChat = () => {
    const newId = generateUUID();
    setSessionId(newId);
    setMessages([]); 
    localStorage.setItem('last_active_session', newId);
    
    // Initialize with a generic name. We will rename it when the user types.
    const newChatEntry = { id: newId, title: 'New Chat' };
    setChatHistory(prev => [newChatEntry, ...prev]);
  };

  const loadChat = async (id) => {
    setSessionId(id);
    localStorage.setItem('last_active_session', id);
    setIsLoading(true); // Show loading state

    try {
      // Call the new backend endpoint
      const response = await fetch(`http://localhost:5000/api/history/${id}`);
      if (!response.ok) throw new Error("Failed to load history");
      
      const historyData = await response.json();
      
      // Update the message window
      setMessages(historyData); 
    } catch (err) {
      console.error("Could not load chat history:", err);
      // If fails, just show empty or an error message
      setMessages([{role: 'assistant', content: 'Could not load past history.'}]);
    } finally {
      setIsLoading(false);
    }
  }



  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const currentInput = input.trim();
    // If this is the very first message in the window, rename the chat
    if (messages.length === 0) {
      const newTitle = currentInput.length > 25 
        ? currentInput.substring(0, 25) + '...' 
        : currentInput;

      setChatHistory(prev => prev.map(chat => 
        chat.id === sessionId ? { ...chat, title: newTitle } : chat
      ));
    }


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
      const first = retrievedProblems[0] ? retrievedProblems[0].problem : "";
      const second = retrievedProblems[1] ? retrievedProblems[1].problem : "";

      const steps = await fetch('http://localhost:5000/api/solve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          problem: first,
          second_problem: second,
          user_query: userMessage.content,
          session_id: sessionId
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

      const stepsRaw = Array.isArray(data?.steps) ? data.steps : [];
      const formattedSteps = stepsRaw.map((step, index) => ({
        number: index + 1,
        title: `Step ${index + 1}`,
        description: step.description ||'',
        code: step.code || '',
        language: 'python',
        output: step.output || step.result || '',
        error: step.error || '',
      }));

      const fallbackResponse = (typeof data === 'string' ? data : JSON.stringify(data, null, 2));

      const assistantMessage = formattedSteps.length
        ? {
            role: 'assistant',
            type: 'steps',
            title: 'Solution Steps',
            summary: '',
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
      
      {/* --- SIDEBAR --- */}
      <div className="sidebar">
        <button onClick={startNewChat} className="new-chat-btn">
          {/* Plus Icon */}
          <svg stroke="currentColor" fill="none" strokeWidth="2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round" height="1em" width="1em" xmlns="http://www.w3.org/2000/svg">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          <span>New Chat</span>
        </button>

        <div className="history-list">
          <div className="history-label">Previous 7 Days</div>
          {chatHistory.map((chat) => (
            <button
              key={chat.id}
              onClick={() => loadChat(chat.id)}
              className={`history-item ${sessionId === chat.id ? 'active' : ''}`}
            >
              {/* Chat Bubble Icon */}
              <svg stroke="currentColor" fill="none" strokeWidth="2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round" height="1em" width="1em" xmlns="http://www.w3.org/2000/svg" style={{marginRight: '8px'}}>
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
              </svg>
              {chat.title}
            </button>
          ))}
        </div>
      </div>

      {/* --- MAIN CHAT AREA --- */}
      <div className="chat-container">
        <div className="chat-header">
          <h1>Chat Assistant</h1>
        </div>

        <div className="messages-container">
          {messages.length === 0 ? (
            <div className="empty-state">
              <h2>How can I help you today?</h2>
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
                  <span></span><span></span><span></span>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>      const first = retrievedProblems[0] ? retrievedProblems[0].problem : "";


        <div className="input-container">
          <div className="input-wrapper">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyPress}
              placeholder="Send a message..."
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
                width="16"
                height="16"
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