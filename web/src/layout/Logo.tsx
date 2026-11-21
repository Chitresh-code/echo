export function Logo({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <circle cx="6" cy="12" r="2" />
      <path d="M11 7a7 7 0 0 1 0 10" />
      <path d="M15 4a11 11 0 0 1 0 16" />
    </svg>
  )
}
