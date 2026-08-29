import { motion } from "framer-motion";

export default function ValueProp() {
  return (
    <div className="text-center mb-8">
      <motion.h1
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-3xl md:text-4xl font-bold tracking-tight mb-3"
      >
        What would you like{" "}
        <span className="text-gradient">AURA</span> to do?
      </motion.h1>
      <motion.p
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.1 }}
        className="text-muted-foreground text-sm max-w-xl mx-auto"
      >
        Give AURA a task. It will create a plan, work across your tools, and deliver the result — with you in control.
      </motion.p>
    </div>
  );
}