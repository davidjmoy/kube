import { useState, useCallback, useRef } from 'react';

const STORAGE_KEY = 'k8s-chat-history';

let nextId = Date.now();

const WELCOME_MESSAGE = {
    id: 0,
    role: 'assistant',
    content: 'Hi! I can help you explore the Kubernetes codebase and documentation. Try asking about functions, call relationships, architecture patterns, or Kubernetes concepts.\n\nExamples:\n- What does ValidateObjectMeta do?\n- Who calls VisitContainers?\n- How does the kubelet controller work?\n- What is a Pod lifecycle?\n- How do I configure a NetworkPolicy?',
    toolCalls: [],
    executionSteps: [],
    executionTrace: null,
};

function loadFromStorage() {
    try {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored) {
            const parsed = JSON.parse(stored);
            if (parsed.length > 0) {
                nextId = Math.max(nextId, ...parsed.map(m => m.id || 0)) + 1;
            }
            return parsed;
        }
        return [];
    } catch {
        return [];
    }
}

function saveToStorage(messages) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
    } catch {
        // Storage full or unavailable
    }
}

export function useConversation() {
    const [messages, setMessages] = useState(() => {
        const saved = loadFromStorage();
        return saved.length > 0 ? saved : [WELCOME_MESSAGE];
    });

    // Debounce localStorage writes during streaming
    const saveTimerRef = useRef(null);
    const debouncedSave = useCallback((msgs) => {
        if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
        saveTimerRef.current = setTimeout(() => saveToStorage(msgs), 500);
    }, []);

    const addMessage = useCallback((msg) => {
        setMessages(prev => {
            const updated = [...prev, { ...msg, id: nextId++ }];
            saveToStorage(updated);
            return updated;
        });
    }, []);

    const updateLastMessage = useCallback((updater) => {
        setMessages(prev => {
            if (prev.length === 0) return prev;
            const updated = [...prev];
            updated[updated.length - 1] = updater(updated[updated.length - 1]);
            debouncedSave(updated);
            return updated;
        });
    }, [debouncedSave]);

    const clearHistory = useCallback(() => {
        setMessages([WELCOME_MESSAGE]);
        saveToStorage([WELCOME_MESSAGE]);
    }, []);

    const exportHistory = useCallback(() => {
        const current = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
        const blob = new Blob([JSON.stringify(current, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `k8s-chat-${new Date().toISOString().slice(0, 10)}.json`;
        a.click();
        URL.revokeObjectURL(url);
    }, []);

    return { messages, addMessage, updateLastMessage, clearHistory, exportHistory };
}
