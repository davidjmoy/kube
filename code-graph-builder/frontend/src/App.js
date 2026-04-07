import React, { useRef } from 'react';
import Header from './components/Header';
import ChatBot from './ChatBot';
import './App.css';

function App() {
    const clearRef = useRef(null);
    const exportRef = useRef(null);

    return (
        <div className="app-container">
            <Header
                onClearHistory={() => clearRef.current?.()}
                onExportHistory={() => exportRef.current?.()}
            />
            <ChatBot clearHistoryRef={clearRef} exportHistoryRef={exportRef} />
        </div>
    );
}

export default App;
