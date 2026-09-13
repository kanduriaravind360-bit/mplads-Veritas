import * as SliderPrimitive from "@radix-ui/react-slider";
import { cn } from "@/lib/utils";

export function Slider({
  value,
  onChange,
  min,
  max,
  step,
  label,
  className,
}: {
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step: number;
  label: string;
  className?: string;
}) {
  return (
    <SliderPrimitive.Root
      className={cn("relative flex h-5 w-full touch-none select-none items-center", className)}
      value={[value]}
      min={min}
      max={max}
      step={step}
      onValueChange={(values) => onChange(values[0] ?? value)}
    >
      <SliderPrimitive.Track className="relative h-1.5 grow overflow-hidden rounded-full bg-raised">
        <SliderPrimitive.Range className="absolute h-full rounded-full bg-saffron" />
      </SliderPrimitive.Track>
      <SliderPrimitive.Thumb
        aria-label={label}
        className="block size-4 rounded-full border-2 border-saffron bg-surface shadow focus:outline-none focus-visible:ring-2 focus-visible:ring-saffron/50"
      />
    </SliderPrimitive.Root>
  );
}
