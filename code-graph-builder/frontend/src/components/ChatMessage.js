import React from 'react';
import MarkdownRenderer from './MarkdownRenderer';
import ExecutionTimeline from './ExecutionTimeline';
import './ChatMessage.css';

const ChatMessage = React.memo(({ message, onRetry }) => {
    const { role, content, executionSteps, executionTrace, toolCalls, isStreaming, error } = message;

    return (
        <div className={`msg ${role}`}>
            {role === 'assistant' && (
                <ExecutionTimeline
                    steps={executionSteps}
                    trace={executionTrace}
                    fallbackCalls={toolCalls}
                    isStreaming={isStreaming}
                />
            )}
            <div className="msg-content">
                {role === 'assistant' && content ? (
                    <MarkdownRenderer content={content} />
                ) : (
                    <span className="msg-text">{content}</span>
                )}
                {isStreaming && <span className="cursor" />}
            </div>
            {error && (
                <div className="msg-error">
                    <span className="error-text">Error: {error}</span>
                    {onRetry && (
                        <button className="retry-btn" onClick={onRetry}>
                            Retry
                        </button>
                    )}
                </div>
            )}
        </div>
    );
});

ChatMessage.displayName = 'ChatMessage';

export default ChatMessage;
