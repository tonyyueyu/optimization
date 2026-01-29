import React, { useState, useEffect } from 'react';
import ChatPanel from './components/ChatPanel';
import CodePanel from './components/CodePanel';
import './index.css';

// Constants moved up from CodePanel
const API_BASE_URL = '/api'; 
const SESSION_STORAGE_KEY = 'hippoFloSessionId';

const INITIAL_CELL_CONTENT_PYTHON = '# Python kernel activated.';
const INITIAL_CELL_CONTENT_JULIA = '# Julia kernel activated.';

function App() {
  // Lifted state for cells
  const [cells, setCells] = useState([
    { id: 1, type: 'code', content: INITIAL_CELL_CONTENT_PYTHON },
  ]);

  // Lifted state for cell outputs
  const [cellOutputs, setCellOutputs] = useState({}); // { cellId: { output: ..., error: ..., ... } }

  // Lifted state for sessionId
  const [sessionId, setSessionId] = useState(() => {
    // Initialize from sessionStorage or generate new
    const storedSessionId = sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (storedSessionId) {
      console.log('App: Restored Session ID:', storedSessionId);
      return storedSessionId;
    }
    const newSessionId = crypto.randomUUID();
    sessionStorage.setItem(SESSION_STORAGE_KEY, newSessionId);
    console.log('App: Generated new Session ID:', newSessionId);
    return newSessionId;
  });

  // Lifted state for selectedKernel
  const [selectedKernel, setSelectedKernel] = useState('python');

  // Effect to update sessionStorage when sessionId changes *programmatically*
  useEffect(() => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, sessionId);
    console.log('App: Session ID updated in sessionStorage:', sessionId);
  }, [sessionId]);

  // Function to add a new code cell 
  const handleCodeReceived = (codeSnippet) => {
    console.log("App: Received code snippet:", codeSnippet);
    setCells(currentCells => {
      const nextId = currentCells.length > 0 ? Math.max(...currentCells.map(c => c.id)) + 1 : 1;
      const newCell = {
        id: nextId,
        type: 'code',
        content: codeSnippet,
        runAutomatically: true // Add flag to trigger auto-run
      };
      return [...currentCells, newCell];
    });
  };

  // Function to be called by CodePanel when a kernel switch requires a new session
  const handleNewSessionStart = (newSessionId, newKernelName) => {
    console.log(`App: Starting new session ${newSessionId} for kernel ${newKernelName}`);
    setSessionId(newSessionId);
    setSelectedKernel(newKernelName);
    const initialContent = newKernelName === 'julia' ? INITIAL_CELL_CONTENT_JULIA : INITIAL_CELL_CONTENT_PYTHON;
    setCells([{ id: 1, type: 'code', content: initialContent }]);
    setCellOutputs({});
    // Chat history on the backend is per session_id, so it will be fresh.
    // ChatPanel itself will re-initialize due to sessionId prop change (see ChatPanel modifications).
  };

  // Effect to run code automatically when a cell is marked
  useEffect(() => {
    const cellToAutoRun = cells.find(cell => cell.runAutomatically);
    if (cellToAutoRun && sessionId && selectedKernel) {
      console.log(`App: useEffect auto-running cell ${cellToAutoRun.id} with kernel ${selectedKernel}.`);
      handleRunCode(cellToAutoRun.id, cellToAutoRun.content, selectedKernel);
      setCells(currentCells => 
        currentCells.map(cell => 
          cell.id === cellToAutoRun.id ? { ...cell, runAutomatically: false } : cell
        )
      );
    }
  }, [cells, sessionId, selectedKernel]);

  // Lifted function to handle content change
  const handleContentChange = (cellId, newContent) => {
    setCells(currentCells =>
      currentCells.map(cell =>
        cell.id === cellId ? { ...cell, content: newContent } : cell
      )
    );
  };

  // Updated handleRunCode to accept kernelName
  const handleRunCode = async (cellId, codeContent, kernelName) => {
    if (!codeContent || !sessionId || !kernelName) { 
      console.error("App: Cannot run code: Missing required info.", {cellId, sessionId, kernelName, hasCode: !!codeContent});
      setCellOutputs(prev => ({ ...prev, [cellId]: { output: null, error: 'Client error: Missing required info for execution.', error_type: 'client_error', image_data: null, image_mime_type: null } }));
      return;
    }

    console.log(`App: Running code for cell ${cellId}, session ${sessionId}, kernel ${kernelName}`);
    setCellOutputs(prev => ({ ...prev, [cellId]: { output: 'Running...', error: null, error_type: null, image_data: null, image_mime_type: null } }));

    try {
      const response = await fetch(`${API_BASE_URL}/execute`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          code: codeContent, // Use passed codeContent
          session_id: sessionId,
          kernel_name: kernelName // Pass kernel_name to backend
        }),
      });

      let result = {};
      try {
        result = await response.json();
      } catch (parseError) {
        result.detail = await response.text() || `HTTP error! status: ${response.status}`;
      }

      if (!response.ok) {
        throw new Error(result.detail || `HTTP error! status: ${response.status}`);
      }

      const errorToDisplay = result.error ? result.error : result.stderr;
      const errorTypeToDisplay = result.error_type || (errorToDisplay ? 'unknown_kernel_error' : null);
      setCellOutputs(prev => ({ 
        ...prev, 
        [cellId]: { 
          output: result.stdout, 
          error: errorToDisplay, 
          error_type: errorTypeToDisplay,
          image_data: result.image_data, 
          image_mime_type: result.image_mime_type
        } 
      }));

    } catch (error) {
      console.error(`App: Failed to execute code for cell ${cellId}:`, error);
      const backendErrorMessage = error.message || 'Unknown error during fetch';
      setCellOutputs(prev => ({ 
        ...prev, 
        [cellId]: { 
          output: null, 
          error: backendErrorMessage, 
          error_type: 'http_error', 
          image_data: null,
          image_mime_type: null
        } 
      }));
    }
  };

  // Function to call backend to reset session state for the *old* session ID
  const handleSessionReset = async (oldSessionId) => {
    if (!oldSessionId) return;
    console.log(`App: Requesting reset for old session ID: ${oldSessionId}`);
    try {
      const response = await fetch(`${API_BASE_URL}/reset_session`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: oldSessionId }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: response.statusText }));
        console.error(`App: Failed to reset old session ${oldSessionId}:`, errorData.detail);
      } else {
        console.log(`App: Successfully requested reset for old session ${oldSessionId}.`);
      }
    } catch (error) {
      console.error(`App: Network error resetting old session ${oldSessionId}:`, error);
    }
  };

  return (
    <div className="app-container">
      <ChatPanel 
        sessionId={sessionId} 
        cells={cells} 
        cellOutputs={cellOutputs}
        onCodeReceived={handleCodeReceived}
        selectedKernel={selectedKernel}
      />
      {/* Pass down all necessary state and callbacks */}
      <CodePanel 
        sessionId={sessionId}
        selectedKernel={selectedKernel}
        setSelectedKernel={setSelectedKernel}
        onNewSessionStart={handleNewSessionStart}
        onSessionReset={handleSessionReset}
        cells={cells} 
        cellOutputs={cellOutputs}
        onContentChange={handleContentChange}
        onRunCode={handleRunCode}
      />
    </div>
  );
}

export default App;
