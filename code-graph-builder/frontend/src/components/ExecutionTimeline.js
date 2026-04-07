import React, { useState } from 'react';
import './ExecutionTimeline.css';

const TOOL_COLORS = {
    grep_code: '#4a9eff',
    find_files: '#4a9eff',
    read_file: '#4caf50',
    get_function_body: '#4caf50',
    get_callers: '#9c5fff',
    get_callees: '#9c5fff',
    search_graph: '#9c5fff',
    search_docs: '#ff9800',
    get_git_history: '#ff9800',
};

function toolColor(name) {
    return TOOL_COLORS[name] || '#6b8aaf';
}

function formatDuration(ms) {
    if (ms == null) return '...';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
}

const ExecutionTimeline = ({ steps, trace, fallbackCalls, isStreaming }) => {
    const [expanded, setExpanded] = useState(false);

    // Use structured steps if available, otherwise fall back to legacy toolCalls
    const hasSteps = steps && steps.length > 0;
    const hasFallback = !hasSteps && fallbackCalls && fallbackCalls.length > 0;

    if (!hasSteps && !hasFallback) return null;

    // During streaming with steps: show the active tool
    if (isStreaming && hasSteps) {
        const active = steps.filter(s => s.status === 'running');
        const done = steps.filter(s => s.status === 'done');
        return (
            <div className="exec-timeline">
                <div className="exec-streaming-status">
                    {active.length > 0 && (
                        <div className="exec-active-tool">
                            <span className="exec-spinner" />
                            <span className="exec-active-name" style={{ color: toolColor(active[active.length - 1].name) }}>
                                {active[active.length - 1].argsSummary || active[active.length - 1].name}
                            </span>
                        </div>
                    )}
                    {done.length > 0 && (
                        <span className="exec-done-count">{done.length} tool{done.length !== 1 ? 's' : ''} completed</span>
                    )}
                </div>
            </div>
        );
    }

    // Fallback: legacy toolCalls (no structured data)
    if (hasFallback) {
        return (
            <div className="exec-timeline">
                <button className="exec-toggle" onClick={() => setExpanded(!expanded)}>
                    <span className="exec-icon">&#128269;</span>
                    {fallbackCalls.length} tool call{fallbackCalls.length !== 1 ? 's' : ''} executed
                    <span className={`exec-arrow ${expanded ? 'expanded' : ''}`}>&#9654;</span>
                </button>
                {expanded && (
                    <ul className="exec-fallback-list">
                        {fallbackCalls.map((tc, idx) => (
                            <li key={idx} className="exec-fallback-item">{tc.description}</li>
                        ))}
                    </ul>
                )}
            </div>
        );
    }

    // Completed: collapsible panel with timing details
    const totalCalls = trace ? trace.totalToolCalls : steps.length;
    const rounds = trace ? trace.rounds : Math.max(...steps.map(s => s.round || 1));
    const totalMs = trace ? trace.totalDurationMs : steps.reduce((sum, s) => sum + (s.durationMs || 0), 0);
    const maxDuration = Math.max(...steps.map(s => s.durationMs || 0), 1);

    return (
        <div className="exec-timeline">
            <button className="exec-toggle" onClick={() => setExpanded(!expanded)}>
                <span className="exec-icon">&#9889;</span>
                {totalCalls} tool call{totalCalls !== 1 ? 's' : ''} across {rounds} round{rounds !== 1 ? 's' : ''} ({formatDuration(totalMs)})
                <span className={`exec-arrow ${expanded ? 'expanded' : ''}`}>&#9654;</span>
            </button>
            {expanded && (
                <div className="exec-steps">
                    {steps.map((step, idx) => (
                        <div key={idx} className="exec-step-row">
                            <span className="exec-round-badge" style={{ borderColor: toolColor(step.name) }}>R{step.round || 1}</span>
                            <span className="exec-step-name" style={{ color: toolColor(step.name) }}>{step.name}</span>
                            <div className="exec-bar-track">
                                <div
                                    className="exec-bar-fill"
                                    style={{
                                        width: `${Math.max(((step.durationMs || 0) / maxDuration) * 100, 4)}%`,
                                        backgroundColor: toolColor(step.name),
                                    }}
                                />
                            </div>
                            <span className="exec-step-duration">{formatDuration(step.durationMs)}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default ExecutionTimeline;
