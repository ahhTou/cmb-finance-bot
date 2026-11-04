import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import type { ButtonHTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

const button = cva(
  'inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap font-medium text-fg/95 ' +
    'transition-[background-color,opacity,transform] duration-150 active:scale-[0.97] active:opacity-75 ' +
    'disabled:pointer-events-none disabled:opacity-40 outline-none focus-visible:ring-2 focus-visible:ring-accent/60',
  {
    variants: {
      variant: {
        default: 'bg-button hover:bg-[#404040]',
        primary: 'bg-accent hover:bg-[#e8505f]',
        ghost: 'bg-transparent text-muted hover:text-fg',
      },
      size: {
        default: 'h-[34px] rounded-lg px-3.5 text-xs',
        compact: 'h-[27px] rounded-[7px] px-2 text-[11px]',
        icon: 'size-6 rounded-md p-0',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof button> {
  asChild?: boolean
}

export function Button({ className, variant, size, asChild, type = 'button', ...props }: ButtonProps) {
  const Comp = asChild ? Slot : 'button'
  return <Comp type={type} className={cn(button({ variant, size }), className)} {...props} />
}
