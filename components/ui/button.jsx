import { cva } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const variants = cva(
  'inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:pointer-events-none disabled:opacity-50 h-10 px-4 py-2',
  { variants: { variant: {
    default: 'bg-primary text-primary-foreground hover:opacity-90',
    outline: 'border border-border bg-background hover:bg-muted',
  } }, defaultVariants: { variant: 'default' } },
);

export function Button({ className, variant, type = 'button', ...props }) {
  return <button data-slot="button" type={type} className={cn(variants({ variant }), className)} {...props} />;
}
