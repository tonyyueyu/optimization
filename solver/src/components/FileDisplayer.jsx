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
        if (file.type === 'link') return (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
            </svg>
        );

        const ext = file.name.split('.').pop().toLowerCase();
        return (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
                <polyline points="13 2 13 9 20 9" />
            </svg>
        );
    };

    return (
        <div className="file-displayer">
            <div className="file-displayer-header">
                <div className="file-displayer-top-row">
                    <span className="file-displayer-title">External Files</span>
                    <button className="add-file-icon-btn" onClick={onAddFile} title="Add resource">+</button>
                </div>
            </div>

            <div className="file-displayer-list">
                {files.length === 0 ? (
                    <div className="file-displayer-empty">
                        <div className="file-displayer-empty-icon">
                            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
                                <polyline points="13 2 13 9 20 9" />
                            </svg>
                        </div>
                        <p>No files uploaded yet.</p>
                        <button className="btn-primary" onClick={onAddFile} style={{ marginTop: '8px', padding: '8px 16px', fontSize: '0.85rem' }}>
                            Add Resource
                        </button>
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
