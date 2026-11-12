import { useRef, useState } from "react";
import { FileUp, Loader2 } from "lucide-react";
import { aura } from "@/api/auraClient";
import { uploadBatchError } from "@/lib/uploadLimits.mjs";

const hasFiles = (transfer) => Array.from(transfer?.types || []).includes("Files")
  || Array.from(transfer?.items || []).some((item) => item.kind === "file")
  || transfer?.files?.length > 0;

export default function DocumentUpload({ documents = [], onAttach, compact = false, disabled = false, onBusyChange = undefined }) {
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const fileRef = useRef(null);
  const pending = useRef(false);
  const dragDepth = useRef(0);

  const attachFiles = async (files) => {
    if (!files.length) return;
    if (pending.current) {
      setError("Files are still attaching. Drop these again when finished.");
      return;
    }
    if (disabled) return;
    setError(""); setStatus("");
    const validationError = uploadBatchError(files, documents);
    if (validationError) {
      setError(validationError);
      return;
    }
    pending.current = true;
    setUploading(true);
    onBusyChange?.(true);
    const failures = [];
    let attached = 0;
    try {
      for (const file of files) {
        try {
          const result = await aura.integrations.Core.UploadFile({ file });
          if (!result?.file_url) throw new Error("The file could not be read.");
          onAttach({ name: file.name, file_url: result.file_url, size: file.size });
          attached += 1;
        } catch (cause) {
          failures.push(`${file.name}: ${cause?.message || "AURA could not attach this file."}`);
        }
      }
      if (failures.length) setError(failures.join(" "));
      if (attached) setStatus(`${attached} ${attached === 1 ? "document" : "documents"} attached.`);
    } finally {
      pending.current = false;
      setUploading(false);
      onBusyChange?.(false);
    }
  };

  return <div aria-label="Document upload" aria-busy={uploading}
    onDragEnter={(event) => {
      if (!hasFiles(event.dataTransfer)) return;
      event.preventDefault(); event.stopPropagation();
      dragDepth.current += 1;
      if (!pending.current && !disabled) setDragging(true);
    }}
    onDragOver={(event) => {
      if (!hasFiles(event.dataTransfer)) return;
      event.preventDefault(); event.stopPropagation();
      event.dataTransfer.dropEffect = pending.current || disabled ? "none" : "copy";
    }}
    onDragLeave={(event) => {
      event.preventDefault(); event.stopPropagation();
      dragDepth.current = Math.max(0, dragDepth.current - 1);
      if (!dragDepth.current) setDragging(false);
    }}
    onDrop={(event) => {
      event.preventDefault(); event.stopPropagation();
      dragDepth.current = 0; setDragging(false);
      if (Array.from(event.dataTransfer?.items || []).some((item) => item.webkitGetAsEntry?.()?.isDirectory)) {
        setError("Drop individual files instead of folders.");
        return;
      }
      void attachFiles(Array.from(event.dataTransfer?.files || []));
    }}>
    <button type="button" onClick={() => fileRef.current?.click()} disabled={uploading || disabled}
      className={`flex w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed transition-all disabled:opacity-50 ${compact ? "py-6" : "py-8"} ${dragging ? "border-primary bg-primary/15" : "border-white/15 hover:border-primary/40 hover:bg-primary/5"}`}>
      {uploading ? <Loader2 className="h-5 w-5 animate-spin text-primary" /> : <FileUp className="h-5 w-5 text-primary" />}
      <span className={`${compact ? "text-xs" : "text-sm"} font-medium`}>{uploading ? "Attaching files…" : dragging ? "Drop files here" : "Drop video or files here, or browse"}</span>
      <span className="px-3 text-[11px] text-muted-foreground">MP4/MOV video up to 2 minutes · PDF, DOCX, CSV, spreadsheets and images · Up to 8 files, 10 MB each</span>
    </button>
    <input ref={fileRef} type="file" multiple disabled={uploading || disabled} aria-label="Choose documents" className="hidden"
      onChange={(event) => {
        const files = Array.from(event.target.files || []);
        event.target.value = "";
        void attachFiles(files);
      }} />
    {error && <p role="alert" className="mt-2 text-xs text-red-300">{error}</p>}
    {status && <p role="status" className="mt-2 text-xs text-emerald-300">{status}</p>}
  </div>;
}
