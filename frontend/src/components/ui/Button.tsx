import { forwardRef } from \"react\"
import { cn } from \"../../lib/utils\"

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: \"primary\" | \"secondary\" | \"ghost\"
  size?: \"sm\" | \"md\" | \"lg\"
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = \"primary\", size = \"md\", ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          \"inline-flex items-center justify-center rounded-lg font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:pointer-events-none disabled:opacity-50\",
          {
            \"bg-gradient-to-r from-blue-600 to-indigo-600 text-white hover:from-blue-700 hover:to-indigo-700 shadow-lg shadow-blue-500/25\": variant === \"primary\",
            \"bg-white text-gray-900 border border-gray-200 hover:bg-gray-50 shadow-sm\": variant === \"secondary\",
            \"hover:bg-gray-100 text-gray-700\": variant === \"ghost\",
          },
          {
            \"h-9 px-3 text-sm\": size === \"sm\",
            \"h-10 px-4 text-sm\": size === \"md\",
            \"h-11 px-6 text-base\": size === \"lg\",
          },
          className
        )}
        {...props}
      />
    )
  }
)
Button.displayName = \"Button\"

export { Button }
