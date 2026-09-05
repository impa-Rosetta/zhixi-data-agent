import type { InputHTMLAttributes } from 'react'

export function Field({ label, error, ...props }: InputHTMLAttributes<HTMLInputElement> & {
  label: string
  error?: string
}) {
  const errorId = props.name ? `${props.name}-error` : undefined
  return (
    <label className="field">
      <span>{label}</span>
      <input {...props} aria-invalid={Boolean(error)} aria-describedby={error ? errorId : undefined} />
      {error && <small id={errorId} className="field-error">{error}</small>}
    </label>
  )
}
