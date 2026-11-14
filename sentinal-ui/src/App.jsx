import { useState } from 'react';
import MainUI from './pages/MainUI';
import { configureToken } from './services/wsService';

export default function App() {
  const [token, setToken] = useState('');
  const [connected, setConnected] = useState(false);
  if (connected) return <MainUI />;
  return <main style={{ padding: '3rem', color: '#fff', background: '#111', minHeight: '100vh' }}>
    <h1>Connect to SentinAL</h1>
    <p>Enter the local backend token from .sentinal_token. It stays in memory for this page.</p>
    <form onSubmit={(event) => {
      event.preventDefault();
      configureToken(token.trim());
      setToken('');
      setConnected(true);
    }}>
      <label>API token <input type="password" value={token} autoComplete="off"
        onChange={(event) => setToken(event.target.value)} required /></label>
      <button type="submit">Connect</button>
    </form>
  </main>;
}
