import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('ErrorBoundary caught', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div
          className="cc-root cc-night"
          style={{
            minHeight: '100vh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 32,
          }}
        >
          <div style={{ maxWidth: 560 }}>
            <div className="cc-eyebrow">Render Error</div>
            <h1
              className="serif"
              style={{ fontSize: 48, fontStyle: 'italic', fontWeight: 600, margin: '12px 0 18px' }}
            >
              Something broke on this page.
            </h1>
            <pre
              className="mono"
              style={{
                fontSize: 12,
                color: 'var(--cc-muted)',
                whiteSpace: 'pre-wrap',
                background: 'var(--cc-surface)',
                border: '1px solid var(--cc-line)',
                padding: 14,
                borderRadius: 6,
              }}
            >
              {String(this.state.error?.stack || this.state.error)}
            </pre>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
