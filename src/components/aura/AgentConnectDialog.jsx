import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";

import AgentConnectionForm from "./AgentConnectionForm";

export default function AgentConnectDialog({ open, onClose, onConnected }) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[90] flex items-center justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm"
          onClick={onClose}
        >
          <motion.div
            initial={{ scale: 0.97, y: 10 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.97, y: 10 }}
            onClick={(event) => event.stopPropagation()}
            className="my-auto w-full max-w-xl rounded-2xl border border-white/10 bg-card shadow-2xl"
          >
            <div className="flex items-center justify-between border-b border-white/8 px-5 py-4">
              <span className="text-sm font-semibold">Agent connection</span>
              <button
                type="button"
                aria-label="Close agent connection"
                onClick={onClose}
                className="rounded-lg p-1.5 text-muted-foreground hover:bg-white/5 hover:text-foreground"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="max-h-[calc(100vh-8rem)] overflow-y-auto p-5">
              <AgentConnectionForm onConnected={onConnected} />
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
