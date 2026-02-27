import React from 'react';

/**
 * FileDisplayer component shows a list of files and links in the session.
 */
const FileDisplayer = ({
    isOpen,
    onAddFile,
    onDeleteFile,
    files = [],
    selectedFileIds,
    toggleFileSelection
}) => {
    if (!isOpen) return null;

    const getFileIcon = (file) => {
        if (file.type === 'link') return '🔗';
        const ext = file.name.split('.').pop().toLowerCase();
        switch (ext) {
            case 'pdf': return '📕';
            case 'csv':
            case 'xlsx':
            case 'xls': return '📊';
            case 'png':
            case 'jpg':
            case 'jpeg':
            case 'gif': return '🖼️';
            case 'py': return '🐍';
            case 'json': return '📋';
            case 'stl':
            case 'step':
            case 'stp': return '⚙️';
            default: return '📄';
        }
    };

    return (
        <div className="file-displayer">
            <div className="file-displayer-header">
                <span className="file-displayer-title">Project Files</span>
                <button className="sidebar-plus" onClick={onAddFile} title="Add file or link">+</button>
            </div>

            <div className="file-displayer-list">
                {files.length === 0 ? (
                    <div className="file-displayer-empty">
                        No files uploaded yet.
                    </div>
                ) : (
                    files.map((file) => (
                        <div
                            key={file.id}
                            className={`file-displayer-item ${selectedFileIds.has(file.id) ? 'file-selected' : ''}`}
                            onClick={() => toggleFileSelection(file.id)}
                        >
                            <span className="file-displayer-icon">{getFileIcon(file)}</span>
                            <div className="file-displayer-info">
                                <span className="file-displayer-name">{file.name}</span>
                                <span className="file-displayer-meta">
                                    {file.type === 'link' ? 'Link' : file.size}
                                </span>
                            </div>

                            {selectedFileIds.has(file.id) && (
                                <div className="file-checkmark">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                                        <polyline points="20 6 9 17 4 12" />
                                    </svg>
                                </div>
                            )}

                            <button
                                className="file-delete-btn"
                                onClick={(e) => {
                                    e.stopPropagation();
                                    if (window.confirm(`Delete ${file.name}?`)) {
                                        onDeleteFile(file);
                                    }
                                }}
                                title="Delete file"
                            >
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M3 6h18m-2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                                </svg>
                            </button>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
};

export default FileDisplayer;
