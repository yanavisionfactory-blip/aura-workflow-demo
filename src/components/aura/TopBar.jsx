import { motion } from "framer-motion";
import ConnectionsPill from "./ConnectionsPill";
import { Sparkles, History } from "lucide-react";
import { UserButton } from "@clerk/react";
import { useAuth } from "@/lib/AuthContext";

export default function TopBar({ onHistoryOpen }) {
  const { workspace, workspaces, chooseWorkspace } = useAuth();
  return (
    <motion.header
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="flex items-center justify-between px-6 py-4 border-b border-white/5"
    >
      <div className="flex items-center gap-3">
        <div className="relative">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-accent flex items-center justify-center">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <div className="absolute inset-0 rounded-lg bg-gradient-to-br from-primary to-accent opacity-40 blur-md" />
        </div>
        <span className="text-lg font-semibold tracking-tight">AURA</span>
        <span className="text-[10px] font-medium text-muted-foreground bg-secondary px-2 py-0.5 rounded-full uppercase tracking-widest">
          Pro
        </span>
      </div>
      <div className="flex items-center gap-4">
        {workspaces.length > 1 && (
          <select
            aria-label="AURA workspace"
            value={workspace?.workspace_id || ""}
            onChange={(event) => {
              const next = workspaces.find((item) => item.workspace_id === event.target.value);
              if (next) chooseWorkspace(next);
            }}
            className="max-w-40 rounded-lg border border-white/10 bg-secondary px-2 py-1.5 text-xs"
          >
            {workspaces.map((item) => <option key={item.workspace_id} value={item.workspace_id}>{item.name}</option>)}
          </select>
        )}
        <ConnectionsPill />
        <button
          onClick={onHistoryOpen}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-white/8 text-muted-foreground hover:text-foreground hover:border-white/15 hover:bg-white/5 transition-all text-xs"
        >
          <History className="w-3.5 h-3.5" />
          My workflows
        </button>
        <UserButton />
      </div>
    </motion.header>
  );
}
