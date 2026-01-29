import React, { useState, useEffect, useRef } from 'react';
import CodeCell from './CodeCell';
import SettingsWindow from './SettingsWindow';
import { UserRoundCog, Settings, MessageCircleMore, Check } from 'lucide-react';

// Simple icon components for kernel selection
const PythonIcon = () => (
  <div style={{
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    width: '16px', height: '16px', borderRadius: '50%', border: '1.5px solid currentColor',
    fontSize: '12px', fontWeight: 'bold', lineHeight: '1'
  }}>P</div>
);

const JuliaIcon = () => (
  <div style={{
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    width: '16px', height: '16px', borderRadius: '50%', border: '1.5px solid currentColor',
    fontSize: '12px', fontWeight: 'bold', lineHeight: '1'
  }}>J</div>
);

// Updated props to include selectedKernel and setSelectedKernel from App.jsx
function CodePanel({ 
  cells, cellOutputs, onContentChange, onRunCode, 
  sessionId, onNewSessionStart, onSessionReset, 
  selectedKernel, setSelectedKernel 
}) {
  // State to track collapsed state for each cell { cellId: boolean }
  // Default to collapsed (true)
  const [collapsedStates, setCollapsedStates] = useState({});
  const notebookRef = useRef(null);
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const userMenuRef = useRef(null);
  const userMenuButtonRef = useRef(null);

  // State for kernel selection dropdown
  const [isKernelMenuOpen, setIsKernelMenuOpen] = useState(false);
  const kernelMenuButtonRef = useRef(null);
  const kernelMenuRef = useRef(null);

  // To track if ensure_kernel has been called for the current session/kernel combo
  const [kernelEnsured, setKernelEnsured] = useState({}); // E.g., {"python_session123": true}
  const ensureCallInFlight = useRef({}); // Ref to track in-flight calls, e.g., {"python_session123": true}

  // Function to toggle the collapsed state for a cell
  const handleToggleCollapse = (cellId) => {
    setCollapsedStates(prev => ({ ...prev, [cellId]: !(prev[cellId] !== false) }));
  };

  // Toggle user menu open/closed
  const toggleUserMenu = () => {
    setIsUserMenuOpen(prev => !prev);
  };

  // Function to open settings window
  const openSettings = () => {
    setIsSettingsOpen(true);
    setIsUserMenuOpen(false);
  };

  // Function to close settings window
  const closeSettings = () => {
    setIsSettingsOpen(false);
  };

  // Kernel menu functions
  const toggleKernelMenu = () => {
    setIsKernelMenuOpen(prev => !prev);
  };

  const handleSelectKernel = async (newKernelName) => {
    setIsKernelMenuOpen(false);
    if (newKernelName !== selectedKernel) {
      console.log(`CodePanel: Kernel changed from ${selectedKernel} to ${newKernelName}. Requesting new session.`);
      const oldSessionId = sessionId;
      const newSessionId = crypto.randomUUID();
      
      if (onNewSessionStart) {
        // onNewSessionStart in App.jsx will call setSelectedKernel(newKernelName)
        onNewSessionStart(newSessionId, newKernelName);
      }
      // setSelectedKernel(newKernelName); // REMOVED - App.jsx handles this via onNewSessionStart
      setKernelEnsured({}); 
      
      if (onSessionReset && oldSessionId) {
        await onSessionReset(oldSessionId);
      }
    } else {
      console.log(`CodePanel: Kernel ${newKernelName} already selected.`);
    }
  };

  // Effect to pre-warm kernel when sessionId or selectedKernel changes
  useEffect(() => {
    const ensureKey = `${selectedKernel}_${sessionId}`;
    console.log(`CodePanel Effect: Evaluating ensure_kernel. Session: ${sessionId}, Kernel: ${selectedKernel}, EnsureKey: ${ensureKey}, AlreadyEnsured: ${!!kernelEnsured[ensureKey]}, InFlight: ${!!ensureCallInFlight.current[ensureKey]}`);

    if (sessionId && selectedKernel && !kernelEnsured[ensureKey] && !ensureCallInFlight.current[ensureKey]) {
      console.log(`CodePanel Effect: CALLING ensureKernelIsReady. Session: ${sessionId}, Kernel: ${selectedKernel}, Key: ${ensureKey}`);
      
      const ensureKernelIsReady = async () => {
        ensureCallInFlight.current[ensureKey] = true; // Mark as in-flight for this specific key
        try {
          const response = await fetch('/api/ensure_kernel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId, kernel_name: selectedKernel }),
          });
          if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: response.statusText }));
            console.error(`Error ensuring kernel ${selectedKernel} for session ${sessionId}:`, errorData.detail);
            // Consider resetting inFlight flag on error if retries are desired, or based on error type
          } else {
            const data = await response.json();
            console.log(`Kernel ${selectedKernel} for session ${sessionId} ensured (kernel ID: ${data.kernel_id}). Message: ${data.message}. Setting ensureKey: ${ensureKey} to true.`);
            setKernelEnsured(prev => ({...prev, [ensureKey]: true }));
          }
        } catch (error) {
          console.error(`Network error ensuring kernel ${selectedKernel} for session ${sessionId}:`, error);
          // Consider resetting inFlight flag on error
        } finally {
          ensureCallInFlight.current[ensureKey] = false; // Clear in-flight status for this key when done (success or fail)
        }
      };
      ensureKernelIsReady();
    } else if (sessionId && selectedKernel && kernelEnsured[ensureKey]){
      console.log(`CodePanel Effect: SKIPPING ensureKernelIsReady (already ensured). Session: ${sessionId}, Kernel: ${selectedKernel}, Key: ${ensureKey}`);
    } else if (sessionId && selectedKernel && ensureCallInFlight.current[ensureKey]) {
      console.log(`CodePanel Effect: SKIPPING ensureKernelIsReady (call already in flight). Session: ${sessionId}, Kernel: ${selectedKernel}, Key: ${ensureKey}`);
    } else {
      console.log(`CodePanel Effect: SKIPPING ensureKernelIsReady (conditions not met). Session: ${sessionId}, Kernel: ${selectedKernel}`);
    }
  }, [sessionId, selectedKernel, kernelEnsured]); // ensureCallInFlight.current is a ref, not needed in deps

  // Close user menu if clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      // Close user menu
      if (isUserMenuOpen &&
          userMenuRef.current &&
          !userMenuRef.current.contains(event.target) &&
          userMenuButtonRef.current &&
          !userMenuButtonRef.current.contains(event.target)) {
        setIsUserMenuOpen(false);
      }
      // Close kernel menu
      if (isKernelMenuOpen &&
          kernelMenuRef.current &&
          !kernelMenuRef.current.contains(event.target) &&
          kernelMenuButtonRef.current &&
          !kernelMenuButtonRef.current.contains(event.target)) {
        setIsKernelMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isUserMenuOpen, isKernelMenuOpen]);

  // Auto-scroll to bottom when new cells or outputs are added
  useEffect(() => {
    if (notebookRef.current) {
      notebookRef.current.scrollTop = notebookRef.current.scrollHeight;
    }
    // Adding dependencies: scroll when cells array or cellOutputs object changes.
  }, [cells, cellOutputs]);

  // When calling onRunCode, make sure to pass selectedKernel
  const handleRunCell = (cellId) => {
    const cellToRun = cells.find(c => c.id === cellId);
    if (cellToRun) {
      onRunCode(cellId, cellToRun.content, selectedKernel); // Pass selectedKernel here
    }
  };

  return (
    <div className="code-panel" ref={notebookRef}>
      {/* Use common header class, keep specific ID/class if needed */}
      <div className="panel-header code-panel-header">
        <h2>Code & Results</h2>
        <div className="header-menus">
          {/* Kernel Selection Menu Button */}
          <div className="menu-container"> { /* Wrapper for positioning */}
            <button
              ref={kernelMenuButtonRef}
              className="menu-button"
              onClick={toggleKernelMenu}
              title={`Select Kernel (Current: ${selectedKernel})`}
              aria-haspopup="true"
              aria-expanded={isKernelMenuOpen}
              disabled={!sessionId} // Disable if no session ID yet
            >
              {selectedKernel === 'python' ? <PythonIcon /> : <JuliaIcon />}
            </button>
            {isKernelMenuOpen && (
              <div ref={kernelMenuRef} className="dropdown-menu kernel-menu"> {/* Added kernel-menu class for specific styling if needed*/}
                <ul>
                  <li> 
                    <button onClick={() => handleSelectKernel('python')}>
                      <span className="menu-icon">
                        {selectedKernel === 'python' ? <Check size={16} strokeWidth={2}/> : <span style={{width: '16px'}}/>}
                      </span>
                      Python
                    </button>
                  </li>
                  <li>
                    <button onClick={() => handleSelectKernel('julia')}>
                      <span className="menu-icon">
                        {selectedKernel === 'julia' ? <Check size={16} strokeWidth={2}/> : <span style={{width: '16px'}}/>}
                      </span>
                      Julia
                    </button>
                  </li>
                </ul>
              </div>
            )}
          </div>

          {/* User/Settings Menu Button */}
          <div className="menu-container"> { /* Wrapper for positioning */}
            <button
              ref={userMenuButtonRef}
              className="menu-button"
              onClick={toggleUserMenu}
              title="Menu"
              aria-haspopup="true"
              aria-expanded={isUserMenuOpen}
            >
              <UserRoundCog size={20} />
            </button>
            {isUserMenuOpen && (
              <div ref={userMenuRef} className="dropdown-menu">
                <ul>
                  <li>
                    <button onClick={openSettings}>
                      <span className="menu-icon"><Settings size={16} strokeWidth={1.5}/></span> Settings
                    </button>
                  </li>
                  <li>
                    <a href="https://discord.gg/vdffZG9hES" target="_blank" rel="noopener noreferrer">
                      <span className="menu-icon"><MessageCircleMore size={16} strokeWidth={1.5}/></span> Give Feedback
                    </a>
                  </li>
                </ul>
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="notebook-cells">
        {cells.map(cell => {
          // Get the output/error state for this specific cell from props
          const outputState = cellOutputs[cell.id] || { output: null, error: null, error_type: null, image_data: null, image_mime_type: null };
          // Determine if the cell is collapsed (default to true if not in state)
          const isCollapsed = collapsedStates[cell.id] !== false; // Treat undefined as collapsed (true)
          
          return (
            <CodeCell
              key={cell.id}
              // Pass the cell data (content) and the output/image state
              cell={{ ...cell, ...outputState }} // Kernel is passed to onRunCode, not directly to CodeCell unless needed for display
              isCollapsed={isCollapsed} // Pass collapsed state down
              onContentChange={onContentChange} // Pass the prop down
              // Pass the modified handleRunCell which includes selectedKernel
              onRunCode={() => handleRunCell(cell.id)} // Pass the onRunCode prop down
              onToggleCollapse={handleToggleCollapse} // Pass toggle function down
            />
          );
        })}
      </div>
      {/* Render SettingsWindow conditionally */}
      <SettingsWindow isOpen={isSettingsOpen} onClose={closeSettings} />
    </div>
  );
}

export default CodePanel;
