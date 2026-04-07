import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';

const plugins = [remarkGfm];

const codeBlockStyle = {
    margin: '8px 0',
    borderRadius: '6px',
    fontSize: '12px',
};

const mdComponents = {
    code({ inline, className, children, ...props }) {
        const match = /language-(\w+)/.exec(className || '');
        return !inline && match ? (
            <SyntaxHighlighter
                style={oneDark}
                language={match[1]}
                PreTag="div"
                customStyle={codeBlockStyle}
                {...props}
            >
                {String(children).replace(/\n$/, '')}
            </SyntaxHighlighter>
        ) : !inline && !match && String(children).includes('\n') ? (
            <SyntaxHighlighter
                style={oneDark}
                language="text"
                PreTag="div"
                customStyle={codeBlockStyle}
                {...props}
            >
                {String(children).replace(/\n$/, '')}
            </SyntaxHighlighter>
        ) : (
            <code className="inline-code" {...props}>
                {children}
            </code>
        );
    },
    a({ href, children }) {
        return (
            <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
            </a>
        );
    },
};

const MarkdownRenderer = React.memo(({ content }) => {
    return (
        <div className="markdown-body">
            <ReactMarkdown
                remarkPlugins={plugins}
                components={mdComponents}
            >
                {content}
            </ReactMarkdown>
        </div>
    );
});

MarkdownRenderer.displayName = 'MarkdownRenderer';

export default MarkdownRenderer;
