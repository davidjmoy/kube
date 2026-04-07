import React, { useState, useRef, useEffect, useCallback } from 'react';
import ChatMessage from './components/ChatMessage';
import { useConversation } from './hooks/useConversation';
import { useChat } from './hooks/useChat';
import './ChatBot.css';

const API_BASE = process.env.REACT_APP_API_URL || '';

function getTrailingToken(text, cursor) {
    const head = text.slice(0, cursor);
    const match = head.match(/([A-Za-z_][A-Za-z0-9_.]*)$/);
    if (!match) {
        return null;
    }

    const token = match[1];
    return {
        token,
        start: cursor - token.length,
        end: cursor,
    };
}

const ChatBot = ({ clearHistoryRef, exportHistoryRef }) => {
    const { messages, addMessage, updateLastMessage, clearHistory, exportHistory } = useConversation();
    const { sendMessage, isStreaming, cancel } = useChat({ messages, addMessage, updateLastMessage });
    const [inputValue, setInputValue] = useState('');
    const [suggestions, setSuggestions] = useState([]);
    const [showSuggestions, setShowSuggestions] = useState(false);
    const [activeSuggestionIndex, setActiveSuggestionIndex] = useState(-1);
    const [suggestionRange, setSuggestionRange] = useState(null);
    const messagesEndRef = useRef(null);
    const messagesContainerRef = useRef(null);
    const userAtBottomRef = useRef(true);
    const textareaRef = useRef(null);
    const autocompleteAbortRef = useRef(null);

    // Track whether user is scrolled to bottom
    const handleScroll = useCallback(() => {
        const el = messagesContainerRef.current;
        if (!el) return;
        const threshold = 80;
        userAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
    }, []);

    // Only auto-scroll if user is near the bottom
    useEffect(() => {
        if (userAtBottomRef.current) {
            messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        }
    }, [messages]);

    // Expose clear/export to parent via refs
    useEffect(() => {
        if (clearHistoryRef) clearHistoryRef.current = clearHistory;
        if (exportHistoryRef) exportHistoryRef.current = exportHistory;
    }, [clearHistory, exportHistory, clearHistoryRef, exportHistoryRef]);

    // Escape key cancels streaming
    useEffect(() => {
        const handleKeyDown = (e) => {
            if (e.key === 'Escape' && isStreaming) {
                cancel();
            }
        };
        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [isStreaming, cancel]);

    const doSend = useCallback(() => {
        if (!inputValue.trim() || isStreaming) return;
        sendMessage(inputValue);
        setInputValue('');
        // Reset textarea height
        if (textareaRef.current) textareaRef.current.style.height = 'auto';
    }, [inputValue, isStreaming, sendMessage]);

    const handleSubmit = (e) => {
        e.preventDefault();
        doSend();
    };

    useEffect(() => {
        if (isStreaming) {
            setShowSuggestions(false);
            setSuggestions([]);
            setActiveSuggestionIndex(-1);
            return;
        }

        const textarea = textareaRef.current;
        if (!textarea) return;

        const cursor = textarea.selectionStart ?? inputValue.length;
        const range = getTrailingToken(inputValue, cursor);
        if (!range || range.token.length < 2) {
            setShowSuggestions(false);
            setSuggestions([]);
            setActiveSuggestionIndex(-1);
            setSuggestionRange(null);
            return;
        }

        setSuggestionRange(range);

        const timeout = setTimeout(async () => {
            autocompleteAbortRef.current?.abort();
            const controller = new AbortController();
            autocompleteAbortRef.current = controller;

            try {
                const response = await fetch(
                    `${API_BASE}/graph/suggest?q=${encodeURIComponent(range.token)}&limit=8`,
                    { signal: controller.signal }
                );
                if (!response.ok) {
                    return;
                }

                const data = await response.json();
                const next = Array.isArray(data.results) ? data.results : [];
                setSuggestions(next);
                setShowSuggestions(next.length > 0);
                setActiveSuggestionIndex(next.length > 0 ? 0 : -1);
            } catch (err) {
                if (err.name !== 'AbortError') {
                    setShowSuggestions(false);
                }
            }
        }, 180);

        return () => clearTimeout(timeout);
    }, [inputValue, isStreaming]);

    const applySuggestion = useCallback((suggestion) => {
        if (!suggestion || !textareaRef.current || !suggestionRange) return;

        const before = inputValue.slice(0, suggestionRange.start);
        const after = inputValue.slice(suggestionRange.end);
        const nextValue = `${before}${suggestion.insert_text}${after}`;
        const nextCursor = before.length + suggestion.insert_text.length;

        setInputValue(nextValue);
        setShowSuggestions(false);
        setSuggestions([]);
        setActiveSuggestionIndex(-1);

        requestAnimationFrame(() => {
            const textarea = textareaRef.current;
            if (!textarea) return;
            textarea.focus();
            textarea.selectionStart = nextCursor;
            textarea.selectionEnd = nextCursor;
            textarea.style.height = 'auto';
            textarea.style.height = Math.min(textarea.scrollHeight, 150) + 'px';
        });
    }, [inputValue, suggestionRange]);

    const handleKeyDown = (e) => {
        if (showSuggestions && suggestions.length > 0) {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                setActiveSuggestionIndex((idx) => (idx + 1) % suggestions.length);
                return;
            }
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                setActiveSuggestionIndex((idx) => (idx <= 0 ? suggestions.length - 1 : idx - 1));
                return;
            }
            if ((e.key === 'Enter' || e.key === 'Tab') && activeSuggestionIndex >= 0) {
                e.preventDefault();
                applySuggestion(suggestions[activeSuggestionIndex]);
                return;
            }
            if (e.key === 'Escape') {
                e.preventDefault();
                setShowSuggestions(false);
                return;
            }
        }

        // Enter sends, Shift+Enter adds newline
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            doSend();
        }
    };

    const handleTextareaChange = (e) => {
        setInputValue(e.target.value);
        // Auto-resize textarea
        e.target.style.height = 'auto';
        e.target.style.height = Math.min(e.target.scrollHeight, 150) + 'px';
    };

    const handleRetry = useCallback(() => {
        // Remove the errored assistant message, then resend
        const lastUserMsg = [...messages].reverse().find(m => m.role === 'user');
        if (lastUserMsg) {
            // Remove last two messages (user + errored assistant) and re-send
            updateLastMessage(() => null); // will be replaced by sendMessage
            sendMessage(lastUserMsg.content);
        }
    }, [messages, sendMessage, updateLastMessage]);

    return (
        <>
            <div className="messages" ref={messagesContainerRef} onScroll={handleScroll}>
                {messages.map((msg, idx) => (
                    msg && <ChatMessage
                        key={msg.id}
                        message={msg}
                        onRetry={msg.error && idx === messages.length - 1 ? handleRetry : null}
                    />
                ))}
                <div ref={messagesEndRef} />
            </div>
            <form className="input-area" onSubmit={handleSubmit}>
                <div className="input-with-suggestions">
                    <textarea
                        ref={textareaRef}
                        value={inputValue}
                        onChange={handleTextareaChange}
                        onKeyDown={handleKeyDown}
                        onBlur={() => setTimeout(() => setShowSuggestions(false), 120)}
                        onFocus={() => {
                            if (suggestions.length > 0) setShowSuggestions(true);
                        }}
                        placeholder="Ask about Kubernetes code or docs... (Shift+Enter for newline)"
                        autoComplete="off"
                        autoFocus
                        rows={1}
                    />
                    {showSuggestions && suggestions.length > 0 && (
                        <div className="autocomplete-menu">
                            {suggestions.map((suggestion, idx) => (
                                <button
                                    key={`${suggestion.kind}-${suggestion.name}-${suggestion.package}-${idx}`}
                                    type="button"
                                    className={`autocomplete-item ${idx === activeSuggestionIndex ? 'active' : ''}`}
                                    onMouseDown={(e) => {
                                        e.preventDefault();
                                        applySuggestion(suggestion);
                                    }}
                                >
                                    <span className={`autocomplete-kind ${suggestion.kind}`}>{suggestion.kind}</span>
                                    <span className="autocomplete-name">{suggestion.name}</span>
                                    <span className="autocomplete-package">{suggestion.package}</span>
                                </button>
                            ))}
                        </div>
                    )}
                </div>
                {isStreaming ? (
                    <button type="button" onClick={cancel} className="cancel-btn">
                        Stop
                    </button>
                ) : (
                    <button type="submit" disabled={!inputValue.trim()}>
                        Send
                    </button>
                )}
            </form>
        </>
    );
};

export default ChatBot;
