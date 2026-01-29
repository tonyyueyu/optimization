import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import PropTypes from 'prop-types';

// Assume the backend is running on localhost:8000
const BACKEND_API_URL = '/api/chat';

const initialMessages = [
  { sender: 'assistant', text: "Hi, I am HippoFlo, your scientific computing assistant." }
];

function ChatPanel({ sessionId, cells, cellOutputs, onCodeReceived, selectedKernel }) {
  // State for the list of messages
  // Each message could be an object like { sender: 'user' | 'assistant', text: 'message content' }
  const [messages, setMessages] = useState(initialMessages);

  // State for the current value in the input field
  const [inputValue, setInputValue] = useState('');

  const [isLoading, setIsLoading] = useState(false); // State to track loading

  // Ref for the message list div
  const messageListRef = useRef(null);
  const textareaRef = useRef(null); // Ref for the textarea

  // Effect to reset messages when sessionId changes
  useEffect(() => {
    console.log("ChatPanel: sessionId changed to", sessionId, ". Resetting messages.");
    setMessages(initialMessages);
    setInputValue(''); // Also clear input field
    // Backend chat history is tied to sessionId, so new session starts fresh there.
  }, [sessionId]);

  // Function to scroll message list to the bottom
  const scrollToBottom = () => {
    // Add slight delay to allow DOM update before scrolling
    setTimeout(() => {
        if (messageListRef.current) {
            messageListRef.current.scrollTop = messageListRef.current.scrollHeight;
        }
    }, 0);
  };

  // Scroll to bottom whenever messages update
  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Function to adjust textarea height
  const adjustTextareaHeight = () => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto'; // Reset height to recalculate scrollHeight
      textarea.style.height = `${textarea.scrollHeight}px`; // Set height based on content
    }
  };

  // Adjust height on input change
  const handleInputChange = (event) => {
    setInputValue(event.target.value);
    // We'll use useEffect for height adjustment to handle all value changes
  };

  // Adjust height whenever inputValue changes
  useEffect(() => {
    adjustTextareaHeight();
  }, [inputValue]);

  const handleSendMessage = async () => {
    const userMessageText = inputValue.trim();
    if (!userMessageText || isLoading || !sessionId) {
      console.error("ChatPanel: Cannot send message: Text empty, loading, or session ID missing.");
      return;
    }

    // --- Construct Code Panel Context String --- //
    let codePanelContext = "\n\n--- Current Code Panel State ---\n";
    if (cells && cells.length > 0) {
      cells.forEach(cell => {
        codePanelContext += `\n\n[Cell ${cell.id} - Code]\n\`\`\`python\n${cell.content}\n\`\`\`\n`;
        const output = cellOutputs[cell.id];
        if (output) {
          if (output.output) {
            codePanelContext += `[Cell ${cell.id} - stdout]\n${output.output}\n`;
          }
          if (output.error) {
            codePanelContext += `[Cell ${cell.id} - stderr/error] (${output.error_type || 'unknown'})\n${output.error}\n`;
          }
          if (output.image_data) {
             codePanelContext += `[Cell ${cell.id} - image output generated (type: ${output.image_mime_type})]\n`;
          }
        }
      });
    } else {
      codePanelContext += "\n(Code Panel is empty)\n";
    }
    codePanelContext += "--- End Code Panel State ---\n";
    // console.log("Code Panel Context:", codePanelContext); // Debugging

    // 1. Add user message to state immediately
    const newUserMessage = { sender: 'user', text: userMessageText };
    setMessages(prevMessages => [...prevMessages, newUserMessage]);

    // 2. Clear input field and reset height
    setInputValue('');
    // Height adjustment will happen automatically via the useEffect watching inputValue

    setIsLoading(true); // Set loading state

    try {
      // 3. Call backend API, including session_id and code_panel_context
      const response = await fetch(BACKEND_API_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ 
          text: userMessageText, 
          session_id: sessionId,
          code_panel_context: codePanelContext, // Add code panel context string
          kernel_name: selectedKernel // Use kernel_name to match backend model
        })
      });

      if (!response.ok) {
        // Handle HTTP errors (e.g., 500 Internal Server Error)
        const errorData = await response.json().catch(() => ({ detail: response.statusText })); // Try to parse error detail
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }

      const data = await response.json(); // response = { response: raw_text, explanation: ..., code_snippet: ... }

      // Determine the text to display in the chat
      const chatText = data.explanation?.trim() || data.response;
      
      // Add assistant message (explanation part) to chat state
      const assistantMessage = { sender: 'assistant', text: chatText };
      setMessages(prevMessages => [...prevMessages, assistantMessage]);

      // If a code snippet was received, pass it up via the callback
      if (data.code_snippet) {
        console.log("Code snippet received from backend, calling onCodeReceived...");
        if (typeof onCodeReceived === 'function') {
          onCodeReceived(data.code_snippet);
        } else {
          console.warn("ChatPanel received code but onCodeReceived prop is not a function.");
        }
      }

    } catch (error) {
      console.error("ChatPanel: Error sending message:", error);
      // Add an error message to the chat state
      const errorMessage = { sender: 'assistant', text: `Error: ${error.message || 'Could not reach backend.'}` };
      setMessages(prevMessages => [...prevMessages, errorMessage]);
    } finally {
        setIsLoading(false); // Reset loading state
    }
  };

  const handleKeyPress = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="chat-panel">
      <div className="panel-header">
        <h2>HippoFlo v0.1</h2>
      </div>

      {/* Message Display Area */}
      <div ref={messageListRef} className="message-list">
        {messages.map((msg, index) => (
          <div key={index} className={`message ${msg.sender}`}>
            {msg.sender === 'assistant' ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>
            ) : (
              msg.text // Keep rendering user messages as plain text
            )}
          </div>
        ))}
        {isLoading && (
            <div className="loading-indicator">
              <i>HippoFlo is thinking<span className="dot-container">
                <span className="dot dot1">.</span>
                <span className="dot dot2">.</span>
                <span className="dot dot3">.</span>
              </span></i>
            </div>
         )}
      </div>

      {/* Input Area */}
      <div className="input-area">
        <textarea
          ref={textareaRef} // Assign the ref
          value={inputValue}
          onChange={handleInputChange}
          onKeyPress={handleKeyPress}
          placeholder={isLoading ? "Waiting for response..." : "Type your message..."}
          rows="1" // Start with 1 row, CSS handles height/scrolling
          disabled={isLoading} // Only disable textarea when loading
          // Add an onInput handler as well, sometimes more reliable for height changes
          onInput={adjustTextareaHeight}
        />
        <button 
          className="send-icon-button" 
          onClick={handleSendMessage} 
          // Disable if loading OR if input is empty (after trimming)
          disabled={isLoading || !inputValue.trim()}
          title="Send message"
        >
          {/* Arrow is now drawn using CSS ::after pseudo-element */}
        </button>
      </div>
    </div>
  );
}

ChatPanel.propTypes = {
  sessionId: PropTypes.string,
  cells: PropTypes.array.isRequired,
  cellOutputs: PropTypes.object.isRequired,
  onCodeReceived: PropTypes.func.isRequired,
  selectedKernel: PropTypes.string
};

export default ChatPanel;
