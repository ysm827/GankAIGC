import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';

class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('GankAIGC frontend render failed:', error, info);
  }

  render() {
    if (!this.state.error) {
      return this.props.children;
    }

    const message = this.state.error?.message || '未知前端错误';

    return (
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
        background: '#f5f7fb',
        color: '#0f172a',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      }}>
        <div style={{
          width: 'min(560px, 100%)',
          borderRadius: 24,
          border: '1px solid rgba(148, 163, 184, 0.28)',
          background: '#ffffff',
          boxShadow: '0 24px 70px rgba(15, 23, 42, 0.10)',
          padding: 28,
        }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#0066cc', marginBottom: 10 }}>
            GankAIGC 前端加载失败
          </div>
          <h1 style={{ fontSize: 24, lineHeight: 1.2, margin: '0 0 12px', letterSpacing: '-0.03em' }}>
            页面没有正常挂载
          </h1>
          <p style={{ margin: '0 0 18px', color: '#475569', lineHeight: 1.7 }}>
            多数是浏览器缓存了旧的静态资源。请先按 Ctrl + F5 强制刷新；如果仍失败，把下面错误发给开发者。
          </p>
          <pre style={{
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            padding: 14,
            borderRadius: 16,
            background: '#f8fafc',
            color: '#be123c',
            fontSize: 13,
            lineHeight: 1.6,
          }}>{message}</pre>
          <button
            type="button"
            onClick={() => window.location.reload()}
            style={{
              marginTop: 18,
              border: 0,
              borderRadius: 999,
              padding: '10px 18px',
              background: '#0066cc',
              color: '#fff',
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            重新加载
          </button>
        </div>
      </div>
    );
  }
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </React.StrictMode>
);
