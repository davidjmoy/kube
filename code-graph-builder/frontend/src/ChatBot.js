import React, { useState, useRef, useEffect } from 'react';
import './ChatBot.css';

const ChatBot = () => {
    const [messages, setMessages] = useState([
        {
            id: 0,
            role: 'assistant',
            content: 'Hi! I\'m the Kubernetes Code Assistant. I can help you understand the Kubernetes codebase. Ask me about functions, classes, or architecture!',
            references: []
        }
    ]);
    const [inputValue, setInputValue] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    const messagesEndRef = useRef(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    const handleSendMessage = async (e) => {
        e.preventDefault();
        if (!inputValue.trim()) return;

        // Add user message
        const userMessage = {
            id: messages.length,
            role: 'user',
            content: inputValue,
            references: []
        };
        setMessages(prev => [...prev, userMessage]);
        setInputValue('');
        setIsLoading(true);
        setError(null);

        try {
            // Build conversation history
            const conversationHistory = messages
                .filter(m => m.role !== 'system')
                .map(m => ({
                    role: m.role,
                    content: m.content
                }));

            // Stream the response
            const response = await fetch('/chat/stream', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: inputValue,
                    conversation_history: conversationHistory,
                    include_graph_context: true
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            // Create assistant message that will accumulate tokens
            const assistantMessage = {
                id: messages.length + 1,
                role: 'assistant',
                content: '',
                references: [],
                isStreaming: true
            };

            setMessages(prev => [...prev, assistantMessage]);

            // Process the stream
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines[lines.length - 1];

                for (let i = 0; i < lines.length - 1; i++) {
                    const line = lines[i];
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.slice(6));

                            if (data.token) {
                                // Accumulate token
                                setMessages(prev => {
                                    const updated = [...prev];
                                    updated[updated.length - 1].content += data.token;
                                    return updated;
                                });
                            }

                            if (data.type === 'references' && data.references) {
                                setMessages(prev => {
                                    const updated = [...prev];
                                    updated[updated.length - 1].references = data.references;
                                    return updated;
                                });
                            }

                            if (data.type === 'complete') {
                                setMessages(prev => {
                                    const updated = [...prev];
                                    updated[updated.length - 1].isStreaming = false;
                                    return updated;
                                });
                            }

                            if (data.type === 'error') {
                                setError(data.message);
                                setMessages(prev => {
                                    const updated = [...prev];
                                    updated[updated.length - 1].isStreaming = false;
                                    return updated;
                                });
                            }
                        } catch (e) {
                            console.error('Failed to parse SSE data:', e);
                        }
                    }
                }
            }
        } catch (err) {
            setError(err.message);
            console.error('Error:', err);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="chatbot-container">
            <div className="chatbot-header">
                <h1>Kubernetes Code Assistant</h1>
                <p>Ask questions about the Kubernetes codebase</p>
            </div>

            <div className="messages-container">
                {messages.map((msg) => (
                    <div key={msg.id} className={`message ${msg.role}`}>
                        <div className="message-content">
                            <div className="message-text">{msg.content}</div>
                            {msg.isStreaming && <span className="streaming-cursor">▌</span>}
                        </div>

                        {msg.references && msg.references.length > 0 && (
                            <div className="references">
                                <div className="references-title">Code References:</div>
                                {msg.references.map((ref, idx) => (
                                    <div key={idx} className="reference-item">
                                        <div className="reference-name">{ref.function_name}</div>
                                        <div className="reference-location">
                                            {ref.file}:{ref.line}
                                        </div>
                                        <div className="reference-package">{ref.package}</div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                ))}
                {error && (
                    <div className="message error">
                        <div className="message-content">
                            <span className="error-icon">⚠️</span> {error}
                        </div>
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>

            <form className="input-form" onSubmit={handleSendMessage}>
                <input
                    type="text"
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    placeholder="Ask about Kubernetes code..."
                    disabled={isLoading}
                    className="message-input"
                />
                <button type="submit" disabled={isLoading} className="send-button">
                    {isLoading ? '...' : 'Send'}
                </button>
            </form>
        </div>
    );
};

export default ChatBot;
