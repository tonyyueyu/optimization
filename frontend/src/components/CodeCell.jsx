import React from 'react';
import Editor from '@monaco-editor/react';

function CodeCell({ cell, isCollapsed, onContentChange, onRunCode, onToggleCollapse }) {
  // Basic structure for a code cell
  // Later, we'll add a code editor (like Monaco or CodeMirror)
  // and display the actual output from the backend.

  const handleEditorChange = (value) => {
    onContentChange(cell.id, value); // Call the callback with cell ID and new value
  };

  const handleRunClick = () => {
    onRunCode(cell.id);
  };

  const handleToggleClick = () => {
    onToggleCollapse(cell.id);
  };

  const hasOutput = cell.output || cell.error || cell.image_data;

  return (
    <div className={`code-cell ${isCollapsed ? 'collapsed' : 'expanded'}`}>
      {/* Conditionally render Run button only when expanded */}
      {!isCollapsed && (
          <button 
            className="run-button-overlay"
            onClick={handleRunClick}
            title="Run code"
          >
            {/* Arrow is now drawn using CSS ::after pseudo-element */}
          </button>
      )}

      {/* Conditionally render Code Input Area */}
      {!isCollapsed && (
        <div className="code-input-area">
          <Editor
            height="200px"
            language="python"
            theme="vs-light"
            value={cell.content}
            onChange={handleEditorChange}
            options={{
              minimap: { enabled: false },
              fontSize: 14,
              wordWrap: 'on',
              scrollBeyondLastLine: false,
              automaticLayout: true,
              lineNumbers: 'off',
              renderLineHighlight: 'none',
              hideCursorInOverviewRuler: true
            }}
          />
        </div>
      )}

      <div className="output-wrapper">
        <button 
          className="toggle-collapse-button" 
          onClick={handleToggleClick}
          title={isCollapsed ? "Show Code" : "Hide Code"}
        >
          {/* Text removed, shape will be added via CSS */}
        </button>

        {/* Display Standard Output */}
        {cell.output && (
          <div className="code-output-area output-stdout">
            <pre>
              <code>{cell.output}</code>
            </pre>
          </div>
        )}

        {/* Display Image Output */}
        {cell.image_data && cell.image_mime_type && (
          <div className="code-output-area output-image">
            <img 
              src={`data:${cell.image_mime_type};base64,${cell.image_data}`}
              alt="Generated Plot"
              style={{ 
                maxWidth: '100%', 
                maxHeight: '400px', // Limit the maximum display height
                width: 'auto',       // Adjust width automatically based on height constraint
                height: 'auto'       // Adjust height automatically based on width constraint
              }} 
            />
          </div>
        )}

        {/* Display Error Output */}
        {cell.error && (
          <div className={`code-output-area output-error error-type-${cell.error_type || 'generic'}`}>
            <pre>
              {/* Optional: Add prefix based on error type */}
              {cell.error_type === 'timeout' && <strong>Timeout: </strong>}
              {cell.error_type === 'connection_error' && <strong>Connection Error: </strong>}
              {cell.error_type === 'http_error' && <strong>HTTP Error: </strong>}
              {cell.error_type === 'system_error' && <strong>System Error: </strong>}
              {/* Display error content */}
              <code>{cell.error}</code>
            </pre>
          </div>
        )}

        {/* Placeholder if no output, error, or image */}
        {!hasOutput && (
          <div className="code-output-placeholder">
            <p>Results will appear here.</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default CodeCell; 