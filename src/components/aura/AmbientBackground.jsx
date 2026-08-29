import { motion } from "framer-motion";

export default function AmbientBackground({ phase }) {
  const gradients = {
    input: "from-primary/[0.03] via-transparent to-accent/[0.02]",
    confirm: "from-primary/[0.05] via-transparent to-accent/[0.02]",
    plan: "from-primary/[0.05] via-transparent to-transparent",
    preview: "from-accent/[0.05] via-transparent to-primary/[0.03]",
    executing: "from-accent/[0.05] via-transparent to-primary/[0.03]",
    error: "from-amber-500/[0.06] via-transparent to-red-500/[0.03]",
    results: "from-emerald-500/[0.04] via-transparent to-primary/[0.02]",
  };

  return (
    <div className="fixed inset-0 overflow-hidden pointer-events-none">
      <motion.div
        key={phase}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 1.5 }}
        className={`absolute inset-0 bg-gradient-to-br ${gradients[phase] || gradients.input}`}
      />

      <motion.div
        animate={{ x: [0, 30, -20, 0], y: [0, -20, 15, 0] }}
        transition={{ duration: 20, repeat: Infinity, ease: "linear" }}
        className="absolute top-1/4 left-1/4 w-96 h-96 rounded-full bg-primary/[0.03] blur-3xl"
      />
      <motion.div
        animate={{ x: [0, -25, 20, 0], y: [0, 15, -25, 0] }}
        transition={{ duration: 25, repeat: Infinity, ease: "linear" }}
        className="absolute bottom-1/4 right-1/4 w-80 h-80 rounded-full bg-accent/[0.03] blur-3xl"
      />

      <div
        className="absolute inset-0 opacity-[0.02]"
        style={{
          backgroundImage: `linear-gradient(rgba(255,255,255,0.1) 1px, transparent 1px),
                            linear-gradient(90deg, rgba(255,255,255,0.1) 1px, transparent 1px)`,
          backgroundSize: "60px 60px",
        }}
      />
    </div>
  );
}