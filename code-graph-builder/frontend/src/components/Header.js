import React from 'react';
import { useHealth } from '../hooks/useHealth';
import './Header.css';

const Header = ({ onClearHistory, onExportHistory }) => {
    const health = useHealth();

    let statsText = 'Loading graph...';
    if (health) {
        if (health.status === 'unreachable') {
            statsText = 'Backend unreachable';
        } else if (health.graph_loaded) {
            statsText = `Graph: ${health.functions?.toLocaleString()} functions`;
            if (health.docs_indexed) {
                statsText += ` | Docs: ${health.docs_count?.toLocaleString()} pages`;
            }
        } else {
            statsText = 'Graph not loaded';
        }
    }

    return (
        <header className="app-header">
            <div className="header-left">
                <h1>Kubernetes Code Assistant</h1>
                <div className="stats">{statsText}</div>
            </div>
            <div className="header-actions">
                <button className="header-btn" onClick={onExportHistory} title="Export chat history as JSON">
                    Export
                </button>
                <button className="header-btn header-btn-danger" onClick={onClearHistory} title="Clear chat history">
                    Clear
                </button>
            </div>
        </header>
    );
};

export default Header;
