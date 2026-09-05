export function LoadingScreen({ label }: { label: string }) {
  return (
    <main className="center-screen" aria-live="polite">
      <div className="spinner" />
      <p>{label}</p>
    </main>
  )
}
