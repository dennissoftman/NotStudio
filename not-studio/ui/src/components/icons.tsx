import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const shared = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export function PlayIcon(props: IconProps) {
  return <svg {...shared} {...props}><path d="m8 5 11 7-11 7V5Z" fill="currentColor" stroke="none" /></svg>;
}

export function PauseIcon(props: IconProps) {
  return <svg {...shared} {...props}><path d="M9 5v14M15 5v14" strokeWidth="2.4" /></svg>;
}

export function ThumbsUpIcon(props: IconProps) {
  return <svg {...shared} {...props}><path d="M7 10v11H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3Zm0 11h9.2a2 2 0 0 0 1.9-1.4l2.2-7A2 2 0 0 0 18.4 10H14l.7-3.5A2.9 2.9 0 0 0 12 3l-5 7v11Z" /></svg>;
}

export function ThumbsDownIcon(props: IconProps) {
  return <svg {...shared} {...props}><path d="M7 14V3H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3Zm0-11h9.2a2 2 0 0 1 1.9 1.4l2.2 7a2 2 0 0 1-1.9 2.6H14l.7 3.5A2.9 2.9 0 0 1 12 21l-5-7V3Z" /></svg>;
}

export function TrashIcon(props: IconProps) {
  return <svg {...shared} {...props}><path d="M4 7h16M9 7V4h6v3M6.5 7l.8 14h9.4l.8-14M10 11v6M14 11v6" /></svg>;
}

export function DownloadIcon(props: IconProps) {
  return <svg {...shared} {...props}><path d="M12 3v12m0 0 4-4m-4 4-4-4M4 20h16" /></svg>;
}

export function CopyIcon(props: IconProps) {
  return <svg {...shared} {...props}><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></svg>;
}

export function PlusIcon(props: IconProps) {
  return <svg {...shared} {...props}><path d="M12 5v14M5 12h14" /></svg>;
}

export function SparklesIcon(props: IconProps) {
  return <svg {...shared} {...props}><path d="m12 3 1.1 3.2L16 8l-2.9 1.8L12 13l-1.1-3.2L8 8l2.9-1.8L12 3ZM5 14l.8 2.2L8 17.5l-2.2 1.3L5 21l-.8-2.2L2 17.5l2.2-1.3L5 14Zm13-2 .8 2.2 2.2 1.3-2.2 1.3L18 19l-.8-2.2-2.2-1.3 2.2-1.3L18 12Z" /></svg>;
}

export function XIcon(props: IconProps) {
  return <svg {...shared} {...props}><path d="m6 6 12 12M18 6 6 18" /></svg>;
}

export function ChevronIcon(props: IconProps & { direction?: "up" | "down" }) {
  const { direction = "down", ...rest } = props;
  return <svg {...shared} {...rest}><path d={direction === "up" ? "m7 14 5-5 5 5" : "m7 10 5 5 5-5"} /></svg>;
}
