import { forwardRef } from "react"
import { cn } from "../../lib/utils"

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "subtle" | "outline"
  size?: "sm" | "md" | "lg"
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center rounded-lg font-medium tracking-tight transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-moss/25 focus-visible:ring-offset-1 focus-visible:ring-offset-chalk-50 disabled:pointer-events-none disabled:opacity-40",
          {
            "bg-ink text-white hover:bg-ink-200 active:bg-ink shadow-subtle": variant === "primary",
            "bg-white text-ink border border-ink/10 hover:bg-chalk-50/90 hover:border-ink/18 shadow-subtle": variant === "secondary",
            "bg-transparent text-ink-100 hover:text-ink hover:bg-ink/5": variant === "ghost",
            "text-ink-100 hover:text-ink border border-transparent hover:border-ink/10 hover:bg-white/70": variant === "subtle",
            "bg-transparent text-ink border border-ink/12 hover:bg-white/70 hover:border-ink/18": variant === "outline",
          },
          {
            "h-8 px-2.5 text-[12px] gap-1.5": size === "sm",
            "h-9 px-3.5 text-[13px] gap-1.5": size === "md",
            "h-10 px-4 text-[13px] gap-2": size === "lg",
          },
          className
        )}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button }