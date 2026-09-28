// Small inline icon set (lucide-style strokes). Inline SVG instead of the
// lucide-react package so no new dependency is added (INSTRUCTIONS.md: ask
// before adding dependencies).

const PATHS = {
  dashboard: 'M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z',
  map: 'M5 6a2 2 0 1 0 0-.01M19 6a2 2 0 1 0 0-.01M12 18a2 2 0 1 0 0-.01M7 6h10M6 8l5 8M18 8l-5 8',
  sources: 'M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4M4.9 19.1l2.8-2.8M16.3 7.7l2.8-2.8M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8',
  chain: 'M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7',
  ai: 'M9 3h6M12 3v3M5 9a7 7 0 0 1 14 0v4a7 7 0 0 1-14 0zM9 11h.01M15 11h.01M9 15c1.5 1 4.5 1 6 0',
  analytics: 'M3 3v18h18M7 15l4-4 3 3 6-6',
  settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 3 15H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.2-2.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 9 4.6V4a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1A1.7 1.7 0 0 0 20 11h1a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 0z',
  wind: 'M3 8h10a3 3 0 1 0-3-3M3 12h15a3 3 0 1 1-3 3M3 16h7',
  hydro: 'M12 2.5S5 10 5 14.5a7 7 0 0 0 14 0C19 10 12 2.5 12 2.5z',
  solar: 'M12 3v2M12 19v2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M3 12h2M19 12h2M5.6 18.4 7 17M17 7l1.4-1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8',
  grid: 'M12 2 4 22M12 2l8 20M7 14h10M8.5 9h7M3 22h18',
  bus: 'M4 12h16M8 8v8M16 8v8M4 6v12M20 6v12',
  bolt: 'M13 2 4 14h7l-1 8 9-12h-7z',
  gauge: 'M12 14l4-4M3.3 17a9 9 0 1 1 17.4 0',
  nodes: 'M12 5a2 2 0 1 0 0-.01M5 19a2 2 0 1 0 0-.01M19 19a2 2 0 1 0 0-.01M12 7v4M12 11l-6 6M12 11l6 6',
  plug: 'M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0zM12 18v4',
  alert: 'M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z',
  check: 'M20 6 9 17l-5-5',
  copy: 'M9 9h11v11H9zM5 15H4V4h11v1',
  block: 'M12 2 3 7v10l9 5 9-5V7zM3 7l9 5 9-5M12 12v10',
  arrow: 'M5 12h14M13 6l6 6-6 6',
  chevron: 'M6 9l6 6 6-6',
  logout: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9',
  shield: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z',
  bell: 'M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0',
  server: 'M3 4h18v6H3zM3 14h18v6H3zM7 7h.01M7 17h.01',
  user: 'M20 21a8 8 0 0 0-16 0M12 13a5 5 0 1 0 0-10 5 5 0 0 0 0 10z',
  leaf: 'M11 20A7 7 0 0 1 4 13c0-6 7-10 16-10 0 9-4 16-10 16M2 22c3-6 6-9 10-11',
  rupee: 'M6 3h12M6 8h12M6 13l8.5 8M6 13h3a5 5 0 0 0 0-10',
  heal: 'M12 21s-8-4.5-8-11a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 10c0 6.5-8 11-8 11zM12 9v6M9 12h6',
  brain: 'M9.5 2A2.5 2.5 0 0 0 7 4.5v0A2.5 2.5 0 0 0 4.5 7 2.5 2.5 0 0 0 3 9.5a2.5 2.5 0 0 0 1 4.5 3 3 0 0 0 3 4 2.5 2.5 0 0 0 5 1V4.5A2.5 2.5 0 0 0 9.5 2zM14.5 2A2.5 2.5 0 0 1 17 4.5 2.5 2.5 0 0 1 19.5 7 2.5 2.5 0 0 1 21 9.5a2.5 2.5 0 0 1-1 4.5 3 3 0 0 1-3 4 2.5 2.5 0 0 1-5 1',
  pulse: 'M22 12h-4l-3 9L9 3l-3 9H2',
  x: 'M18 6 6 18M6 6l12 12',
}

export default function Icon({ name, size = 18, className = '', strokeWidth = 1.8, ...rest }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
      {...rest}
    >
      <path d={PATHS[name] ?? PATHS.bolt} />
    </svg>
  )
}

export function SourceIcon({ type, ...rest }) {
  const name = { wind: 'wind', hydro: 'hydro', solar: 'solar', grid: 'grid', bus: 'bus' }[type] ?? 'bolt'
  return <Icon name={name} {...rest} />
}
