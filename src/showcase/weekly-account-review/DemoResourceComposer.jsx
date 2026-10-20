import { ResourceList } from './DemoResources';
export default function DemoResourceComposer({ open, onClose }) {
  if (!open) return null;
  return <div className="absolute left-0 top-8 z-40 w-[min(23rem,80vw)] rounded-2xl border border-white/10 bg-[#101a2c] p-4 shadow-2xl"><h3 className="mb-3 text-sm font-semibold">Scoped sample inputs</h3><ResourceList/><button type="button" onClick={onClose} className="mt-4 rounded-lg border border-white/10 px-3 py-2 text-xs">Close</button></div>;
}
