import React, { useState } from 'react';

export default function CadUpload({ onAnalysisComplete }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleFileChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith('.step') && !file.name.toLowerCase().endsWith('.stp')) {
      setError("Please upload a valid .STEP or .STP file");
      return;
    }

    setLoading(true);
    setError(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      // We use /upload_cad assuming you set up the proxy in vite.config.js
      // If no proxy, change this to: http://localhost:8000/upload_cad
      const response = await fetch('/upload_cad', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) throw new Error("Backend connection failed");

      const data = await response.json();
      if (data.error) throw new Error(data.error);

      onAnalysisComplete(data.summary);

    } catch (err) {
      console.error(err);
      setError("Failed to analyze. Is Docker running?");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: '10px', border: '1px solid #444', borderRadius: '8px', background: '#222', marginBottom: '15px' }}>
      <h4 style={{ margin: '0 0 10px 0', color: '#ccc', fontSize: '0.9rem' }}>CAD OPTIMIZER</h4>
      
      <input 
        type="file" 
        accept=".step,.stp"
        onChange={handleFileChange}
        style={{ color: '#fff', fontSize: '0.8rem' }}
      />
      
      {loading && <p style={{ color: '#00ccff', fontSize: '0.8rem' }}>Analyzing geometry...</p>}
      {error && <p style={{ color: '#ff4444', fontSize: '0.8rem' }}>{error}</p>}
    </div>
  );
}