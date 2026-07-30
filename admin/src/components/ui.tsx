import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

export function cn(...values: Array<string | false | null | undefined>) { return values.filter(Boolean).join(" "); }
export function Button({ className, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={cn("button", className)} {...props} />;
}
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("card", className)} {...props} />;
}
export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn("field", className)} {...props} />;
}
export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "success" | "warning" | "danger" | "sync" }) {
  const tones = { neutral: "bg-white/5", success: "border-success/30 bg-success/10 text-success", warning: "border-warning/30 bg-warning/10 text-warning", danger: "border-danger/30 bg-danger/10 text-danger", sync: "border-sync/30 bg-sync/10 text-sync" };
  return <span className={cn("badge", tones[tone])}>{children}</span>;
}
export function Empty({ title, detail }: { title: string; detail: string }) {
  return <div className="grid min-h-48 place-items-center rounded-lg border border-dashed p-8 text-center"><div><p className="font-medium">{title}</p><p className="muted mt-1">{detail}</p></div></div>;
}
