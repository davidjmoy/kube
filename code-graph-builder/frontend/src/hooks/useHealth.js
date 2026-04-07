import { useState, useEffect } from 'react';

const API_BASE = process.env.REACT_APP_API_URL || '';

export function useHealth() {
    const [health, setHealth] = useState(null);

    useEffect(() => {
        const fetchHealth = async () => {
            try {
                const res = await fetch(`${API_BASE}/health`);
                const data = await res.json();
                setHealth(data);
            } catch {
                setHealth({ status: 'unreachable' });
            }
        };
        fetchHealth();
        const interval = setInterval(fetchHealth, 60000);
        return () => clearInterval(interval);
    }, []);

    return health;
}
