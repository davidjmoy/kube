import { useState, useCallback, useRef } from 'react';

const API_BASE = process.env.REACT_APP_API_URL || '';

export function useChat({ messages, addMessage, updateLastMessage }) {
    const [isStreaming, setIsStreaming] = useState(false);
    const abortRef = useRef(null);

    const sendMessage = useCallback(async (text) => {
        if (!text.trim() || isStreaming) return;

        addMessage({ role: 'user', content: text, toolCalls: [] });
        addMessage({ role: 'assistant', content: '', toolCalls: [], executionSteps: [], executionTrace: null, isStreaming: true });

        setIsStreaming(true);
        const controller = new AbortController();
        abortRef.current = controller;

        try {
            const history = messages
                .filter(m => m.role === 'user' || m.role === 'assistant')
                .slice(-10)
                .map(m => ({ role: m.role, content: m.content }));

            const response = await fetch(`${API_BASE}/chat/stream`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: text,
                    conversation_history: history,
                    include_graph_context: true,
                }),
                signal: controller.signal,
            });

            if (!response.ok) {
                const errText = await response.text();
                throw new Error(`HTTP ${response.status}: ${errText}`);
            }

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
                    const line = lines[i].trim();
                    if (!line.startsWith('data: ')) continue;

                    try {
                        const data = JSON.parse(line.slice(6));

                        if (data.type === 'tool_start') {
                            updateLastMessage(msg => ({
                                ...msg,
                                executionSteps: [...(msg.executionSteps || []), {
                                    name: data.name,
                                    argsSummary: data.args_summary,
                                    round: data.round,
                                    startTime: Date.now(),
                                    status: 'running',
                                }],
                            }));
                        }

                        if (data.type === 'tool_end') {
                            updateLastMessage(msg => {
                                const steps = [...(msg.executionSteps || [])];
                                // Find the last running step with matching name
                                for (let j = steps.length - 1; j >= 0; j--) {
                                    if (steps[j].name === data.name && steps[j].status === 'running') {
                                        steps[j] = { ...steps[j], durationMs: data.duration_ms, resultChars: data.result_chars, status: 'done' };
                                        break;
                                    }
                                }
                                return { ...msg, executionSteps: steps };
                            });
                        }

                        if (data.type === 'trace') {
                            updateLastMessage(msg => ({
                                ...msg,
                                executionTrace: {
                                    rounds: data.rounds,
                                    totalDurationMs: data.total_duration_ms,
                                    totalToolCalls: data.total_tool_calls,
                                    steps: data.steps,
                                },
                            }));
                        }

                        // Backward compat: also accumulate status events into toolCalls
                        if (data.type === 'status') {
                            updateLastMessage(msg => ({
                                ...msg,
                                toolCalls: [...(msg.toolCalls || []), { description: data.message, timestamp: Date.now() }],
                            }));
                        }

                        if (data.token) {
                            updateLastMessage(msg => ({
                                ...msg,
                                content: msg.content + data.token,
                            }));
                        }

                        if (data.type === 'complete') {
                            updateLastMessage(msg => ({ ...msg, isStreaming: false }));
                        }

                        if (data.type === 'error') {
                            updateLastMessage(msg => ({
                                ...msg,
                                isStreaming: false,
                                error: data.message,
                            }));
                        }
                    } catch (parseErr) {
                        if (parseErr.message && !parseErr.message.includes('JSON')) throw parseErr;
                    }
                }
            }

            updateLastMessage(msg => ({ ...msg, isStreaming: false }));
        } catch (err) {
            if (err.name === 'AbortError') {
                updateLastMessage(msg => ({ ...msg, isStreaming: false, content: msg.content || '(cancelled)' }));
                return;
            }
            updateLastMessage(msg => ({
                ...msg,
                isStreaming: false,
                error: err.message,
            }));
        } finally {
            setIsStreaming(false);
            abortRef.current = null;
        }
    }, [isStreaming, messages, addMessage, updateLastMessage]);

    const cancel = useCallback(() => {
        abortRef.current?.abort();
    }, []);

    return { sendMessage, isStreaming, cancel };
}
