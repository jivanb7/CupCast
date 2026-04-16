import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null, resetKey: 0 }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  handleReset = () => {
    this.setState((s) => ({ hasError: false, error: null, resetKey: s.resetKey + 1 }))
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-deep flex flex-col items-center justify-center px-4">
          <div className="cc-card p-8 text-center max-w-md">
            <p className="text-lg font-semibold text-foreground mb-2">Something went wrong</p>
            <p className="text-sm text-foreground-muted mb-4">{this.state.error?.message}</p>
            <button
              onClick={this.handleReset}
              className="cc-pill cc-pill-active"
            >
              Try again
            </button>
          </div>
        </div>
      )
    }
    return <div key={this.state.resetKey}>{this.props.children}</div>
  }
}
