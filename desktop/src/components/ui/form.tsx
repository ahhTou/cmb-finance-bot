import * as SwitchPrimitive from '@radix-ui/react-switch'
import { Check } from 'lucide-react'
import { motion } from 'motion/react'
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        'h-[38px] w-full min-w-0 rounded-lg bg-field px-3 text-[13px] text-fg outline-none',
        'placeholder:text-muted/60 focus:ring-2 focus:ring-accent/50 disabled:opacity-50',
        '[color-scheme:dark]',
        className,
      )}
      {...props}
    />
  )
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        'h-[34px] rounded-lg bg-field px-2.5 text-[13px] text-fg outline-none focus:ring-2 focus:ring-accent/50',
        'disabled:opacity-50',
        className,
      )}
      {...props}
    >
      {children}
    </select>
  )
}

export function Field({
  label,
  children,
  className,
}: {
  label: string
  children: ReactNode
  className?: string
}) {
  return (
    <label className={cn('flex min-w-0 flex-1 flex-col gap-2', className)}>
      <span className="text-[11px] text-muted">{label}</span>
      {children}
    </label>
  )
}

export function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean
  onChange: (value: boolean) => void
  label: string
  disabled?: boolean
}) {
  return (
    <label className={cn('flex items-center justify-between gap-3 text-[13px]', disabled && 'opacity-45')}>
      <span>{label}</span>
      <SwitchPrimitive.Root
        checked={checked}
        onCheckedChange={onChange}
        disabled={disabled}
        className="relative h-[22px] w-[38px] shrink-0 rounded-full bg-button transition-colors data-[state=checked]:bg-accent"
      >
        <SwitchPrimitive.Thumb asChild>
          <motion.span
            layout
            transition={{ type: 'spring', stiffness: 700, damping: 35 }}
            className={cn(
              'absolute top-[2px] block size-[18px] rounded-full bg-white shadow',
              checked ? 'right-[2px]' : 'left-[2px]',
            )}
          />
        </SwitchPrimitive.Thumb>
      </SwitchPrimitive.Root>
    </label>
  )
}

/** Checkbox confirmation; the real input stays on top so clicking and focus work. */
export function Checkbox({
  checked,
  onChange,
  label,
  disabled,
  testId,
}: {
  checked: boolean
  onChange: (value: boolean) => void
  label: ReactNode
  disabled?: boolean
  testId?: string
}) {
  return (
    <label
      className={cn(
        'relative flex items-start gap-2.5 text-[13px] leading-snug',
        disabled ? 'opacity-45' : 'cursor-pointer',
      )}
    >
      <input
        type="checkbox"
        data-testid={testId}
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="peer absolute top-[1px] left-0 z-10 size-4 cursor-pointer opacity-0 disabled:cursor-default"
      />
      <span
        aria-hidden
        className={cn(
          'pointer-events-none mt-[1px] flex size-4 shrink-0 items-center justify-center rounded-[4px] ring-1 transition-colors',
          checked ? 'bg-accent ring-accent' : 'bg-field ring-white/25',
          'peer-focus-visible:ring-2 peer-focus-visible:ring-accent/60',
        )}
      >
        <Check
          className={cn('size-3 text-white transition-opacity', checked ? 'opacity-100' : 'opacity-0')}
          strokeWidth={3}
        />
      </span>
      <span>{label}</span>
    </label>
  )
}

/** Segmented control with a sliding highlight. */
export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  label,
}: {
  value: T
  options: { value: T; label: string }[]
  onChange: (value: T) => void
  label: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex rounded-lg bg-field p-[3px]">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          onClick={() => onChange(option.value)}
          className="relative flex-1 rounded-md py-1.5 font-medium text-xs"
        >
          {value === option.value && (
            <motion.span
              layoutId={`segment-${label}`}
              className="absolute inset-0 rounded-md bg-button"
              transition={{ type: 'spring', stiffness: 500, damping: 38 }}
            />
          )}
          <span className="relative">{option.label}</span>
        </button>
      ))}
    </div>
  )
}
