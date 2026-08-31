import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
export function cn(...inputs: (string|undefined|boolean)[]) { return twMerge(clsx(inputs)); }
export function Button({ className, variant="default", ...props }: any) {
  const base = "inline-flex items-center justify-center rounded px-3 py-1.5 text-sm font-medium border";
  const variants: any = {
    default: "bg-black text-white hover:bg-zinc-800",
    outline: "bg-white hover:bg-secondary",
    ghost: "border-0 hover:bg-secondary",
  };
  return <button className={cn(base, variants[variant], className)} {...props} />;
}
